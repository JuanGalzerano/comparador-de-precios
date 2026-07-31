import { NextResponse } from "next/server";
import { API_URL } from "@/lib/config";

/**
 * Proxy de `POST /auth/login`. Route Handler (no Server Action) porque hay
 * que reenviar el header `Set-Cookie` CRUDO que manda el backend — la cookie
 * de sesion es `HttpOnly` y se setea en la respuesta HTTP, no algo que un
 * Server Action pueda producir (esos no tienen acceso a la response cruda).
 */
export async function POST(request: Request) {
  const body = await request.text();

  const upstream = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    cache: "no-store",
  });

  const payload = upstream.status === 204 ? null : await upstream.json().catch(() => null);
  const res = NextResponse.json(payload, { status: upstream.status });
  for (const c of upstream.headers.getSetCookie()) res.headers.append("set-cookie", c);
  return res;
}
