"use server";

import { revalidatePath } from "next/cache";
import { API_URL } from "@/lib/config";
import { sessionHeader } from "@/lib/session";

/**
 * Toggle de favorito — Server Action (no Route Handler): no hay ningun
 * `Set-Cookie` que reenviar aca (a diferencia de login/register/logout), y
 * `revalidatePath` sólo está disponible en Server Actions, no en Route
 * Handlers. `PUT`/`DELETE /me/favorites/{id}` devuelven 204 sin body.
 */
export async function toggleFavorite(productId: number, currentlySaved: boolean) {
  const method = currentlySaved ? "DELETE" : "PUT";
  const res = await fetch(`${API_URL}/me/favorites/${productId}`, {
    method,
    headers: await sessionHeader(),
    cache: "no-store",
  });

  if (res.status === 401) throw new Error("no autenticado");
  if (!res.ok) throw new Error("no se pudo actualizar favoritos");

  revalidatePath("/guardados");
  revalidatePath(`/productos/${productId}`);
  return { saved: !currentlySaved };
}
