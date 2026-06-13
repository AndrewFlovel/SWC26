# SWC26 — Instrucciones de instalación

> 🌐 [English](SETUP.md) · **Español**

Hay dos formas de ejecutar la plataforma: **Docker** (recomendada, sin toolchain
local) o **desarrollo local** (recarga en caliente en ambos lados).

---

## Opción A — Docker (recomendada)

### Requisitos previos

- Docker Engine 24+ con el plugin de Compose (`docker compose version`)

### Ejecución

```bash
git clone https://github.com/AndrewFlovel/SWC26.git
cd SWC26
docker compose up --build
```

| Servicio | URL | Notas |
| --- | --- | --- |
| Frontend | <http://localhost:5173> | nginx sirve la app compilada y redirige `/api` al backend |
| Backend | <http://localhost:8001> | FastAPI + uvicorn; documentación OpenAPI en `/docs` |

Detén con `Ctrl+C`, o con `docker compose down` si lo iniciaste con `-d`.

### Cómo se comunican los contenedores

La imagen del frontend se compila con `VITE_API_BASE=""`, de modo que la app hace
peticiones relativas `/api/*` a su propio origen. nginx (ver `frontend/nginx.conf`)
las redirige a `http://backend:8001` por la red de Compose — sin CORS de por medio.

---

## Opción B — Desarrollo local

### Requisitos previos

- Python **3.10+** (se recomienda 3.12+)
- Node.js **20+** y npm
- Puertos libres: **8001** (backend) y **5173** (frontend)

### 1. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8001
```

Verificación rápida:

```bash
curl http://localhost:8001/api/health
# {"status":"ok","teams":48}
```

### 2. Frontend

En una segunda terminal:

```bash
cd frontend
npm install
npm run dev
```

Abre <http://localhost:5173>. En modo desarrollo la app llama directamente al
backend en `http://localhost:8001` (el CORS para el origen de Vite ya está
configurado). Para apuntar a otro motor, define `VITE_API_BASE`:

```bash
VITE_API_BASE=http://mi-servidor:9000 npm run dev
```

### 3. Tests

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

Resultado esperado: `56 passed` (motor predictivo, seguimiento de resultados y analizador de jugadores).

### 4. Build de producción del frontend (opcional)

```bash
cd frontend
npm run build      # genera frontend/dist
npm run preview    # sirve el bundle de producción localmente
```

---

## Uso de la plataforma

1. **Elige un grupo** (A–L). Las tarjetas de partido muestran sede, jornada y
   distintivos ambientales (⛰ altitud ≥ 1.000 m, 🔥 carga térmica WBGT,
   ★ selección anfitriona).
2. **Haz clic en un partido** para abrir el modal de análisis.
3. **Mueve los controles**: forma xG, impacto de lesiones, altitud, calor, mezcla
   xG/Elo, ventaja de anfitrión. Cada cambio dispara una nueva predicción con
   debounce (~250 ms): las barras de victoria/empate/derrota, los marcadores más
   probables y el mapa de calor de marcador exacto se actualizan en vivo.
4. **Abre un análisis de jugadores** con el botón "⚔ Análisis de jugadores" del modal
   de partido. La superposición scrapea ambas plantillas (con respaldo semilla) y
   muestra tarjetas de jugador con su Player Performance Score, un campo SVG con un
   mapa de dominio 3×3, la tabla de duelos posicionales y un optimizador del mejor
   once. Se incluyen plantillas semilla para España, Uruguay, Argentina y Austria
   (prueba Uruguay vs España en el Grupo H, o Argentina vs Austria en el Grupo J);
   el resto de partidos muestra un aviso de "sin datos de plantilla".
5. **Cambia el idioma** (EN/ES/PT) con el selector de arriba a la derecha. La
   elección se guarda en `localStorage`; en la primera visita se detecta
   automáticamente el idioma del navegador.

## Solución de problemas

| Síntoma | Solución |
| --- | --- |
| `address already in use` en 8001/5173 | Otro proceso ocupa el puerto. Deténlo, o cambia el mapeo en `docker-compose.yml` / las banderas `--port`. |
| El frontend muestra "Motor inaccesible" | El backend no está corriendo, o `VITE_API_BASE` apunta al host equivocado. Verifica con `curl localhost:8001/api/health`. |
| Fondo negro pero sin escena 3D | WebGL no está disponible en tu navegador/GPU; la app usa un degradado estático como respaldo por diseño. |
| `docker compose` no toma los cambios | Usa `docker compose up --build` (la bandera `--build` fuerza la reconstrucción de imágenes). |
