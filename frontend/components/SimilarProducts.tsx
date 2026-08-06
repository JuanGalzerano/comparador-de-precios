import Link from "next/link";
import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import { money, toNumber } from "@/lib/format";
import type { SimilarProduct, SimilarProductsResponse } from "@/lib/types";

/**
 * "Productos similares" — modelos parecidos, NO el mismo producto.
 *
 * Van separados de la tabla comparativa por una razón concreta: el cartel de "ahorrás
 * hasta X" solo tiene sentido cuando las publicaciones son del mismo producto. Si un
 * modelo vecino más barato entrara al cluster, ese número diría que ahorrás plata
 * cuando en realidad estarías comprando otra cosa. Acá el precio se muestra sin
 * prometer ahorro: es una alternativa para mirar, no una comparación.
 */
export async function SimilarProducts({ productId }: { productId: number }) {
  const result = await fetchJson<SimilarProductsResponse>(
    `${API_URL}/products/${productId}/similar?limit=6`,
  );
  if (!result.ok || result.data.items.length === 0) return null;

  return (
    <section style={{ marginTop: 56 }}>
      <div className="section-header">
        <h2 className="section-title">Similares</h2>
        <span className="text-muted" style={{ fontSize: 12 }}>
          otros modelos parecidos, no el mismo producto
        </span>
        <span className="section-count">{result.data.items.length}</span>
      </div>

      <div className="similar-grid">
        {result.data.items.map((item) => (
          <SimilarCard key={item.id} item={item} />
        ))}
      </div>
    </section>
  );
}

function SimilarCard({ item }: { item: SimilarProduct }) {
  const min = item.min_final_price != null ? toNumber(item.min_final_price) : null;

  return (
    <Link href={`/productos/${item.id}`} className="similar-card">
      <div style={{ fontSize: 13.5, fontWeight: 500, lineHeight: 1.35 }}>
        {item.canonical_title}
      </div>

      {(item.brand || item.model) && (
        <div className="text-muted" style={{ fontSize: 11.5, marginTop: 3 }}>
          {[item.brand, item.model].filter(Boolean).join(" · ")}
        </div>
      )}

      <div style={{ marginTop: "auto", paddingTop: "var(--space-3)" }}>
        <div className="num" style={{ fontSize: 17, letterSpacing: "-0.02em" }}>
          {min != null ? money(min) : "sin precio"}
        </div>
        <div className="text-muted" style={{ fontSize: 11, marginTop: 2 }}>
          {item.retailer_count > 1
            ? `en ${item.retailer_count} tiendas`
            : `${item.listing_count} ${item.listing_count === 1 ? "publicación" : "publicaciones"}`}
        </div>
      </div>
    </Link>
  );
}
