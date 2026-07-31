import Link from "next/link";
import { money } from "@/lib/format";

/**
 * Campos en comun entre `ProductCluster` (`/search`) y `SavedProduct`
 * (`/me/favorites`) — ver `lib/types.ts`. Se tipa acá con
 * `min_final_price`/`max_final_price` como `string | null` (el shape más
 * amplio, el de `SavedProduct`) porque un `ProductCluster` con `string` es
 * asignable a esto sin cast.
 */
export interface ProductClusterCardData {
  id: number;
  canonical_title: string;
  brand: string | null;
  model: string | null;
  category: string | null;
  listing_count: number;
  min_final_price: string | null;
  max_final_price: string | null;
  best_score: number;
}

/**
 * Tarjeta de cluster de producto — extraida de la lista de resultados de
 * `/search` en `app/page.tsx` para reusarla también en `/guardados` y en las
 * secciones nuevas de la home ("Productos relevantes"/"Mejores oportunidades").
 * Mismo layout/clases que el original, sin cambios visuales.
 */
export function ProductClusterCard({ cluster }: { cluster: ProductClusterCardData }) {
  return (
    <Link
      href={`/productos/${cluster.id}`}
      style={{
        display: "grid",
        gridTemplateColumns: "88px minmax(0, 1fr) 210px",
        gap: "var(--space-6)",
        alignItems: "center",
        padding: "var(--space-4) 0",
        borderBottom: "1px solid color-mix(in srgb, var(--color-text) 8%, transparent)",
        textDecoration: "none",
        color: "inherit",
      }}
    >
      <div
        style={{
          aspectRatio: "1",
          borderRadius: "var(--radius-sm)",
          background:
            "repeating-linear-gradient(135deg, var(--color-neutral-900) 0 6px, var(--color-bg) 6px 12px)",
        }}
      />

      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 16, fontWeight: 500, letterSpacing: "-0.01em" }}>
          {cluster.canonical_title}
        </div>
        <div className="text-muted" style={{ fontSize: 13, marginTop: 3 }}>
          {[cluster.brand, cluster.model, cluster.category].filter(Boolean).join(" · ")}
        </div>
        <div className="text-muted num" style={{ fontSize: 13, marginTop: "var(--space-3)" }}>
          {cluster.listing_count} {cluster.listing_count === 1 ? "publicación" : "publicaciones"} ·
          score máximo {cluster.best_score}
        </div>
      </div>

      <div style={{ textAlign: "right" }}>
        {cluster.min_final_price === null ? (
          <div className="text-muted num" style={{ fontSize: 14 }}>
            sin publicaciones vigentes
          </div>
        ) : (
          <>
            <div className="num" style={{ fontSize: 22, letterSpacing: "-0.02em" }}>
              {money(cluster.min_final_price)}
            </div>
            <div className="text-muted" style={{ fontSize: 12, marginTop: 2 }}>
              la más barata de {cluster.listing_count}
            </div>
            {cluster.max_final_price !== null && cluster.max_final_price !== cluster.min_final_price && (
              <div style={{ fontSize: 13, marginTop: "var(--space-3)", color: "var(--color-accent)" }}>
                hasta {money(cluster.max_final_price)}
              </div>
            )}
          </>
        )}
      </div>
    </Link>
  );
}
