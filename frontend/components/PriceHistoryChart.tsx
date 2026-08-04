"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/config";
import { money, toNumber } from "@/lib/format";
import type { PriceHistoryResponse } from "@/lib/types";

/**
 * Grafico de historial de precio minimo por dia, ultimos 90 dias
 * (`GET /products/{id}/price-history`). Client component: el endpoint
 * devuelve puntos crudos por publicacion, sin agregar — la agregacion
 * (minimo por dia, entre todas las publicaciones del producto) se hace aca.
 * Si no hay al menos 2 dias con datos no hay linea que trazar, así que el
 * componente no se muestra (mejor que un grafico plano de un punto).
 */
export function PriceHistoryChart({ productId }: { productId: number }) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "empty" }
    | { status: "error" }
    | { status: "ready"; days: { date: string; min: number }[] }
  >({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/products/${productId}/price-history?days=90`)
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json() as Promise<PriceHistoryResponse>;
      })
      .then((data) => {
        if (cancelled) return;
        const byDay = new Map<string, number>();
        for (const point of data.points) {
          const day = point.captured_at.slice(0, 10);
          const total = toNumber(point.price) + toNumber(point.shipping_cost);
          const prev = byDay.get(day);
          if (prev === undefined || total < prev) byDay.set(day, total);
        }
        const days = [...byDay.entries()]
          .map(([date, min]) => ({ date, min }))
          .sort((a, b) => a.date.localeCompare(b.date));
        setState(days.length >= 2 ? { status: "ready", days } : { status: "empty" });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [productId]);

  if (state.status === "loading" || state.status === "error") return null;
  if (state.status === "empty") {
    return (
      <p className="text-muted" style={{ fontSize: 13, marginTop: "var(--space-4)" }}>
        Todavía no tenemos suficiente historial de precios para este producto — volvé en unos
        días.
      </p>
    );
  }

  return <Chart days={state.days} />;
}

function Chart({ days }: { days: { date: string; min: number }[] }) {
  const width = 640;
  const height = 160;
  const padX = 8;
  const padY = 16;

  const values = days.map((d) => d.min);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const range = hi - lo || 1;

  const points = days.map((d, i) => {
    const x = padX + (i / (days.length - 1)) * (width - padX * 2);
    const y = height - padY - ((d.min - lo) / range) * (height - padY * 2);
    return { x, y, d };
  });

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const areaPath = `${linePath} L ${points[points.length - 1].x} ${height - padY} L ${points[0].x} ${height - padY} Z`;

  const first = days[0].min;
  const last = days[days.length - 1].min;
  const delta = last - first;
  const deltaPct = first ? Math.round((delta / first) * 100) : 0;

  return (
    <div style={{ marginTop: "var(--space-4)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: "var(--space-2)",
          flexWrap: "wrap",
          gap: "var(--space-2)",
        }}
      >
        <div className="text-muted" style={{ fontSize: 12 }}>
          Precio más bajo · últimos {days.length} días con datos
        </div>
        {delta !== 0 && (
          <div
            className="num"
            style={{
              fontSize: 12.5,
              color: delta < 0 ? "#4ade80" : "#fca5a5",
            }}
          >
            {delta < 0 ? "↓" : "↑"} {money(Math.abs(delta))} ({Math.abs(deltaPct)}%) desde el
            primer dato
          </div>
        )}
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        style={{ display: "block", overflow: "visible" }}
        role="img"
        aria-label="Gráfico de historial de precio mínimo"
      >
        <defs>
          <linearGradient id="phc-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#phc-fill)" stroke="none" />
        <path d={linePath} fill="none" stroke="var(--color-accent)" strokeWidth={2} />
        {points.map((p, i) => (
          <circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={i === points.length - 1 ? 3.5 : 2}
            fill="var(--color-bg)"
            stroke="var(--color-accent)"
            strokeWidth={1.5}
          >
            <title>
              {p.d.date} · {money(p.d.min)}
            </title>
          </circle>
        ))}
      </svg>

      <div
        className="text-muted num"
        style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginTop: 4 }}
      >
        <span>{formatShortDate(days[0].date)}</span>
        <span>{formatShortDate(days[days.length - 1].date)}</span>
      </div>
    </div>
  );
}

function formatShortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}
