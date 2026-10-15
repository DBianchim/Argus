/** Tema escuro NOC do Argus — tokens semânticos fixos.
 *  Cores de status NUNCA mudam de significado:
 *  ok=verde · warn=âmbar · crit=vermelho · offline/unknown=cinza
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0B1220", // fundo da aplicação
          raised: "#111B2E",  // cards e painéis
          border: "#1E2A3F",  // bordas e divisores
        },
        status: {
          ok: "#10B981",
          warn: "#F59E0B",
          crit: "#EF4444",
          offline: "#64748B",
          unknown: "#94A3B8",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        // Usadas na tela "Dashboard" (visão geral) — demais telas seguem Inter
        // até o resto do redesenho ser implementado.
        "plex-sans": ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        "plex-mono": ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      keyframes: {
        "status-pulse": {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.35 },
        },
      },
      animation: {
        // Dot de servidor crítico no card do dashboard
        "status-pulse": "status-pulse 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
