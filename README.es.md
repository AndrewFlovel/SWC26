# SWC26 — Sangre y Gloria

> 🌐 [English](README.md) · **Español** · Guías de instalación: [EN](SETUP.md) / [ES](SETUP.es.md)

**Plataforma interactiva de analítica predictiva para la Copa Mundial FIFA 2026**,
construida a partir de telemetría de investigación profunda sobre las 48 selecciones
clasificadas: ratings Elo, perfiles tácticos xG/xGA, momento de forma, desgaste por
lesiones, carga de viajes transcontinentales, hipoxia de altitud y estrés térmico WBGT.

Oscura, rojo sangre, impulsada por WebGL. Mueve los controles deslizantes: el motor
recalcula en tiempo real. Abre cualquier partido para un desglose jugador por jugador:
valoraciones de plantilla, enfrentamientos de formación, un optimizador del mejor once y
una descarga con un clic de las **alineaciones confirmadas del día del partido**. La
interfaz está disponible en **inglés, español y portugués** (selector arriba a la
derecha; también detecta automáticamente el idioma del navegador).

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

## Analizador de jugadores por partido

Más allá del modelo a nivel de selección, cualquier partido puede abrirse para un
desglose **jugador por jugador**. Al seleccionar un encuentro se dispara un scraping
híbrido de plantillas — `requests` contra las tablas de FBref (renderizadas en el
servidor), con plantillas semilla incluidas como respaldo fiable (Selenium con Chrome
headless añade las alineaciones confirmadas del día del partido bajo demanda — ver
abajo). Cada jugador recibe
un **Player Performance Score (PPS)**: una mezcla ponderada por rol de facetas
ofensivas, defensivas y físicas, cada una normalizada contra rangos de referencia
fijos del fútbol de élite, de modo que los puntajes son absolutos y comparables entre
plantillas.

A partir de dos onces el motor deriva el enfrentamiento de forma geométrica — funciona
con cualquier par de formaciones, sin tablas codificadas a mano:

- **PMS** — puntajes de duelo posicional (cada atacante contra los defensores que lo marcan)
- **FSI** — un único Índice de Fuerza de Formación, simétrico, para el enfrentamiento
- **PIS** — desajuste de presión vs progresión de balón entre los equipos
- **PDH** — un mapa de calor de dominio territorial de 3×3
- **Once óptimo** — la mejor alineación para una formación frente a un rival dado,
  mediante la asignación húngara (`scipy.optimize.linear_sum_assignment`), con
  alternativas ordenadas

La interfaz abre una superposición a pantalla completa (Plantilla · Formación · Duelos ·
Optimizador) con un campo SVG, nodos de jugador coloreados por PPS y el mapa de dominio.
Se incluyen plantillas semilla para España, Uruguay, Argentina y Austria (partidos
Uruguay–España y Argentina–Austria); el resto de partidos degrada con elegancia hasta
que sus plantillas se scrapeen o se sembren.

**Alineaciones confirmadas.** La acción "XI confirmado" obtiene los onces titulares
anunciados desde Sofascore mediante Chrome headless. Como esa página se renderiza en el
cliente y el scraping es lento, se ejecuta como tarea en segundo plano
(`POST /api/scrape/lineups`) que la interfaz consulta
(`GET /api/scrape/players/status/{fixture_id}`); cuando ambos onces están confirmados se
emparejan con la plantilla, se ordenan en las posiciones de la formación y se aplican al
campo — si no, el analizador mantiene su once óptimo. El scraper nunca lanza excepciones:
la falta de Chrome, un partido sin mapear o alineaciones aún no anunciadas recurren al
once óptimo.

| Método | Ruta | Propósito |
| --- | --- | --- |
| GET | `/api/players/{slug}` | Plantilla con PPS de una selección — semilla o scrapeada |
| POST | `/api/scrape/players` | Scrapea ambas plantillas de un partido (FBref, respaldo semilla) |
| POST | `/api/analyze/lineup` | FSI, presión, duelos posicionales y mapa de dominio 3×3 de dos onces |
| POST | `/api/analyze/optimal-xi` | Mejor once (húngaro) frente a un rival — top-3 candidatos |
| GET | `/api/formations` | Coordenadas de las posiciones por formación (4-3-3, 4-2-3-1, 4-4-2, 3-5-2) |
| POST | `/api/scrape/lineups` | Inicia un scrape de XI confirmado en segundo plano (Sofascore, Chrome headless) |
| GET | `/api/scrape/players/status/{fixture_id}` | Consulta el estado/resultado del trabajo de alineación confirmada |

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
                       simuladores Monte Carlo, calibración MLE, capa de datos) +
                       analizador de jugadores (modelos de jugador, scorer PPS,
                       analizador de alineación/FSI/once-óptimo)
backend/app/services/  Almacén de resultados + replay de métricas, scraper del día,
                       la caché de plantillas + scraper híbrido de jugadores (FBref), y
                       el scraper Selenium de alineaciones confirmadas + registro de
                       trabajos en segundo plano (hilos)
backend/app/data/      Dataset de 48 selecciones + catálogo de 16 sedes; data/players/
                       guarda plantillas semilla (España, Uruguay, Argentina, Austria)
backend/tests/         Tests del motor, de resultados y del analizador de jugadores
frontend/src/i18n.tsx  Traducciones EN/ES/PT + contexto de idioma
frontend/src/three/    Escena 3D temática de sangre con React Three Fiber
frontend/src/components/  Dashboard, tablas de grupos, análisis interactivo, y el
                       analizador de jugadores (tarjetas de plantilla, campo SVG +
                       mapa de calor, duelos posicionales, optimizador de alineación)
research.md            Documento fuente de investigación profunda
monteCarlo.py          Pipeline predictivo original de un solo archivo (referencia)
```

## Procedencia

El dataset y la fundamentación del modelo derivan de `research.md` (Fases 1–3:
infraestructura, clima, logística, fisiología, táctica y la base matemática de
Dixon-Coles). El motor refactoriza y extiende `monteCarlo.py`.
