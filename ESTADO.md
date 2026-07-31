# Estado de Cotejo

Documento vivo. Se actualiza en cada iteración (implementación, revisión, o ronda de mejoras)
— no es una foto única, es el registro acumulado del proyecto.

Última actualización: 2026-07-31 (iteración 3).

---

## Funcionalidad actual (lo que YA funciona, verificado con tests y preview local)

- **Modelo de datos** (Postgres/SQLAlchemy): `retailer_source`, `product`, `listing`,
  `price_history`, `product_match`, `user_event`. Migración Alembic inicial aplicada.
- **Interfaz `SourceAdapter`**: contrato común para cualquier fuente de datos (API, VTEX,
  feed SEPA, scraper), con modos `search` / `batch` / `refresh`.
- **`MercadoLibreAdapter`**: búsqueda, refresco de precios por lote, normalización de
  garantía/reputación de vendedor. 24 tests, sin llamadas de red reales (mockeadas).
- **`score_of()`**: score compuesto (precio, reputación, opiniones, garantía, envío/cuotas)
  portado 1:1 desde el prototipo, con tests de los casos límite.
- **`GET /search`**: agrupa publicaciones por producto (clusters), pagina, ordena por precio
  final mínimo.
- **`GET /products/{id}`**: ficha con listings ordenables/filtrables + score.
- **`GET /products/{id}/price-history`**: serie de precios (ventana de 90 días).
- **Worker de ingesta** (`app/workers/ingest.py`): llama al adapter, normaliza, hace upsert
  en `listing` y agrega un punto de `price_history` solo cuando cambia precio/envío (evita
  ruido). Errores por item no rompen el resto del batch; errores de fuente completa sí se
  propagan y marcan `retailer_source.last_error`. CLI: `python -m app.workers.ingest <slug>`.
- **51 tests pasando** en total (corridos contra SQLite en memoria — ver limitación abajo).
- **Frontend Next.js real** (`frontend/`): páginas `/` (home + búsqueda), `/ingresar`
  (login/registro toggle), `/mi-perfil` (guard de sesión server-side), `/guardados`
  (favoritos paginados). Header real con buscador y bloque de sesión (`HeaderAuth`).
- **Secciones home** ("Productos relevantes" + "Mejores oportunidades") alimentadas por
  `GET /search` sin filtro — heurística de spread mientras no haya historial de 90 días.
- **Detección de URL de MercadoLibre en el buscador**: al pegar una URL de ML, `SearchInput`
  extrae los términos del slug de la URL (Client Component), y el Server Component muestra
  un banner "Buscamos el mejor precio para X en todas las fuentes" + link "Ver en ML →".
  Soporta fichas de catálogo (`/slug/p/MLAXXX`), publicaciones directas (`/MLAXXX-slug`),
  y URLs cortas (`/p/MLAXXX`).
- **Backend corriendo sobre SQLite local** (`dev.db`, 2 productos / 5 listings de ejemplo)
  para desarrollo sin Postgres. Verificado: `GET /health`, `GET /search?q=iphone` devuelven
  datos reales.

## Errores conocidos / supuestos sin verificar

Cosas que se escribieron con la mejor información disponible pero que necesitan chequeo
contra la realidad antes de confiar en ellas a ciegas:

1. **Mapeo de nivel de vendedor de ML** (`power_seller_status` → platinum/gold/silver/green):
   asumido por lectura de documentación, no verificado contra una respuesta real de la API.
2. **Parser de garantía en texto libre** (`WARRANTY_TIME`/`WARRANTY_TYPE`): cubre los formatos
   más comunes ("N meses", "N años", "N días"), no exhaustivo — puede fallar con frases raras
   ("garantía extendida", rangos).
3. **Nombre de tienda oficial**: se aproxima con el nickname del vendedor cuando hay
   `official_store_id`, no se resuelve el nombre real (requiere una llamada extra no
   implementada).
4. **Costo de envío**: solo se completa cuando es gratis; el costo real no está disponible sin
   una llamada dependiente del código postal del comprador, así que queda `None` en vez de
   inventado.
5. **Sin Postgres real conectado todavía**: todo el desarrollo y los tests corrieron contra
   SQLite en memoria porque no hay una instancia de Postgres alcanzable en este entorno. La
   columna generada `final_price` se comportó igual en ambos motores (verificado), pero el
   proyecto nunca corrió contra el motor real de producción.
