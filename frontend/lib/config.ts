/**
 * URL base del backend (FastAPI). Sale de `NEXT_PUBLIC_API_URL` — nunca
 * hardcodeada en el codigo de las paginas (ver `.env.local.example`).
 *
 * El fallback a `http://localhost:8000` es solo una comodidad de desarrollo
 * local (mismo criterio que `backend/app/config.py` usa para `database_url`:
 * un default razonable para local, nunca para produccion) — cualquier
 * despliegue real DEBE definir la variable de entorno explicitamente.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * URL publica del sitio. Se usa en el sitemap, en `robots.txt` y como `metadataBase`
 * de las etiquetas Open Graph.
 *
 * Sale de `NEXT_PUBLIC_SITE_URL` porque el dominio propio todavia no existe: mientras
 * el sitio viva en `*.vercel.app`, tener `cotejo.ar` hardcodeado hacia que el sitemap
 * listara URLs inexistentes y que Google indexara mal.
 */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
