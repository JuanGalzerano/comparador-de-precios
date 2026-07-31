import { NextResponse } from "next/server";
import { API_URL } from "@/lib/config";

/** Proxy de `POST /auth/register` — mismo patron que `login/route.ts` (ver ahi). */
export async function POST(request: Request) {
  const body = await request.text();

  const upstream = await fetch(`${API_URL}/auth/register`, {
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
