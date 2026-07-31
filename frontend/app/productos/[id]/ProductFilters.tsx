"use client";

import { useRouter } from "next/navigation";
import type { ConditionFilter, SortKey } from "@/lib/types";

/**
 * Toolbar de orden/filtro de la tabla — port de los controles de
 * `project/Cotejo - Comparador.dc.html:256-281` (`conditions`/`toggles`/
 * `sort`). El backend ya sabe ordenar/filtrar via query params
 * (`GET /products/{id}?sort=...&free=...`), asi que este componente de
 * cliente solo actualiza la URL; el Server Component de la pagina vuelve a
 * hacer fetch con los nuevos params (SSR, no client-side filtering).
 */

interface FiltersState {
  sort: SortKey;
  condition: ConditionFilter;
  free: boolean;
  official: boolean;
  warranty: boolean;
}

interface ProductFiltersProps extends FiltersState {
  productId: number;
}

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "score", label: "Ordenar por score" },
  { value: "price", label: "Ordenar por precio final" },
  { value: "rating", label: "Ordenar por opiniones" },
  { value: "warranty", label: "Ordenar por garantía" },
  { value: "seller", label: "Ordenar por reputación" },
];

// El prototipo solo expone Todas/Nuevas/Usadas (`.dc.html:260-265`); el
// backend acepta ademas "refurbished"/"unknown" pero no hay UI para eso en
// el mock que estamos portando, asi que no se agrega ac.
const CONDITIONS: { value: ConditionFilter; label: string }[] = [
  { value: "all", label: "Todas" },
  { value: "new", label: "Nuevas" },
  { value: "used", label: "Usadas" },
];

const TOGGLES: { key: "free" | "official" | "warranty"; label: string }[] = [
  { key: "free", label: "Envío gratis" },
  { key: "official", label: "Tienda oficial" },
  { key: "warranty", label: "Garantía 6m+" },
];

export function ProductFilters(props: ProductFiltersProps) {
  const router = useRouter();

  function update(patch: Partial<FiltersState>) {
    const next: FiltersState = {
      sort: props.sort,
      condition: props.condition,
      free: props.free,
      official: props.official,
      warranty: props.warranty,
      ...patch,
    };
    const params = new URLSearchParams({ sort: next.sort, condition: next.condition });
    if (next.free) params.set("free", "true");
    if (next.official) params.set("official", "true");
    if (next.warranty) params.set("warranty", "true");
    router.push(`/productos/${props.productId}?${params.toString()}`);
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        flexWrap: "wrap",
      }}
    >
      <div className="seg">
        {CONDITIONS.map((c) => (
          <label className="seg-opt" key={c.value}>
            <input
              type="radio"
              name="cond"
              checked={props.condition === c.value}
              onChange={() => update({ condition: c.value })}
            />
            <span>{c.label}</span>
          </label>
        ))}
      </div>

      {TOGGLES.map((t) => (
        <label className="radio" style={{ fontSize: 13 }} key={t.key}>
          <input
            type="checkbox"
            checked={props[t.key]}
            onChange={() => update({ [t.key]: !props[t.key] } as Partial<FiltersState>)}
          />
          <span className="dot" />
          {t.label}
        </label>
      ))}

      <select
        className="input"
        value={props.sort}
        onChange={(e) => update({ sort: e.target.value as SortKey })}
        style={{ width: "auto", cursor: "pointer" }}
      >
        {SORT_OPTIONS.map((o) => (
          <option value={o.value} key={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
