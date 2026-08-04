import { Suspense } from "react";
import Link from "next/link";
import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import type { ProductCluster, SearchResponse, SourcesResponse } from "@/lib/types";
import { ProductClusterCard } from "@/components/ProductClusterCard";
import { SearchInput } from "@/components/SearchInput";
import { parseProductUrl } from "@/lib/ml-url";

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

  const linkInfo = query ? parseProductUrl(query) : null;
  const effectiveQuery = linkInfo ? linkInfo.terms : query;

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
        <>
          {linkInfo && <ProductUrlBanner query={effectiveQuery} link={linkInfo} />}
          {/* `key` fuerza un Suspense nuevo por búsqueda: sin eso, al buscar otra cosa
              React reusa el resultado anterior y la pantalla queda congelada mostrando
              los productos viejos durante los ~2s que tarda la consulta a las tiendas. */}
          <Suspense key={effectiveQuery} fallback={<SearchSkeleton query={effectiveQuery} />}>
            <SearchResults query={effectiveQuery} />
          </Suspense>
        </>
      )}
    </main>
  );
}

/**
 * Banner que aparece cuando el usuario pegó el link de un producto (de
 * cualquier tienda) en vez de escribir texto. Deja explícito que Cotejo no
 * solo trae ese link de vuelta: busca el mismo producto en todas las fuentes
 * activas para comparar precios entre tiendas.
 */
function ProductUrlBanner({
  query,
  link,
}: {
  query: string;
  link: { originalUrl: string; source: string };
}) {
  return (
    <div
      className="card"
      style={{
        marginBottom: "var(--space-6)",
        padding: "var(--space-4) var(--space-5)",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "var(--space-4)",
        flexWrap: "wrap",
        border: "1px solid rgba(145,132,217,0.22)",
        background: "rgba(145,132,217,0.06)",
      }}
    >
      <div>
        <div className="card-title" style={{ fontSize: 14 }}>
          Buscamos el mejor precio para &ldquo;{query}&rdquo; en todas las fuentes
        </div>
        <p className="card-body" style={{ marginTop: 2 }}>
          Detectamos un link de {link.source}. Comparamos ese mismo producto contra el resto de
          las tiendas activas antes de decirte dónde conviene.
        </p>
      </div>
      <a
        href={link.originalUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="btn btn-secondary"
        style={{ whiteSpace: "nowrap" }}
      >
        Ver publicación original →
      </a>
    </div>
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

/** Secciones de descubrimiento bajo el hero. */
async function DiscoverySections() {
  // Dos criterios distintos, dos consultas: el backend ordena por cantidad de
  // tiendas comparadas y por diferencia de precio dentro del cluster
  // (`GET /search?sort=`), así la home no queda ordenada por "lo más barato del
  // catálogo", que no dice nada sobre dónde conviene comparar.
  const [comparados, oportunidades] = await Promise.all([
    fetchJson<SearchResponse>(
      `${API_URL}/search?${new URLSearchParams({
        page_size: "6",
        sort: "retailers",
        min_retailers: "2",
      })}`,
    ),
    fetchJson<SearchResponse>(
      `${API_URL}/search?${new URLSearchParams({
        page_size: "6",
        sort: "spread",
        min_retailers: "2",
      })}`,
    ),
  ]);

  if (!comparados.ok || comparados.data.items.length === 0) {
    // Sin productos (o backend caido): las secciones simplemente no se
    // muestran, el error ya se explica en el flujo de busqueda si el
    // usuario intenta buscar algo.
    return null;
  }

  return (
    <>
      <ClusterSection
        title="Comparados en varias tiendas"
        subtitle="mismo producto, distintos precios"
        items={comparados.data.items}
      />
      {oportunidades.ok && oportunidades.data.items.length > 0 && (
        <ClusterSection
          title="Donde más se ahorra eligiendo bien"
          subtitle="mayor diferencia entre la publicación más cara y la más barata"
          items={oportunidades.data.items}
        />
      )}
      <BestPriceStores />
    </>
  );
}

/**
 * Ranking de tiendas por competitividad real (`GET /sources`): en qué fracción de los
 * productos donde compite contra otra tienda tiene el precio más bajo. Sale de los
 * datos propios, no de una lista curada a mano.
 */
async function BestPriceStores() {
  const result = await fetchJson<SourcesResponse>(`${API_URL}/sources`);
  if (!result.ok) return null;

  const ranked = result.data.items.filter((s) => s.win_rate !== null && s.listing_count > 0);
  if (ranked.length < 2) return null;

  return (
    <section style={{ marginTop: 56 }}>
      <div className="section-header">
        <h2 className="section-title">Tiendas que más seguido tienen el mejor precio</h2>
        <span className="section-count">sobre productos comparados</span>
      </div>

      <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
        {ranked.map((source) => {
          const pct = Math.round((source.win_rate ?? 0) * 100);
          return (
            <div
              key={source.slug}
              className="card"
              style={{ padding: "var(--space-4)", minWidth: 200, flex: "1 1 200px" }}
            >
              <div className="card-title" style={{ fontSize: 15 }}>
                {source.display_name ?? source.slug}
              </div>
              <div
                className="num"
                style={{ fontSize: 26, letterSpacing: "-0.03em", color: "var(--color-accent)" }}
              >
                {pct}%
              </div>
              <div className="savings-bar" style={{ marginTop: 0 }}>
                <div className="savings-bar-fill" style={{ width: `${pct}%` }} />
              </div>
              <div className="text-muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                mejor precio en {source.cheapest_count} de los productos donde compite
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-muted" style={{ fontSize: 12, marginTop: "var(--space-3)" }}>
        Ninguna tienda paga por aparecer acá — el orden sale de comparar sus precios.{" "}
        <Link href="/como-funciona">Cómo se calcula</Link>
      </p>
    </section>
  );
}

function ClusterSection({
  title,
  subtitle,
  items,
}: {
  title: string;
  subtitle?: string;
  items: ProductCluster[];
}) {
  return (
    <section style={{ marginTop: 56 }}>
      <div className="section-header">
        <h2 className="section-title">{title}</h2>
        {subtitle && (
          <span className="text-muted" style={{ fontSize: 12 }}>
            {subtitle}
          </span>
        )}
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

/**
 * Lo que se ve mientras el backend consulta las tiendas. Solo aparece cuando el término
 * no está en la base todavía (la primera vez que alguien lo busca): a partir de ahí sale
 * de la base y la respuesta es inmediata.
 */
function SearchSkeleton({ query }: { query: string }) {
  return (
    <section style={{ marginTop: 24 }}>
      <div className="section-header">
        <h2 className="section-title">{query}</h2>
        <span className="section-count">buscando…</span>
      </div>

      <p className="text-muted" style={{ fontSize: 13, marginBottom: "var(--space-4)" }}>
        Consultando Frávega, Cetrogar y Naldo…
      </p>

      {[0, 1, 2].map((i) => (
        <div key={i} className="cluster-card skeleton-card" aria-hidden="true">
          <div className="product-avatar skeleton-block" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="skeleton-line" style={{ width: "45%" }} />
            <div className="skeleton-line" style={{ width: "28%", height: 10 }} />
            <div className="skeleton-line" style={{ width: "18%", height: 10 }} />
          </div>
          <div style={{ minWidth: 140 }}>
            <div className="skeleton-line" style={{ width: "70%", height: 18, marginLeft: "auto" }} />
          </div>
        </div>
      ))}
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
