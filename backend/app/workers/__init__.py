"""Jobs de ingesta en background (Celery + Redis).

VACIO A PROPOSITO. La configuracion de Celery y el worker de ingesta son tareas aparte;
este paquete existe para que ya tengan lugar y para dejar escrito el contrato que van a
cumplir.

Forma prevista (segun el plan):

    celery_app.py          -> instancia Celery apuntando a `settings.redis_url`
    ingest.py              -> tarea unica que corre CUALQUIER fuente:
                                1. levanta las filas de `retailer_source` con
                                   `status='active'`
                                2. `adapter = build_adapter(source)`
                                   (`app.adapters.registry`)
                                3. `for raw in adapter.fetch_listings(request):`
                                   `normalize` -> upsert en `listing` por la clave
                                   (retailer_source_id, external_id)
                                4. inserta en `price_history` solo si cambio el precio o
                                   el envio respecto del ultimo snapshot
                                5. escribe `last_run_at` / `last_success_at` / `last_error`
                                   segun el resultado; `BlockedBySource` pasa la fuente a
                                   `status='blocked_tos_review'` y NO reintenta
    matching.py            -> paso separado que llena `listing.product_id` y `product_match`
                              (no bloquea la ingesta: `listing.product_id` es nullable)

El rate limit y los reintentos por fuente salen de `AdapterConfig`
(`rate_limit_rps`, `max_retries`), no de constantes en el worker.
"""
