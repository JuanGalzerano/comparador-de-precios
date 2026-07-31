# MercadoLibre API — Guía de integración para Cotejo

La API pública de ML pasó a requerir OAuth 2.0 en todos sus endpoints
(incluyendo `/sites/MLA/search`, antes sin auth). Sin un `access_token` válido,
todo responde `403 Forbidden`.

Esta guía cubre el camino mínimo para que el `MercadoLibreAdapter` existente
funcione con datos reales.

---

## 1. Registrar una aplicación en el portal de desarrolladores

1. Ir a **https://developers.mercadolibre.com.ar**
2. Loguearse con una cuenta de MercadoLibre (la tuya personal sirve).
3. Ir a **"Mis aplicaciones"** → **"Crear aplicación"**.
4. Completar:
   - **Nombre:** `cotejo-dev` (o cualquier nombre)
   - **Descripción breve:** `Comparador de precios`
   - **Dominio:** `localhost` (para desarrollo)
   - **URI de redirección:** `http://localhost:8000/auth/ml/callback`
     (se usa para el flujo Authorization Code — ver §3)
   - **Permisos/Scopes:** `read` alcanza para leer búsquedas y detalles.
5. Al guardar, ML te da:
   - `client_id` — número largo (ej. `1234567890123456`)
   - `client_secret` — string alfanumérico

Guardarlos en `backend/.env`:

```env
ML_CLIENT_ID=1234567890123456
ML_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUv
```

---

## 2. Flujos de OAuth disponibles

ML soporta dos flujos. Para Cotejo el más simple es **Client Credentials**
(solo para lectura de datos públicos, sin cuenta de usuario):

### 2a. Client Credentials (recomendado para el comparador)

No requiere que un usuario autorice nada. El token tiene acceso de lectura
a búsquedas, ítems, vendedores y reseñas — todo lo que necesita el adapter.

```bash
curl -X POST https://api.mercadolibre.com/oauth/token \
  -H "accept: application/json" \
  -H "content-type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=TU_CLIENT_ID&client_secret=TU_CLIENT_SECRET"
```

Respuesta:

```json
{
  "access_token": "APP_USR-1234...",
  "token_type": "Bearer",
  "expires_in": 21600,
  "scope": "read",
  "jti": "..."
}
```

- `expires_in`: segundos hasta que vence (6 horas = 21600 s).
- No hay `refresh_token` en este flujo; hay que pedir uno nuevo al vencer.

### 2b. Authorization Code (si en el futuro se necesita actuar en nombre de un usuario)

Se necesitaría si Cotejo quisiera publicar, comprar, o leer datos privados de
cuenta. **No es necesario ahora** — el comparador solo lee datos públicos.

---

## 3. Poner el token en el adapter

### 3a. En `backend/.env`

Agregar el token obtenido en §2a directamente (para desarrollo rápido):

```env
ML_CLIENT_ID=1234567890123456
ML_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUv
ML_ACCESS_TOKEN=APP_USR-1234...
```

### 3b. Cambios en `app/config.py`

Agregar los tres campos nuevos a `Settings`:

```python
# --- MercadoLibre OAuth ------------------------------------------------
ml_client_id: str | None = None
ml_client_secret: str | None = None
ml_access_token: str | None = None
```

### 3c. Cambios en `app/adapters/mercadolibre.py`

En `_client()`, inyectar el token como header `Authorization`:

```python
def _client(self) -> httpx.Client:
    headers = dict(self.config.headers)
    if self.config.user_agent:
        headers.setdefault("User-Agent", self.config.user_agent)

    # Inyectar Bearer token si está configurado
    token = settings.ml_access_token
    if token:
        headers["Authorization"] = f"Bearer {token}"

    kwargs: dict[str, Any] = dict(
        base_url=self._base_url(),
        timeout=self.config.timeout_seconds,
        headers=headers,
    )
    if self.config.proxy_url:
        kwargs["proxy"] = self.config.proxy_url
    return httpx.Client(**kwargs)
```

Nada más cambia — el resto del adapter ya funciona correctamente.

### 3d. Auto-renovación del token (opcional, para producción)

El token dura 6 horas. Para no tener que renovarlo a mano, agregar un helper
que lo renueve automáticamente cuando está por vencer:

```python
# app/adapters/mercadolibre_token.py
import time
import httpx
from app.config import settings

_cached: dict = {}

def get_access_token() -> str:
    now = time.time()
    if _cached.get("token") and _cached.get("expires_at", 0) - now > 300:
        return _cached["token"]

    resp = httpx.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.ml_client_id,
            "client_secret": settings.ml_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _cached["token"] = data["access_token"]
    _cached["expires_at"] = now + data["expires_in"]
    return _cached["token"]
```

Luego en `_client()` usar `get_access_token()` en vez de `settings.ml_access_token`.

---

## 4. Endpoints que usa el adapter (ya implementados)

| Endpoint | Para qué | Auth requerida |
|---|---|---|
| `GET /sites/MLA/search?q=...` | Búsqueda paginada | ✅ Sí (antes era pública) |
| `GET /items?ids=ID1,ID2` | Detalle de ítems en batch | ✅ Sí |
| `GET /users/{seller_id}` | Reputación del vendedor | ✅ Sí |
| `GET /reviews/item/{item_id}` | Calificaciones y reseñas | ✅ Sí |
| `GET /sites/MLA` | Health check | ✅ Sí |

Todos usan el mismo `Bearer` token — un solo cambio en `_client()` los cubre todos.

---

## 5. Límites de la API (rate limits)

Con `client_credentials` (app sin usuario):

| Recurso | Límite |
|---|---|
| Búsquedas (`/search`) | ~200 req/hora por app |
| Detalles (`/items`) | 20 IDs por llamada, ~600 req/hora |
| Vendedores (`/users`) | ~600 req/hora |
| Reseñas (`/reviews`) | ~600 req/hora |

Para el worker de ingesta (corre cada 1-4 horas), estos límites son más que
suficientes para cientos de productos.

---

## 6. Pasos concretos para activar (checklist)

```
[ ] 1. Crear app en developers.mercadolibre.com.ar
[ ] 2. Copiar client_id y client_secret → backend/.env
[ ] 3. Ejecutar el curl de §2a → copiar access_token → backend/.env
[ ] 4. Agregar ml_client_id / ml_client_secret / ml_access_token a app/config.py Settings
[ ] 5. Modificar MercadoLibreAdapter._client() para inyectar el Authorization header
[ ] 6. Correr: python -m app.workers.ingest mercadolibre --term "iphone 13" --max-results 20
[ ] 7. Verificar que GET /search?q=iphone devuelve resultados con permalinks reales
[ ] 8. (Prod) Implementar auto-renovación del token (§3d) o un cron que lo renueve cada 5h
```

---

## 7. Notas de ToS

ML permite el acceso a datos públicos de su catálogo vía API con fines informativos
(comparación de precios, análisis de mercado). Lo que prohíben es:
- Reproducir el contenido de ML como si fuera propio sin atribución.
- Hacer scraping del sitio web (la API es el canal oficial).
- Usar los datos para competir directamente con ML (marketplace propio).

Cotejo cae dentro del uso permitido: agrega y compara información públicamente
disponible, con link directo a cada publicación original en ML.

Referencia: https://developers.mercadolibre.com.ar/es_ar/terminos-y-condiciones
