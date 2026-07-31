"use client";

import { useRef, useState, useEffect } from "react";
import Link from "next/link";

interface UserMenuProps {
  label: string;
}

export function UserMenu({ label }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="btn btn-secondary"
        style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}
      >
        Mi perfil
        <span style={{ fontSize: 10, opacity: 0.6 }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 8px)",
            minWidth: 180,
            background: "var(--color-surface)",
            border: "1px solid var(--color-divider)",
            borderRadius: "var(--radius-md)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.32)",
            zIndex: 50,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "var(--space-3) var(--space-4)",
              borderBottom: "1px solid var(--color-divider)",
              fontSize: 12,
            }}
            className="text-muted"
          >
            {label}
          </div>
          <Link
            href="/mi-perfil"
            onClick={() => setOpen(false)}
            style={{
              display: "block",
              padding: "var(--space-3) var(--space-4)",
              fontSize: 14,
              textDecoration: "none",
              color: "inherit",
            }}
          >
            Mi perfil
          </Link>
          <Link
            href="/guardados"
            onClick={() => setOpen(false)}
            style={{
              display: "block",
              padding: "var(--space-3) var(--space-4)",
              fontSize: 14,
              textDecoration: "none",
              color: "inherit",
            }}
          >
            Guardados
          </Link>
        </div>
      )}
    </div>
  );
}
