"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { toggleFavorite } from "@/app/actions/favorites";

interface SaveButtonProps {
  productId: number;
  initialSaved: boolean;
  /** Si no hay sesion, no tiene sentido intentar togglear (el server action
   * tiraria 401): en vez de fallar en silencio, el boton linkea a
   * `/ingresar` con `?next=` de vuelta a esta ficha. */
  loggedIn: boolean;
}

/** Corazón/estrella de "guardar" — pega a la Server Action `toggleFavorite`
 * (PUT/DELETE `/me/favorites/{id}`). Optimistic UI: togglea el estado local
 * al click y revierte si la action tira error. */
export function SaveButton({ productId, initialSaved, loggedIn }: SaveButtonProps) {
  const [saved, setSaved] = useState(initialSaved);
  const [isPending, startTransition] = useTransition();

  if (!loggedIn) {
    return (
      <Link
        href={`/ingresar?next=${encodeURIComponent(`/productos/${productId}`)}`}
        className="btn btn-secondary"
        title="Ingresá para guardar este producto"
      >
        ☆ Guardar
      </Link>
    );
  }

  function handleClick() {
    const wasSaved = saved;
    setSaved(!wasSaved);
    startTransition(async () => {
      try {
        await toggleFavorite(productId, wasSaved);
      } catch {
        setSaved(wasSaved);
      }
    });
  }

  return (
    <button
      type="button"
      className={saved ? "btn btn-primary" : "btn btn-secondary"}
      onClick={handleClick}
      disabled={isPending}
      aria-pressed={saved}
    >
      {saved ? "★ Guardado" : "☆ Guardar"}
    </button>
  );
}
