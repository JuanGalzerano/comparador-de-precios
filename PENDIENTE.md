# Pendiente — todo lo que falta hacer en Cotejo

Generado 2026-07-31. Orden: de lo más bloqueante a lo más futuro.
Distingue entre lo que tenés que hacer **vos** y lo que puede hacer Claude.

---

## 🔴 BLOQUEO 1 — MercadoLibre OAuth (te bloquea tener datos reales de ML)

Necesitás una cuenta en el portal de devs de ML y un token. Sin esto, el `MercadoLibreAdapter` existe y tiene tests pero **no puede hacer ninguna llamada real**.

### Pasos (los hacés vos)

1. Entrá a **https://developers.mercadolibre.com.ar** con tu cuenta de ML.
2. **Crear aplicación** → nombre: `cotejo-dev`, dominio: `localhost`, redirect URI: `http://localhost:8000/auth/ml/callback`, scope: `read`.
3. Copiá el `client_id` y `client_secret` que te da ML.
4. En `backend/.env` agregá:
   ```
   ML_CLIENT_ID=<tu_client_id>
   ML_CLIENT_SECRET=<tu_client_secret>
   ```
5. Corrés este curl para obtener el token:
   ```bash
   curl -X POST https://api.mercadolibre.com/oauth/token \
     -H "content-type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials&client_id=TU_CLIENT_ID&client_secret=TU_CLIENT_SECRET"
   ```
6. Copiás el `access_token` de la respuesta y lo agregás a `backend/.env`:
   ```
   ML_ACCESS_TOKEN=APP_USR-xxxxxx
   ```
7. **Avisarme** → Claude modifica `app/config.py` y `app/adapters/mercadolibre.py` (son 3 líneas de código) para inyectar el token.
8. Corrés la ingesta real: `python -m app.workers.ingest mercadolibre --term "iphone 13" --max-results 20`

> Guía completa: `MERCADOLIBRE_API.md` en la raíz del proyecto.

---

## 🔴 BLOQUEO 2 — Cetrogar y Naldo no están en la base de datos

Los adapters ya existen y funcionan. Falta que las tiendas tengan su fila en `retailer_source` para poder correr la ingesta.

### Pasos (te pido que me digas "agregá Cetrogar y Naldo" — Claude lo hace)

Claude inserta en `dev.db`:
```sql
INSERT INTO retailer_source (slug, display_name, kind, base_url, status)
VALUES
  ('cetrogar', 'Cetrogar', 'vtex', 'https://www.cetrogar.com.ar', 'active'),
  ('naldo',    'Naldo',    'vtex', 'https://www.naldo.com.ar',    'active');
```
Y corre la ingesta. Podés simplemente decirme "agregá Cetrogar y Naldo" y lo hago yo.

---

## 🟡 FEATURES PENDIENTES (Claude puede implementarlos cuando vos lo pidas)

Estas cosas **no las hice todavía** porque esperaban que el MVP básico estuviera sólido. Decime cuál querés primero.

### A. Gráfico de historial de precios en el frontend
- Página de producto con línea de precio a lo largo del tiempo.
- Necesita un chart (Recharts o Chart.js) y un fetch a `GET /products/{id}/price-history`.
- **Lo hace Claude completo.**

### B. Alertas de bajada de precio
- El usuario guardado pone un precio objetivo → el worker avisa cuando se alcanza.
- Necesitás definir: ¿aviso por email? ¿por notificación push? ¿solo en el panel?
- **Decisión tuya** sobre el canal; implementación la hace Claude.

### C. Worker de ingesta automático (Celery + cron)
- Hoy la ingesta corre a mano (`python -m app.workers.ingest`).
- Para que los precios se actualicen solos necesitás Redis + Celery.
- Necesitás contratar Redis (Upstash gratis sirve para empezar — ver `INFRAESTRUCTURA.md`).
- Una vez que tenés el `REDIS_URL`, Claude arma el worker de Celery.

### D. Matching entre tiendas (dedup de productos)
- Hoy cada tienda tiene sus propias filas en `product`. Para mostrar "mismo producto en 3 tiendas" necesitás el matcher (fuzzy + embeddings).
- **Lo hace Claude** una vez que haya datos de ≥2 tiendas.

### E. Panel de administración
- Ver salud de las fuentes, disparar ingestas, revisar matches dudosos.
- **Lo hace Claude.**

### F. Página de transparencia / "cómo funciona"
- Por buenas prácticas y para AdSense, conviene tener un `/como-funciona` que explique qué es Cotejo y de dónde salen los datos.
- **Lo hace Claude.**

### G. SEO / Open Graph / sitemap
- `<meta>` tags, `sitemap.xml`, `robots.txt`.
- **Lo hace Claude.**

### H. Responsive mobile
- El frontend funciona en desktop. Hay que revisar que todo se vea bien en celular.
- **Lo hace Claude** (requiere que puedas abrir el preview en un celular o DevTools).

