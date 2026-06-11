"""
World Cup 2026 Predictive Pipeline
==================================
Pipeline de analitica futbolistica para estimar resultados del Mundial 2026.

Arquitectura
------------
1. Grounding en Elo        : ratings reales (eloratings.net) de los 48 clasificados.
2. Elo -> supremacia (tanh): mapeo acotado Elo -> goles esperados.
3. Poisson + Dixon-Coles   : matriz conjunta de marcadores con correccion de
                             baja anotacion (rho).
4. Ajustes de contexto 2026: altitud (CDMX ~2240 m), calor y localia de anfitriones.
5. Calibracion (MLE)       : ajuste de hiperparametros por maxima verosimilitud
                             con decaimiento temporal estilo Dixon-Coles.
6. Monte Carlo             : simulacion de los 12 grupos N veces con desempates
                             FIFA y logica de los 8 mejores terceros.

Python : 3.10+
Deps   : numpy, scipy, pandas, requests, beautifulsoup4
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

try:
    import requests
    from bs4 import BeautifulSoup

    _HAS_SCRAPER = True
except ImportError:  # pragma: no cover
    _HAS_SCRAPER = False


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wc2026")


# ===========================================================================
# Configuracion
# ===========================================================================
@dataclass(frozen=True)
class ModelConfig:
    """Hiperparametros del motor predictivo (calibrables/documentados)."""

    avg_total_goals: float = 2.72
    max_supremacy: float = 3.00
    supremacy_beta: float = 0.0018
    home_advantage_elo: float = 65.0
    dixon_coles_rho: float = -0.13
    min_lambda: float = 0.15
    max_goals: int = 8

    def __post_init__(self) -> None:
        if not (-1.0 < self.dixon_coles_rho < 1.0):
            raise ValueError("dixon_coles_rho debe estar en (-1, 1).")
        if self.max_goals < 4:
            raise ValueError("max_goals demasiado bajo para una matriz util.")


@dataclass
class TeamProfile:
    name: str
    elo: float
    confederation: str = "UEFA"
    is_host: bool = False
    altitude_adapted: bool = False
    recent_form: float = 1.0

    def __post_init__(self) -> None:
        if self.elo <= 0:
            raise ValueError(f"Elo invalido para {self.name}: {self.elo}")


@dataclass
class MatchContext:
    altitude_m: float = 0.0
    heat_index: float = 0.0
    home_team: Optional[str] = None


# ===========================================================================
# Nucleo matematico compartido (UNICA fuente de verdad Elo -> probabilidades)
# ===========================================================================
def elo_to_lambdas(
    elo_home: float,
    elo_away: float,
    cfg: ModelConfig,
    *,
    home_adv: bool = False,
    away_adv: bool = False,
    form_home: float = 1.0,
    form_away: float = 1.0,
) -> Tuple[float, float]:
    """Convierte ratings Elo en goles esperados (lambda) de cada equipo."""
    eh = elo_home + (cfg.home_advantage_elo if home_adv else 0.0)
    ea = elo_away + (cfg.home_advantage_elo if away_adv else 0.0)
    supremacy = cfg.max_supremacy * math.tanh(cfg.supremacy_beta * (eh - ea))
    lam_h = max((cfg.avg_total_goals + supremacy) / 2.0 * form_home, cfg.min_lambda)
    lam_a = max((cfg.avg_total_goals - supremacy) / 2.0 * form_away, cfg.min_lambda)
    return lam_h, lam_a


def dc_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Factor de correccion de baja anotacion de Dixon-Coles (escalar)."""
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    if x == 0 and y == 1:
        return 1.0 + lam * rho
    if x == 1 and y == 0:
        return 1.0 + mu * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def dc_tau_vec(
    gh: np.ndarray, ga: np.ndarray, lam: np.ndarray, mu: np.ndarray, rho: float
) -> np.ndarray:
    """Version vectorizada de la correccion Dixon-Coles para calibracion."""
    tau = np.ones_like(lam, dtype=float)
    m00 = (gh == 0) & (ga == 0)
    m01 = (gh == 0) & (ga == 1)
    m10 = (gh == 1) & (ga == 0)
    m11 = (gh == 1) & (ga == 1)
    tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
    tau[m01] = 1.0 + lam[m01] * rho
    tau[m10] = 1.0 + mu[m10] * rho
    tau[m11] = 1.0 - rho
    return np.clip(tau, 1e-6, None)


