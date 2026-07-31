/**
 * Lectura de la cookie de sesion en Server Components / Route Handlers /
 * Server Actions. La cookie es `HttpOnly` (ver `backend/app/config.py`
 * `session_cookie_name`): nunca se lee ni se guarda desde codigo de cliente,
 * solo se reenvia como header `Cookie` en el `fetch` server-side al backend.
 */
import { cache } from "react";
import { cookies } from "next/headers";
import { API_URL } from "./config";
import { fetchJson } from "./fetch-result";
import type { User } from "./types";

export const SESSION_COOKIE = "cotejo_session";

export async function sessionHeader(): Promise<HeadersInit> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  return token ? { Cookie: `${SESSION_COOKIE}=${token}` } : {};
}

/**
 * `cache()`: memoiza por render/request de React — varias secciones de la
 * misma pagina (header, contenido) pueden pedir el usuario actual sin que
 * eso dispare mas de un `GET /auth/me` real.
 */
export const getCurrentUser = cache(async (): Promise<User | null> => {
  const res = await fetchJson<User>(`${API_URL}/auth/me`, { headers: await sessionHeader() });
  return res.ok ? res.data : null;
});
