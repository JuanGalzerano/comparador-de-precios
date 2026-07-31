import { redirect } from "next/navigation";
import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import { getCurrentUser, sessionHeader } from "@/lib/session";
import type { SavedProductsResponse } from "@/lib/types";
import { ProductClusterCard } from "@/components/ProductClusterCard";

/** Productos guardados del usuario logueado. Mismo guard de sesion que
 * `/mi-perfil`; el listado pega a `GET /me/favorites` y reusa la misma
 * tarjeta de cluster que `/` y los resultados de busqueda. */
export default async function GuardadosPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/ingresar?next=/guardados");

  const url = `${API_URL}/me/favorites?${new URLSearchParams({ page: "1", page_size: "50" })}`;
  const result = await fetchJson<SavedProductsResponse>(url, { headers: await sessionHeader() });

  return (
    <main
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "var(--space-8) var(--space-8) 80px",
        width: "100%",
      }}
    >
      <div style={{ padding: "56px 0 var(--space-6)" }}>
        <h2 style={{ margin: 0 }}>Guardados</h2>
      </div>

      {!result.ok ? (
        <div className="card" style={{ maxWidth: 620 }}>
          <div className="card-title">No pudimos cargar tus guardados</div>
          <p className="card-body">
            {result.kind === "network"
              ? `No pudimos conectar con el backend en ${API_URL}. Verificá que esté corriendo.`
              : `El backend respondió con un error (${result.status}).${
                  result.message ? ` ${result.message}` : ""
                }`}
          </p>
        </div>
      ) : result.data.items.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 14 }}>
          Todavía no guardaste ningún producto.
        </p>
      ) : (
        <div>
          {result.data.items.map((product) => (
            <ProductClusterCard key={product.id} cluster={product} />
          ))}
        </div>
      )}
    </main>
  );
}
