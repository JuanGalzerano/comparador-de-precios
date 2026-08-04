/**
 * Detecta si un string pegado en el buscador es la URL de una publicación de
 * producto (de cualquier tienda) y extrae términos de búsqueda a partir de
 * ella. Objetivo: el usuario pega el link de un producto en la tienda que
 * sea (MercadoLibre, Frávega, Amazon, lo que sea) y Cotejo busca ese mismo
 * producto en todas las fuentes activas, no solo en la tienda de origen.
 *
 * MercadoLibre tiene parsers dedicados (`parseMlUrl`) porque conocemos su
 * estructura de URL exacta (slug + ID de catálogo/publicación) y podemos
 * armar un link directo "Ver en ML". Para cualquier otra tienda,
 * `parseGenericProductUrl` aplica una heurística: toma el último segmento
 * de la ruta (normalmente el slug del producto) y lo limpia.
 */

export interface MlUrlInfo {
  terms: string;
  originalUrl: string;
  catalogId: string | null;
  /** Hostname de origen (ej. "articulo.mercadolibre.com.ar", "www.fravega.com"). */
  source: string;
}

const ML_HOSTNAME_RE = /mercadolibre\.(com\.ar|com\.mx|com\.co|com\.br|com\.uy|cl)/i;

/** Detecta y parsea específicamente URLs de MercadoLibre (slugs conocidos). */
export function parseMlUrl(input: string): MlUrlInfo | null {
  const trimmed = input.trim();

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }

  if (!ML_HOSTNAME_RE.test(parsed.hostname)) return null;

  const path = parsed.pathname;

  // Ficha de catálogo: /apple-iphone-13-128gb-azul/p/MLA20118043
  const catalogWithSlug = path.match(/^\/([a-z0-9][a-z0-9-]{2,})\/p\/(MLA\w+)/i);
  if (catalogWithSlug) {
    return {
      terms: slugToTerms(catalogWithSlug[1]),
      originalUrl: trimmed,
      catalogId: catalogWithSlug[2].toUpperCase(),
      source: parsed.hostname,
    };
  }

  // URL corta de catálogo: /p/MLA20118043
  const catalogShort = path.match(/^\/p\/(MLA\w+)/i);
  if (catalogShort) {
    const id = catalogShort[1].toUpperCase();
    return { terms: id, originalUrl: trimmed, catalogId: id, source: parsed.hostname };
  }

  // Publicación directa en articulo.mercadolibre: /MLA-2146734073-apple-iphone-13-_JM
  const itemSlug = path.match(/^\/MLA-\d+-([a-z0-9-]+?)(?:[-_]+jm)?$/i);
  if (itemSlug) {
    return {
      terms: slugToTerms(itemSlug[1]),
      originalUrl: trimmed,
      catalogId: null,
      source: parsed.hostname,
    };
  }

  // Publicación directa con ID numérico: /MLA12345678 (sin slug)
  const itemShort = path.match(/^\/(MLA\d+)$/i);
  if (itemShort) {
    return { terms: itemShort[1].toUpperCase(), originalUrl: trimmed, catalogId: null, source: parsed.hostname };
  }

  return null;
}

/** Palabras de ruta que no aportan al término de búsqueda (paginación, categorías genéricas, ids de tracking). */
const STOP_SEGMENTS = new Set([
  "p",
  "product",
  "productos",
  "producto",
  "dp",
  "item",
  "items",
  "articulo",
  "catalogo",
  "catalog",
  "shop",
  "tienda",
]);

/**
 * Heurística genérica para URLs de producto de tiendas sin parser dedicado:
 * toma el segmento de ruta más "denso" (más letras, no puramente numérico
 * como un SKU) y lo convierte en términos de búsqueda. Devuelve `null` si la
 * URL no tiene forma de link a un producto (ej. la home de una tienda).
 */
export function parseGenericProductUrl(input: string): MlUrlInfo | null {
  const trimmed = input.trim();

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }

  const segments = parsed.pathname
    .split("/")
    .map((s) => decodeURIComponent(s))
    .filter((s) => s.length > 0 && !STOP_SEGMENTS.has(s.toLowerCase()));

  if (segments.length === 0) return null;

  // El slug de producto suele ser el segmento con más letras y guiones/
  // guiones bajos (vs. un ID corto tipo "SKU12345" o un número de página).
  const candidate = [...segments].sort((a, b) => lettersCount(b) - lettersCount(a))[0];

  if (lettersCount(candidate) < 6) return null; // muy corto para ser un slug de producto

  return {
    terms: slugToTerms(candidate),
    originalUrl: trimmed,
    catalogId: null,
    source: parsed.hostname,
  };
}

/** Punto de entrada único del buscador: intenta el parser de ML primero
 * (más preciso), y si no matchea, cae al heurístico genérico. */
export function parseProductUrl(input: string): MlUrlInfo | null {
  return parseMlUrl(input) ?? parseGenericProductUrl(input);
}

function lettersCount(segment: string): number {
  return (segment.match(/[a-zA-Z]/g) ?? []).length;
}

function slugToTerms(slug: string): string {
  return slug
    .toLowerCase()
    .replace(/[-_]+/g, " ")
    .replace(/\.\w{2,5}$/, "") // extensión de archivo residual (.html, .aspx)
    .replace(/\s+/g, " ")
    .trim();
}
