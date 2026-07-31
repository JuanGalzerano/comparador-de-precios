"""`retailer_source` — una fila por fuente de datos (MercadoLibre, Fravega, SEPA, ...).

Es la tabla de control de la ingesta: el worker itera las filas con `status='active'`,
instancia el adapter que corresponde a `kind` parametrizado con `config_json`, y escribe
de vuelta `last_run_at` / `last_success_at` / `last_error`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import SourceKind, SourceStatus
from app.models.base import (
    Base,
    IdMixin,
    JsonDict,
    JSONBType,
    TimestampMixin,
    TZDateTime,
    pg_enum,
)

if TYPE_CHECKING:
    from app.models.listing import Listing


class RetailerSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "retailer_source"

    #: Identificador estable usado en codigo y config (`mercadolibre`, `fravega_vtex`).
    #: Es la clave por la que un `SourceAdapter` se asocia a su fila (`adapter.source_slug`).
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128))

    kind: Mapped[SourceKind] = mapped_column(
        pg_enum(SourceKind, "source_kind"), nullable=False
    )
    status: Mapped[SourceStatus] = mapped_column(
        pg_enum(SourceStatus, "source_status"),
        nullable=False,
        default=SourceStatus.EXPERIMENTAL,
        server_default=SourceStatus.EXPERIMENTAL.value,
    )

    #: Por que esta fuente esta (o no) habilitada: riesgo de ToS, aprobacion del usuario,
    #: anti-bot detectado, etc. Se muestra en el panel admin y en la pagina de transparencia.
    tos_risk_note: Mapped[str | None] = mapped_column(Text)

    #: Parametros del adapter (base URL VTEX, site_id de ML, categorias, rate limit,
    #: URL del dataset SEPA...). Deliberadamente sin schema fijo: cada `kind` valida el
    #: suyo en el adapter (ver `app/adapters/types.py: AdapterConfig`).
    config_json: Mapped[JsonDict] = mapped_column(
        JSONBType, nullable=False, default=dict, server_default="{}"
    )

    last_run_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)

    listings: Mapped[list["Listing"]] = relationship(
        back_populates="retailer_source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # El worker de ingesta busca exactamente por esto: "fuentes activas de tipo X".
        Index("ix_retailer_source_status_kind", "status", "kind"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<RetailerSource {self.slug} kind={self.kind} status={self.status}>"
