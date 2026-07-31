import type { Metadata } from "next";
import Link from "next/link";
import { HeaderAuth } from "@/components/HeaderAuth";
import "../styles/nocturne.css";

export const metadata: Metadata = {
  title: "Cotejo — Comparador de precios",
  description: "Buscá un producto y comparalo en todas sus publicaciones.",
};

/**
 * Layout minimo a proposito (alcance de esta tarea, ver ESTADO.md): solo
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
            style={{
              position: "sticky",
              top: 0,
              zIndex: 20,
              background: "var(--color-bg)",
              boxShadow: "0 1px 0 var(--color-divider)",
            }}
          >
            <div
              style={{
                maxWidth: 1240,
                margin: "0 auto",
                padding: "var(--space-4) var(--space-8)",
                display: "flex",
                alignItems: "center",
                gap: "var(--space-8)",
              }}
            >
              <Link
                href="/"
                style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", textDecoration: "none", color: "inherit" }}
              >
                <span style={{ fontSize: 20, color: "var(--color-accent)" }}>⚖</span>
                <span style={{ fontSize: 17, fontWeight: 500, letterSpacing: "-0.01em" }}>Cotejo</span>
              </Link>

              <form action="/" method="get" style={{ flex: 1, maxWidth: 560 }}>
                <input
                  className="input"
                  type="search"
                  name="q"
                  placeholder="Buscar un producto"
                  aria-label="Buscar un producto"
                />
              </form>

              <HeaderAuth />
            </div>
          </header>

          <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>{children}</div>
        </div>
      </body>
    </html>
  );
}
