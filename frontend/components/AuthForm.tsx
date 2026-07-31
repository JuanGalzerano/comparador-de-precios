"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Mode = "login" | "register";

/**
 * Formulario de login/registro (toggle entre los dos modos, mismo form).
 * Pega a los Route Handlers `/api/auth/login` y `/api/auth/register` (no
 * directo al backend): esos endpoints reenvian el `Set-Cookie` de sesion que
 * un `fetch` de cliente jamas podria ver/setear el mismo, por ser `HttpOnly`.
 *
 * Al exito: `router.push` + `router.refresh()`. El refresh es obligatorio —
 * sin el, Server Components ya renderizados (el header, por ejemplo) no se
 * vuelven a pedir y siguen mostrando "Ingresar" con la sesion ya activa.
 */
export function AuthForm({ next }: { next?: string }) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const res = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          mode === "register"
            ? { email, password, display_name: displayName.trim() || null }
            : { email, password },
        ),
      });

      if (res.ok) {
        router.push(next ?? "/");
        router.refresh();
        return;
      }

      const body: unknown = await res.json().catch(() => null);
      const detail =
        body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
          ? body.detail
          : "No pudimos completar la operación. Probá de nuevo.";
      setError(detail);
    } catch {
      setError("No pudimos conectar con el servidor. Probá de nuevo.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 420, padding: "var(--space-6)" }}>
      <div style={{ display: "flex", gap: "var(--space-3)", marginBottom: "var(--space-4)" }}>
        <button
          type="button"
          className={mode === "login" ? "btn btn-primary" : "btn btn-secondary"}
          onClick={() => {
            setMode("login");
            setError(null);
          }}
          style={{ flex: 1 }}
        >
          Ingresar
        </button>
        <button
          type="button"
          className={mode === "register" ? "btn btn-primary" : "btn btn-secondary"}
          onClick={() => {
            setMode("register");
            setError(null);
          }}
          style={{ flex: 1 }}
        >
          Crear cuenta
        </button>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        {mode === "register" && (
          <div className="field">
            <label htmlFor="display_name">Nombre (opcional)</label>
            <input
              id="display_name"
              className="input"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={80}
              autoComplete="name"
            />
          </div>
        )}

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            className="input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </div>

        <div className="field">
          <label htmlFor="password">Contraseña</label>
          <input
            id="password"
            className="input"
            type="password"
            required
            minLength={mode === "register" ? 8 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
        </div>

        {error && (
          <p style={{ color: "#e08a8a", fontSize: 13, margin: 0 }} role="alert">
            {error}
          </p>
        )}

        <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
          {submitting ? "Un momento…" : mode === "login" ? "Ingresar" : "Crear cuenta"}
        </button>
      </form>
    </div>
  );
}
