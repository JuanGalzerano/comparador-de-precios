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
