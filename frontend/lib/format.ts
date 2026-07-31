/**
 * Helpers de formato/derivacion portados desde `renderVals()` del prototipo
 * (`project/Cotejo - Comparador.dc.html:585-670`), adaptados a los campos
 * que el backend REALMENTE devuelve (ver `lib/types.ts`). El calculo de
 * score/orden/filtrado en si ya lo hace el backend (`GET /products/{id}`
 * con `sort`/`free`/`official`/`warranty`/`condition`); esto solo formatea
 * lo que llega.
 */
import type { Listing } from "./types";

/** Decimal-como-string -> number. Nunca null-safe a proposito: llamar solo
 * con campos que ya se chequearon (`??`) en el call site. */
export function toNumber(value: string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return Number(value);
}

export function money(value: string | number): string {
  const n = typeof value === "string" ? Number(value) : value;
  return "$ " + Math.round(n).toLocaleString("es-AR");
}

/** Port de `repLabel()` (`.dc.html:600`). */
export function repLabel(listing: Listing): string {
  if (listing.official_store) return "Tienda oficial";
  const byLevel: Record<string, string> = {
    platinum: "MercadoLíder Platinum",
    gold: "MercadoLíder Gold",
    silver: "MercadoLíder",
    green: "Sin trayectoria",
  };
  return (listing.seller_level && byLevel[listing.seller_level]) || "Sin datos";
}

/** Port de `repNote` (`.dc.html:631`). */
export function repNote(listing: Listing): string {
  const sales = listing.seller_sales ?? 0;
  return sales >= 1000 ? Math.round(sales / 1000) + "k ventas" : sales + " ventas";
}

/** Port de `shipNote` (`.dc.html:628`). */
export function shipNote(listing: Listing): string {
  const ship = toNumber(listing.shipping_cost);
  if (ship === 0) {
    return listing.fulfillment ? "envío gratis · FULL" : "envío gratis";
  }
  return "incluye " + money(ship) + " de envío";
}

/** Port de `instMain`/`instNote` (`.dc.html:629-630`). */
export function installments(listing: Listing): { main: string; note: string } {
  const qty = listing.installments_qty ?? 0;
  if (qty > 1 && listing.installments_amount) {
    return {
      main: qty + " × " + money(listing.installments_amount),
      note: listing.interest_free ? "sin interés" : "con interés",
    };
  }
  return { main: "sin cuotas", note: "pago único" };
}

/** Port de `rating`/`reviews` de fila (`.dc.html:633-634`). */
export function ratingDisplay(listing: Listing): { rating: string; reviews: string } {
  const reviews = listing.reviews_count ?? 0;
  if (reviews === 0 || !listing.rating) {
    return { rating: "—", reviews: "sin opiniones" };
  }
  return {
    rating: Number(listing.rating).toFixed(1),
    reviews: reviews.toLocaleString("es-AR") + " opiniones",
  };
}

/** Port de `warranty`/`warrantyNote` (`.dc.html:635-636`). */
export function warrantyDisplay(listing: Listing): { label: string; note: string } {
  const months = listing.warranty_months ?? 0;
  const label = months > 0 ? months + " meses" : "sin garantía";
  const note =
    listing.warranty_type === "oficial"
      ? "de fábrica"
      : listing.warranty_type === "vendedor"
        ? "del vendedor"
        : "—";
  return { label, note };
}

/** Port de `markOf()` (`.dc.html:637-643`): marca textual sobre la fila
 * "recomendada"/"la más barata"/"más garantía"/"más opiniones", calculada
 * sobre el mismo set visible que ya llegó filtrado/ordenado del backend. */
export function computeMarks(listings: Listing[]): Map<number, string> {
  const marks = new Map<number, string>();
  if (listings.length === 0) return marks;

  const best = listings.reduce((a, b) => (b.score > a.score ? b : a));
  const cheapest = listings.reduce((a, b) =>
    toNumber(b.final_price) < toNumber(a.final_price) ? b : a,
  );
  const longestWarranty = listings.reduce((a, b) =>
    (b.warranty_months ?? 0) > (a.warranty_months ?? 0) ? b : a,
  );
  const mostReviewed = listings.reduce((a, b) =>
    (b.reviews_count ?? 0) > (a.reviews_count ?? 0) ? b : a,
  );

  marks.set(best.id, "recomendada");
  if (!marks.has(cheapest.id)) marks.set(cheapest.id, "la más barata");
  if ((longestWarranty.warranty_months ?? 0) > 0 && !marks.has(longestWarranty.id)) {
    marks.set(longestWarranty.id, "más garantía");
  }
  if ((mostReviewed.reviews_count ?? 0) > 0 && !marks.has(mostReviewed.id)) {
    marks.set(mostReviewed.id, "más opiniones");
  }
  return marks;
}
