import Link from "next/link";

export function Footer() {
  return (
    <footer
      style={{
        borderTop: "1px solid var(--color-divider)",
        marginTop: 64,
      }}
    >
      <div
        style={{
          maxWidth: 1240,
          margin: "0 auto",
          padding: "var(--space-8)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "var(--space-4)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 14, color: "var(--color-accent)" }}>⚖</span>
          <span className="text-muted" style={{ fontSize: 13 }}>
            Cotejo — comparador de precios, Argentina
          </span>
        </div>

        <nav style={{ display: "flex", gap: "var(--space-6)", flexWrap: "wrap" }}>
          <Link href="/como-funciona" style={{ fontSize: 13 }}>
            Cómo funciona
          </Link>
          <a
            href="https://developers.mercadolibre.com.ar"
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 13 }}
          >
            Fuente: MercadoLibre
          </a>
        </nav>
      </div>
    </footer>
  );
}
