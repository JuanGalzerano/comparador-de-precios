"""Configuracion de la app.

Todo sale de variables de entorno (cargadas desde `.env` via python-dotenv/pydantic-settings).
No hay credenciales hardcodeadas: `DATABASE_URL` es obligatoria en cualquier entorno que
toque la base.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---------------------------------------------------------------
    app_name: str = "Cotejo API"
    cotejo_env: str = "local"
    log_level: str = "INFO"

    # --- Base de datos -----------------------------------------------------
    # El default es la SQLite de desarrollo, NO una URL de Postgres: si el deploy se
    # olvida de inyectar `DATABASE_URL`, el error tiene que ser obvio ("está usando
    # SQLite") y no una app que arranca apuntando a un `localhost:5432` que puede llegar
    # a existir y ser la base equivocada. `check_database_url_for_env` avisa al arrancar.
    database_url: str = Field(
        default="sqlite+pysqlite:///./dev.db",
        description="URL SQLAlchemy de la base. En produccion, Postgres.",
    )
    sql_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    #: Cuota de almacenamiento del plan contratado, en MB. La base es un cache de lo que
    #: la gente busca, asi que necesita saber cuando parar: a partir del 75% se borra lo
    #: frio y a partir del 90% se deja de guardar (`app/services/maintenance.py`).
    #: Default 512 MB = free tier de Neon. Supabase free = 500.
    storage_quota_mb: int = 512

    # --- Cola de ingesta ---------------------------------------------------
    # Reservado para Celery. La configuracion del worker es una tarea aparte;
    # esto queda declarado para que no haya que tocar config despues.
    redis_url: str = "redis://localhost:6379/0"

    # --- Frontend ----------------------------------------------------------
    #: `NoDecode` es necesario: sin eso pydantic-settings intenta JSON-decodear el valor
    #: de entorno ANTES de correr el validator, así que `CORS_ORIGINS=http://a,http://b`
    #: reventaba con `SettingsError` y el validator de abajo era código muerto. Con
    #: `NoDecode` el string llega crudo y se acepta tanto CSV como JSON.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Acepta `http://a,http://b` (CSV) y `["http://a","http://b"]` (JSON)."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value

    # --- Cuentas de usuario / sesion -----------------------------------------
    # La sesion es un token opaco guardado en `user_session` (ver `app/security.py`),
    # no un JWT: no hace falta ningun secreto de firma aca, solo el nombre de la cookie
    # y su TTL.
    session_cookie_name: str = "cotejo_session"
    session_ttl_days: int = 30
    #: `None` = decidir por `cookie_secure` segun el entorno. Explicito solo para poder
    #: forzarlo en un entorno raro (proxy que termina TLS antes de llegar a la app).
    session_cookie_secure: bool | None = None
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # --- MercadoLibre OAuth ------------------------------------------------
    # Client Credentials flow. Ver MERCADOLIBRE_API.md.
    #
    # Lo normal es setear SOLO client_id/secret: `app/services/ml_token.py` pide el
    # token y lo renueva cuando vence (dura 6 horas y no hay refresh token).
    #: Override manual. Si esta seteado gana sobre la renovacion automatica: sirve para
    #: debuggear con un token pegado a mano. Vence a las 6 horas y no se renueva.
    ml_access_token: str | None = None
    #: Credenciales de la aplicacion. Con estas dos el token se obtiene y renueva solo.
    #: Sin ninguna de las dos vias, el adapter de ML recibe 403 y esa fuente queda vacia.
    ml_client_id: str | None = None
    ml_client_secret: str | None = None

    @property
    def uses_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def storage_quota_bytes(self) -> int:
        return self.storage_quota_mb * 1024 * 1024

    @property
    def is_local(self) -> bool:
        return self.cotejo_env.lower() in {"local", "dev", "development", "test"}

    @property
    def cookie_secure(self) -> bool:
        """`Secure` de la cookie de sesion: `True` salvo que se este en local/test.

        Un browser descarta una cookie `Secure` sobre HTTP plano, que es como se corre
        local (`http://localhost:8000`); en cualquier otro entorno se asume HTTPS.
        """
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return not self.is_local


@lru_cache
def get_settings() -> Settings:
    """Settings cacheadas (una sola lectura de entorno por proceso)."""
    return Settings()


settings = get_settings()


def check_database_url_for_env() -> str | None:
    """Devuelve un warning si la config de base no tiene sentido para el entorno.

    El caso que importa: desplegar a produccion sin inyectar `DATABASE_URL`. Antes eso
    arrancaba contra un Postgres `localhost` inventado; ahora arranca contra SQLite, que
    parece funcionar hasta que el contenedor se reinicia y se pierde todo. Un warning
    explicito al arrancar es la diferencia entre verlo en el primer log y descubrirlo
    una semana despues.
    """
    if settings.uses_sqlite and not settings.is_local:
        return (
            f"COTEJO_ENV={settings.cotejo_env!r} pero DATABASE_URL apunta a SQLite "
            f"({settings.database_url!r}). Los datos se pierden cuando se reinicia el "
            "proceso: definí DATABASE_URL con la URL de Postgres."
        )
    return None
