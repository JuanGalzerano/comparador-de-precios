import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import type { Source, SourcesResponse } from "@/lib/types";

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  active: { label: "Activa", color: "#4ade80" },
  experimental: { label: "Experimental", color: "#facc15" },
  blocked_tos_review: { label: "Pausada por revisión de términos", color: "#fca5a5" },
  disabled: { label: "Desactivada", color: "var(--color-neutral-500)" },
};

const KIND_LABEL: Record<string, string> = {
  api: "API oficial de la plataforma",
  vtex: "API pública de catálogo de la tienda",
  feed: "Archivo público de datos",
  scraper: "Lectura del sitio público",
};

/**
 * Tabla de fuentes con datos reales de `GET /sources`, no una lista escrita a mano:
 * el estado de cada tienda y su competitividad de precio salen de lo que hay en la
 * base. Si el backend no responde, la sección simplemente no se muestra (la página
 * de transparencia sigue explicando el método sin ella).
 */
export async function SourcesTable() {
  const result = await fetchJson<SourcesResponse>(`${API_URL}/sources`);
  if (!result.ok || result.data.items.length === 0) return null;

  const sources = result.data.items;
  const withData = sources.filter((s) => s.listing_count > 0);

  return (
    <div style={{ marginTop: "var(--space-4)", display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {sources.map((source) => (
        <SourceCard key={source.slug} source={source} />
      ))}
      {withData.length > 0 && (
        <p className="text-muted" style={{ fontSize: 12, marginTop: "var(--space-2)" }}>
          &ldquo;Mejor precio&rdquo; se mide solo sobre los productos donde la tienda compite
          contra al menos otra: tener el precio más bajo cuando nadie más publica el producto
          no dice nada.
        </p>
      )}
    </div>
  );
}

function SourceCard({ source }: { source: Source }) {
  const status = STATUS_LABEL[source.status] ?? {
    label: source.status,
    color: "var(--color-neutral-500)",
  };
  const name = source.display_name ?? source.slug;
  const winPct = source.win_rate !== null ? Math.round(source.win_rate * 100) : null;

  return (
    <div className="card" style={{ padding: "var(--space-4)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "var(--space-3)",
          flexWrap: "wrap",
        }}
      >
        <div className="card-title" style={{ fontSize: 15 }}>
          {name}
        </div>
        <span style={{ fontSize: 11, fontWeight: 600, color: status.color, whiteSpace: "nowrap" }}>
          ● {status.label}
        </span>
      </div>

      <p className="card-body">
        {KIND_LABEL[source.kind] ?? source.kind}
        {source.tos_risk_note ? ` — ${source.tos_risk_note}` : ""}
      </p>

      {source.listing_count > 0 ? (
        <div
          className="num"
          style={{
            display: "flex",
            gap: "var(--space-8)",
            fontSize: 12,
            flexWrap: "wrap",
            marginTop: "var(--space-1)",
          }}
        >
          <span className="text-muted">
            {source.listing_count.toLocaleString("es-AR")} publicaciones
          </span>
          <span className="text-muted">
            {source.product_count.toLocaleString("es-AR")} productos
          </span>
          {winPct !== null && (
            <span style={{ color: "var(--color-accent-300)" }}>
              mejor precio en {winPct}% de los productos comparados
            </span>
          )}
        </div>
      ) : (
        <div className="text-muted" style={{ fontSize: 12 }}>
          Sin datos cargados todavía.
        </div>
      )}
    </div>
  );
}
