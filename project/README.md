# Cotejo — comparador de publicaciones (prototipo de UI)

Comparador de precios que agrupa las **publicaciones del mismo producto** (fase 1: solo
MercadoLibre, vía su API pública) y las ordena por un score compuesto: precio final con
envío, cuotas, reputación del vendedor, opiniones y garantía. Servicio gratuito, sostenido
con Google AdSense; el CTA lleva a la publicación original (`item.permalink`).

## Archivos

| Archivo | Qué es |
| --- | --- |
| `Cotejo — Comparador.dc.html` | Todo el prototipo: markup + lógica (React sin build). Los comentarios del código marcan qué endpoint de la API alimenta cada bloque. |
| `nocturne.css` | Design system Nocturne: tokens (`--color-*`, `--space-*`, `--radius-*`) y clases (`.btn`, `.input`, `.card`, `.table`, `.seg`, `.tag`). Única fuente de estilo. |
| `_ds/nocturne-*/` | El design system original completo (readme con las reglas de uso). |
| `support.js` | Runtime del formato de componente usado por el `.dc.html`. |

Abrir `Cotejo — Comparador.dc.html` en el navegador alcanza para verlo; no hay build.

## Vistas

- **home** — titular, buscador, cómo funciona.
- **resultados** — productos agrupados (clusters de publicaciones), no publicaciones sueltas.
- **producto** — ficha + recomendación con link de compra; al scrollear, comparación lado a
  lado (2–4 columnas) y tabla completa con orden y filtros.
- **precios insuperables** (`/ofertas`) — precio actual vs mediana de 90 días.
- **para vos** (`/para-vos`) — recomendaciones; requiere consentimiento de cookies.

## Backend pendiente (fase 1, sin scraping)

```
GET https://api.mercadolibre.com/sites/MLA/search?q=<query>&limit=50
GET /items?ids=MLA1,MLA2            (batch, hasta 20)
GET /users/:seller_id               -> seller_reputation
GET /reviews/item/:id               -> rating (no siempre disponible)
attributes[] -> WARRANTY_TYPE / WARRANTY_TIME (texto libre: parsear a meses + tipo)
```

Tablas mínimas:

- `listing(id, product_key, seller_id, price, shipping_cost, final_price, installments_qty,
  installments_amount, interest_free, seller_level, seller_sales, official_store, rating,
  reviews_count, warranty_months, warranty_type, condition, permalink, fetched_at)`
- `price_history(listing_id, price, shipping_cost, captured_at)` — alimenta /ofertas.
- `user_event(anon_id, type, product_key, listing_id, ts)` — alimenta /para-vos (solo con
  `cotejo_consent = granted`; `anon_id` en cookie first-party `cotejo_cid`).

`product_key` = `catalog_product_id` cuando existe; si no, hash de marca + modelo +
atributos (matching propio).

La fórmula del score está aislada en el método `scoreOf(l, min, max)` del componente:
portarla tal cual al backend, normalizando cada eje contra el set visible.

## Fases siguientes

1. Historial de precios y alertas.
2. Segunda tienda: primero buscar API oficial; scraping solo si no hay, con proxies y
   tolerancia a cambios de HTML.
3. Matching entre tiendas (normalización de títulos + atributos, fuzzy/embeddings).