# ===========================================================================
# Capa de datos
# ===========================================================================
class DataGenerator:
    """Fuente de datos con scraping + fallback a Elo real de junio-2026 (48 eq.)."""

    _SEED_ELO: Dict[str, Tuple[float, str, bool]] = {
        # name: (elo, confederation, altitude_adapted)
        "Spain": (2155, "UEFA", False),
        "Argentina": (2114, "CONMEBOL", False),
        "France": (2062, "UEFA", False),
        "England": (2021, "UEFA", False),
        "Brazil": (1991, "CONMEBOL", False),
        "Portugal": (1986, "UEFA", False),
        "Colombia": (1982, "CONMEBOL", True),
        "Netherlands": (1959, "UEFA", False),
        "Ecuador": (1933, "CONMEBOL", True),
        "Croatia": (1933, "UEFA", False),
        "Norway": (1922, "UEFA", False),
        "Germany": (1910, "UEFA", False),
        "Switzerland": (1897, "UEFA", False),
        "Uruguay": (1890, "CONMEBOL", False),
        "Turkey": (1880, "UEFA", False),
        "Japan": (1879, "AFC", False),
        "Senegal": (1869, "CAF", False),
        "Denmark": (1864, "UEFA", False),
        "Morocco": (1860, "CAF", False),
        "Belgium": (1849, "UEFA", False),
        "Sweden": (1820, "UEFA", False),
        "Austria": (1790, "UEFA", False),
        "Iran": (1780, "AFC", False),
        "Mexico": (1760, "CONCACAF", True),
        "Czechia": (1760, "UEFA", False),
        "Ivory Coast": (1760, "CAF", False),
        "Algeria": (1760, "CAF", False),
        "Scotland": (1750, "UEFA", False),
        "United States": (1750, "CONCACAF", False),
        "South Korea": (1745, "AFC", False),
        "Egypt": (1730, "CAF", False),
        "Australia": (1730, "AFC", False),
        "Paraguay": (1700, "CONMEBOL", False),
        "Ghana": (1700, "CAF", False),
        "Tunisia": (1690, "CAF", False),
        "Canada": (1690, "CONCACAF", False),
        "DR Congo": (1680, "CAF", False),
        "Bosnia and Herzegovina": (1660, "UEFA", False),
        "Panama": (1660, "CONCACAF", False),
        "Uzbekistan": (1640, "AFC", False),
        "Saudi Arabia": (1620, "AFC", False),
        "Qatar": (1610, "AFC", False),
        "Iraq": (1600, "AFC", False),
        "Jordan": (1600, "AFC", False),
        "South Africa": (1600, "CAF", False),
        "Cape Verde": (1590, "CAF", False),
        "Haiti": (1500, "CONCACAF", False),
        "New Zealand": (1500, "OFC", False),
        "Curacao": (1450, "CONCACAF", False),
    }

    def __init__(self, seed: int = 2026) -> None:
        self._rng = np.random.default_rng(seed)

    def fetch(self, prefer_live: bool = True) -> Dict[str, TeamProfile]:
        if prefer_live and _HAS_SCRAPER:
            try:
                live = self._scrape_elo()
                if live:
                    logger.info("Scraping en vivo OK: %d equipos.", len(live))
                    return self._attach_form(live)
                logger.warning("Scraping devolvio vacio; usando fallback.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scraping fallo (%s); usando fallback.", exc)
        else:
            logger.info("Scraping indisponible; usando fallback.")
        return self._attach_form(dict(self._SEED_ELO))

    def _scrape_elo(self, timeout: int = 8) -> Dict[str, Tuple[float, str, bool]]:
        url = "https://www.eloratings.net/2026_World_Cup"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; wc2026-bot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        parsed: Dict[str, Tuple[float, str, bool]] = {}
        for row in soup.select("table tr"):
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) >= 2:
                try:
                    parsed[cols[0]] = (float(cols[1].replace(",", "")), "UEFA", False)
                except (ValueError, IndexError):
                    continue
        return parsed

    def _attach_form(
        self, raw: Dict[str, Tuple[float, str, bool]]
    ) -> Dict[str, TeamProfile]:
        hosts = {"United States", "Mexico", "Canada"}
        profiles: Dict[str, TeamProfile] = {}
        for name, (elo, conf, alt) in raw.items():
            form = float(np.clip(self._rng.normal(1.0, 0.035), 0.92, 1.08))
            profiles[name] = TeamProfile(
                name=name, elo=elo, confederation=conf,
                is_host=name in hosts, altitude_adapted=alt, recent_form=round(form, 3),
            )
        return profiles


