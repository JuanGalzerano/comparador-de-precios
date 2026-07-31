import Link from "next/link";

export default function ProductNotFound() {
  return (
    <main style={{ maxWidth: 1240, margin: "0 auto", padding: "var(--space-8)" }}>
      <Link href="/" style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 5 }}>
        ← Volver a la búsqueda
      </Link>
      <div className="card" style={{ maxWidth: 480, marginTop: "var(--space-6)" }}>
        <div className="card-title">Producto no encontrado</div>
        <p className="card-body">No existe ningún producto con ese id.</p>
      </div>
    </main>
  );
}
