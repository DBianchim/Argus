import { Eye, Loader2 } from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, storeSession } from "../api/client";

export function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const session = await login(username, password);
      storeSession(session);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro inesperado");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2">
          <Eye className="h-10 w-10 text-status-ok" aria-hidden />
          <h1 className="text-2xl font-semibold tracking-[0.25em] text-slate-100">
            ARGUS
          </h1>
          <p className="text-sm text-slate-500">
            cem olhos sobre a sua infraestrutura
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-surface-border bg-surface-raised p-6"
        >
          <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">
            Usuário
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              className="mt-1.5 w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-status-ok/60"
            />
          </label>

          <label className="mt-4 block text-xs font-medium uppercase tracking-wide text-slate-400">
            Senha
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="mt-1.5 w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-status-ok/60"
            />
          </label>

          {error && (
            <p className="mt-4 rounded-lg border border-status-crit/40 bg-status-crit/10 px-3 py-2 text-xs text-red-200">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-status-ok/90 px-4 py-2 text-sm font-medium text-emerald-950 transition hover:bg-status-ok disabled:opacity-60"
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            Entrar
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-slate-600">
          Acesso restrito. Solicite credenciais ao administrador.
        </p>
      </div>
    </main>
  );
}