6. **Precios Claros / SEPA**: no se confirmó todavía si las cadenas de electro/tecnología
   realmente publican ahí (falta el spike de investigación, ver plan).

## Mejoras pendientes (por fase, ver plan completo)

- **Frontend real en Next.js**: ✅ implementado (iteración 3). Páginas, header, home,
  detección de URL de ML — todo funcionando en `http://localhost:3000` contra el backend.
- Historial de precios con gráfico en el frontend + alertas de baja de precio.
- Programar el worker de ingesta (Celery/cron) para que corra solo — hoy `app/workers/ingest.py`
  existe y funciona pero hay que ejecutarlo a mano o vía CLI.
- Adapter VTEX (Frávega/Cetrogar) — pendiente de aprobación explícita por el riesgo de ToS.
- Matching/dedup entre tiendas (fuzzy + embeddings) — recién tiene sentido con ≥2 fuentes.
- Panel de administración (salud de fuentes, cola de revisión de matches).
- SEO/SSR, accesibilidad, responsive mobile, analytics.
- Página de transparencia (qué fuente es API oficial vs. no sancionada).

Plan completo con fases y tabla de delegación por modelo:
`C:\Users\juani\.claude\plans\ahora-hace-un-plan-idempotent-chipmunk.md`.

---

## Qué necesita esto para funcionar de verdad (infraestructura pendiente)

Hoy todo corre local (SQLite de test, servidor no desplegado). Para que sea un sitio real
hace falta:

| Pieza | Para qué | Estado |
| --- | --- | --- |
| **Base de datos Postgres en la nube** | Persistencia real de `product`/`listing`/`price_history`. Opciones típicas: Neon, Supabase, Railway, RDS. | ❌ No contratada |
| **Servidor/hosting para la API (FastAPI)** | Correr el backend 24/7. Opciones: Railway, Render, Fly.io, un VPS. | ❌ No desplegado |
| **Redis** | Cola de Celery para los jobs de ingesta (correr los adapters de forma programada). | ❌ No existe |
| **Hosting del frontend (Next.js)** | Servir el sitio real al público. Opción típica: Vercel. | ❌ Frontend real ni siquiera existe todavía |
| **Dominio propio** | Identidad del sitio, necesario también para Google AdSense. | ❌ No comprado |
| **Gestión de secrets en el hosting** | `DATABASE_URL`, `REDIS_URL`, futuras API keys — nunca en el repo. | ❌ Pendiente (hoy todo vive en `.env` local) |
| **CI** | Correr los tests automáticamente en cada cambio antes de desplegar. | ❌ No configurado |
| **Monitoreo/logs en producción** | Saber cuándo un adapter se rompe o el sitio cae. | ❌ No configurado |
| **Cuenta de Google AdSense** | Monetización planeada. | ❌ No solicitada |

Ninguna de estas piezas es necesaria para seguir desarrollando localmente — sí lo son para
que el sitio esté online y lo use gente real.

---

## Historial de iteraciones

- **2026-07-30 (1)**: diseño inicial (modelo de datos, interfaz de adapters, skeleton
  FastAPI) + `MercadoLibreAdapter` + `score_of()` + endpoints `/search`/`/products`. Todo
  local, sin desplegar.
- **2026-07-30 (2)**: revisor confirmó 44/44 tests OK, sin discrepancias vs. este documento;
  detectó que nada poblaba la base todavía → se implementó el worker de ingesta
  (`app/workers/ingest.py`, 7 tests nuevos, 51/51 total). Nota del revisor: `backend/` sigue
  sin trackear en git (no se commiteó, a la espera de que el usuario lo pida). El usuario
  reprioriza manualmente: siguiente iteración va directo a frontend Next.js en vez del
  próximo ítem que hubiera elegido el revisor.
- **2026-07-31 (3)**: frontend Next.js completo verificado en preview local. Páginas
  login/registro/perfil/favoritos + header real + secciones home implementadas. Feature:
  detección de URL de MercadoLibre en el buscador (`lib/ml-url.ts`, `SearchInput.tsx`,
  banner en `page.tsx`). Backend corriendo sobre SQLite local con `.env` de desarrollo.
  Creados `INFRAESTRUCTURA.md` (guía de integración Vercel/Railway/Neon/Redis/AdSense).
