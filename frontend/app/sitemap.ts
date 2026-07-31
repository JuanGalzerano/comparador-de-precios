import type { MetadataRoute } from "next";
import { API_URL } from "@/lib/config";
import { fetchJson } from "@/lib/fetch-result";
import type { SearchResponse } from "@/lib/types";

const BASE = "https://cotejo.ar";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const static_pages: MetadataRoute.Sitemap = [
    { url: BASE, changeFrequency: "daily", priority: 1 },
    { url: `${BASE}/ingresar`, changeFrequency: "monthly", priority: 0.3 },
  ];

  const result = await fetchJson<SearchResponse>(
    `${API_URL}/search?${new URLSearchParams({ page_size: "200" })}`,
  );
  if (!result.ok) return static_pages;

  const product_pages: MetadataRoute.Sitemap = result.data.items.map((cluster) => ({
    url: `${BASE}/productos/${cluster.id}`,
    changeFrequency: "daily" as const,
    priority: 0.8,
  }));

  return [...static_pages, ...product_pages];
}
