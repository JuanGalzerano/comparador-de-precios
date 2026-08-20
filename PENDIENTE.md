# Pendiente — todo lo que falta hacer en Cotejo

Actualizado: 2026-08-04, después de dos auditorías completas del código (estructura del
backend, y si los pasos manuales de estos `.md` realmente funcionan).

**Estado en una línea:** el comparador funciona de verdad en local — busca en Frávega,
Cetrogar y Naldo en vivo, agrupa el mismo producto entre tiendas y guarda lo que
encuentra. Lo que falta es ponerlo online y que los precios se actualicen solos.

---

## Índice

1. [Lo que tenés que hacer vos](#1-lo-que-tenés-que-hacer-vos)
2. [¿Alcanza una base de datos gratis?](#2-alcanza-una-base-de-datos-gratis)
3. [Alternativas de diseño (no guardar el mundo)](#3-alternativas-de-diseño)
4. [Lo que puede hacer Claude](#4-lo-que-puede-hacer-claude)
5. [Deuda técnica conocida](#5-deuda-técnica-conocida)
6. [Lo que ya está hecho](#6-lo-que-ya-está-hecho)

---

## 1. Lo que tenés que hacer vos

### ⛔ A. MercadoLibre — cerrado del lado de ML (2026-08-20)

Es el único bloqueo que no puede resolver el código. ML dejó de permitir acceso sin
autenticación: hoy responde `403` a todo.

1. Entrá a **https://developers.mercadolibre.com.ar** → **Mis aplicaciones** →
   **Crear nueva aplicación**.
2. **Dejá tildado solo el flujo `Client Credentials`.** Destildá `Authorization Code` y
   `Refresh Token`: si no, el campo "Redirect URIs" se vuelve obligatorio (y ML **no
   acepta `localhost`** ahí), y el token te sale con permisos de escritura que no
   necesitás. Permisos todos en `Sin acceso` — o `Lectura` si no te deja sacarlos.
   Tópicos, ninguno.
3. Copiá `client_id` y `client_secret` (el secret está detrás del menú **⋮** de la
   tarjeta de la app; si no aparece, "Restablecer Client Secret").
4. Pegalos en `backend/.env`:
   ```
   ML_CLIENT_ID=1234567890123456
   ML_CLIENT_SECRET=xxxxxxxxxxxxxxxx
   ```
5. Reiniciá el backend. **Nada más.**

Los pasos exactos del formulario, con las trampas de cada campo, están en
el portal de developers de ML.

> **Ya no hace falta pedir el token a mano.** Desde el 2026-08-20 el backend lo pide solo
> con esas dos credenciales y lo renueva cuando vence (`app/services/ml_token.py`). Antes
> había que correr un `curl` cada 6 horas — inviable en producción. `ML_ACCESS_TOKEN`
> sigue existiendo como override manual para debuggear.

**Pero eso ya no alcanza.** Verificado el 2026-08-20 con un token valido: ML responde
`403 forbidden` en `/sites/MLA/search`, el endpoint del que sale todo. La busqueda de
catalogo (`/products/search`) si contesta, pero devuelve productos sin precio ni link —
inservible para un comparador. Detalle abajo.

**Conclusion: no es una tarea pendiente tuya, es acceso que ML no da.** El adapter, el
token y la auto-renovacion funcionan. Las otras cinco tiendas no dependen de esto.

Si algun dia reabren el acceso o consegues permisos por el programa de partners, la
fuente vuelve sola: una corrida exitosa la reactiva.

#### El detalle, endpoint por endpoint

**Con el token funcionando, `/sites/MLA/search` responde `403 forbidden`.** No es un
problema de credenciales: el mismo token entra sin drama a otros endpoints. MercadoLibre
cerro la busqueda por sitio para aplicaciones comunes.

Probado endpoint por endpoint con un token recien emitido:

| Endpoint | Resultado |
|---|---|
| `GET /sites/MLA` | 200 |
| `GET /sites/MLA/search?q=iphone` | **403 forbidden** |
| `GET /products/search?site_id=MLA&q=...` | 200 |
| `GET /items?ids=...` | 200 |
| `GET /users/me` | 200 |

#### Por que `/products/search` no alcanza como reemplazo

Encuentra bien los productos (`Apple iPhone 15 (128 GB) - Verde`), pero devuelve el
**catalogo**, no publicaciones: sin precio y sin link. Se probo pidiendo el detalle de
cada producto — `buy_box_winner` viene `null` y `permalink` vacio en todos los casos
consultados, tanto en celulares como en accesorios.

Sin precio no hay nada que comparar. Es el unico dato que Cotejo necesita de una fuente.

#### Que queda

- **La fuente `mercadolibre` no puede alimentar el comparador hoy.** El adapter esta
  escrito, testeado y funcionando — lo que falta es acceso, no codigo.
- **El token y su auto-renovacion andan** . Si ML reabre el acceso, o si consegue
  permisos por otra via, no hay que tocar nada mas.
- La via formal para pedir mas acceso es el programa de partners de ML (la app figura
  como "no certificada"). No esta verificado que lo den para un proyecto personal.
- **Las otras cinco tiendas no dependen de esto.** Fravega, Cetrogar, Naldo, OnCity,
  Megatone y Compra Gamer usan sus propias APIs publicas y siguen funcionando.

---

---

### 🟡 B. Que los precios se actualicen solos — elegí un camino

Hoy la ingesta la disparás a mano, así que **los precios son una foto del día que la
corriste y el gráfico de historial casi no tiene puntos**. Sin esto, la promesa de
"detectar ofertas que no bajaron nada" no se puede cumplir: no hay con qué comparar.

**Qué es Redis / Upstash, por si no te suena:** Redis es una base de datos en memoria,
muy rápida. Acá no guardaría productos (eso sigue en Postgres) sino que funcionaría como
**cola de tareas**: la lista de "traer precios de Frávega a las 9, a las 13 y a las 17".
Celery es el programa que lee esa cola y ejecuta. Upstash es un Redis alojado, con plan
gratis de 10.000 comandos por día — muchísimo más de lo que esto necesita.

| | Programador de tareas de Windows | Upstash + Celery |
|---|---|---|
| Costo | Gratis | Gratis |
| Configuración tuya | Ninguna, lo hace Claude | Crear cuenta, copiar `REDIS_URL` (5 min) |
| Sirve en producción | No: solo con tu PC prendida | Sí |
| Cuándo | **Ahora**, para empezar a juntar historial | Cuando subas el sitio |

**Recomendación:** arrancá hoy con el Programador de Windows para que el historial se
empiece a llenar, y pasá a Upstash cuando despliegues. Decime *"configurá la tarea
programada"* y lo hago.

### 🔵 C. Subir el sitio (cuando quieras lanzar)

Orden exacto, ya verificado contra el código:

1. **Base de datos** — crear proyecto en [neon.tech](https://neon.tech), copiar la
   connection string.
2. **Backend** en [railway.app](https://railway.app): root `backend/`, start command
   `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
   Variables: `DATABASE_URL`, `COTEJO_ENV=production`, `CORS_ORIGINS`, `ML_ACCESS_TOKEN`
   y **`STORAGE_QUOTA_MB`**.

   > **Sobre `STORAGE_QUOTA_MB`:** es la cuota de tu plan de base, y de ahí salen los
   > umbrales del caché (75% borra lo frío, 90% deja de guardar). El default del código
   > es **512, que es justo el free tier de Neon**, así que **si vas con Neon gratis no
   > tenés que tocar nada**. Cambialo solo si contratás otra cosa:
   >
   > | Plan | Valor |
   > |---|---|
   > | Neon free | 512 (default, no hace falta setearlo) |
   > | Supabase free | 500 |
   > | Neon Launch | 10240 |
   > | Railway Postgres | lo que tenga asignado el volumen |
   >
   > Si lo dejás más alto que la cuota real, el freno actúa tarde y la base se llena de
   > verdad. Más bajo no rompe nada: solo empieza a reciclar antes.
3. **Correr las migraciones y sembrar las tiendas** — este paso faltaba por completo en
   las versiones anteriores de la documentación, y sin él el backend arranca contra una
   base vacía donde toda ingesta falla:
   ```bash
   alembic upgrade head
   python -m scripts.seed_sources
   ```
4. **Frontend** en [vercel.com](https://vercel.com): root `frontend/`, variables
   `NEXT_PUBLIC_API_URL` (la URL de Railway) y `NEXT_PUBLIC_SITE_URL` (la de Vercel).
5. **Dominio** (opcional al principio).

**Tres trampas concretas, todas verificadas:**

- **`CORS_ORIGINS` tiene que incluir la URL de Vercel**, no solo `cotejo.ar`. El gráfico
  de historial de precios es lo único que llama al backend desde el navegador; con el
  dominio mal configurado, ese gráfico desaparece en silencio y el resto anda. Formato:
  `CORS_ORIGINS=["https://tu-app.vercel.app"]` o `https://a.com,https://b.com` (desde hoy
  se aceptan las dos formas; antes la forma con comas hacía que la app **no arrancara**).
- **`NEXT_PUBLIC_API_URL` se congela cuando Vercel hace el build.** Si la agregás después
  del primer deploy sin forzar rebuild, todo el sitio va a decir "No pudimos conectar con
  el backend en http://localhost:8000".
- **El backend no tiene `Procfile` ni `Dockerfile`**, solo `pyproject.toml`. Railway lo va
  a detectar solo, pero contá con iterar un poco ahí; no es "un clic".

### Monetización (para cuando el sitio esté online)

Google AdSense necesita **dominio propio, contenido real y algo de tráfico** antes de
aprobar la cuenta — no se puede preparar antes de lanzar. La integración en sí es un
`<Script>` de `pagead2.googlesyndication.com` en `frontend/app/layout.tsx` más un
componente `<AdBanner slot="...">` entre secciones, y verificar el dominio en su consola.

### Decisiones que son tuyas

1. **Dominio**: `cotejo.ar`, `cotejo.com.ar`, otro. (Ya no está hardcodeado: el código
   toma `NEXT_PUBLIC_SITE_URL`.)
2. **Canal de las alertas de precio**: email (necesita Resend/SendGrid), push, o solo
   panel interno.
3. **Cuándo lanzar.** Condiciona todo lo demás.
4. **Login con Google/GitHub**, además del propio.

---

## 2. ¿Alcanza una base de datos gratis?

Medido sobre los datos reales del proyecto, no estimado:

| Tabla | Bytes por fila (datos) | Con overhead de Postgres |
|---|---|---|
| `listing` (una publicación) | 238 | ~500 |
| `price_history` (un punto) | 31 | ~100 |
| `product` | 121 | ~300 |

| Plan gratis | Espacio | Publicaciones que entran |
|---|---|---|
| **Neon** | 512 MB | ~1.000.000 |
| **Supabase** | 500 MB | ~1.000.000 |

**Un millón de publicaciones entra en el plan gratis.** Hoy tenés ~950, y crecen solas
con cada búsqueda nueva (§3). El catálogo entero
de las tiendas integradas son decenas de miles, no millones. **El catálogo no es el problema.**

### El problema real es el historial de precios

Esa tabla crece para siempre:

```
50.000 publicaciones × 1 punto por día × 365 días = 18.000.000 filas ≈ 1,8 GB
```

Ahí sí revienta cualquier plan gratis. **Resuelto el 2026-08-04** con la política de
reemplazo de abajo.

### La base nunca se llena ni deja de funcionar

`app/services/maintenance.py` — tres capas, el patrón estándar de cualquier caché:

| Capa | Qué hace | Cuándo actúa |
|---|---|---|
| **1. Retención** | Borra el historial de precios de más de 90 días. Nunca deja una publicación sin ningún punto. | Siempre (es barato) |
| **2. Evicción** | Borra los productos **fríos y poco buscados**, con sus publicaciones. | Al 75% de la cuota |
| **3. Freno** | Deja de guardar: busca en vivo y sirve los resultados **desde memoria**. | Al 90% de la cuota |

**El criterio de la capa 2 combina recencia y frecuencia**, que es lo que hace cualquier
caché serio, porque cada señal sola se equivoca: por edad pura se borran los clásicos que
se buscan siempre; por frecuencia pura nunca entra nada nuevo. Concretamente, un producto
se borra solo si cumple **todo** esto:

- Tiene más de 7 días (uno recién traído todavía no tuvo la oportunidad de que lo busquen).
- Nadie lo vio en 30 días.
- Se vio menos de 5 veces en total.
- **Nadie lo tiene en favoritos** — eso no se toca nunca.

Se borra lo peor primero: menos accesos y, a igualdad, más viejo. Y borrar no pierde
nada: si mañana alguien lo busca, vuelve de las tiendas en ~2 segundos.

**La capa 3 es la que garantiza que el sitio nunca deje de funcionar.** Verificado
simulando la base al 95%: consulta las tiendas, devuelve 25 resultados y escribe
cero. Se degrada a "buscador en tiempo real" — más lento, nunca roto.

Para ver cuánto espacio queda:

```bash
python -m app.workers.maintenance --status
```

O el endpoint `GET /health/storage`, que además avisa si ya está evictando o en modo
solo-lectura.

### Dos trampas de los planes gratis

- **Supabase pausa el proyecto** si no recibe requests durante una semana. Para un sitio
  nuevo con poco tráfico, es un problema real.
- **Neon limita horas de cómputo** (100 CU-hours/mes en el plan gratis), pero no pausa.

**Recomendación: Neon.**

### Lo que NO entra, para que quede claro

**Precios Claros / SEPA** (el dato oficial del gobierno) son **~12 millones de registros
por día**. Un solo día no entra en 500 MB. Si algún día se integra, hay que importar
únicamente las categorías y comercios que interesen, nunca el volcado completo.

---

## 3. Alternativas de diseño

### ¿Puede scrapear la computadora del usuario?

**No, y no es una limitación de nuestro código.** El navegador lo prohíbe: una página
servida desde `cotejo.ar` no puede leer la respuesta de `fravega.com` (política de mismo
origen / CORS). La única forma sería que cada visitante instalara una extensión.

**Pero el problema que querés resolver — "no guardar todos los productos del mundo" —
sí tiene solución, y es mejor que esa.**

### La alternativa correcta: caché bajo demanda

Medición real de este proyecto, consultando las 3 tiendas en paralelo desde el servidor:

```
"iphone 15":        1762 ms
"smart tv 55":      1530 ms
"lavarropas drean": 2182 ms
```

**Dos segundos.** Eso habilita este diseño:

> El usuario busca algo → si no está en la base, se les pide a las tiendas **en el
> momento** (2s), se muestra **y se guarda**. La próxima persona que busque lo mismo lo
> ve instantáneo.

La base deja de ser "un catálogo del mundo" y pasa a ser **un caché de lo que la gente
realmente busca**. Guardás miles de productos, no millones, y el plan gratis te sobra por
años.

### ✅ Implementado el 2026-08-04 — `app/services/live_search.py`

Verificado de punta a punta buscando "aspiradora robot", que no existía en la base:

```
1ra búsqueda:  2002 ms   -> consulta las 3 tiendas, guarda 29 publicaciones, las agrupa
2da búsqueda:   660 ms   -> sale de la base
```

Cómo funciona:

1. `/search` mira cuántos productos tiene la base para ese término. Si son menos de 5,
   consulta las tiendas.
2. Las tres se consultan **en paralelo** (1,8 s en vez de más de 4 secuencial). Una tienda
   caída o lenta no rompe la búsqueda: se muestra lo que contestaron las otras.
3. Lo que llega se guarda con el **mismo `upsert` que la ingesta programada**, así una
   publicación traída en vivo y una traída por el worker son indistinguibles.
4. Se corre el matcher, para que lo nuevo quede agrupado y aparezca en los resultados.

Detalles que importan:

- **Cooldown de 15 minutos por término.** Sin esto, cada F5 sobre una búsqueda popular
  dispararía tres llamadas HTTP a las tiendas.
- **Solo en la primera página y solo con término de búsqueda.** Paginar o navegar el
  catálogo nunca genera tráfico hacia las tiendas.
- **Se puede desactivar** con `?live=false` (útil para el sitemap o para debug).
- **La escritura corre en el hilo principal**, no en los hilos que hacen HTTP: una
  `Session` de SQLAlchemy no es thread-safe.

Lo que **no** reemplaza: el worker de ingesta sigue siendo quien mantiene frescos los
precios de lo que ya se conoce. Esto solo cubre el hueco de "nadie buscó esto todavía".

### Cómo hacerlo más rápido

Los 2 segundos son casi todos espera de red, no cálculo:

1. **Devolver resultados a medida que llegan.** Naldo contesta en 640 ms y Frávega en
   1758 ms; hoy se espera a la más lenta para mostrar todo. (Las consultas ya son
   paralelas; falta que la respuesta se vaya enviando en partes.)
2. **Pasar los adapters a `async`.** Hoy son bloqueantes: dos usuarios buscando a la vez
   se hacen cola. Es el cambio más importante para aguantar tráfico real (§5-2).
3. **Caché de búsquedas frecuentes** (15 minutos). "iphone" lo van a buscar mil veces.

### Sobre las herramientas open source de scraping

Conviene tener clara una distinción: **hoy no estás scrapeando**. Estás usando las APIs
JSON públicas de cada tienda — más rápido, más estable y más defendible que leer HTML.
Meter Scrapy o Playwright para las tiendas que ya funcionan sería un **retroceso**.

Dónde sí sirven herramientas de terceros:

| Herramienta | Para qué | Veredicto |
|---|---|---|
| [OpenDataCordoba/precios_claros](https://github.com/OpenDataCordoba/precios_claros) | Portal oficial del gobierno | Útil si algún día querés supermercados. Es casi todo alimentos, no electro, y el volumen no entra en un plan gratis. |
| **Playwright** | Tiendas sin API (Musimundo, Garbarino) | Último recurso: lento, frágil, y necesita un navegador corriendo en el servidor. |
| **Scrapy** | Scraping a gran escala | No aporta nada sobre lo que ya hay. |

**La forma más barata de sumar tiendas no es scrapear: es encontrar la API pública que ya
tienen.** Frávega, Cetrogar y Naldo se integraron así, sin scrapear una sola línea de
HTML. Vale la pena probar ese camino primero con cada tienda nueva.

---

## 4. Lo que puede hacer Claude

Ordenado por impacto. Decime cuál querés.

### A. ✅ Búsqueda en vivo + guardado automático — HECHO (2026-08-04)
Ver §3. El sitio ya responde cualquier búsqueda, no solo lo que estaba cargado.

### B. 🥇 Alertas de bajada de precio
Necesita que vos elijas el canal (email / push / panel).

### C. ✅ Política de reemplazo del caché — HECHO (2026-08-04)
Tres capas, ver §2. La base ya no puede crecer sin límite ni dejar de funcionar.

### D. Categorías / navegación por rubro
Los productos que crea el matcher no tienen categoría, así que no hay forma de navegar
"todos los celulares". Se puede inferir del título o del breadcrumb de cada tienda.

### E. Panel de administración
Salud de las fuentes (el dato ya existe en `/sources`), disparar ingestas, y revisar los
matches dudosos — que ya se acumulan en `product_match` con su nivel de confianza.

### F. ✅ Auto-renovación del token de ML — HECHO (2026-08-20)
`app/services/ml_token.py`: pide el token con Client Credentials, lo cachea con 5 minutos
de margen antes del vencimiento, es thread-safe (los adapters corren en hilos), nunca
levanta excepción y espera 60 s antes de reintentar si ML rechaza las credenciales.
10 tests, sin red.

### G. Imagen de Open Graph
Para que el link se vea bien al compartirlo. Necesita una decisión de diseño tuya.

### H. Adapters nuevos
Estado al 2026-08-20, verificado con requests reales:

| Tienda | Estado |
|---|---|
| **Easy, Carrefour, Jumbo** | ✅ Integradas. VTEX, solo configuración |
| **Coto** | Migró a Constructor.io (`key_r6xzz4IAoTWcipni`). Necesita adapter nuevo, ~1 día. A cambio: 4.911 productos de electro, con descuentos y cuotas ya en el payload, y filtro por categoría (`catv00001990` = Electro) |
| **ChangoMás** | VTEX puro, sin bloqueo, trae EAN. Integrable en 5 minutos — **pero sus términos prohíben el deep-linking sin permiso escrito** (cláusula 18). Decisión legal pendiente |
| **Tiendamia** | Bloqueada por Cloudflare. Ver §4-H |
| **Garbarino** | ⛔ Quiebra decretada en marzo 2026. El dominio no resuelve. Cerrado |
| **Musimundo** | Sitio caído desde el 2026-03-09, catálogo congelado en octubre 2025, empresa en concurso preventivo. Su backend VTEX responde (`musimundo.myvtex.com`, cuenta `musimundo`) pero servir precios de hace 10 meses sería engañoso. Vale un re-check en unos meses: si relanzan, es configuración pura |
| **Día, Farmacity** | APIs funcionando, pero son almacén y farmacia — poco que comparar con electro |
| **Disco y Vea** | ⛔ Descartadas a proposito. Son el mismo catalogo que Jumbo: sobre 10 resultados de "heladera", 9 productos son los mismos y **los tres con precio identico**. Cencosud las corre sobre la misma cuenta VTEX y el canal de ventas esta desactivado (`sc is inactive`). Sumarlas haria que una ficha diga "3 tiendas comparadas" mostrando un solo precio tres veces |
| Rodó, Casa del Audio, Dexter, Solo Deportes, Avenida, Mexx, Philco | 404 en las rutas VTEX. No usan esa plataforma |
| Full H4rd, Venex, Maximus | 403 o HTML. Sin API accesible |

**Precios Claros / SEPA quedó descartado con datos:** se midió que Coto y Jumbo reportan
ahí **cero televisores y cero notebooks**. Ni siquiera Frávega reporta TVs. Es casi todo
alimentos — no es una vía para electro.

---

### H. Tiendamia — bloqueada por Cloudflare (2026-08-20)

Investigada a fondo porque tiene mucho catalogo. **No se integro**, y el motivo final es
tecnico, no de diseno: despues de un rato de consultas, Cloudflare empezo a devolver
`403` con `cf-mitigated: challenge` a **todo el sitio** (la home incluida) desde cualquier
User-Agent, incluido uno de Chrome completo. Solo pasa `robots.txt`.

Pasar ese desafio significa evadir deteccion de bots. No se hace: es la linea que el
proyecto ya decidio no cruzar, y ademas se arriesga a que bloqueen la IP del servidor.

Lo que se averiguo antes del bloqueo, por si algun dia se retoma:

| Punto | Hallazgo |
|---|---|
| API oficial | No existe. `api.tiendamia.com` solo sirve el historial del autocomplete |
| Plataforma | Magento 2, buscador propio, resultados renderizados en el servidor |
| GraphQL | Expuesto pero con el catalogo vacio (`total_count: 0`) y prohibido por `robots.txt` |
| Ruta util | `GET /search/{vendor}/{termino}` con vendor en `amazon`, `ebay`, `china` |
| Paginacion | Cuarto segmento del path, en base64: `cGFnZSUzRDI=` = `page%3D2`. El `?page=N` se ignora |
| Datos por producto | Atributos `data-sku`, `data-price` (USD), `data-list-price`, `data-discount`, mas marca, titulo, link e imagen. No hace falta navegador headless |
| `robots.txt` | **Permite** `/search/` y `/p/`; prohibe `/api/`, `/graphql/`, `/rest/` |
| Terminos | Sin clausula anti-automatizacion: cero menciones de scraping, robots, crawlers o mineria de datos en 92.000 caracteres |

**El precio de Tiendamia no es comparable con el de un retailer local, y no por un
porcentaje fijo.** Verificado con aritmetica: en una misma pagina de resultados, un
cuaderno de USD 6,59 y una notebook de USD 469,84 salen ambos multiplicados por
**1770,48** exactos. Un precio con envio incluido no puede ser un multiplo fijo, porque el
envio depende del peso. Es el precio del producto en dolares, a una cotizacion propia
~17% arriba del oficial.

Lo que falta encima: envio internacional (variable por peso) mas impuestos de aduana, que
dependen del **historial de compras del usuario** — hay 12 franquicias anuales de USD 50 y,
pasado el cupo, 50% sobre el costo. No hay forma de declarar esa brecha como un numero.

Decision tomada: si algun dia se integra, va igual en la comparacion principal (decision
del 2026-08-20), pero **con la etiqueta visible en la ficha** aclarando que el precio no
incluye envio ni impuestos de importacion — el mismo criterio que se uso con el descuento
por transferencia de Compra Gamer.

Vias legitimas para retomarla: esperar y reintentar desde otra IP (el desafio parece de
reputacion, no permanente), o pedir acceso por su programa de afiliados
(`affiliateprogram.tiendamia.com`), que seria la via limpia y ademas monetizable.


---

## 5. Deuda técnica conocida

Nada de esto rompe hoy. Está acá para que no sorprenda después.

### 1. El matcher es O(n²)
Medido: 250 publicaciones → 0,26 s; 4.000 → 30 s. Extrapolado, 40.000 → ~50 minutos.
Con las 426 de hoy tarda menos de un segundo. **Antes de sumar la cuarta y quinta tienda**
hay que agrupar por marca/código antes de comparar, en vez de comparar todos contra todos.

### 2. Los adapters son bloqueantes
FastAPI corre los endpoints sincrónicos en un pool de 40 hilos compartido. Si ML está
lento, 40 búsquedas simultáneas pueden dejar sin responder al resto del backend —
incluido `/health`, lo que haría que el hosting reinicie el proceso.

### 3. `/sources` recalcula todo en cada visita
Lee la tabla `listing` entera para calcular el ranking de tiendas. Tolerable hasta ~50.000
publicaciones; a partir de ~300.000 hay que cachearlo. **Ya tiene el índice que le faltaba.**

### 4. Las búsquedas por texto no usan índice
`ILIKE '%texto%'` obliga a recorrer la tabla completa. La solución (índice GIN con
`pg_trgm`) solo aplica a Postgres, así que recién se puede hacer después de desplegar.

### 5. Los precios no siempre son comparables entre tiendas

Compra Gamer destaca el precio **con 10% de descuento por transferencia**; con tarjeta
sale bastante más. Las otras cinco publican su precio de lista sin descuentos por medio
de pago.

Decisión tomada el 2026-08-06: se guarda el precio que la tienda destaca, porque es el
que el usuario ve al hacer clic — mostrar otro número haría dudar del comparador. La
consecuencia es que **Compra Gamer aparece más barata de lo que sale con tarjeta**.

La solución de fondo es guardar los dos precios y mostrar "$X con transferencia · $Y con
tarjeta". Necesita una columna nueva en `listing` y tocar la ficha. Conviene hacerlo
cuando haya una segunda fuente que exponga precios por medio de pago — en el retail
argentino es habitual, así que va a pasar.

### 6. La evicción no corre sola todavía
La política existe y funciona, pero hay que dispararla (`python -m app.workers.maintenance`).
Cuando armemos la ingesta automática (§1-B) va en el mismo cron, una vez por día.

---

## 6. Lo que ya está hecho

Para no volver a pedirlo:

- ✅ **Nueve tiendas con datos reales**: Frávega, Cetrogar, Naldo, OnCity, Megatone,
  Compra Gamer, Easy, Carrefour y Jumbo. La base crece sola con cada búsqueda nueva.
- ✅ **Similares**: los modelos parecidos se muestran aparte de la comparación estricta,
  para que el "ahorrás hasta X" no compare productos distintos.
- ✅ **Matching entre tiendas**: 50 productos comparables entre 2 y 3 tiendas.
- ✅ **Ranking de tiendas por competitividad** (`/sources`), con datos propios.
- ✅ **Gráfico de historial de precios** en la ficha de producto.
- ✅ **Página de transparencia** `/como-funciona`, alimentada en vivo.
- ✅ **Pegar el link de cualquier tienda** en el buscador.
- ✅ **SEO**: sitemap, robots, metadatos. Falta solo la imagen de Open Graph.
- ✅ **Responsive**, verificado a 390 px y 1600×600.
- ✅ **182 tests**.
- ✅ **Seed de tiendas para producción** (`scripts/seed_sources.py`).
- ✅ **Sin secretos en el repo** — auditado sobre todo el historial de git.

### Bugs corregidos el 2026-08-04 tras las auditorías

Los que cambiaban lo que veía el usuario:

- El cluster del **iPhone 13 se había comido publicaciones de iPhone 14 y 15**, y mostraba
  un rango de precios que comparaba tres teléfonos distintos.
- Dos tiendas que publicaban **el mismo televisor con el código del fabricante** quedaban
  en clusters separados, o sea sin comparar — justo lo que el sitio existe para hacer.
- Los **links a Frávega** llevaban a su página de búsqueda en vez de al producto.
- `/search` devolvía **error 500 en la home** si MercadoLibre respondía con HTML.
- El **sitemap no incluía ningún producto** (pedía 200 y el máximo era 100).

Los que te iban a frenar en el deploy:

- `CORS_ORIGINS` en el formato que documentaba el ejemplo **impedía que la app arrancara**.
- Un **token de ML vencido dejaba la fuente marcada como "bloqueada por ToS" para siempre**,
  y eso se publicaba en la página de transparencia.
- **No existía forma de sembrar las tiendas** en una base nueva.
- Ningún campo se truncaba: en Postgres, **un título largo aborta la corrida entera** del
  matcher (SQLite no dice nada).
- `DATABASE_URL` tenía un default que apuntaba a un Postgres de producción inventado.
