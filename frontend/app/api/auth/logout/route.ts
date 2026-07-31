import { NextResponse } from "next/server";
import { API_URL } from "@/lib/config";
import { sessionHeader } from "@/lib/session";

/**
 * Proxy de `POST /auth/logout`. Sin body: reenvia la cookie de sesion actual
 * como header `Cookie` (para que el backend sepa que fila de `user_session`
 * borrar) y reenvia el `Set-Cookie` de borrado que manda el backend de vuelta
 * al browser — mismo patron que `login`/`register`, ver ahi.
 */
export async function POST() {
  const upstream = await fetch(`${API_URL}/auth/logout`, {
    method: "POST",
    headers: await sessionHeader(),
    cache: "no-store",
  });

  const payload = upstream.status === 204 ? null : await upstream.json().catch(() => null);
  const res = NextResponse.json(payload, { status: upstream.status });
  for (const c of upstream.headers.getSetCookie()) res.headers.append("set-cookie", c);
  return res;
}
