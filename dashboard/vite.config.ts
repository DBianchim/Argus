import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Em dev, o Vite roda em :5173 e repassa as chamadas de API para a FastAPI
// em :8000. Em produção, o build (dist/) é servido pela própria API.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["argus-eye.svg"],
      pwaAssets: {
        image: "public/argus-eye.svg",
      },
      manifest: {
        name: "Argus — Monitoramento de Infraestrutura",
        short_name: "Argus",
        description: "Central de monitoramento de servidores Windows e Linux",
        lang: "pt-BR",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "any",
        background_color: "#0B1220",
        theme_color: "#0B1220",
      },
      workbox: {
        // O SPA é servido pela API; o SW nunca intercepta a API nem o /docs,
        // para os dados (autenticados) chegarem sempre frescos.
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/, /^\/health/, /^\/docs/, /^\/redoc/],
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff2}"],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
