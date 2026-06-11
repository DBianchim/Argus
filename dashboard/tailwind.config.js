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
      },
    },
  },
  plugins: [],
};
