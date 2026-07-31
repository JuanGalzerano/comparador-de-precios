/** @type {import('next').NextConfig} */
const nextConfig = {
  // Fija la raiz del workspace a este directorio: hay un package-lock.json
  // ajeno al proyecto en un ancestro (fuera de comparador-de-precios/) que si
  // no, Next lo detecta como raiz por error.
  turbopack: {
    root: import.meta.dirname,
  },
};

export default nextConfig;