# Sorteo oficial del Mundial 2026 (5 dic 2025, playoffs ya resueltos).
DRAW_2026: Dict[str, List[str]] = {
    "A": ["Mexico", "South Korea", "South Africa", "Czechia"],
    "B": ["Canada", "Switzerland", "Qatar", "Bosnia and Herzegovina"],
    "C": ["Brazil", "Morocco", "Scotland", "Haiti"],
    "D": ["United States", "Australia", "Paraguay", "Turkey"],
    "E": ["Germany", "Ecuador", "Ivory Coast", "Curacao"],
    "F": ["Netherlands", "Japan", "Tunisia", "Sweden"],
    "G": ["Belgium", "Iran", "Egypt", "New Zealand"],
    "H": ["Spain", "Uruguay", "Saudi Arabia", "Cape Verde"],
    "I": ["France", "Senegal", "Norway", "Iraq"],
    "J": ["Argentina", "Austria", "Algeria", "Jordan"],
    "K": ["Portugal", "Colombia", "Uzbekistan", "DR Congo"],
    "L": ["England", "Croatia", "Panama", "Ghana"],
}


# ===========================================================================
# Motor predictivo
# ===========================================================================
class EloPoissonModel:
    def __init__(self, config: Optional[ModelConfig] = None) -> None:
        self.cfg = config or ModelConfig()

    def _expected_lambdas(
        self, home: TeamProfile, away: TeamProfile, ctx: MatchContext
    ) -> Tuple[float, float]:
        lam_h, lam_a = elo_to_lambdas(
            home.elo, away.elo, self.cfg,
            home_adv=(ctx.home_team == home.name),
            away_adv=(ctx.home_team == away.name),
            form_home=home.recent_form, form_away=away.recent_form,
        )
        return self._apply_context(home, away, ctx, lam_h, lam_a)

    def _apply_context(
        self, home: TeamProfile, away: TeamProfile, ctx: MatchContext,
        lam_h: float, lam_a: float,
    ) -> Tuple[float, float]:
        if ctx.altitude_m > 1500:
            penalty = min((ctx.altitude_m - 1500) / 1500, 1.0) * 0.08
            if not home.altitude_adapted:
                lam_h *= (1 - penalty)
            if not away.altitude_adapted:
                lam_a *= (1 - penalty)
        if ctx.heat_index > 0:
            factor = 1 - 0.05 * ctx.heat_index
            lam_h *= factor
            lam_a *= factor
        return max(lam_h, self.cfg.min_lambda), max(lam_a, self.cfg.min_lambda)

    def score_matrix(
        self, home: TeamProfile, away: TeamProfile, ctx: Optional[MatchContext] = None
    ) -> Tuple[np.ndarray, float, float]:
        ctx = ctx or MatchContext()
        lam_h, lam_a = self._expected_lambdas(home, away, ctx)
        n = self.cfg.max_goals + 1
        matrix = np.outer(poisson.pmf(np.arange(n), lam_h),
                          poisson.pmf(np.arange(n), lam_a))
        for x in (0, 1):
            for y in (0, 1):
                matrix[x, y] *= dc_tau(x, y, lam_h, lam_a, self.cfg.dixon_coles_rho)
        total = matrix.sum()
        if total <= 0:
            raise RuntimeError("Matriz de marcador degenerada (suma <= 0).")
        return matrix / total, lam_h, lam_a


@dataclass
class MatchPrediction:
    home: str
    away: str
    lambda_home: float
    lambda_away: float
    p_home: float
    p_draw: float
    p_away: float
    top_scorelines: List[Tuple[str, float]]
    matrix: np.ndarray = field(repr=False)


