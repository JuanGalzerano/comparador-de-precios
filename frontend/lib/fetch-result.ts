/**
 * Wrapper generico de `fetch` + clasificacion de error — NO es un cliente de
 * API (no tiene metodos por endpoint): cada pagina sigue construyendo su
 * propia URL e invocando `fetchJson` directo, como pide la tarea ("Server
 * Components con fetch() directo... en vez de un cliente API separado").
 * Esto solo evita repetir el mismo try/catch de red en cada pagina, porque
 * el prototipo (`project/`) no manejaba NINGUN estado de error (gap
 * explicito del plan) y las dos paginas necesitan el mismo manejo.
 */
export type FetchResult<T> =
  | { ok: true; data: T }
  | { ok: false; kind: "network"; message: string }
  | { ok: false; kind: "http"; status: number; message: string };

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<FetchResult<T>> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, cache: "no-store" });
  } catch (error) {
    return {
      ok: false,
      kind: "network",
      message: error instanceof Error ? error.message : "No se pudo conectar con el servidor.",
    };
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // el body de error no es JSON (o esta vacio): sin detalle adicional
    }
    return { ok: false, kind: "http", status: response.status, message: detail };
  }

  return { ok: true, data: (await response.json()) as T };
}
