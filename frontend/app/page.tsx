import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import { toNumber } from "@/lib/format";
import type { ProductCluster, SearchResponse } from "@/lib/types";
import { ProductClusterCard } from "@/components/ProductClusterCard";

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

  return (
    <main
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "var(--space-8) var(--space-8) 80px",
        width: "100%",
      }}
    >
      {query === "" ? (
        <>
          <Hero />
          <DiscoverySections />
        </>
      ) : (
        <SearchResults query={query} />
      )}
    </main>
  );
}

function Hero() {
  return (
    <div>
      <div style={{ padding: "56px 0 var(--space-8)", maxWidth: 620 }}>
        <h1 style={{ fontSize: 44, marginBottom: "var(--space-4)" }}>
          Buscá un producto y comparalo en todas sus publicaciones.
        </h1>
        <p className="text-muted" style={{ fontSize: 16, margin: 0 }}>
          Precio con envío, cuotas, vendedor, garantía y opiniones — y el link para comprarlo
          donde está publicado.
        </p>
      </div>

      <form
        action="/"
        method="get"
        style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", maxWidth: 520 }}
      >
        <input
          className="input"
          type="search"
          name="q"
          placeholder="iPhone 13 128GB, remera Nike…"
          style={{ minHeight: 42, fontSize: 15 }}
        />
        <button className="btn btn-primary" type="submit" style={{ minHeight: 42 }}>
          Buscar
        </button>
      </form>
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

function ClusterSection({ title, items }: { title: string; items: ProductCluster[] }) {
  return (
    <section style={{ marginTop: 56 }}>
      <div
        style={{
          borderBottom: "1px solid var(--color-divider)",
          paddingBottom: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <h4 style={{ margin: 0 }}>{title}</h4>
      </div>

      <div>
        {items.map((cluster) => (
          <ProductClusterCard key={cluster.id} cluster={cluster} />
        ))}
      </div>
    </section>
  );
}

async function SearchResults({ query }: { query: string }) {
  const url = `${API_URL}/search?${new URLSearchParams({ q: query })}`;
  const result = await fetchJson<SearchResponse>(url);

  if (!result.ok) {
    return (
      <section style={{ marginTop: 56 }}>
        <ErrorBanner result={result} apiUrl={API_URL} />
      </section>
    );
  }

  const { items, total } = result.data;

  return (
    <section style={{ marginTop: 56 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: "var(--space-4)",
          borderBottom: "1px solid var(--color-divider)",
          paddingBottom: "var(--space-3)",
        }}
      >
        <h4 style={{ margin: 0 }}>{query}</h4>
        <span className="text-muted" style={{ fontSize: 13 }}>
          {total} {total === 1 ? "producto agrupado" : "productos agrupados"}
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
