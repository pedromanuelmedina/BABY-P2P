# 🔧 Reporte de Bugs: Local → Producción (Cloud)

**Proyecto:** P2P Sentinel Pro  
**Fecha:** 2026-10-09  
**Contexto:** El dashboard funciona correctamente en local pero falla en producción (cloud).  
**Objetivo:** Este documento contiene todos los bugs identificados, su ubicación exacta en el código, y las instrucciones paso a paso para corregirlos.

---

## Resumen Ejecutivo

Se identificaron **5 bugs críticos** que causan fallos en producción. El más grave (#1) hace que el dashboard se quede **completamente vacío** en la nube porque el JavaScript del AJAX polling intenta conectarse a `127.0.0.1` del navegador del usuario, no del servidor.

| #  | Severidad | Bug | Archivo(s) |
|----|-----------|-----|------------|
| 1  | 🔴 CRÍTICO | AJAX apunta a `localhost` — dashboard vacío en prod | `assets/ajax.js`, `api.py`, `app.py` |
| 2  | 🔴 CRÍTICO | SQLite en filesystem efímero — data se pierde en cada deploy | `database.py`, `worker.py`, `api.py`, `config.py` |
| 3  | 🟠 ALTO | Worker daemon no sobrevive en PaaS | `worker.py` |
| 4  | 🟡 MEDIO | Scraping bloqueado desde IPs de datacenter | `scraper.py`, `config.py` |
| 5  | 🟡 BAJO | Self-heal modifica código en prod (filesystem read-only) | `self_heal.py` |

---

## Bug #1: AJAX apunta a `localhost` (CRÍTICO)

### Problema

El archivo `assets/ajax.js` (línea 29) tiene hardcodeado:
```javascript
var apiBase = 'http://127.0.0.1:8080/api';
```

Este JavaScript se ejecuta **en el navegador del usuario**. En producción, el browser intenta conectarse a `127.0.0.1:8080` de la máquina del usuario (no del servidor cloud), lo que causa:
- Todas las llamadas `fetch()` fallan silenciosamente
- Los KPIs, watchlist, gráfico y heartbeat nunca se actualizan
- El dashboard queda **completamente vacío** tras la carga inicial

Adicionalmente, `api.py` (línea 169) bindea Uvicorn a `127.0.0.1`:
```python
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```
Esto **rechaza conexiones externas** en la nube.

Y `app.py` (línea 142) también tiene fallback a localhost:
```python
_api_url = os.environ.get("P2P_API_URL", "http://127.0.0.1:8080/api")
```

### Fix

#### 1. `assets/ajax.js` — Líneas 28-36: Usar URL relativa

**ANTES:**
```javascript
// Detectar URL base de la API
var apiBase = 'http://127.0.0.1:8080/api';
try {
    var host = win.location.hostname;
    if (host.indexOf('trycloudflare') !== -1 || host.indexOf('loca.lt') !== -1) {
        apiBase = win.__p2p_api_url || 'http://127.0.0.1:8080/api';
    }
} catch(e) { /* fallback */ }
var API_BASE = apiBase;
```

**DESPUÉS:**
```javascript
// Detectar URL base de la API dinámicamente
var apiBase;
try {
    // Si hay una URL explícita inyectada desde Streamlit/env, usarla
    apiBase = win.__p2p_api_url || null;
} catch(e) { apiBase = null; }

if (!apiBase) {
    // Construir URL basada en el origen actual del browser
    try {
        var proto = win.location.protocol;
        var host = win.location.hostname;
        var apiPort = win.__p2p_api_port || '8080';
        // En local, usar localhost:8080. En prod, usar el mismo host con el puerto de la API.
        if (host === 'localhost' || host === '127.0.0.1') {
            apiBase = proto + '//127.0.0.1:' + apiPort + '/api';
        } else {
            // En producción: la API debería estar detrás del mismo dominio (reverse proxy)
            // o en un subdominio/puerto accesible externamente.
            apiBase = proto + '//' + host + '/api';
        }
    } catch(e) {
        apiBase = '/api'; // Fallback: URL relativa (funciona con reverse proxy)
    }
}
var API_BASE = apiBase;
```

> **NOTA:** La solución más limpia en producción es poner un **reverse proxy** (Nginx, Caddy, Cloudflare Tunnel) que enrute `/api/*` al FastAPI y `/` al Streamlit. En ese caso, basta con `var API_BASE = '/api';`.

#### 2. `api.py` — Línea 169: Bindear a `0.0.0.0`

**ANTES:**
```python
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

**DESPUÉS:**
```python
host = os.environ.get("API_HOST", "0.0.0.0")
uvicorn.run(app, host=host, port=port, log_level="warning")
```

#### 3. `app.py` — Línea 142: Fallback inteligente

**ANTES:**
```python
_api_url = os.environ.get("P2P_API_URL", "http://127.0.0.1:8080/api")
```

**DESPUÉS:**
```python
_api_url = os.environ.get("P2P_API_URL", "/api")
```

> En producción, setear la variable de entorno `P2P_API_URL` a la URL pública de la API, o usar `/api` con reverse proxy.

---

## Bug #2: SQLite en filesystem efímero (CRÍTICO)

### Problema

La base de datos `p2p_sentinel.db` se guarda directamente en el directorio del proyecto:

- `worker.py` línea 44: `DB_PATH = os.path.join(os.path.dirname(__file__), "p2p_sentinel.db")`
- `api.py` línea 33: `DB_PATH = os.path.join(os.path.dirname(__file__), "p2p_sentinel.db")`
- `app.py` línea 147: `DB_PATH = os.path.join(os.path.dirname(__file__), L["db_path"])`

En plataformas cloud (Render, Heroku, Railway, Fly.io, contenedores Docker sin volúmenes), **el filesystem es efímero**: se resetea en cada deploy, restart o scaling event. **Toda la data histórica se pierde.**

Los logs también se escriben localmente:
- `worker.py` línea 47: `LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")`

### Fix — Opción A: Volumen persistente (si la plataforma lo soporta)

Mover `DB_PATH` a un directorio con almacenamiento persistente:

```python
# En config.py, agregar:
import os

DATA_DIR = os.environ.get("P2P_DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(DATA_DIR, "p2p_sentinel.db")
LOG_DIR = os.path.join(DATA_DIR, "logs")
```

Luego referenciar `config.DB_PATH` y `config.LOG_DIR` desde `worker.py`, `api.py` y `app.py` en vez de calcularlos localmente.

En producción, setear `P2P_DATA_DIR=/persistent/data` (Render Disk, Docker Volume, etc.).

### Fix — Opción B: Migrar a PostgreSQL (recomendado para escalar)

Reemplazar SQLite por PostgreSQL (Supabase, Neon, Railway Postgres, etc.):

1. Agregar `psycopg2-binary` o `asyncpg` a `requirements.txt`
2. Refactorizar `database.py` para usar `DATABASE_URL` de variable de entorno
3. Adaptar las queries (SQLite PRAGMAs no aplican en PostgreSQL)
4. Remover WAL checkpoint logic de `worker.py`

> **NOTA:** Si solo quieres que funcione rápido, Opción A es suficiente. Si planeas escalar o tener alta disponibilidad, Opción B es la correcta.

---

## Bug #3: Worker daemon no sobrevive en PaaS (ALTO)

### Problema

`worker.py` está diseñado para correr como proceso background:
```bash
nohup python3 worker.py &   # (línea 10 del docstring)
```

En PaaS (Render, Heroku, Railway), los procesos background se matan. Solo sobrevive el proceso principal (web).

### Fix

Depende de la plataforma:

**Opción A — Servicio/Worker separado:**
- Render: crear un "Background Worker" service aparte del web service
- Heroku: agregar `worker: python -m project.worker` al `Procfile`
- Railway: crear un servicio separado con `python -m project.worker`

**Opción B — Thread dentro de Streamlit (quick & dirty):**
```python
# En app.py, agregar al inicio (después de imports):
import threading
from .worker import main as worker_main

def _start_worker_thread():
    """Inicia el worker en un thread si no está corriendo."""
    if not hasattr(st, '_worker_started'):
        t = threading.Thread(target=worker_main, daemon=True, name="p2p-worker")
        t.start()
        st._worker_started = True

_start_worker_thread()
```

> **ADVERTENCIA:** La Opción B no es robusta. Si Streamlit reinicia, el worker muere. Usar solo como solución temporal.

**Opción C — Procfile (recomendado):**
```
web: streamlit run project/app.py --server.port=$PORT --server.address=0.0.0.0
worker: python -m project.worker
api: python -m project.api
```

---

## Bug #4: Scraping bloqueado desde IPs de datacenter (MEDIO)

### Problema

El scraper (`scraper.py`) implementa delays y User-Agent rotation, pero Binance P2P tiene protección Cloudflare agresiva. Las IPs de datacenter (AWS, GCP, DigitalOcean, Render, etc.) **son bloqueadas o rate-limited severamente** comparado con IPs residenciales.

Síntomas en producción:
- HTTP 403 Forbidden constantes
- HTTP 429 Too Many Requests frecuentes
- Timeouts
- El worker no logra recolectar datos

### Fix

**Opción A — Proxy residencial rotativo:**
```python
# En config.py, agregar:
PROXY_URL = os.environ.get("PROXY_URL", None)  # e.g., "http://user:pass@proxy.example.com:8080"

# En scraper.py, al crear el httpx.AsyncClient:
proxies = {"all://": config.PROXY_URL} if config.PROXY_URL else None
client = httpx.AsyncClient(proxies=proxies, ...)
```

Servicios de proxy recomendados: Bright Data, Oxylabs, SmartProxy.

**Opción B — Ejecutar worker en local, API en cloud:**
- Mantener el worker corriendo en una máquina local (residencial)
- Que el worker escriba directamente a una DB PostgreSQL en la nube
- El dashboard en la nube lee de esa DB

---

## Bug #5: Self-heal modifica código en producción (BAJO)

### Problema

`self_heal.py` con `--apply` ejecuta `ruff --fix` que **modifica archivos Python en disco** (línea 266):
```python
r = _run(["python3", "-m", "ruff", "check", "--fix", str(BASE_DIR)], timeout=30)
```

En producción:
- Containers Docker tienen filesystem **read-only** → crash
- Modificar código en runtime es un anti-patrón crítico de seguridad
- Requiere `ruff`, `mypy`, `pytest` en prod (bloat innecesario)

### Fix

1. **Desactivar self_heal en producción:**
```python
# Al inicio de main() en self_heal.py:
import os
if os.environ.get("ENVIRONMENT", "development") == "production":
    logger.info("Self-heal desactivado en producción")
    sys.exit(0)
```

2. **Mover a CI/CD:** ejecutar self_heal como step del pipeline de CI (GitHub Actions, GitLab CI).

3. **Separar dependencias:** crear `requirements-dev.txt` para ruff/mypy/pytest, no incluirlas en el build de producción.

---

## Variables de Entorno Requeridas en Producción

```bash
# Obligatorias
P2P_API_URL=/api                    # O la URL pública de la API
API_HOST=0.0.0.0                    # Permitir conexiones externas
API_PORT=8080                       # Puerto de la API FastAPI
ENVIRONMENT=production              # Desactivar self-heal

# Recomendadas
P2P_DATA_DIR=/persistent/data       # Directorio con volumen persistente
PROXY_URL=http://user:pass@proxy:8080  # Proxy residencial para scraping
DATABASE_URL=postgresql://...       # Si se migra a PostgreSQL
```

---

## Checklist de Deploy

- [ ] Cambiar `ajax.js` para usar URL dinámica o relativa (`/api`)
- [ ] Cambiar `api.py` para bindear a `0.0.0.0`
- [ ] Cambiar `app.py` para usar fallback `/api` en vez de `localhost`
- [ ] Configurar almacenamiento persistente para SQLite o migrar a PostgreSQL
- [ ] Configurar worker como servicio separado (no daemon suelto)
- [ ] Configurar proxy residencial para scraping (o ejecutar worker en local)
- [ ] Desactivar self-heal en producción
- [ ] Setear variables de entorno listadas arriba
- [ ] Configurar reverse proxy (Nginx/Caddy) para enrutar `/api/*` → FastAPI, `/` → Streamlit

---

## Arquitectura Recomendada para Producción

```
                    ┌──────────────────────────────────┐
                    │         Reverse Proxy             │
                    │    (Nginx / Caddy / Cloudflare)   │
                    │                                    │
                    │   /     → Streamlit (:8501)        │
                    │   /api  → FastAPI   (:8080)        │
                    └───────────────┬────────────────────┘
                                    │
                    ┌───────────────┼────────────────────┐
                    │               │                     │
              ┌─────▼─────┐  ┌─────▼─────┐  ┌───────────▼──┐
              │ Streamlit  │  │  FastAPI   │  │   Worker     │
              │  (web)     │  │  (api)     │  │  (daemon)    │
              │  :8501     │  │  :8080     │  │  background  │
              └─────┬──────┘  └─────┬──────┘  └──────┬───────┘
                    │               │                 │
                    └───────────────┼─────────────────┘
                                    │
                           ┌────────▼────────┐
                           │   PostgreSQL     │
                           │  (o SQLite +     │
                           │   persistent vol)│
                           └─────────────────┘
```

---

*Generado por análisis automatizado. Revisar cada fix antes de aplicar.*