class MatchPredictor:
    def __init__(self, model: EloPoissonModel) -> None:
        self.model = model

    def predict(
        self, home: TeamProfile, away: TeamProfile,
        ctx: Optional[MatchContext] = None, top_n: int = 5,
    ) -> MatchPrediction:
        matrix, lam_h, lam_a = self.model.score_matrix(home, away, ctx)
        flat = [
            (f"{i}-{j}", float(matrix[i, j]))
            for i in range(matrix.shape[0]) for j in range(matrix.shape[1])
        ]
        flat.sort(key=lambda kv: kv[1], reverse=True)
        return MatchPrediction(
            home=home.name, away=away.name,
            lambda_home=round(lam_h, 3), lambda_away=round(lam_a, 3),
            p_home=round(float(np.tril(matrix, -1).sum()), 4),
            p_draw=round(float(np.trace(matrix)), 4),
            p_away=round(float(np.triu(matrix, 1).sum()), 4),
            top_scorelines=[(s, round(p, 4)) for s, p in flat[:top_n]],
            matrix=matrix,
        )


# ===========================================================================
# MODULO 1: Calibracion por maxima verosimilitud
# ===========================================================================
@dataclass
class HistoricalMatch:
    """Un resultado historico con los Elo vigentes en la fecha del partido."""

    elo_home: float
    elo_away: float
    goals_home: int
    goals_away: int
    home_advantage: bool = False
    weight: float = 1.0


class ModelCalibrator:
    """
    Ajusta (avg_total_goals, supremacy_beta, dixon_coles_rho, home_advantage_elo)
    maximizando la log-verosimilitud de los marcadores observados dado el Elo.

    Reutiliza EXACTAMENTE la misma matematica que el modelo (elo_to_lambdas +
    dc_tau_vec), por lo que la config ajustada es plug-and-play.
    """

    _PARAM_NAMES = ("avg_total_goals", "supremacy_beta", "dixon_coles_rho",
                    "home_advantage_elo")
    _BOUNDS = [(1.5, 4.0), (1e-4, 1e-2), (-0.5, 0.3), (0.0, 150.0)]

    def __init__(self, base: Optional[ModelConfig] = None) -> None:
        self.base = base or ModelConfig()

    def _config_from_theta(self, theta: Sequence[float]) -> ModelConfig:
        total, beta, rho, home_elo = theta
        return replace(
            self.base, avg_total_goals=float(total), supremacy_beta=float(beta),
            dixon_coles_rho=float(rho), home_advantage_elo=float(home_elo),
        )

    def _neg_log_likelihood(
        self, theta: np.ndarray, eh: np.ndarray, ea: np.ndarray,
        gh: np.ndarray, ga: np.ndarray, hadv: np.ndarray, w: np.ndarray,
    ) -> float:
        total, beta, rho, home_elo = theta
        eh_eff = eh + np.where(hadv, home_elo, 0.0)
        supremacy = self.base.max_supremacy * np.tanh(beta * (eh_eff - ea))
        lam_h = np.clip((total + supremacy) / 2.0, self.base.min_lambda, None)
        lam_a = np.clip((total - supremacy) / 2.0, self.base.min_lambda, None)
        p = (poisson.pmf(gh, lam_h) * poisson.pmf(ga, lam_a)
             * dc_tau_vec(gh, ga, lam_h, lam_a, rho))
        return float(-np.sum(w * np.log(np.clip(p, 1e-12, None))))

    @staticmethod
    def time_decay_weights(
        ages_days: Sequence[float], half_life_days: float = 365.0
    ) -> np.ndarray:
        """Pesos exp(-xi * edad) estilo Dixon-Coles; partidos viejos pesan menos."""
        if half_life_days <= 0:
            raise ValueError("half_life_days debe ser positivo.")
        xi = math.log(2) / half_life_days
        return np.exp(-xi * np.asarray(ages_days, dtype=float))

    def fit(self, matches: Sequence[HistoricalMatch]) -> Tuple[ModelConfig, object]:
        if len(matches) < 50:
            logger.warning("Pocos partidos (%d): la calibracion sera inestable.",
                            len(matches))
        eh = np.array([m.elo_home for m in matches], dtype=float)
        ea = np.array([m.elo_away for m in matches], dtype=float)
        gh = np.array([m.goals_home for m in matches], dtype=int)
        ga = np.array([m.goals_away for m in matches], dtype=int)
        hadv = np.array([m.home_advantage for m in matches], dtype=bool)
        w = np.array([m.weight for m in matches], dtype=float)

        x0 = np.array([getattr(self.base, n) for n in self._PARAM_NAMES], dtype=float)
        res = minimize(
            self._neg_log_likelihood, x0, args=(eh, ea, gh, ga, hadv, w),
            method="L-BFGS-B", bounds=self._BOUNDS,
        )
        if not res.success:
            logger.warning("Optimizacion no convergio: %s", res.message)
        else:
            logger.info("Calibracion OK | -logL=%.1f en %d evaluaciones.",
                        res.fun, res.nfev)
        return self._config_from_theta(res.x), res


