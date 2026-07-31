import Link from "next/link";
import { money } from "@/lib/format";

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
  permalink?: string | null;
}

// Paleta de colores por categoría de producto
const AVATAR_PALETTE: Record<string, { bg: string; fg: string }> = {
  celular:   { bg: "rgba(124, 110, 224, 0.14)", fg: "#b5abfc" },
  iphone:    { bg: "rgba(124, 110, 224, 0.14)", fg: "#b5abfc" },
  samsung:   { bg: "rgba(91, 142, 224, 0.14)",  fg: "#93c5fd" },
  laptop:    { bg: "rgba(91, 142, 224, 0.14)",  fg: "#93c5fd" },
  notebook:  { bg: "rgba(91, 142, 224, 0.14)",  fg: "#93c5fd" },
  macbook:   { bg: "rgba(91, 142, 224, 0.14)",  fg: "#93c5fd" },
  audio:     { bg: "rgba(224, 124, 110, 0.14)", fg: "#fca5a5" },
  auricular: { bg: "rgba(224, 124, 110, 0.14)", fg: "#fca5a5" },
  parlante:  { bg: "rgba(224, 124, 110, 0.14)", fg: "#fca5a5" },
  tv:        { bg: "rgba(224, 185, 110, 0.14)", fg: "#fcd34d" },
  smart:     { bg: "rgba(224, 185, 110, 0.14)", fg: "#fcd34d" },
  tablet:    { bg: "rgba(110, 224, 185, 0.14)", fg: "#6ee7b7" },
  gaming:    { bg: "rgba(110, 224, 124, 0.14)", fg: "#86efac" },
  playstat:  { bg: "rgba(110, 224, 124, 0.14)", fg: "#86efac" },
  camara:    { bg: "rgba(224, 124, 185, 0.14)", fg: "#f0abfc" },
  impres:    { bg: "rgba(176, 110, 224, 0.14)", fg: "#d8b4fe" },
};

function getAvatarColors(cluster: ProductClusterCardData): { bg: string; fg: string } {
  const key = [cluster.category, cluster.brand, cluster.canonical_title]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  for (const [k, v] of Object.entries(AVATAR_PALETTE)) {
    if (key.includes(k)) return v;
  }
  return { bg: "rgba(145, 132, 217, 0.14)", fg: "#b5abfc" };
}

function scoreBadgeClass(score: number): string {
  if (score >= 65) return "score-badge score-high";
  if (score >= 35) return "score-badge score-mid";
  return "score-badge score-low";
}

function scoreLabel(score: number): string {
  if (score >= 65) return "buena opción";
  if (score >= 35) return "aceptable";
  return "score bajo";
}

export function ProductClusterCard({ cluster }: { cluster: ProductClusterCardData }) {
  const minPrice = cluster.min_final_price != null ? parseFloat(cluster.min_final_price) : null;
  const maxPrice = cluster.max_final_price != null ? parseFloat(cluster.max_final_price) : null;
  const savings = minPrice != null && maxPrice != null && maxPrice > minPrice
    ? maxPrice - minPrice
    : 0;
  const savingsPct =
    savings > 0 && maxPrice ? Math.min(100, Math.round((savings / maxPrice) * 100)) : 0;

  const { bg, fg } = getAvatarColors(cluster);
  const letter = (cluster.brand ?? cluster.canonical_title ?? "?")[0].toUpperCase();

  const cardContent = (
    <>
      {/* Avatar */}
      <div
        className="product-avatar"
        style={{ background: bg, color: fg }}
        aria-hidden="true"
      >
        {letter}
      </div>

      {/* Info principal */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {cluster.category && (
          <div
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--color-accent)",
              marginBottom: 4,
              fontWeight: 500,
            }}
          >
            {cluster.category}
          </div>
        )}
        <div
          style={{
            fontSize: 15.5,
            fontWeight: 500,
            letterSpacing: "-0.01em",
            lineHeight: 1.3,
          }}
        >
          {cluster.canonical_title}
        </div>
        {(cluster.brand || cluster.model) && (
          <div className="text-muted" style={{ fontSize: 12.5, marginTop: 3 }}>
            {[cluster.brand, cluster.model].filter(Boolean).join(" · ")}
          </div>
        )}

        {/* Badges */}
        <div
          style={{
            marginTop: "var(--space-3)",
            display: "flex",
            alignItems: "center",
            gap: "var(--space-2)",
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontSize: 12,
              color: "color-mix(in srgb, var(--color-text) 45%, transparent)",
            }}
          >
            {cluster.listing_count}{" "}
            {cluster.listing_count === 1 ? "publicación" : "publicaciones"}
          </span>
          <span className={scoreBadgeClass(cluster.best_score)}>
            {scoreLabel(cluster.best_score)}
          </span>
        </div>

        {/* Barra de ahorro */}
        {savingsPct > 6 && (
          <div style={{ marginTop: "var(--space-2)", maxWidth: 260 }}>
            <div className="savings-bar">
              <div className="savings-bar-fill" style={{ width: `${savingsPct}%` }} />
            </div>
            <div
              style={{
                fontSize: 11,
                marginTop: 3,
                color: "var(--color-accent-300)",
              }}
            >
              ahorrás hasta {money(savings)} eligiendo bien
            </div>
          </div>
        )}
      </div>

      {/* Precio */}
      <div style={{ textAlign: "right", flexShrink: 0, minWidth: 140 }}>
        {minPrice == null ? (
          <div className="text-muted" style={{ fontSize: 13 }}>
            sin publicaciones
          </div>
        ) : (
          <>
            <div
              className="num"
              style={{
                fontSize: 22,
                fontWeight: 500,
                letterSpacing: "-0.03em",
                color: "var(--color-text)",
              }}
            >
              {money(minPrice)}
            </div>
            <div className="text-muted" style={{ fontSize: 11.5, marginTop: 2 }}>
              precio más bajo
            </div>
            {maxPrice != null && maxPrice > minPrice && (
              <div
                className="text-muted num"
                style={{ fontSize: 12.5, marginTop: "var(--space-2)" }}
              >
                hasta {money(maxPrice)}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );

  if (cluster.permalink) {
    return (
      <a
        href={cluster.permalink}
        target="_blank"
        rel="noopener noreferrer"
        className="cluster-card"
      >
        {cardContent}
      </a>
    );
  }

  return (
    <Link href={`/productos/${cluster.id}`} className="cluster-card">
      {cardContent}
    </Link>
  );
}
