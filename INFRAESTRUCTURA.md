# Infraestructura de itsfree.dev — Guía de integración

Documento de referencia: qué herramienta cubre qué parte del stack de Cotejo y
cómo conectarla. Se actualiza a medida que se contratan los servicios.

---

## Stack objetivo (producción)

```
Usuario
  │
  ▼
[Vercel]         ← Next.js frontend (SSR + API Routes)
  │ fetch()
  ▼
[Railway / Render]  ← FastAPI backend (uvicorn)
  │
  ├─► [Neon / Supabase]  ← PostgreSQL (productos, listings, historial)
  └─► [Upstash Redis]    ← Cola Celery para workers de ingesta
```

---

## 1. Vercel — Hosting del frontend (Next.js)

**Para qué:** servir el sitio al público con SSR, CDN global, deploys automáticos.

**Integración:**
1. Conectar el repo de GitHub a Vercel (import project).
2. Root directory: `frontend/`.
3. Framework preset: Next.js (auto-detectado).
4. Variables de entorno en el dashboard de Vercel:
   ```
   NEXT_PUBLIC_API_URL=https://api.cotejo.ar   # URL del backend en Railway/Render
   ```
5. Cada push a `main` dispara un deploy. PRs generan preview URLs.

**Dominio:** en Settings → Domains → agregar `cotejo.ar` (o `itsfree.dev`).

**Free tier:** 100 GB de ancho de banda/mes, builds ilimitados en repos personales.

---

## 2. Railway — Hosting del backend (FastAPI) + PostgreSQL

**Para qué:** correr `uvicorn app.main:app` 24/7 y opcionalmente el worker Celery.

**Integración:**
1. New project → Deploy from GitHub repo → seleccionar el repo.
2. Root directory: `backend/`.
3. Start command: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Variables de entorno en Railway:
   ```
   DATABASE_URL=postgresql+psycopg2://<user>:<pw>@<host>/<db>
   REDIS_URL=redis://:@<host>:<port>/0
   CORS_ORIGINS=["https://cotejo.ar","https://www.cotejo.ar"]
   COTEJO_ENV=production
   ```
5. Agregar plugin PostgreSQL desde el dashboard (Railway provisiona Postgres
   automáticamente y pone `DATABASE_URL` como variable interna).
6. Para Redis: agregar plugin Redis de Railway o usar Upstash (ver §5).

**Alternativa:** Render.com — misma idea, distinta UI. Railway tiene mejor DX.

---

## 3. Neon — PostgreSQL serverless (alternativa a Railway Postgres)

**Para qué:** base de datos Postgres managed con branching (útil para tests en CI).

**Integración:**
1. Crear proyecto en neon.tech → obtener connection string.
2. Usar como `DATABASE_URL` en Railway/Render:
   ```
   postgresql+psycopg2://user:pw@ep-xxx.us-east-2.aws.neon.tech/cotejo?sslmode=require
   ```
3. En `backend/app/db.py`, agregar `connect_args={"sslmode": "require"}` si se usa Neon:
   ```python
   engine = create_engine(settings.database_url, connect_args={"sslmode": "require"}, ...)
   ```
4. Neon soporta branching: crear un branch `dev` para tests de CI sin tocar producción.

**Free tier:** 0.5 GB storage, 1 proyecto, branch ilimitados.

---

## 4. Supabase — Alternativa a Neon con más servicios

**Para qué:** Postgres + Auth + Storage + Realtime en uno.

**Cuándo elegirlo sobre Neon:** si en el futuro se quiere agregar auth de terceros
(Google, GitHub) o realtime (alertas de precio en vivo con websockets).

**Integración actual:** igual que Neon — solo se usa el string de conexión Postgres.
El resto de features de Supabase no se usan hoy (la auth es propia).

---

## 5. Upstash Redis — Cola para workers Celery

**Para qué:** el worker `app/workers/ingest.py` necesita una cola para ejecutarse
de forma programada sin bloquear la API. Celery usa Redis como broker.

**Integración:**
1. Crear database en upstash.com → copiar `REDIS_URL` (formato `redis://...`).
2. Instalar Celery: `pip install celery[redis]`.
3. Crear `backend/app/celery_app.py`:
   ```python
   from celery import Celery
   from app.config import settings
   celery = Celery("cotejo", broker=settings.redis_url, backend=settings.redis_url)
   celery.conf.beat_schedule = {
       "ingest-ml-every-hour": {
           "task": "app.workers.ingest.run",
           "schedule": 3600,
           "args": ["mercadolibre"],
       }
   }
   ```
4. En Railway: agregar un segundo servicio con start command:
   ```
   python -m celery -A app.celery_app worker --beat -l info
   ```

**Free tier:** 10.000 comandos/día, 256 MB.

---

## 6. GitHub Actions — CI

**Para qué:** correr los 51 tests automáticamente en cada PR antes de mergear.

**Integración:** crear `.github/workflows/ci.yml`:
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e "backend/[dev]"
      - run: pytest backend/tests/
        env:
          DATABASE_URL: sqlite+pysqlite:///./test.db
```

**Costo:** gratis para repos públicos, 2000 min/mes en repos privados.

---

## 7. Google AdSense — Monetización

**Para qué:** ingresos por publicidad display (banner en resultados de búsqueda).

**Integración en Next.js:**
1. Agregar el script de AdSense en `frontend/app/layout.tsx`:
   ```tsx
   <Script
     src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-XXXXXXX"
     strategy="lazyOnload"
     crossOrigin="anonymous"
   />
   ```
2. Crear componente `<AdBanner slot="XXXXXXX" />` y colocarlo entre secciones.
3. Verificar el dominio en la consola de AdSense (subir archivo HTML de verificación
   o usar meta tag en `<head>`).

**Requisitos:** el sitio debe estar en línea con contenido real y tráfico mínimo
antes de que AdSense apruebe la cuenta.

---

## 8. Dominio propio (Namecheap / NIC.ar)

**Para qué:** identidad del sitio, requerido por AdSense y para confiar credibilidad.

**Integración con Vercel:**
1. Comprar dominio (ej. `cotejo.ar` en NIC.ar o `cotejo.com` en Namecheap).
2. En Vercel → Settings → Domains → Add Domain.
3. Vercel da los nameservers o registros DNS a apuntar.
4. Certificado TLS automático (Let's Encrypt via Vercel).

---

## Resumen de estado actual vs. producción

| Pieza                | Local (hoy)          | Producción (pendiente)         |
|----------------------|----------------------|-------------------------------|
| Base de datos        | SQLite (`dev.db`)    | Neon / Railway Postgres        |
| Backend              | `python -m uvicorn`  | Railway / Render               |
| Frontend             | `npm run dev` :3000  | Vercel                         |
| Cola de ingesta      | sin cola (CLI manual)| Upstash Redis + Celery beat    |
| CI                   | sin CI               | GitHub Actions                 |
| Dominio              | localhost            | Namecheap / NIC.ar             |
| AdSense              | sin ads              | Requiere dominio + tráfico real|
