import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/config";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/mi-perfil", "/guardados", "/ingresar"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