def synthesize_history(
    true_cfg: ModelConfig, n_matches: int = 3000, seed: int = 7,
    elo_pool: Optional[Sequence[float]] = None,
) -> List[HistoricalMatch]:
    """
    Genera un historico sintetico muestreando del propio modelo con parametros
    conocidos. Sirve para VALIDAR que el calibrador recupera la verdad.
    En produccion se reemplaza por resultados reales (CSV: fecha, equipos,
    goles, Elo del momento).
    """
    rng = np.random.default_rng(seed)
    model = EloPoissonModel(true_cfg)
    if elo_pool is None:
        elo_pool = list(DataGenerator(seed)._SEED_ELO.values())
        elo_pool = [v[0] for v in elo_pool]
    pool = np.asarray(elo_pool, dtype=float)

    matches: List[HistoricalMatch] = []
    for _ in range(n_matches):
        eh, ea = rng.choice(pool, size=2, replace=False)
        hadv = bool(rng.random() < 0.55)
        home = TeamProfile("H", float(eh))
        away = TeamProfile("A", float(ea))
        ctx = MatchContext(home_team="H" if hadv else None)
        matrix, _, _ = model.score_matrix(home, away, ctx)
        idx = int(rng.choice(matrix.size, p=matrix.ravel()))
        x, y = divmod(idx, matrix.shape[1])
        matches.append(HistoricalMatch(float(eh), float(ea), x, y, hadv))
    return matches


# ===========================================================================
# MODULO 2: Simulacion Monte Carlo (grupo individual + torneo de 12 grupos)
# ===========================================================================
@dataclass
class GroupRecord:
    name: str
    pts: int
    gf: int
    ga: int
    elo: float

    @property
    def gd(self) -> int:
        return self.gf - self.ga


class MonteCarloSimulator:
    """Simula un grupo de 4 equipos con desempates FIFA. Base del torneo."""

    def __init__(self, model: EloPoissonModel, seed: int = 2026) -> None:
        self.model = model
        self._rng = np.random.default_rng(seed)
        self._cdf_cache: Dict[Tuple[str, str], Tuple[np.ndarray, int]] = {}

    def _cdf(self, home: TeamProfile, away: TeamProfile) -> Tuple[np.ndarray, int]:
        """CDF acumulada del marcador (cacheada) para muestreo O(log n)."""
        key = (home.name, away.name)
        if key not in self._cdf_cache:
            # Localia para anfitriones en su grupo (si solo uno es local).
            host = None
            if home.is_host ^ away.is_host:
                host = home.name if home.is_host else away.name
            matrix, _, _ = self.model.score_matrix(
                home, away, MatchContext(home_team=host)
            )
            self._cdf_cache[key] = (np.cumsum(matrix.ravel()), matrix.shape[1])
        return self._cdf_cache[key]

    def _sample_score(self, home: TeamProfile, away: TeamProfile) -> Tuple[int, int]:
        cdf, ncols = self._cdf(home, away)
        idx = int(np.searchsorted(cdf, self._rng.random()))
        idx = min(idx, cdf.size - 1)
        return divmod(idx, ncols)

    @staticmethod
    def _rank_records(
        teams: Sequence[TeamProfile],
        results: Dict[Tuple[str, str], Tuple[int, int]],
    ) -> List[GroupRecord]:
        """Ordena el grupo: pts -> DG -> GF -> head-to-head -> Elo."""
        stats = {t.name: GroupRecord(t.name, 0, 0, 0, t.elo) for t in teams}
        for (h, a), (gh, ga) in results.items():
            stats[h].gf += gh
            stats[h].ga += ga
            stats[a].gf += ga
            stats[a].ga += gh
            if gh > ga:
                stats[h].pts += 3
            elif gh < ga:
                stats[a].pts += 3
            else:
                stats[h].pts += 1
                stats[a].pts += 1

        def h2h(name: str, tied: List[str]) -> int:
            pts = 0
            for (h, a), (gh, ga) in results.items():
                if h == name and a in tied:
                    pts += 3 if gh > ga else (1 if gh == ga else 0)
                elif a == name and h in tied:
                    pts += 3 if ga > gh else (1 if gh == ga else 0)
            return pts

        def base_key(r: GroupRecord) -> Tuple[int, int, int]:
            return (r.pts, r.gd, r.gf)

        order = sorted(stats.values(), key=base_key, reverse=True)
        final: List[GroupRecord] = []
        i = 0
        while i < len(order):
            block = [order[i]]
            j = i + 1
            while j < len(order) and base_key(order[j]) == base_key(order[i]):
                block.append(order[j])
                j += 1
            if len(block) > 1:
                names = [r.name for r in block]
                block.sort(key=lambda r: (h2h(r.name, names), r.elo), reverse=True)
            final.extend(block)
            i = j
        return final

    def simulate_group_once(self, teams: Sequence[TeamProfile]) -> List[GroupRecord]:
        if len(teams) != 4:
            raise ValueError("Un grupo del Mundial 2026 tiene 4 equipos.")
        pairs = [(teams[i], teams[j]) for i in range(4) for j in range(i + 1, 4)]
        results = {(h.name, a.name): self._sample_score(h, a) for h, a in pairs}
        return self._rank_records(teams, results)

    def simulate_group(
        self, teams: Sequence[TeamProfile], n_sims: int = 10_000
    ) -> pd.DataFrame:
        if n_sims <= 0:
            raise ValueError("n_sims debe ser positivo.")
        names = [t.name for t in teams]
        tally = {n: {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "pts": 0} for n in names}
        for _ in range(n_sims):
            ranked = self.simulate_group_once(teams)
            for pos, rec in enumerate(ranked, start=1):
                tally[rec.name][f"P{pos}"] += 1
                tally[rec.name]["pts"] += rec.pts
        rows = [
            {
                "Equipo": n,
                "Gana grupo %": round(100 * tally[n]["P1"] / n_sims, 1),
                "2do %": round(100 * tally[n]["P2"] / n_sims, 1),
                "Clasifica (Top2) %": round(
                    100 * (tally[n]["P1"] + tally[n]["P2"]) / n_sims, 1),
                "3ro %": round(100 * tally[n]["P3"] / n_sims, 1),
                "Pts medios": round(tally[n]["pts"] / n_sims, 2),
            }
            for n in names
        ]
        return pd.DataFrame(rows).sort_values(
            "Clasifica (Top2) %", ascending=False
        ).reset_index(drop=True)


