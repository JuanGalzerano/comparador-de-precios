/**
 * Detecta si un string es una URL de MercadoLibre y extrae términos de búsqueda.
 * Soporta:
 *   - Ficha de catálogo: /product-slug/p/MLAXXX
 *   - Publicación directa (articulo.ml): /MLAXXX-product-slug-_JM
 *   - URL corta de catálogo: /p/MLAXXX  (sin slug → usa el ID)
 */

export interface MlUrlInfo {
  terms: string;
  originalUrl: string;
  catalogId: string | null;
}

const ML_HOSTNAME_RE = /mercadolibre\.(com\.ar|com\.mx|com\.co|com\.br|com\.uy|cl)/i;

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
    };
  }

  // URL corta de catálogo: /p/MLA20118043
  const catalogShort = path.match(/^\/p\/(MLA\w+)/i);
  if (catalogShort) {
    const id = catalogShort[1].toUpperCase();
    return { terms: id, originalUrl: trimmed, catalogId: id };
  }

  // Publicación directa en articulo.mercadolibre: /MLA-2146734073-apple-iphone-13-_JM
  const itemSlug = path.match(/^\/MLA-\d+-([a-z0-9-]+?)(?:[-_]+jm)?$/i);
  if (itemSlug) {
    return {
      terms: slugToTerms(itemSlug[1]),
      originalUrl: trimmed,
      catalogId: null,
    };
  }

  // Publicación directa con ID numérico: /MLA12345678 (sin slug)
  const itemShort = path.match(/^\/(MLA\d+)$/i);
  if (itemShort) {
    return { terms: itemShort[1].toUpperCase(), originalUrl: trimmed, catalogId: null };
  }

  return null;
}

function slugToTerms(slug: string): string {
  return slug
    .toLowerCase()
    .replace(/-+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
