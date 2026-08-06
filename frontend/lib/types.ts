/**
 * Tipos TS que reflejan 1:1 los Pydantic response models de
 * `backend/app/schemas/search.py` y `backend/app/schemas/product.py`.
 *
 * Verificado contra el shape REAL devuelto (no inventado): se corrio
 * `GET /search` y `GET /products/{id}` con `TestClient` contra una DB
 * SQLite sembrada igual que `backend/tests/conftest.py` (Postgres no esta
 * alcanzable en este entorno — ver README/ESTADO.md del backend). Punto no
 * obvio: pydantic serializa `Decimal` como STRING en el JSON (ej.
 * `"702000.00"`, `"4.30"`), no como number — por eso todos los campos de
 * plata/rating son `string` aca, no `number`. Los enums viajan como su
 * `.value` en minuscula (`"used"`, `"vendedor"`, etc).
 */

export type ItemCondition = "new" | "used" | "refurbished" | "unknown";

export type WarrantyType = "oficial" | "vendedor" | "sin" | "unknown";

/** `ProductClusterOut` — un resultado de `/search` (cluster de listings). */
export interface ProductCluster {
  id: number;
  canonical_title: string;
  brand: string | null;
  model: string | null;
  category: string | null;
  catalog_product_id: string | null;
  listing_count: number;
  /** Tiendas distintas que publican este producto. */
  retailer_count: number;
  retailer_names: string[];
  /** Decimal como string, ej. "702000.00". */
  min_final_price: string;
  max_final_price: string;
  best_score: number;
  /** URL externa directa (resultados live de ML). Null para items de la DB. */
  permalink?: string | null;
}

/** Sobre paginado de `GET /search`. */
export interface SearchResponse {
  items: ProductCluster[];
  page: number;
  page_size: number;
  total: number;
}

/** `ListingOut` — una publicacion dentro de la ficha de producto. */
export interface Listing {
  id: number;
  title: string;
  permalink: string;
  condition: ItemCondition;

  price: string;
  shipping_cost: string | null;
  final_price: string;

  installments_qty: number | null;
  installments_amount: string | null;
  interest_free: boolean | null;

  seller_name: string | null;
  seller_level: string | null;
  seller_sales: number | null;
  official_store: string | null;

  fulfillment: boolean | null;

  rating: string | null;
  reviews_count: number | null;

  warranty_months: number | null;
  warranty_type: WarrantyType;

  /** Tienda de la que salió este precio. */
  retailer_slug: string | null;
  retailer_name: string | null;

  score: number;
}

/** `ProductDetailOut` — respuesta de `GET /products/{id}`. */
export interface ProductDetail {
  id: number;
  canonical_title: string;
  brand: string | null;
  model: string | null;
  category: string | null;
  catalog_product_id: string | null;
  listings: Listing[];
}

/** Mismos valores que `SortKey` de `app/api/routers/products.py`. */
export type SortKey = "score" | "price" | "rating" | "warranty" | "seller";

/** Mismos valores que acepta `condition` en ambos routers. */
export type ConditionFilter = "all" | "new" | "used" | "refurbished" | "unknown";

/** `UserOut` — respuesta de `/auth/register`, `/auth/login` y `GET /auth/me`. */
export interface User {
  id: number;
  email: string;
  display_name: string | null;
  created_at: string;
}

/**
 * `SavedProductOut` — un item de `GET /me/favorites`. Mismo resumen de
 * cluster que `ProductCluster`, mas `saved_at`. A diferencia de `ProductCluster`,
 * `min_final_price`/`max_final_price` son `string | null`: un favorito puede
 * haberse quedado sin publicaciones vigentes (todas dadas de baja) y el
 * favorito sigue existiendo (LEFT JOIN en el backend, no INNER JOIN).
 */
export interface SavedProduct {
  id: number;
  canonical_title: string;
  brand: string | null;
  model: string | null;
  category: string | null;
  catalog_product_id: string | null;
  listing_count: number;
  min_final_price: string | null;
  max_final_price: string | null;
  best_score: number;
  saved_at: string;
}

/** Sobre paginado de `GET /me/favorites`. */
export interface SavedProductsResponse {
  items: SavedProduct[];
  page: number;
  page_size: number;
  total: number;
}

/** Respuesta de `GET /me/favorites/ids` — solo los ids guardados, para pintar
 * el estado inicial de `SaveButton` sin pedir el detalle completo. */
export interface SavedProductIdsResponse {
  product_ids: number[];
}

/**
 * `SimilarProductOut` — un producto PARECIDO, no el mismo.
 *
 * Sale de `GET /products/{id}/similar`: son los candidatos que el matcher evaluó y
 * descartó como cluster. Se muestran aparte de la tabla comparativa a propósito —
 * mezclarlos haría que el ahorro anunciado compare productos distintos.
 */
export interface SimilarProduct {
  id: number;
  canonical_title: string;
  brand: string | null;
  model: string | null;
  listing_count: number;
  retailer_count: number;
  min_final_price: string | null;
  max_final_price: string | null;
  /** Cuánto se parece al producto de la ficha, 0..1. */
  confidence: number;
}

export interface SimilarProductsResponse {
  product_id: number;
  items: SimilarProduct[];
}

/** `SourceOut` — una fuente de datos en `GET /sources`. */
export interface Source {
  slug: string;
  display_name: string | null;
  kind: string;
  status: string;
  tos_risk_note: string | null;
  listing_count: number;
  product_count: number;
  cheapest_count: number;
  /** Fracción 0..1 de productos disputados donde esta tienda tiene el mejor precio. */
  win_rate: number | null;
  last_success_at: string | null;
  last_error: string | null;
}

export interface SourcesResponse {
  items: Source[];
}

/** `PriceHistoryPoint` — un punto crudo de `GET /products/{id}/price-history`. */
export interface PriceHistoryPoint {
  listing_id: number;
  captured_at: string;
  price: string;
  shipping_cost: string | null;
}

/** `PriceHistoryResponse` — respuesta de `GET /products/{id}/price-history`. */
export interface PriceHistoryResponse {
  product_id: number;
  since: string;
  points: PriceHistoryPoint[];
}