class TournamentSimulator:
    """
    Simula los 12 grupos del Mundial 2026 e implementa la clasificacion de los
    8 mejores terceros (criterios FIFA: pts -> DG -> GF -> ranking/Elo).
    """

    def __init__(
        self, model: EloPoissonModel, draw: Dict[str, List[TeamProfile]],
        seed: int = 2026,
    ) -> None:
        if len(draw) != 12:
            raise ValueError("El Mundial 2026 tiene exactamente 12 grupos.")
        self.mc = MonteCarloSimulator(model, seed=seed)
        self.draw = draw

    @classmethod
    def from_draw(
        cls, model: EloPoissonModel, profiles: Dict[str, TeamProfile],
        draw_names: Dict[str, List[str]] = DRAW_2026, seed: int = 2026,
    ) -> "TournamentSimulator":
        """Construye el torneo resolviendo nombres -> perfiles, validando todo."""
        resolved: Dict[str, List[TeamProfile]] = {}
        for group, names in draw_names.items():
            missing = [n for n in names if n not in profiles]
            if missing:
                raise KeyError(f"Faltan perfiles para {missing} (grupo {group}).")
            resolved[group] = [profiles[n] for n in names]
        return cls(model, resolved, seed=seed)

    def simulate(self, n_sims: int = 10_000) -> pd.DataFrame:
        if n_sims <= 0:
            raise ValueError("n_sims debe ser positivo.")
        all_names = [t.name for g in self.draw.values() for t in g]
        tally = {
            n: {"P1": 0, "P2": 0, "P3": 0, "P4": 0,
                "q_top2": 0, "q_third": 0, "qualified": 0}
            for n in all_names
        }

        for _ in range(n_sims):
            thirds: List[GroupRecord] = []
            for teams in self.draw.values():
                ranked = self.mc.simulate_group_once(teams)
                for pos, rec in enumerate(ranked, start=1):
                    tally[rec.name][f"P{pos}"] += 1
                    if pos <= 2:
                        tally[rec.name]["q_top2"] += 1
                        tally[rec.name]["qualified"] += 1
                thirds.append(ranked[2])  # tercero del grupo
            # Ranking de los 12 terceros -> los 8 mejores clasifican.
            thirds.sort(key=lambda r: (r.pts, r.gd, r.gf, r.elo), reverse=True)
            for rec in thirds[:8]:
                tally[rec.name]["q_third"] += 1
                tally[rec.name]["qualified"] += 1

        rows = []
        for g, teams in self.draw.items():
            for t in teams:
                d = tally[t.name]
                rows.append({
                    "Grupo": g,
                    "Equipo": t.name,
                    "Elo": int(t.elo),
                    "Gana grupo %": round(100 * d["P1"] / n_sims, 1),
                    "Top2 %": round(100 * d["q_top2"] / n_sims, 1),
                    "Mejor 3ro %": round(100 * d["q_third"] / n_sims, 1),
                    "Clasifica R32 %": round(100 * d["qualified"] / n_sims, 1),
                })
        return pd.DataFrame(rows).sort_values(
            "Clasifica R32 %", ascending=False
        ).reset_index(drop=True)


