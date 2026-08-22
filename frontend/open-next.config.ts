import { defineCloudflareConfig } from "@opennextjs/cloudflare";

/**
 * Config minima a proposito: sin caches externos.
 *
 * El adaptador permite guardar el cache incremental de Next en R2, pero Cotejo casi no
 * tiene contenido estatico que cachear — todas las paginas se arman con datos vivos del
 * backend. Sumar un bucket seria un servicio mas que configurar y pagar sin ganar nada.
 */
export default defineCloudflareConfig();
