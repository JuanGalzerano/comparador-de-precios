import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import { toNumber } from "@/lib/format";
import type { ProductCluster, SearchResponse } from "@/lib/types";
import { ProductClusterCard } from "@/components/ProductClusterCard";
import { SearchInput } from "@/components/SearchInput";
import { parseMlUrl } from "@/lib/ml-url";

interface HomePageProps {
  searchParams: Promise<{ q?: string }>;
}

/**
 * Home + busqueda, en una sola vista (como `isSearch` en el prototipo: la
 * busqueda reemplaza el contenido, no navega a otra pestaña). Sin resultado
 * de busqueda -> hero + secciones de descubrimiento; con `?q=` -> pega a
 * `GET /search` y muestra los clusters agrupados
 * (`project/Cotejo - Comparador.dc.html:96-126`).
 */
export default async function HomePage({ searchParams }: HomePageProps) {
  const { q } = await searchParams;
  const query = q?.trim() ?? "";

  const mlInfo = query ? parseMlUrl(query) : null;
  const effectiveQuery = mlInfo ? mlInfo.terms : query;

  return (
    <main
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "var(--space-8) var(--space-8) 80px",
        width: "100%",
      }}
    >
      {effectiveQuery === "" ? (
        <>
          <Hero />
          <DiscoverySections />
        </>
      ) : (
        <SearchResults query={effectiveQuery} />
      )}
    </main>
  );
}

function Hero() {
  return (
    <div className="hero-section">
      <div className="hero-glow" aria-hidden="true" />

      <div style={{ padding: "80px 0 32px", maxWidth: 680, position: "relative" }}>
        <h1 style={{
          fontSize: 52,
          marginBottom: 18,
          lineHeight: 1.04,
          letterSpacing: "-0.03em",
          fontWeight: 600,
        }}>
          Encontrá el mejor precio
          <br />
          <span style={{ color: "var(--color-accent)" }}>en todas las tiendas</span>
        </h1>

        <p style={{
          fontSize: 17,
          margin: 0,
          lineHeight: 1.6,
          maxWidth: 520,
          color: "color-mix(in srgb, var(--color-text) 65%, transparent)",
        }}>
          Comparamos MercadoLibre, Frávega, Cetrogar, Naldo y más —
          precio final con envío, cuotas y garantía.
        </p>
      </div>

      <form
        action="/"
        method="get"
        style={{ display: "flex", alignItems: "center", gap: 10, maxWidth: 560, position: "relative" }}
      >
        <SearchInput
          placeholder="Escribí un producto o pegá un link de MercadoLibre…"
          style={{ minHeight: 48, fontSize: 15, flex: 1, borderRadius: 10 }}
        />
        <button
          className="btn btn-solid"
          type="submit"
          style={{ minHeight: 48, paddingInline: 24, whiteSpace: "nowrap", borderRadius: 10, fontSize: 15 }}
        >
          Buscar
        </button>
      </form>

      <div style={{
        display: "flex",
        gap: 8,
        marginTop: 20,
        flexWrap: "wrap",
        position: "relative",
      }}>
        {["Sin comisión", "Actualizado periódicamente", "Link directo a la tienda"].map((t) => (
          <span key={t} style={{
            fontSize: 12,
            padding: "3px 10px",
            borderRadius: 100,
            background: "rgba(145,132,217,0.07)",
            border: "1px solid rgba(145,132,217,0.16)",
            color: "color-mix(in srgb, var(--color-text) 60%, transparent)",
          }}>
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * Dos secciones de descubrimiento bajo el hero, ambas alimentadas por el
 * mismo `GET /search` sin `q` (que ya devuelve TODOS los productos ordenados
 * por precio final mínimo ascendente, paginado): un solo fetch, dos vistas.
 */
async function DiscoverySections() {
  const url = `${API_URL}/search?${new URLSearchParams({ page_size: "8" })}`;
  const result = await fetchJson<SearchResponse>(url);

  if (!result.ok || result.data.items.length === 0) {
    // Sin productos (o backend caido): las secciones simplemente no se
    // muestran, el error ya se explica en el flujo de busqueda si el
    // usuario intenta buscar algo.
    return null;
  }

  const { items } = result.data;

  // Heurística TEMPORAL de "oportunidad" mientras no haya historial de
  // precios poblado para un /ofertas real (mediana de 90 días, etc.): mayor
  // spread entre la publicación más cara y la más barata del mismo cluster
  // sugiere más margen para comparar y ahorrar eligiendo bien. No es una
  // "oferta" real (no hay baseline temporal detrás), por eso el nombre en
  // la UI es "Mejores oportunidades" y no "Ofertas".
  const bySpread = [...items].sort(
    (a, b) => spread(b) - spread(a),
  );

  return (
    <>
      <ClusterSection title="Productos relevantes" items={items} />
      <ClusterSection title="Mejores oportunidades" items={bySpread} />
    </>
  );
}

function spread(cluster: ProductCluster): number {
  return toNumber(cluster.max_final_price) - toNumber(cluster.min_final_price);
}

function ClusterSection({
  title,
  items,
}: {
  title: string;
  items: ProductCluster[];
}) {
  return (
    <section style={{ marginTop: 56 }}>
      <div className="section-header">
        <h2 className="section-title">{title}</h2>
        <span className="section-count">{items.length} productos</span>
      </div>

      <div>
        {items.map((cluster) => (
          <ProductClusterCard key={cluster.id} cluster={cluster} />
        ))}
      </div>
    </section>
  );
}

async function SearchResults({
  query,
}: {
  query: string;
}) {
  const url = `${API_URL}/search?${new URLSearchParams({ q: query })}`;
  const result = await fetchJson<SearchResponse>(url);

  if (!result.ok) {
    return (
      <section style={{ marginTop: 24 }}>
        <ErrorBanner result={result} apiUrl={API_URL} />
      </section>
    );
  }

  const { items, total } = result.data;

  return (
    <section style={{ marginTop: 24 }}>
      <div className="section-header">
        <h2 className="section-title">{query}</h2>
        <span className="section-count">
          {total} {total === 1 ? "producto" : "productos"}
        </span>
      </div>

      {items.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 14 }}>
          No encontramos publicaciones para &ldquo;{query}&rdquo;. Probá con otros términos de
          búsqueda.
        </p>
      ) : (
        <div>
          {items.map((cluster) => (
            <ProductClusterCard key={cluster.id} cluster={cluster} />
          ))}
        </div>
      )}
    </section>
  );
}

function ErrorBanner({
  result,
  apiUrl,
}: {
  result: { kind: "network" | "http"; message: string; status?: number };
  apiUrl: string;
}) {
  const description =
    result.kind === "network"
      ? `No pudimos conectar con el backend en ${apiUrl}. Verificá que esté corriendo (ver README de backend/).`
      : `El backend respondió con un error${result.status ? ` (${result.status})` : ""}.${
          result.message ? ` ${result.message}` : ""
        }`;

  return (
    <div className="card" style={{ maxWidth: 620 }}>
      <div className="card-title">No pudimos completar la búsqueda</div>
      <p className="card-body">{description}</p>
    </div>
  );
}
