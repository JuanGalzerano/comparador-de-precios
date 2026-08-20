# MercadoLibre API — Guía de integración para Cotejo

La API pública de ML pasó a requerir OAuth 2.0 en todos sus endpoints
(incluyendo `/sites/MLA/search`, antes sin auth). Sin un `access_token` válido,
todo responde `403 Forbidden`.

Esta guía cubre el camino mínimo para que el `MercadoLibreAdapter` existente
funcione con datos reales.

---

## 1. Registrar una aplicación en el portal de desarrolladores

Verificado contra el formulario real el **2026-08-20** — el portal cambió respecto de lo
que documentaban las versiones anteriores de este archivo.

1. Ir a **https://developers.mercadolibre.com.ar** → **Mis aplicaciones** →
   **Crear nueva aplicación**.

2. **Información básica:**

   | Campo | Valor |
   |---|---|
   | Nombre | `Cotejo - comparador de precios` |
   | Nombre corto | `cotejo` (va en la URL: sin espacios ni acentos) |
   | Descripción | `Comparador de precios de electro y tecnologia en Argentina` |
   | Propósito | Personal |
   | Cantidad de usuarios | el rango más chico |
   | Logo | opcional |

3. **Flujos OAuth: dejar tildado solo `Client Credentials`.** Destildar
   `Authorization Code` y `Refresh Token`.

   > Esto importa por dos motivos. Primero, **el campo "Redirect URIs" es obligatorio
   > por culpa de Authorization Code**, y ML **rechaza `localhost`** ahí (con http y con
   > https): exige un dominio público. Destildando el flujo, el campo deja de pedirse.
   > Segundo, si dejás Authorization Code tildado, el token que devuelve Client
   > Credentials viene con scopes de más — se vio `offline_access`, `write` y
   > `urn:global:admin:users:/read-write` en un token que solo tenía que leer catálogo.
   >
   > Si por lo que sea necesitás llenar Redirect URIs, poné cualquier HTTPS público
   > (no `localhost`). **Nunca se usa** con Client Credentials, y se puede editar después
   > sin que cambien `client_id` ni `client_secret`. En el backend **no existe** ninguna
   > ruta `/auth/ml/callback`.

4. **PKCE:** destildado. Solo aplica a Authorization Code.

5. **Permisos:** todo en `Sin acceso`. Cotejo solo lee catálogo público (búsquedas,
   ítems, vendedores, reseñas) y eso no necesita ninguno. Si el desplegable de alguno no
   ofrece "Sin acceso", elegir **`Lectura`**, nunca "Lectura y escritura". El permiso
   "Usuarios" aparece fijo en gris: no se puede cambiar.

6. **Tópicos:** ninguno. Son webhooks para vendedores — ML avisa de cambios en *tu*
   cuenta, no del catálogo global, y necesitan una URL pública que reciba los POST. El
   backend no tiene ese endpoint ni lo necesita: el modelo es pull (la ingesta consulta
   cada X horas), no push.

7. Al guardar, la app queda como **"Aplicación no certificada"**. Está bien: la
   certificación es del programa de partners, para apps que operan sobre cuentas de
   terceros. No aplica.

8. Las credenciales quedan en la tarjeta de la app. El **Client ID** se ve directo; el
   **Client Secret** está detrás del menú **⋮** de la tarjeta. Si ML no lo muestra
   (solo lo revela al crear la app), usar **Restablecer Client Secret** — el `client_id`
   no cambia.

   - **Client ID**: identificador público, 16 dígitos. Viaja en cada request, no es secreto.
   - **Client Secret**: la contraseña de la app. No se commitea ni se comparte.

Guardarlos en `backend/.env` (ver §3a):

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

## 3. Poner las credenciales en el backend

> **✅ Todo lo de esta sección ya está implementado** (auto-renovación incluida,
> 2026-08-20). Lo único que hacés vos es el paso 3a.

### 3a. En `backend/.env`

Con el `client_id` y el `client_secret` de §1 alcanza — **el token se pide y se renueva
solo**:

```env
ML_CLIENT_ID=1234567890123456
ML_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUv
```

`ML_ACCESS_TOKEN` quedó como override manual opcional: si lo ponés, gana sobre la
renovación automática, pero vence a las 6 horas y no se renueva. Sirve para debuggear.

El `.env` está en `.gitignore` y vive solo en el servidor: nunca viaja al navegador.
El `client_secret` es una contraseña — no se commitea ni se pega en un chat.

### 3b. Cómo funciona la renovación — `app/services/ml_token.py`

`get_token()` es la única puerta de entrada. Lo usan `MercadoLibreAdapter._client()` y la
búsqueda en vivo de `/search`.

| Situación | Qué hace |
|---|---|
| Hay `ML_ACCESS_TOKEN` | Lo devuelve tal cual (override manual) |
| Hay token cacheado y vigente | Lo devuelve sin tocar la red |
| Cacheado vencido, o no hay | Pide uno nuevo con Client Credentials y lo cachea |
| No hay credenciales | Devuelve `None` |
| ML rechaza / no hay red | Devuelve `None`, reintenta recién en 60 s |

Cuatro decisiones que importan:

- **Margen de 5 minutos** antes del vencimiento real. Un token que vence en 30 segundos
  no le sirve a una ingesta que tarda minutos, y el reloj del server puede estar corrido.
- **Thread-safe.** Los adapters corren en un `ThreadPoolExecutor`; sin `Lock`, N hilos que
  ven el token vencido piden N tokens a la vez.
- **Nunca levanta excepción.** Una falla de auth de una tienda no puede tumbar una
  búsqueda que las otras cinco pueden contestar: degrada a `None` y ML queda vacía.
- **Backoff de 60 s tras una falla.** Si las credenciales son malas, no mejoran en 200 ms;
  reintentar en cada request sería pegarle a ML para nada.

`invalidate()` descarta el token cacheado, para llamar si ML devuelve 401/403.

Cubierto por `tests/test_ml_token.py` (10 tests, sin red).

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
[ ] 1. Crear app en developers.mercadolibre.com.ar (solo flujo Client Credentials)
[ ] 2. Copiar client_id y client_secret → backend/.env
[x] 3. Agregar los campos a app/config.py Settings                   (YA HECHO)
[x] 4. Inyectar el header Authorization en el adapter y en /search   (YA HECHO)
[x] 5. Auto-renovacion del token (app/services/ml_token.py)          (YA HECHO)
[ ] 6. Reiniciar el backend
[ ] 7. Correr: python -m app.workers.ingest mercadolibre --term "iphone 13" --max-results 20
[ ] 8. Verificar que GET /search?q=iphone devuelve resultados con permalinks reales
```

Ya no hace falta el paso de pedir el `access_token` con `curl`: con `client_id` y
`client_secret` en el `.env`, el backend lo pide solo. El `curl` de §2a queda como forma
de comprobar a mano que las credenciales andan.

Verificado contra el código (2026-08-04):

- La fuente `mercadolibre` está hoy en estado `blocked_tos_review` porque la API responde
  403. **Eso NO impide correr la ingesta**: el worker resuelve la fuente por slug, sin
  mirar el estado — y una corrida exitosa ahora la reactiva sola.
- ML devuelve **403 tanto si te bloqueó como si se venció el token** (dura 6 horas). Eso
  ya no obliga a nada manual: desde 2026-08-20 el token se renueva solo (§3b).
- La búsqueda en vivo de `/search` (`_ml_live_search`) **antes no mandaba el token**, así
  que iba a seguir devolviendo vacío aun con el token bien configurado. Corregido.

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
