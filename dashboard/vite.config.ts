import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em dev, o Vite roda em :5173 e repassa as chamadas de API para a FastAPI
// em :8000. Em produção, o build (dist/) é servido pela própria API.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
