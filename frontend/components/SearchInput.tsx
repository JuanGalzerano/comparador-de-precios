"use client";

import { useState, useRef } from "react";
import { parseProductUrl } from "@/lib/ml-url";

interface SearchInputProps {
  defaultValue?: string;
  placeholder?: string;
  style?: React.CSSProperties;
}

/**
 * Input de búsqueda con detección de URL de MercadoLibre.
 * Al pegar una URL de ML, extrae los términos de búsqueda y los pone en el
 * input en lugar de la URL cruda. El form sigue siendo un GET estándar.
 */
export function SearchInput({ defaultValue = "", placeholder, style }: SearchInputProps) {
  const [value, setValue] = useState(defaultValue);
  const [urlDetected, setUrlDetected] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value;
    setValue(v);
    setUrlDetected(null);

    const link = parseProductUrl(v);
    if (link) {
      setValue(link.terms);
      setUrlDetected(link.source);
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text");
    const link = parseProductUrl(pasted);
    if (!link) return;

    e.preventDefault();
    setValue(link.terms);
    setUrlDetected(link.source);
  }

  return (
    <div style={{ position: "relative", flex: style?.flex ?? 1, maxWidth: style?.maxWidth }}>
      <input
        ref={inputRef}
        className="input"
        type="search"
        name="q"
        value={value}
        onChange={handleChange}
        onPaste={handlePaste}
        placeholder={placeholder ?? "Buscar producto o pegar link de MercadoLibre"}
        aria-label="Buscar un producto"
        style={{ width: "100%", ...style, flex: undefined, maxWidth: undefined }}
      />
      {urlDetected && (
        <span
          style={{
            position: "absolute",
            bottom: "calc(100% + 4px)",
            left: 0,
            fontSize: 11,
            color: "var(--color-accent)",
            background: "var(--color-surface)",
            border: "1px solid var(--color-divider)",
            borderRadius: 4,
            padding: "2px 6px",
            whiteSpace: "nowrap",
            pointerEvents: "none",
          }}
        >
          Link de {urlDetected} detectado — comparando en todas las tiendas ✓
        </span>
      )}
    </div>
  );
}