---

## 🟡 ADAPTERS PENDIENTES (investigación a continuar)

| Tienda | Estado | Próximo paso |
|--------|--------|-------------|
| **Musimundo** | En mantenimiento (2026-07-31) | Cuando vuelva online, Claude investiga su API y arma el adapter |
| **Garbarino** | Timeout/bloqueado (curl da 000) | Claude puede probar en browser cuando vos me avisés |
| **Mexx** | Sitio custom PHP, sin VTEX ni GraphQL evidente | Claude puede investigar en browser |
| **Ribeiro** | 301 → sitio online, no investigado aún | Claude puede probar |

Para avanzar con estos: decime "investigá Garbarino" y lo abro en el browser.

---

## 🔵 INFRAESTRUCTURA — para ir a producción (todo requiere acción tuya)

Nada de esto es necesario para desarrollo local. Lo hacés cuando quieras subir el sitio.

### 1. Base de datos Postgres en la nube
- Recomendado: **Neon** (gratis para dev, escala sola).
- Pasos: crear cuenta en neon.tech → crear proyecto → copiar `DATABASE_URL`.
- Una vez que tenés la URL, Claude adapta `backend/.env` y corre las migraciones.

### 2. Backend (FastAPI) en producción
- Recomendado: **Railway** (tiene free tier, deploy desde GitHub con un clic).
- Pasos:
  1. Crear cuenta en railway.app.
  2. "New Project" → "Deploy from GitHub repo" → elegir `comparador-de-precios/backend`.
  3. Configurar variables de entorno en Railway (las mismas que en `.env`).
  4. Railway te da una URL pública (ej. `api.cotejo.ar` si tenés dominio).

### 3. Frontend (Next.js) en Vercel
- Pasos:
  1. Crear cuenta en vercel.com.
  2. "Import Project" → conectar tu repositorio GitHub.
  3. Root directory: `frontend`.
  4. Agregar variable: `NEXT_PUBLIC_API_URL=https://tu-backend.railway.app`.
  5. Vercel despliega automáticamente en cada push a `main`.

### 4. Redis (para Celery / alertas)
- Recomendado: **Upstash** (gratis hasta 10k req/día).
- Crear cuenta en upstash.com → crear Redis → copiar `REDIS_URL`.
- Agregar `REDIS_URL` al `.env` y a Railway/Render.

### 5. Dominio
- Comprar `cotejo.ar` (o `.com` si `.ar` no está disponible) en NIC.ar o Namecheap.
- Apuntar DNS:
  - `cotejo.ar` → Vercel (frontend)
  - `api.cotejo.ar` → Railway (backend)

### 6. Google AdSense
- Necesitás el sitio online con dominio propio antes de aplicar.
- Aplicás en adsense.google.com con la URL del sitio publicado.
- Google demora 1-4 semanas en aprobar.
- Una vez aprobado, Claude integra los snippets en el frontend.

### 7. CI/CD (GitHub Actions)
- Para que los tests corran automáticamente antes de cada deploy.
- Claude puede crear el workflow `.github/workflows/ci.yml` cuando vos quieras.

### 8. Monitoreo en producción
- Saber cuándo el sitio cae o un adapter se rompe.
- Opciones gratuitas: Better Uptime (ping), Sentry (errores de código).
- Claude integra Sentry en el backend/frontend cuando vos lo indiques.

---

## 🔵 DECISIONES QUE TENÉS QUE TOMAR VOS

1. **¿Nombre de dominio?** → `cotejo.ar`, `cotejo.com.ar`, `comparador.ar`…
2. **¿Primero historial de precios o primero matching entre tiendas?** (ambos son útiles antes de lanzar)
3. **¿Canal para alertas de precio?** → Email (necesita SendGrid/Resend), push notification, o solo panel interno.
4. **¿Cuándo querés subir el sitio a producción?** → Condiciona cuándo empezar la infra.
5. **¿Querés agregar login con Google/GitHub además del login propio?** → Requiere OAuth de Google.

---

## Resumen ejecutivo

| Urgencia | Tarea | Quién |
|----------|-------|-------|
| 🔴 Ahora | Crear app ML en devs portal y conseguir access_token | **Vos** |
| 🔴 Ahora | Avisar a Claude para wrapear el token en el adapter | Claude |
| 🔴 Ahora | Agregar Cetrogar y Naldo a la DB | Claude (cuando vos lo pedís) |
| 🟡 Pronto | Elegir cuál feature construir primero (historial, matching, alertas) | **Vos** |
| 🟡 Pronto | Esperar que Musimundo vuelva de mantenimiento | Esperar |
| 🔵 Cuando quieras lanzar | Contratar Neon + Railway + Vercel + dominio | **Vos** |
| 🔵 Cuando quieras lanzar | Pedir a Claude que conecte todo | Claude |
| 🔵 Post-lanzamiento | Aplicar a AdSense | **Vos** |
