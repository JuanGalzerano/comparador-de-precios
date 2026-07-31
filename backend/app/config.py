"""Configuracion de la app.

Todo sale de variables de entorno (cargadas desde `.env` via python-dotenv/pydantic-settings).
No hay credenciales hardcodeadas: `DATABASE_URL` es obligatoria en cualquier entorno que
toque la base.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Sin default productivo a proposito: si falta la env var, la app falla al arrancar
    # en vez de escribir silenciosamente en una base equivocada.
    database_url: str = Field(
        default="postgresql+psycopg2://cotejo:cotejo@localhost:5432/cotejo",
        description="URL SQLAlchemy de Postgres.",
    )
    sql_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Cola de ingesta ---------------------------------------------------
    # Reservado para Celery. La configuracion del worker es una tarea aparte;
    # esto queda declarado para que no haya que tocar config despues.
    redis_url: str = "redis://localhost:6379/0"

    # --- Frontend ----------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
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
    # Client Credentials flow. Ver MERCADOLIBRE_API.md para obtener el token.
    # Sin token: el MercadoLibreAdapter devuelve 403 en todos los endpoints.
    ml_access_token: str | None = None

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
