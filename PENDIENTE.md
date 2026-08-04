# Pendiente — todo lo que falta hacer en Cotejo

Actualizado 2026-08-04. Orden: de lo más bloqueante a lo más futuro.
Distingue entre lo que tenés que hacer **vos** y lo que puede hacer Claude.

## Lo que ya NO está pendiente (se hizo el 2026-08-04)

- ~~Cetrogar y Naldo no están en la base~~ → cargados, con datos reales.
- ~~Gráfico de historial de precios~~ → hecho.
- ~~Matching entre tiendas~~ → hecho (`app/matching/`), 32 productos comparados entre
  2 y 3 tiendas.
- ~~Página de transparencia~~ → `/como-funciona`, con datos en vivo.
- ~~SEO / sitemap~~ → hecho (falta Open Graph con imagen).
- ~~Responsive mobile~~ → verificado a 390px.

**El único bloqueo real que queda es el token de MercadoLibre.** Todo lo demás ya
funciona con Frávega, Cetrogar y Naldo.

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

## ✅ Tiendas activas hoy (con datos reales en la base)

| Tienda | Cómo se obtiene | Publicaciones | Mejor precio en |
|--------|-----------------|---------------|-----------------|
| **Frávega** | API GraphQL propia (`/api/v2`) | 159 | 75% de los productos comparados |
| **Cetrogar** | VTEX Intelligent Search | 141 | 45% |
| **Naldo** | VTEX Intelligent Search | 126 | 30% |

Para traer más productos:

```bash
python -m app.workers.ingest cetrogar --term "smart tv 55" --max-results 24
```

La ingesta corre el matcher sola al terminar (`--no-match` para saltearlo).

---

## 🟡 FEATURES PENDIENTES (Claude puede implementarlos cuando vos lo pidas)

Estas cosas **no las hice todavía** porque esperaban que el MVP básico estuviera sólido. Decime cuál querés primero.

### A. ✅ Gráfico de historial de precios — HECHO (2026-08-04)
- SVG propio en `frontend/components/PriceHistoryChart.tsx`, sin librerías nuevas.
- Muestra el precio más bajo por día de los últimos 90 días.
- **Para que tenga datos de verdad necesita ingestas repetidas en el tiempo** (hoy hay
  1-2 días de historial). Eso lo resuelve el punto C.

### B. Alertas de bajada de precio
- El usuario guardado pone un precio objetivo → el worker avisa cuando se alcanza.
- Necesitás definir: ¿aviso por email? ¿por notificación push? ¿solo en el panel?
- **Decisión tuya** sobre el canal; implementación la hace Claude.

### C. Worker de ingesta automático — el pendiente más importante

Hoy la ingesta corre a mano (`python -m app.workers.ingest`), así que **los precios son
una foto del día que la corrí y el gráfico de historial casi no tiene puntos**. Sin esto,
la promesa de "detectar ofertas que no bajaron nada" no se puede cumplir: no hay con qué
comparar.

**Qué es Upstash / Redis (por si no te suena):** Redis es una base de datos en memoria,
muy rápida. Acá no se usa para guardar productos (eso sigue en Postgres) sino como **cola
de tareas**: la lista de "traer precios de Frávega a las 9, a las 13 y a las 17". Celery
es el programa que lee esa cola y ejecuta las tareas. Upstash es un Redis alojado en la
nube, con plan gratis de 10.000 comandos por día — muchísimo más de lo que esto necesita.

Dos caminos, elegí uno:

| | Upstash + Celery | Programador de tareas de Windows |
|---|---|---|
| Costo | Gratis | Gratis |
| Sirve para producción | Sí | No — solo mientras tu PC esté prendida |
| Qué tenés que hacer | Crear cuenta en upstash.com, crear una base Redis, copiar el `REDIS_URL` y pasármelo | Nada, lo configuro yo |
| Cuánto tarda | 5 minutos tuyos | 0 |

**Mi recomendación:** empezá por el Programador de tareas de Windows para que el historial
se empiece a llenar desde hoy, y pasá a Upstash cuando subas el sitio a internet. Decime
"configurá la tarea programada" y lo hago.

### D. ✅ Matching entre tiendas — HECHO (2026-08-04)
- `app/matching/` agrupa el mismo producto de distintas tiendas. 32 clusters
  multi-tienda hoy.
- Lo que falta: la vía de embeddings para categorías donde el título no trae código de
  modelo (ropa, muebles, genéricos). Con electro/tecnología el matcher actual alcanza.

### E. Panel de administración
- Ver salud de las fuentes (ya hay datos: `GET /sources`), disparar ingestas, revisar
  matches dudosos (ya se acumulan en `product_match` con su confianza).
- **Lo hace Claude.**

### F. ✅ Página de transparencia — HECHA: `/como-funciona`

### G. SEO / sitemap — hecho salvo la imagen de Open Graph
- Falta una imagen `og:image` (necesita una decisión de diseño tuya o una imagen).

### H. ✅ Responsive mobile — verificado a 390px y 1600×600

### I. Categorías / navegación por rubro
- Los productos creados por el matcher no tienen `category`, así que no hay forma de
  navegar "todos los celulares". Se puede inferir de los títulos o del breadcrumb que
  devuelve cada tienda.
- **Lo hace Claude.**

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
| 🟡 Pronto | Contratar Redis (Upstash gratis) para que la ingesta corra sola — sin eso el historial de precios no se llena | **Vos** |
| 🟡 Pronto | Elegir el canal de las alertas de precio (email / push / panel) | **Vos** |
| 🟡 Pronto | Categorías por producto + panel de admin | Claude |
| 🔵 Cuando quieras lanzar | Contratar Neon + Railway + Vercel + dominio | **Vos** |
| 🔵 Cuando quieras lanzar | Pedir a Claude que conecte todo | Claude |
| 🔵 Post-lanzamiento | Aplicar a AdSense | **Vos** |
