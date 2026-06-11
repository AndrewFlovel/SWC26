# SWC26 — Sangre y Gloria

> 🌐 [English](README.md) · **Español** · Guías de instalación: [EN](SETUP.md) / [ES](SETUP.es.md)

**Plataforma interactiva de analítica predictiva para la Copa Mundial FIFA 2026**,
construida a partir de telemetría de investigación profunda sobre las 48 selecciones
clasificadas: ratings Elo, perfiles tácticos xG/xGA, momento de forma, desgaste por
lesiones, carga de viajes transcontinentales, hipoxia de altitud y estrés térmico WBGT.

Oscura, rojo sangre, impulsada por WebGL. Mueve los controles deslizantes: el motor
recalcula en tiempo real. La interfaz está disponible en **inglés, español y portugués**
(selector arriba a la derecha; también detecta automáticamente el idioma del navegador).

## Inicio rápido (Docker)

```bash
docker compose up --build
```

Abre <http://localhost:5173>. Eso es todo: nginx sirve el frontend y redirige `/api`
al contenedor del backend. Para desarrollo local sin Docker, consulta
[SETUP.es.md](SETUP.es.md).

## Arquitectura

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  React 19 + TypeScript  │  HTTP  │  FastAPI (Python 3.10+)      │
│  Vite · R3F · Motion    │ ─────► │  numpy · scipy · pandas      │
│  héroe 3D, dashboard,   │  JSON  │  Poisson bivariado Elo + xG  │
│  sliders what-if en     │ ◄───── │  Dixon-Coles · Monte Carlo   │
│  vivo, i18n EN/ES/PT    │        │                              │
└─────────────────────────┘        └──────────────────────────────┘
```

**El modelo.** Los ratings Elo se transforman en goles esperados mediante una
supremacía `tanh` acotada, que luego se combina con un modelo cruzado de xG
(ataque propio contra defensa rival). Ambos se modulan con factores de forma
reciente y desgaste por lesiones, y se penalizan por la altitud de la sede
(Estadio Azteca: 2.240 m) y la carga térmica WBGT (NRG Houston: puntaje 100).
Las probabilidades de marcador usan un Poisson bivariado con la corrección de
baja anotación de Dixon-Coles (ρ = −0.13). Los resultados de grupos y del torneo
se estiman por simulación Monte Carlo con los criterios de desempate FIFA
completos y la regla de los 8 mejores terceros. Se incluye un calibrador de
máxima verosimilitud con decaimiento temporal estilo Dixon-Coles
(`backend/app/engine/calibration.py`).

## API

| Método | Ruta | Propósito |
| --- | --- | --- |
| GET | `/api/teams` | 48 selecciones con métricas Elo, xG/xGA, forma y lesiones |
| GET | `/api/groups` | Sorteo oficial de diciembre 2025 (12 grupos) |
| GET | `/api/matches` | 72 partidos de fase de grupos con contexto de sede |
| POST | `/api/predict` | % victoria/empate/derrota, matriz de marcador exacto, marcadores más probables — acepta overrides de parámetros en vivo (forma, lesiones, altitud, calor, ventaja de anfitrión, peso xG, ρ) |
| POST | `/api/simulate/group` | Tabla Monte Carlo de clasificación de un grupo |
| POST | `/api/simulate/tournament` | Probabilidades de clasificar a R32 de las 48 selecciones |

Documentación OpenAPI interactiva en `http://localhost:8001/docs`.

## Estructura del repositorio

```
docker-compose.yml     Despliegue con un solo comando (frontend + backend)
backend/app/engine/    Motor predictivo (config, núcleo matemático, predictor,
                       simuladores Monte Carlo, calibración MLE, capa de datos)
backend/app/data/      Dataset de 48 selecciones + catálogo de 16 sedes (junio 2026)
backend/tests/         Tests de integridad del motor y de la API
frontend/src/i18n.tsx  Traducciones EN/ES/PT + contexto de idioma
frontend/src/three/    Escena 3D temática de sangre con React Three Fiber
frontend/src/components/  Dashboard, tablas de grupos, análisis interactivo
research.md            Documento fuente de investigación profunda
monteCarlo.py          Pipeline predictivo original de un solo archivo (referencia)
```

## Procedencia

El dataset y la fundamentación del modelo derivan de `research.md` (Fases 1–3:
infraestructura, clima, logística, fisiología, táctica y la base matemática de
Dixon-Coles). El motor refactoriza y extiende `monteCarlo.py`.
