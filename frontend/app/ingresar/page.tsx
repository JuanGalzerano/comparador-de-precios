import { AuthForm } from "@/components/AuthForm";

interface IngresarPageProps {
  searchParams: Promise<{ next?: string }>;
}

/**
 * Login/registro. Server Component minimo (titulo + form); el circuito real
 * (fetch, cookie, redirect) vive en `AuthForm` (client) via los Route
 * Handlers de `/api/auth`. `?next=` viaja a traves para volver a donde
 * el usuario venia (ej. `/mi-perfil` cuando el guard de sesion redirige aca).
 */
export default async function IngresarPage({ searchParams }: IngresarPageProps) {
  const { next } = await searchParams;

  return (
    <main
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "var(--space-8) var(--space-8) 80px",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <div style={{ width: "100%", maxWidth: 420, padding: "56px 0 var(--space-6)" }}>
        <h2 style={{ marginBottom: "var(--space-2)" }}>Ingresá a tu cuenta</h2>
        <p className="text-muted" style={{ fontSize: 14, margin: 0 }}>
          Guardá productos y encontralos después en un solo lugar.
        </p>
      </div>

      <AuthForm next={next} />
    </main>
  );
}
