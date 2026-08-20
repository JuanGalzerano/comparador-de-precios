# Cotejo — comparador de precios

Buscador que agrupa publicaciones de distintas tiendas para el **mismo producto** y las
ordena por un score compuesto (precio final con envío, cuotas, reputación del vendedor,
opiniones, garantía) — no solo por el precio más bajo.

## Estructura del repo

| Carpeta | Qué es |
| --- | --- |
| `backend/` | API real (Python/FastAPI/Postgres). Acá vive la lógica de búsqueda, el modelo de datos y los adapters de cada fuente. |
| `project/` | Prototipo de UI (HTML/CSS/JS, exportado de una herramienta de diseño) — es el spec visual de cada pantalla, no corre en producción. |

Plan completo de arquitectura y roadmap: `C:\Users\juani\.claude\plans\ahora-hace-un-plan-idempotent-chipmunk.md`.

## De dónde sale la información

| Fuente | Estado | Cómo se obtiene |
| --- | --- | --- |
| **Frávega** | ✅ Activa | API GraphQL pública del propio sitio (`/api/v2`). |
| **Cetrogar** | ✅ Activa | API pública de catálogo VTEX Intelligent Search. |
| **Naldo** | ✅ Activa | API pública de catálogo VTEX Intelligent Search. |
| **MercadoLibre** | ⛔ Cerrada | ML dejó de dar acceso a la búsqueda: con un token válido, `/sites/MLA/search` responde 403. El adapter, el token y su renovación funcionan — lo que falta es acceso, y no depende de nosotros (ver `PENDIENTE.md`). |
| **Precios Claros / SEPA** (dato oficial del gobierno argentino) | ⏳ Evaluando viabilidad | El Estado obliga a grandes cadenas a publicar precios en archivos diarios. Falta confirmar si las cadenas de electro/tecnología realmente reportan ahí antes de construir el importer. |
| **Musimundo, Garbarino, Compumundo y otras** | ❌ No integradas todavía | No tienen API pública accesible. Si en algún momento se suman, va a ser con scraping propio (servidor propio, nunca con la computadora del visitante — ver más abajo) y con aprobación explícita retailer por retailer. |

El estado y la competitividad de cada fuente se sirven en vivo en `GET /sources` y se
muestran en `/como-funciona`.

Cada fuente queda registrada con su estado (activa / experimental / bloqueada por revisión
de términos de servicio) — nada se activa en silencio.

**Sobre la idea de "que la computadora del cliente scrapee por nosotros":** se investigó y
se descartó. Un sitio no puede leer otro sitio desde el navegador del visitante por las
protecciones de seguridad del propio navegador (CORS / same-origin policy) — la única forma
real de lograrlo sería que el visitante instale una extensión, lo cual no está en el plan
actual. Todo el scraping, si se hace, corre en servidores propios.

## Qué busca diferenciar a Cotejo de otros comparadores

- **Agrupa por producto real, no por publicación suelta.** En vez de mostrar 15 listados
  casi iguales del mismo celular, se muestra un solo grupo con el rango de precios.
- **El orden no es solo "más barato primero".** El score pondera precio final (con envío),
  reputación del vendedor, cuotas sin interés, garantía y opiniones — un vendedor sin
  trayectoria con el precio más bajo no gana automáticamente.
- **Historial de precios real** (en desarrollo): compara el precio actual contra la mediana
  de los últimos 90 días, para detectar "ofertas" que en realidad no bajaron nada.
- **Transparencia de fuente:** cada resultado va a poder mostrar de qué tienda salió el dato
  y si esa fuente es API oficial o no — nada de presentar todo como si fuera igual de
  confiable.
- **Foco en Argentina.** Prioriza integrar retailers locales de electro/tecnología en vez de
  ser un comparador genérico global.
- **Gratuito, sin letra chica.** Se sostiene con publicidad (Google AdSense); el botón de
  compra siempre lleva a la publicación original de la tienda, nunca a un checkout propio.

## Estado actual (MVP funcionando en local)

- ✅ Modelo de datos (Postgres/SQLite) y arquitectura de adapters por fuente.
- ✅ Adapters de Frávega, Cetrogar, Naldo y MercadoLibre, con score testeado.
- ✅ Ingesta con datos reales: ~335 publicaciones de 3 tiendas.
- ✅ Matcher cross-retailer: el mismo producto de distintas tiendas cae en un solo cluster.
- ✅ Frontend Next.js: búsqueda, ficha comparativa, historial de precios, favoritos,
  cuenta de usuario, `/como-funciona`.
- ✅ 111 tests.
- ⏳ Ingesta programada (Celery/Redis), alertas de precio, panel de administración,
  categorías, despliegue.

Lo que falta y por qué, en `PENDIENTE.md`.

## Cómo correrlo en local

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
cd frontend && npm run dev
```

Traer productos nuevos de una tienda (corre el matcher al terminar):

```bash
cd backend && .venv/Scripts/python -m app.workers.ingest fravega --term "smart tv 55" --max-results 24
```
