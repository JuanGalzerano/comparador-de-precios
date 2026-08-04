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

### 🔴 A. Token de MercadoLibre — 15 minutos

Es el único bloqueo que no puede resolver el código. ML dejó de permitir acceso sin
autenticación: hoy responde `403` a todo.

1. Entrá a **https://developers.mercadolibre.com.ar** con tu cuenta de ML.
2. **Crear aplicación**: nombre `cotejo-dev`, dominio `localhost`, redirect URI
   `http://localhost:8000/auth/ml/callback`, scope `read`.
3. Copiá `client_id` y `client_secret`.
4. Pedí el token:
   ```bash
   curl -X POST https://api.mercadolibre.com/oauth/token -H "content-type: application/x-www-form-urlencoded" -d "grant_type=client_credentials&client_id=TU_CLIENT_ID&client_secret=TU_CLIENT_SECRET"
   ```
5. Pegá el `access_token` en `backend/.env`:
   ```
   ML_ACCESS_TOKEN=APP_USR-xxxxxx
   ```
6. Reiniciá el backend. **Nada más.**

> **Corrección importante:** las versiones anteriores de este archivo y de
> `MERCADOLIBRE_API.md` decían que después de conseguir el token había que avisarle a
> Claude para modificar `config.py` y el adapter. **Eso ya está hecho** — el adapter
> inyecta el header `Authorization` desde `2026-07-31`, y desde hoy también lo hace la
> búsqueda en vivo de `/search`. Con poner la variable y reiniciar alcanza.

**El token dura 6 horas.** No hay auto-renovación todavía (ver §4-F). Cuando vence, la
ingesta falla con 403. Ya no queda la fuente marcada como "bloqueada por ToS" para
siempre: desde hoy, una corrida exitosa la reactiva sola.

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
   Variables: `DATABASE_URL`, `COTEJO_ENV=production`, `CORS_ORIGINS`, `ML_ACCESS_TOKEN`.
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

**Un millón de publicaciones entra en el plan gratis.** Hoy tenés ~500, y crecen solas
con cada búsqueda nueva (§3). El catálogo entero
de las tres tiendas son decenas de miles, no millones. **El catálogo no es el problema.**

### El problema real es el historial de precios

Esa tabla crece para siempre:

```
50.000 publicaciones × 1 punto por día × 365 días = 18.000.000 filas ≈ 1,8 GB
```

Ahí sí revienta cualquier plan gratis. Se resuelve con dos reglas:

1. **Guardar un punto solo cuando el precio cambia.** ✅ Ya implementado.
2. **Borrar lo más viejo de 90 días.** ❌ Falta (ver §4-C). Con esto el historial se
   estabiliza en decenas de MB y nunca crece más.

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

### C. 🥉 Retención de 90 días en el historial
Es lo que evita que la base crezca sin límite. Media hora de trabajo, y hay que hacerlo
**antes** de que la ingesta corra sola.

### D. Categorías / navegación por rubro
Los productos que crea el matcher no tienen categoría, así que no hay forma de navegar
"todos los celulares". Se puede inferir del título o del breadcrumb de cada tienda.

### E. Panel de administración
Salud de las fuentes (el dato ya existe en `/sources`), disparar ingestas, y revisar los
matches dudosos — que ya se acumulan en `product_match` con su nivel de confianza.

### F. Auto-renovación del token de ML
Para no depender de que renueves a mano cada 6 horas.

### G. Imagen de Open Graph
Para que el link se vea bien al compartirlo. Necesita una decisión de diseño tuya.

### H. Adapters nuevos
| Tienda | Estado |
|---|---|
| Musimundo | Sin API pública accesible en la última revisión |
| Garbarino | El dominio no resolvía |
| Megatone, Rodó, Casa del Audio | Probadas: no exponen API VTEX estándar |
| Mexx, Ribeiro | Sin investigar |

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

### 5. El historial no tiene límite de tamaño
Ver §4-C. **Es lo único de esta lista que hay que resolver antes de automatizar la ingesta.**

---

## 6. Lo que ya está hecho

Para no volver a pedirlo:

- ✅ **Tres tiendas con datos reales**: Frávega, Cetrogar y Naldo. La base crece sola
  con cada búsqueda nueva (514 publicaciones al momento de escribir esto).
- ✅ **Matching entre tiendas**: 50 productos comparables entre 2 y 3 tiendas.
- ✅ **Ranking de tiendas por competitividad** (`/sources`), con datos propios.
- ✅ **Gráfico de historial de precios** en la ficha de producto.
- ✅ **Página de transparencia** `/como-funciona`, alimentada en vivo.
- ✅ **Pegar el link de cualquier tienda** en el buscador.
- ✅ **SEO**: sitemap, robots, metadatos. Falta solo la imagen de Open Graph.
- ✅ **Responsive**, verificado a 390 px y 1600×600.
- ✅ **130 tests**.
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
