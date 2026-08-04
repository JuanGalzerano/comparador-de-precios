import type { Metadata } from "next";
import Link from "next/link";
import { SourcesTable } from "@/components/SourcesTable";

export const metadata: Metadata = {
  title: "Cómo funciona Cotejo",
  description:
    "De dónde sale la información de Cotejo, cómo se calcula el score de cada publicación y por qué el orden no es solo por precio.",
};

/** Fuentes que todavía no existen como fila en la base — no salen de `/sources`. */
const PENDIENTES = [
  {
    nombre: "Precios Claros / SEPA",
    detalle:
      "Dato oficial del gobierno argentino. Falta confirmar si las cadenas de electro y tecnología reportan ahí antes de construir el importador.",
  },
  {
    nombre: "Musimundo, Garbarino, Compumundo",
    detalle:
      "Sin API pública accesible al momento de la última revisión. Se evalúan una por una; ninguna se activa sin revisar sus términos de servicio.",
  },
];

export default function ComoFuncionaPage() {
  return (
    <main
      style={{
        maxWidth: 760,
        margin: "0 auto",
        padding: "var(--space-8) var(--space-8) 96px",
        width: "100%",
      }}
    >
      <div style={{ padding: "48px 0 var(--space-6)" }}>
        <h1 style={{ fontSize: 34, marginBottom: "var(--space-3)" }}>Cómo funciona Cotejo</h1>
        <p className="text-muted" style={{ fontSize: 15, maxWidth: 600 }}>
          Buscador que agrupa publicaciones de distintas tiendas para el mismo producto y las
          ordena por un score compuesto — no solo por el precio más bajo. Esta página explica de
          dónde sale cada dato y cómo se calcula ese orden.
        </p>
      </div>

      <section style={{ marginTop: 40 }}>
        <h2 style={{ fontSize: 19 }}>De dónde sale la información</h2>
        <p className="text-muted" style={{ fontSize: 14 }}>
          Cada fuente queda registrada con su estado — nada se activa en silencio. Los números
          salen de la base de datos, en vivo.
        </p>

        <SourcesTable />

        <h3 style={{ fontSize: 15, marginTop: 32 }}>Todavía no integradas</h3>
        <div style={{ marginTop: "var(--space-3)", display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          {PENDIENTES.map((f) => (
            <div key={f.nombre} className="card" style={{ padding: "var(--space-4)" }}>
              <div className="card-title" style={{ fontSize: 15 }}>{f.nombre}</div>
              <p className="card-body">{f.detalle}</p>
            </div>
          ))}
        </div>
      </section>

      <section style={{ marginTop: 40 }}>
        <h2 style={{ fontSize: 19 }}>Cómo se calcula el orden</h2>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          El orden por defecto no es &ldquo;más barato primero&rdquo;. Cada publicación recibe un
          score que pondera:
        </p>
        <ul style={{ fontSize: 14.5, lineHeight: 1.9, paddingLeft: 22 }}>
          <li><strong>Precio final</strong> — precio de lista más costo de envío, no el precio &ldquo;pelado&rdquo;.</li>
          <li><strong>Reputación del vendedor</strong> — nivel de MercadoLíder y si es tienda oficial.</li>
          <li><strong>Cuotas sin interés</strong> — pagar en cuotas sin recargo suma puntos.</li>
          <li><strong>Garantía</strong> — meses de cobertura y si es de fábrica o del vendedor.</li>
          <li><strong>Opiniones</strong> — cantidad y calificación de reseñas del producto.</li>
        </ul>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          Un vendedor sin trayectoria con el precio más bajo no gana automáticamente: podés
          reordenar por precio, opiniones, garantía o reputación desde la ficha de cada producto.
        </p>
      </section>

      <section style={{ marginTop: 40 }}>
        <h2 style={{ fontSize: 19 }}>Historial de precios</h2>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          Cada vez que el precio de una publicación cambia, guardamos un punto nuevo. La ficha de
          producto muestra la evolución del precio más bajo disponible en los últimos 90 días,
          para distinguir una oferta real de un precio que &ldquo;bajó&rdquo; después de haber
          subido.
        </p>
      </section>

      <section style={{ marginTop: 40 }}>
        <h2 style={{ fontSize: 19 }}>Qué no hacemos</h2>
        <ul style={{ fontSize: 14.5, lineHeight: 1.9, paddingLeft: 22 }}>
          <li>No procesamos pagos: el botón de compra siempre lleva a la publicación original de la tienda.</li>
          <li>No hacemos scraping desde tu navegador — por seguridad del propio navegador (CORS), eso ni es posible.</li>
          <li>No mostramos todas las fuentes como si fueran igual de confiables: cada resultado indica de dónde sale el dato.</li>
        </ul>
      </section>

      <div style={{ marginTop: 48 }}>
        <Link href="/" className="btn btn-secondary">← Volver a Cotejo</Link>
      </div>
    </main>
  );
}
