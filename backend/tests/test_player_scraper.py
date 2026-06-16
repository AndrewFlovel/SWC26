"""Tests for the expanded player scraper: real defensive-stat parsing from
FBref's comment-wrapped tables, hybrid url-map resolution, graceful degradation,
and the synthetic bootstrap fallback."""

from bs4 import BeautifulSoup

from app.services import fbref_index, player_scraper
from scripts.bootstrap_squads import synthesize_squad
from app.engine.player_models import PlayerProfile
from app.engine.player_scorer import score_squad

# Standard table (visible) + Defensive-Actions and Misc tables wrapped in HTML
# comments, exactly as FBref serves a squad "…-Men-Stats" page.
SQUAD_HTML = """
<table id="stats_standard"><tbody>
  <tr>
    <td data-stat="player">Pedri</td><td data-stat="position">MF</td>
    <td data-stat="age">22</td><td data-stat="games">30</td>
    <td data-stat="goals">3</td><td data-stat="team">Barcelona</td>
    <td data-stat="minutes">900</td><td data-stat="minutes_90s">10.0</td>
    <td data-stat="xg_per90">0.12</td><td data-stat="xg_assist_per90">0.20</td>
    <td data-stat="shots_per90">1.5</td><td data-stat="progressive_passes_per90">6.0</td>
    <td data-stat="sca_per90">3.0</td><td data-stat="take_ons_won_per90">1.1</td>
  </tr>
  <tr>
    <td data-stat="player">Lamine Yamal</td><td data-stat="position">FW</td>
    <td data-stat="age">18</td><td data-stat="games">20</td>
    <td data-stat="goals">9</td><td data-stat="team">Barcelona</td>
    <td data-stat="minutes">450</td><td data-stat="minutes_90s">5.0</td>
    <td data-stat="xg_per90">0.55</td><td data-stat="xg_assist_per90">0.30</td>
    <td data-stat="shots_per90">3.2</td><td data-stat="progressive_passes_per90">2.0</td>
    <td data-stat="sca_per90">4.5</td><td data-stat="take_ons_won_per90">2.8</td>
  </tr>
</tbody></table>
<!--
<table id="stats_defense"><tbody>
  <tr>
    <td data-stat="player">Pedri</td>
    <td data-stat="tackles">20</td><td data-stat="tackles_won">14</td>
    <td data-stat="challenge_tackles_pct">60.0</td>
    <td data-stat="interceptions">15</td><td data-stat="clearances">10</td>
  </tr>
</tbody></table>
-->
<!--
<table id="stats_misc"><tbody>
  <tr><td data-stat="player">Pedri</td><td data-stat="aerials_won_pct">53.0</td></tr>
</tbody></table>
-->
"""


def test_parse_squad_merges_real_defensive_stats():
    players = {p["name"]: p for p in player_scraper.parse_squad(BeautifulSoup(SQUAD_HTML, "html.parser"), "Spain")}

    pedri = players["Pedri"]
    assert pedri["position"] == "CM"            # MF -> CM
    assert pedri["xg90"] == 0.12                # attacking read straight through
    # Defensive metrics merged from the commented tables, per-90 via minutes_90s=10.
    assert pedri["tackles_won_pct"] == 60.0
    assert pedri["interceptions90"] == 1.5      # 15 / 10
    assert pedri["clearances90"] == 1.0         # 10 / 10
    assert pedri["aerial_won_pct"] == 53.0
    # Pressures stay on position defaults (FBref discontinued them).
    assert pedri["pressures90"] == player_scraper._DEF_DEFAULTS["CM"]["pressures90"]


def test_parse_squad_uses_defaults_when_player_absent_from_secondary():
    players = {p["name"]: p for p in player_scraper.parse_squad(BeautifulSoup(SQUAD_HTML, "html.parser"), "Spain")}
    # Lamine Yamal has no row in the defense/misc tables -> ST defaults.
    yamal = players["Lamine Yamal"]
    assert yamal["position"] == "ST"
    assert yamal["interceptions90"] == player_scraper._DEF_DEFAULTS["ST"]["interceptions90"]
    assert yamal["aerial_won_pct"] == player_scraper._DEF_DEFAULTS["ST"]["aerial_won_pct"]


def test_parsed_rows_pass_profile_validation_and_score():
    rows = player_scraper.parse_squad(BeautifulSoup(SQUAD_HTML, "html.parser"), "Spain")
    scored = score_squad([PlayerProfile.from_dict(r) for r in rows])
    assert all(0.0 <= p.pps <= 1.0 for p in scored)


def test_fbref_index_canonicalizes_aliases():
    assert fbref_index.canonical("IR Iran") == "Iran"
    assert fbref_index.canonical("Korea Republic") == "South Korea"
    assert fbref_index.canonical("Spain") == "Spain"  # unmapped passes through


def test_parse_index_keeps_only_tournament_teams():
    html = """
    <a href="/en/squads/aaaaaaaa/Spain-Men-Stats">Spain</a>
    <a href="/en/squads/bbbbbbbb/Iran-Men-Stats">IR Iran</a>
    <a href="/en/squads/cccccccc/Narnia-Men-Stats">Narnia</a>
    <a href="/en/players/dddddddd/Some-Player">Not a squad</a>
    """
    found = fbref_index.parse_index(BeautifulSoup(html, "html.parser"))
    assert found["Spain"].endswith("/Spain-Men-Stats")
    assert found["Iran"].startswith("https://fbref.com/en/squads/bbbbbbbb/")  # alias applied
    assert "Narnia" not in found            # not one of the 48 teams
    assert all("/players/" not in url for url in found.values())


def test_discover_degrades_without_raising(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(fbref_index, "_get_soup", boom)
    # Returns the committed map unchanged instead of raising.
    result = fbref_index.discover_squad_urls(persist=False)
    assert isinstance(result, dict)


def test_scrape_squad_falls_back_to_seed_when_url_unresolved(monkeypatch):
    monkeypatch.setattr(player_scraper, "squad_url", lambda team: None)
    doc, source, messages = player_scraper.scrape_squad("Spain")  # seed file ships in repo
    assert source == "seed"
    assert doc is not None and doc["players"]
    assert any("seed" in m.lower() for m in messages)


def test_synthetic_squad_is_valid_and_complete():
    doc = synthesize_squad("Brazil")
    assert doc["source"] == "synthetic"
    assert len(doc["players"]) == 23
    scored = score_squad([PlayerProfile.from_dict(r) for r in doc["players"]])
    assert all(0.0 <= p.pps <= 1.0 for p in scored)
    # Stronger team scales attacking output above a weaker one.
    strong = synthesize_squad("Brazil")
    weak = synthesize_squad("Haiti")
    s_st = next(p for p in strong["players"] if p["position"] == "ST")
    w_st = next(p for p in weak["players"] if p["position"] == "ST")
    assert s_st["xg90"] > w_st["xg90"]
