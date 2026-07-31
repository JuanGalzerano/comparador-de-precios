"""Modelos Pydantic de respuesta de la API publica.

Separados a proposito de `app.adapters.types` (DTOs de ingesta): estos son el contrato
HTTP hacia el frontend, no el contrato entre un `SourceAdapter` y el worker. Aunque
varios nombres de campo coincidan (son el mismo dato, `listing.*`), conflar los dos
haria que un cambio pensado para la ingesta (p.ej. agregar `raw_params`) se filtre sin
querer a una respuesta publica.

Ningun schema de aca expone campos internos de `retailer_source`
(`config_json`, `tos_risk_note`, `last_error`): esos son de un futuro `/admin`, no de
`/search` ni `/products`.
"""

from __future__ import annotations
