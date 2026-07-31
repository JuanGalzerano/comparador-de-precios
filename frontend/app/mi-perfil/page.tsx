import { redirect } from "next/navigation";
import { LogoutButton } from "@/components/LogoutButton";
import { getCurrentUser } from "@/lib/session";

/** Perfil del usuario logueado. Guard de sesion server-side: sin usuario,
 * redirige a `/ingresar` con `?next=` para volver aca despues de loguearse. */
export default async function MiPerfilPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/ingresar?next=/mi-perfil");

  const displayName = user.display_name ?? user.email.split("@")[0];
  const createdAt = new Date(user.created_at).toLocaleDateString("es-AR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <main
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "var(--space-8) var(--space-8) 80px",
        width: "100%",
      }}
    >
      <div style={{ maxWidth: 480, padding: "56px 0 0" }}>
        <h2 style={{ marginBottom: "var(--space-6)" }}>Mi perfil</h2>

        <div className="card" style={{ padding: "var(--space-6)", gap: "var(--space-4)" }}>
          <div>
            <div className="text-muted" style={{ fontSize: 12, marginBottom: 3 }}>
              Nombre
            </div>
            <div style={{ fontSize: 16 }}>{displayName}</div>
          </div>
          <div>
            <div className="text-muted" style={{ fontSize: 12, marginBottom: 3 }}>
              Email
            </div>
            <div style={{ fontSize: 16 }}>{user.email}</div>
          </div>
          <div>
            <div className="text-muted" style={{ fontSize: 12, marginBottom: 3 }}>
              Miembro desde
            </div>
            <div style={{ fontSize: 16 }}>{createdAt}</div>
          </div>

          <div style={{ marginTop: "var(--space-4)" }}>
            <LogoutButton />
          </div>
        </div>
      </div>
    </main>
  );
}
