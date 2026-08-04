import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import {
  computeMarks,
  installments,
  money,
  ratingDisplay,
  repLabel,
  repNote,
  shipNote,
  toNumber,
  warrantyDisplay,
} from "@/lib/format";
import { getCurrentUser, sessionHeader } from "@/lib/session";
import type {
  ConditionFilter,
  Listing,
  ProductDetail,
  SavedProductIdsResponse,
  SortKey,
} from "@/lib/types";
import { SaveButton } from "@/components/SaveButton";
import { PriceHistoryChart } from "@/components/PriceHistoryChart";
import { ProductFilters } from "./ProductFilters";

interface ProductPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    sort?: string;
    condition?: string;
    free?: string;
    official?: string;
    warranty?: string;
  }>;
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const result = await fetchJson<ProductDetail>(`${API_URL}/products/${id}`);
  if (!result.ok) return { title: "Producto no encontrado" };
  const p = result.data;
  const prices = p.listings.map((l) => toNumber(l.final_price)).filter(Boolean);
  const minPrice = prices.length ? Math.min(...prices) : null;
  const title = p.canonical_title;
  const description = minPrice
    ? `Comparar precios de ${title} en ${p.listings.length} publicaciones. Desde $${Math.floor(minPrice).toLocaleString("es-AR")} con envío, cuotas y garantía.`
    : `Comparar precios de ${title} en múltiples tiendas de Argentina.`;
  return {
    title,
    description,
    openGraph: { title: `${title} — comparar precios`, description },
  };
}

const SORT_VALUES: SortKey[] = ["score", "price", "rating", "warranty", "seller"];
const CONDITION_VALUES: ConditionFilter[] = ["all", "new", "used", "refurbished", "unknown"];

function normalizeSort(value: string | undefined): SortKey {
  return (SORT_VALUES as string[]).includes(value ?? "") ? (value as SortKey) : "score";
}

function normalizeCondition(value: string | undefined): ConditionFilter {
  return (CONDITION_VALUES as string[]).includes(value ?? "") ? (value as ConditionFilter) : "all";
}

/**
 * Ficha de producto — port de la vista `isProduct` del prototipo
 * (`project/Cotejo - Comparador.dc.html:149-345`), tabla completa de
 * `renderVals()` (`.dc.html:585-670`). Se deja afuera a proposito la
 * "comparación lado a lado" (columnas seleccionables con checkboxes,
 * `.dc.html:214-247`): es una feature de seleccion propia, no lo que pide
 * esta tarea ("tabla comparativa... ordenable... filtrable").
 */