# ===========================================================================
# Demostracion
# ===========================================================================
def _fmt_matrix(pred: MatchPrediction, k: int = 6) -> pd.DataFrame:
    sub = np.round(pred.matrix[:k, :k] * 100, 2)
    return pd.DataFrame(
        sub, index=[f"{pred.home} {i}" for i in range(k)],
        columns=[f"{pred.away} {j}" for j in range(k)],
    )


def main() -> None:
    logger.info("Cargando datos (scraping con fallback)...")
    data = DataGenerator(seed=2026).fetch(prefer_live=True)
    logger.info("Equipos cargados: %d", len(data))

    cfg = ModelConfig()
    model = EloPoissonModel(cfg)
    predictor = MatchPredictor(model)

    # --- Showcase partido: Argentina vs Francia ---
    pred = predictor.predict(data["Argentina"], data["France"], MatchContext())
    print("\n" + "=" * 64)
    print("PARTIDO ESTRELLA: Argentina vs Francia (sede neutral)")
    print("=" * 64)
    print(f"Lambda -> Argentina {pred.lambda_home} | Francia {pred.lambda_away}")
    print(f"P(Arg) {pred.p_home:.1%} | Empate {pred.p_draw:.1%} | "
          f"P(Fra) {pred.p_away:.1%}")
    print("Matriz de marcador (%):")
    print(_fmt_matrix(pred, 6).to_string())

    # --- MODULO 1: Calibracion (validacion con datos sinteticos) ---
    print("\n" + "=" * 64)
    print("MODULO 1 - CALIBRACION POR MAXIMA VEROSIMILITUD")
    print("=" * 64)
    true_cfg = replace(cfg, avg_total_goals=2.70, supremacy_beta=0.0020,
                       dixon_coles_rho=-0.12, home_advantage_elo=70.0)
    hist = synthesize_history(true_cfg, n_matches=4000, seed=11)
    fitted, _ = ModelCalibrator(base=cfg).fit(hist)
    comp = pd.DataFrame({
        "Parametro": ["avg_total_goals", "supremacy_beta",
                      "dixon_coles_rho", "home_advantage_elo"],
        "Verdadero": [true_cfg.avg_total_goals, true_cfg.supremacy_beta,
                      true_cfg.dixon_coles_rho, true_cfg.home_advantage_elo],
        "Recuperado": [round(fitted.avg_total_goals, 4),
                       round(fitted.supremacy_beta, 5),
                       round(fitted.dixon_coles_rho, 4),
                       round(fitted.home_advantage_elo, 2)],
    })
    print(comp.to_string(index=False))

    # --- MODULO 2: Torneo completo (12 grupos + mejores terceros) ---
    print("\n" + "=" * 64)
    print("MODULO 2 - SIMULACION DE TORNEO (12 grupos, 10.000 corridas)")
    print("=" * 64)
    tourney = TournamentSimulator.from_draw(model, data, DRAW_2026, seed=2026)
    table = tourney.simulate(n_sims=10_000)
    print("\nTop 16 por probabilidad de clasificar a Ronda de 32:")
    print(table.head(16).to_string(index=False))

    grp_j = table[table["Grupo"] == "J"].sort_values("Clasifica R32 %",
                                                      ascending=False)
    print("\nGrupo J (Argentina) en detalle:")
    print(grp_j.to_string(index=False))


if __name__ == "__main__":
    main()
