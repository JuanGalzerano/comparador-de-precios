"""`user_event` — telemetria anonima que alimenta `/para-vos` y el funnel de analytics.

Solo se escribe con `cotejo_consent = granted`; `anon_id` es el valor de la cookie
first-party `cotejo_cid` (ver `project/README.md`). No hay FK a usuarios porque no hay
usuarios: el sitio no tiene login.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, IdMixin, JsonDict, JSONBType, TZDateTime


class UserEvent(IdMixin, Base):
    __tablename__ = "user_event"

    #: Cookie `cotejo_cid`. Sin indice unico: hay N eventos por visitante.
    anon_id: Mapped[str] = mapped_column(String(64), nullable=False)

    #: `search` | `product_view` | `listing_click` | ... Texto libre y no ENUM a proposito:
    #: el catalogo de eventos de analytics cambia seguido y no vale una migracion por evento.
    type: Mapped[str] = mapped_column(String(48), nullable=False)

    #: SET NULL y no CASCADE: si se borra un producto o una publicacion, el evento
    #: historico sigue siendo valido para el funnel agregado.
    product_id: Mapped[int | None] = mapped_column(
        BigId, ForeignKey("product.id", ondelete="SET NULL")
    )
    listing_id: Mapped[int | None] = mapped_column(
        BigId, ForeignKey("listing.id", ondelete="SET NULL")
    )

    #: Contexto del evento (query de busqueda, posicion en la lista, filtros activos).
    payload_json: Mapped[JsonDict] = mapped_column(
        JSONBType, nullable=False, default=dict, server_default="{}"
    )

    ts: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        # Historial de un visitante (recomendaciones de /para-vos).
        Index("ix_user_event_anon_id_ts", "anon_id", "ts"),
        # Agregados por tipo de evento en una ventana temporal (funnel/analytics).
        Index("ix_user_event_type_ts", "type", "ts"),
        Index("ix_user_event_product_id_ts", "product_id", "ts"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<UserEvent {self.type} anon={self.anon_id[:8]}... at={self.ts}>"
