import type { Metadata } from "next";
import Link from "next/link";
import { HeaderAuth } from "@/components/HeaderAuth";
import { SearchInput } from "@/components/SearchInput";
import { Footer } from "@/components/Footer";
import { SITE_URL } from "@/lib/config";
import "../styles/nocturne.css";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Cotejo — Comparador de precios Argentina",
    template: "%s | Cotejo",
  },
  description:
    "Compará precios de celulares, electrónica y tecnología en MercadoLibre, Frávega, Cetrogar, Naldo y más. Precio final con envío, cuotas y garantía en Argentina.",
  openGraph: {
    siteName: "Cotejo",
    locale: "es_AR",
    type: "website",
    title: "Cotejo — Comparador de precios Argentina",
    description:
      "Compará precios de celulares, electrónica y tecnología en MercadoLibre, Frávega, Cetrogar, Naldo y más. Precio final con envío, cuotas y garantía en Argentina.",
  },
  twitter: {
    card: "summary",
    title: "Cotejo — Comparador de precios Argentina",
    description:
      "Compará precios en MercadoLibre, Frávega, Cetrogar y más. Precio con envío, cuotas y garantía.",
  },
  robots: { index: true, follow: true },
};

/**
 * Layout minimo a proposito (alcance de esta tarea): solo
 * marca + buscador. Nav completa (/ofertas, /para-vos, "Ingresar"), cookie
 * consent y ads del prototipo quedan afuera — no se clona la pagina entera,
 * solo el circuito busqueda -> resultados -> ficha.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-AR">
      <body>
        <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "var(--color-bg)" }}>
          <header
            className="site-header"
            style={{
              position: "sticky",
              top: 0,
              zIndex: 20,
              background: "color-mix(in srgb, var(--color-bg) 90%, transparent)",
              backdropFilter: "blur(12px)",
              WebkitBackdropFilter: "blur(12px)",
              borderBottom: "1px solid var(--color-divider)",
            }}
          >
            <div
              className="site-header-inner"
              style={{
                maxWidth: 1240,
                margin: "0 auto",
                padding: "12px var(--space-8)",
                display: "flex",
                alignItems: "center",
                gap: "var(--space-8)",
              }}
            >
              <Link
                href="/"
                className="site-brand"
                style={{ display: "flex", alignItems: "center", gap: 7, textDecoration: "none", color: "inherit", flexShrink: 0 }}
              >
                <span style={{ fontSize: 18, color: "var(--color-accent)", lineHeight: 1 }}>⚖</span>
                <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em" }}>Cotejo</span>
              </Link>

              <form action="/" method="get" className="site-search-form" style={{ flex: 1, maxWidth: 520 }}>
                <SearchInput placeholder="Buscar producto o pegar link de MercadoLibre" />
              </form>

              <div style={{ marginLeft: "auto", flexShrink: 0 }}>
                <HeaderAuth />
              </div>
            </div>
          </header>

          <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>{children}</div>
          <Footer />
        </div>
      </body>
    </html>
  );
}
