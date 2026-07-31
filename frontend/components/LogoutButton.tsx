"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

/** Cierra la sesion via `/api/auth/logout` (Route Handler: reenvia el
 * `Set-Cookie` de borrado del backend) y refresca para que el resto de la
 * UI (header, guards de sesion) deje de verse logueado. */
export function LogoutButton() {
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();

  async function handleLogout() {
    setSubmitting(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      router.push("/");
      router.refresh();
    }
  }

  return (
    <button className="btn btn-secondary" type="button" onClick={handleLogout} disabled={submitting}>
      {submitting ? "Saliendo…" : "Cerrar sesión"}
    </button>
  );
}
