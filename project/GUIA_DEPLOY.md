# 🚀 INSTRUCCIONES PARA PUBLICAR P2P SENTINEL PRO EN LA NUBE

> **Para tu IA:** Este archivo contiene todo lo que necesitas saber para ayudar al usuario
> a publicar este proyecto en producción. El código ya fue corregido. Solo falta configurar
> el servidor. Lee todo este documento y guía al usuario paso a paso.

---

## ¿Qué es este proyecto?

Un dashboard en tiempo real que monitorea precios P2P de Binance (USDT/VES y USDT/USD).
Tiene 3 procesos que deben correr simultáneamente:

| Proceso | Archivo | Qué hace | Puerto |
|---------|---------|----------|--------|
| **Dashboard** | `app.py` | UI web (Streamlit) | 8501 |
| **API** | `api.py` | Endpoints JSON (FastAPI) | 8080 |
| **Worker** | `worker.py` | Scraper de Binance (background) | — |

---

## ¿Qué ya fue corregido en el código?

✅ El AJAX ya no apunta a `localhost` — detecta la URL automáticamente  
✅ La API ya acepta conexiones externas (`0.0.0.0`)  
✅ Los paths de DB y logs son configurables vía variables de entorno  
✅ Self-heal se desactiva automáticamente en producción  

---

## ¿Qué falta configurar? (tu trabajo, IA)

El usuario necesita ayuda para:

1. **Elegir una plataforma cloud** (si no tiene una)
2. **Configurar los 3 procesos** para que corran en paralelo
3. **Configurar almacenamiento persistente** para la base de datos SQLite
4. **Configurar un reverse proxy** para que `/api` y `/` apunten correctamente
5. **(Opcional)** Configurar proxy residencial si Binance bloquea las IPs del datacenter

---

## Variables de entorno disponibles

```bash
# OBLIGATORIAS EN PRODUCCIÓN
ENVIRONMENT=production              # Desactiva self-heal
API_HOST=0.0.0.0                    # Ya es el default, pero mejor ser explícito
API_PORT=8080                       # Puerto de la API

# RECOMENDADAS
P2P_DATA_DIR=/ruta/persistente      # Directorio para DB y logs (DEBE ser persistente)
P2P_API_URL=https://tudominio.com/api  # URL pública de la API (solo si NO usas reverse proxy)

# OPCIONAL
PROXY_URL=http://user:pass@proxy:8080  # Proxy residencial para scraping
```

---

## Guía por plataforma

### Opción A: Render.com (recomendada para principiantes)

**Paso 1:** Crear cuenta en render.com y conectar el repositorio de GitHub.

**Paso 2:** Crear 3 servicios:

1. **Web Service** (Dashboard Streamlit):
   - Build Command: `pip install -r project/requirements.txt`
   - Start Command: `streamlit run project/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true`
   - Environment: `ENVIRONMENT=production`

2. **Web Service** (API FastAPI):
   - Build Command: `pip install -r project/requirements.txt`
   - Start Command: `python -m project.api`
   - Environment: `API_HOST=0.0.0.0`, `API_PORT=8080`

3. **Background Worker** (Scraper):
   - Build Command: `pip install -r project/requirements.txt`
   - Start Command: `python -m project.worker`
   - Environment: `ENVIRONMENT=production`

**Paso 3:** Crear un **Render Disk** (almacenamiento persistente):
   - Montar en `/data` en los 3 servicios
   - Agregar variable: `P2P_DATA_DIR=/data`

**Paso 4:** Configurar `P2P_API_URL` en el servicio del Dashboard:
   - Valor: la URL pública del servicio API (ej: `https://mi-api.onrender.com/api`)

---

### Opción B: Railway.app

**Paso 1:** Crear proyecto en Railway y conectar GitHub.

**Paso 2:** Crear 3 servicios con estos start commands:

```
# Servicio 1: Dashboard
streamlit run project/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true

# Servicio 2: API
python -m project.api

# Servicio 3: Worker
python -m project.worker
```

**Paso 3:** Agregar un volumen persistente montado en `/data`.
- Variable: `P2P_DATA_DIR=/data`

**Paso 4:** Usar Railway's internal networking para conectar el Dashboard con la API,
o configurar `P2P_API_URL` con la URL pública del servicio API.

---

### Opción C: VPS (DigitalOcean, Hetzner, etc.)

Si el usuario tiene un VPS, la forma más simple es usar Docker Compose.

**Paso 1:** Crear este `docker-compose.yml` en la raíz del proyecto:

```yaml
version: '3.8'

services:
  dashboard:
    build: .
    command: streamlit run project/app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true
    ports:
      - "8501:8501"
    environment:
      - ENVIRONMENT=production
      - P2P_DATA_DIR=/data
      - P2P_API_URL=http://api:8080/api
    volumes:
      - p2p_data:/data
    depends_on:
      - api

  api:
    build: .
    command: python -m project.api
    ports:
      - "8080:8080"
    environment:
      - API_HOST=0.0.0.0
      - API_PORT=8080
      - P2P_DATA_DIR=/data
    volumes:
      - p2p_data:/data

  worker:
    build: .
    command: python -m project.worker
    environment:
      - ENVIRONMENT=production
      - P2P_DATA_DIR=/data
    volumes:
      - p2p_data:/data

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - dashboard
      - api

volumes:
  p2p_data:
```

**Paso 2:** Crear `Dockerfile` en la raíz:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY project/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

**Paso 3:** Crear `nginx.conf` en la raíz:

```nginx
server {
    listen 80;

    location /api/ {
        proxy_pass http://api:8080/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://dashboard:8501/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**Paso 4:** Ejecutar:
```bash
docker-compose up -d
```

---

## ⚠️ Nota sobre scraping desde la nube

Binance tiene protección anti-bot (Cloudflare). Desde IPs de datacenter, el scraper puede
ser bloqueado. Si ves muchos errores 403 o 429 en los logs del worker:

**Solución simple:** Dejar el worker corriendo en una computadora local (casa) y solo
publicar el dashboard + API en la nube. El worker escribe a la misma DB (si usas
PostgreSQL) o puedes sincronizar la DB via rsync/scp.

**Solución pro:** Contratar un servicio de proxy residencial (Bright Data, Oxylabs) y
configurar la variable `PROXY_URL`. Esto requiere modificar `scraper.py` para usar el proxy.

---

## Checklist final

- [ ] Los 3 procesos están corriendo (dashboard, api, worker)
- [ ] La DB está en almacenamiento persistente (no se borra al reiniciar)
- [ ] El dashboard puede conectarse a la API (no sale "Reconectando...")
- [ ] El worker está recolectando datos (ver logs o heartbeat en el dashboard)
- [ ] `ENVIRONMENT=production` está seteado

---

*Archivo generado automáticamente. Código ya corregido — solo falta configurar el servidor.*
