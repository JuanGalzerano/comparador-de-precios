"use client";

import { useState, useRef } from "react";
import { parseMlUrl } from "@/lib/ml-url";

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
  const [mlDetected, setMlDetected] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value;
    setValue(v);
    setMlDetected(false);

    const ml = parseMlUrl(v);
    if (ml) {
      setValue(ml.terms);
      setMlDetected(true);
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text");
    const ml = parseMlUrl(pasted);
    if (!ml) return;

    e.preventDefault();
    setValue(ml.terms);
    setMlDetected(true);
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
      {mlDetected && (
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
          Link de MercadoLibre detectado ✓
        </span>
      )}
    </div>
  );
}