export default async function ProductPage({ params, searchParams }: ProductPageProps) {
  const { id } = await params;
  const sp = await searchParams;

  const sort = normalizeSort(sp.sort);
  const condition = normalizeCondition(sp.condition);
  const free = sp.free === "true";
  const official = sp.official === "true";
  const warranty = sp.warranty === "true";

  const qs = new URLSearchParams({ sort, condition });
  if (free) qs.set("free", "true");
  if (official) qs.set("official", "true");
  if (warranty) qs.set("warranty", "true");

  const url = `${API_URL}/products/${id}?${qs.toString()}`;
  const result = await fetchJson<ProductDetail>(url);

  if (!result.ok) {
    if (result.kind === "http" && result.status === 404) {
      // Devuelve un 404 HTTP real (renderiza app/productos/[id]/not-found.tsx)
      // en vez de una pagina 200 con un mensaje: mejor semantica HTTP/SEO.
      notFound();
    }
    return (
      <main style={{ maxWidth: 1240, margin: "0 auto", padding: "var(--space-8)" }}>
        <BackLink />
        <div className="card" style={{ maxWidth: 620, marginTop: "var(--space-6)" }}>
          <div className="card-title">No pudimos cargar este producto</div>
          <p className="card-body">
            {result.kind === "network"
              ? `No pudimos conectar con el backend en ${API_URL}. Verificá que esté corriendo.`
              : `El backend respondió con un error (${result.status}).${
                  result.message ? ` ${result.message}` : ""
                }`}
          </p>
        </div>
      </main>
    );
  }

  const product = result.data;
  const listings = product.listings;
  const marks = computeMarks(listings);
  const best = listings.length ? listings.reduce((a, b) => (b.score > a.score ? b : a)) : null;
  const finalPrices = listings.map((l) => toNumber(l.final_price));
  const min = finalPrices.length ? Math.min(...finalPrices) : 0;
  const max = finalPrices.length ? Math.max(...finalPrices) : 0;

  // Estado de "guardado": solo se pide si hay sesion (no tiene sentido pegar
  // a un endpoint gateado por auth para un visitante anonimo).
  const user = await getCurrentUser();
  let initialSaved = false;
  if (user) {
    const idsResult = await fetchJson<SavedProductIdsResponse>(`${API_URL}/me/favorites/ids`, {
      headers: await sessionHeader(),
    });
    initialSaved = idsResult.ok && idsResult.data.product_ids.includes(product.id);
  }

  return (
    <main style={{ maxWidth: 1240, margin: "0 auto", padding: "var(--space-6) var(--space-8) 80px" }}>
      <BackLink />

      <section style={{ marginTop: "var(--space-6)" }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: "var(--space-6)",
          }}
        >
          <h2 style={{ marginBottom: "var(--space-2)" }}>{product.canonical_title}</h2>
          <SaveButton productId={product.id} initialSaved={initialSaved} loggedIn={user !== null} />
        </div>
        <div className="text-muted" style={{ fontSize: 13.5 }}>
          {[product.brand, product.model, product.category].filter(Boolean).join(" · ")}
        </div>

        <div
          className="num"
          style={{
            display: "flex",
            gap: 40,
            marginTop: "var(--space-8)",
            paddingBottom: "var(--space-6)",
            borderBottom: "1px solid var(--color-divider)",
            flexWrap: "wrap",
          }}
        >
          <Stat label="Publicaciones (con estos filtros)" value={String(listings.length)} />
          <Stat label="Más barata" value={listings.length ? money(min) : "—"} />
          <Stat label="Más cara" value={listings.length ? money(max) : "—"} />
          <Stat label="Diferencia" value={listings.length ? money(max - min) : "—"} />
        </div>

        {best ? (
          <div className="best-offer">
            <div>
              <div style={{ fontSize: 15, lineHeight: 1.5 }}>
                Conviene {best.retailer_name ?? best.seller_name ?? "un vendedor"} a{" "}
                {money(best.final_price)}
                {toNumber(best.final_price) === min
                  ? ", que además es la más barata."
                  : `, ${money(toNumber(best.final_price) - min)} más que la más barata.`}
              </div>
              <div className="text-muted" style={{ fontSize: 13, marginTop: "var(--space-2)" }}>
                {[
                  repLabel(best),
                  best.warranty_months
                    ? `${best.warranty_months} meses de garantía ${
                        best.warranty_type === "oficial" ? "de fábrica" : "del vendedor"
                      }`
                    : "sin garantía",
                  best.reviews_count
                    ? `${Number(best.rating).toFixed(1)} con ${best.reviews_count.toLocaleString("es-AR")} opiniones`
                    : "sin opiniones",
                ].join(" · ")}
              </div>
            </div>
            {/* `target="_blank"` en todos los links salientes: el usuario se lleva la
                publicación a otra pestaña y Cotejo le queda abierto para seguir
                comparando. `noopener noreferrer` porque son sitios de terceros. */}
            <a
              className="btn btn-primary"
              href={best.permalink}
              target="_blank"
              rel="noopener noreferrer"
              style={{ minHeight: 40, whiteSpace: "nowrap" }}
            >
              Ver en {best.retailer_name ?? "el sitio oficial"} ↗
            </a>
          </div>
        ) : (
          <p className="text-muted" style={{ fontSize: 14, marginTop: "var(--space-6)" }}>
            Ninguna publicación pasa los filtros actuales. Probá sacando alguno.
          </p>
        )}

        <PriceHistoryChart productId={product.id} />
      </section>

      <section style={{ marginTop: 56 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "var(--space-6)",
            marginBottom: "var(--space-4)",
            flexWrap: "wrap",
          }}
        >
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 500 }}>
            Todas las publicaciones{" "}
            <span className="text-muted" style={{ fontSize: 13, fontWeight: 400 }}>
              {listings.length} tras los filtros
            </span>
          </h2>
          <ProductFilters
            productId={product.id}
            sort={sort}
            condition={condition}
            free={free}
            official={official}
            warranty={warranty}
          />
        </div>

        {listings.length === 0 ? (
          <p className="text-muted" style={{ fontSize: 14 }}>
            No hay publicaciones que pasen estos filtros.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Publicación</th>
                  <th style={{ width: 104 }}>Tienda</th>
                  <th style={{ width: 132 }}>Precio final</th>
                  <th style={{ width: 116 }}>Cuotas</th>
                  <th style={{ width: 136 }}>Vendedor</th>
                  <th style={{ width: 100 }}>Opiniones</th>
                  <th style={{ width: 104 }}>Garantía</th>
                  <th style={{ width: 52, textAlign: "right" }}>Score</th>
                  <th style={{ width: 104 }}></th>
                </tr>
              </thead>
              <tbody>
                {listings.map((listing) => (
                  <ListingRow key={listing.id} listing={listing} mark={marks.get(listing.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-muted" style={{ fontSize: 12, marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, letterSpacing: "-0.02em" }}>{value}</div>
    </div>
  );
}

function ListingRow({ listing, mark }: { listing: Listing; mark: string | undefined }) {
  const inst = installments(listing);
  const rating = ratingDisplay(listing);
  const warr = warrantyDisplay(listing);

  return (
    <tr>
      <td style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-3)", flexWrap: "wrap" }}>
          <span style={{ fontWeight: 500 }}>{listing.seller_name ?? "Vendedor sin nombre"}</span>
          {mark && <span style={{ fontSize: 12, color: "var(--color-accent-300)" }}>{mark}</span>}
        </div>
        <div className="text-muted" style={{ fontSize: 12, marginTop: 2 }}>
          {listing.title}
        </div>
      </td>
      <td>
        <span className="retailer-badge">{listing.retailer_name ?? "—"}</span>
      </td>
      <td>
        <div className="num">{money(listing.final_price)}</div>
        <div className="text-muted num" style={{ fontSize: 11.5, marginTop: 1 }}>
          {shipNote(listing)}
        </div>
      </td>
      <td>
        <div className="num" style={{ fontSize: 13 }}>
          {inst.main}
        </div>
        <div className="text-muted" style={{ fontSize: 11.5, marginTop: 1 }}>
          {inst.note}
        </div>
      </td>
      <td>
        <div style={{ fontSize: 13 }}>{repLabel(listing)}</div>
        <div className="text-muted num" style={{ fontSize: 11.5, marginTop: 1 }}>
          {repNote(listing)}
        </div>
      </td>
      <td>
        <div className="num" style={{ fontSize: 13 }}>
          {rating.rating}
        </div>
        <div className="text-muted num" style={{ fontSize: 11.5, marginTop: 1 }}>
          {rating.reviews}
        </div>
      </td>
      <td>
        <div style={{ fontSize: 13 }}>{warr.label}</div>
        <div className="text-muted" style={{ fontSize: 11.5, marginTop: 1 }}>
          {warr.note}
        </div>
      </td>
      <td className="num" style={{ textAlign: "right" }}>
        {listing.score}
      </td>
      <td style={{ textAlign: "right" }}>
        <a
          href={listing.permalink}
          target="_blank"
          rel="noopener noreferrer"
          title={`Se abre en una pestaña nueva${listing.retailer_name ? ` (${listing.retailer_name})` : ""}`}
          style={{ fontSize: 12.5, whiteSpace: "nowrap" }}
        >
          Ir a la publicación ↗
        </a>
      </td>
    </tr>
  );
}

function BackLink() {
  return (
    <Link href="/" style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 5 }}>
      ← Volver a la búsqueda
    </Link>
  );
}
