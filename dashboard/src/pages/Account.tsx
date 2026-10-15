import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import {
  api,
  changePassword,
  getStoredUser,
  listSessions,
  patchOwnProfile,
  revokeSession,
  storeSession,
} from "../api/client";
import { Sidebar } from "../components/Sidebar";
import { UsersPanel } from "../components/UsersPanel";
import type { OverviewOut, SessionOut } from "../types";
import { ROLE_META, relativeTime } from "../utils";

function ProfileCard() {
  const user = getStoredUser();
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () => patchOwnProfile(displayName || null),
    onSuccess: () => {
      setSaved(true);
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setTimeout(() => setSaved(false), 2000);
    },
  });

  if (!user) return null;
  const meta = ROLE_META[user.role];
  const initials = (user.display_name ?? user.username).slice(0, 2).toUpperCase();

  return (
    <section className="flex flex-col gap-3.5 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-[18px] py-[18px]">
      <div className="flex items-center gap-3.5">
        <span className="flex h-[52px] w-[52px] flex-none items-center justify-center rounded-full border border-[#2c3549] bg-[#1e2738] font-plex-sans text-[17px] font-semibold text-[#9fb3d9]">
          {initials}
        </span>
        <div className="flex flex-col gap-0.5">
          <span className="font-plex-sans text-base font-semibold text-[#e2e6f0]">
            {user.display_name ?? user.username}
          </span>
          <span className="font-plex-mono text-xs text-[#5b6274]">{user.username}</span>
        </div>
        <span className={`ml-auto w-fit flex-none self-start rounded px-2.5 py-[3px] font-plex-sans text-[10px] font-semibold tracking-[0.05em] ${meta.badge}`}>
          {meta.label.toUpperCase()}
        </span>
      </div>
      <div className="border-t border-[#232836] pt-3 text-xs leading-[1.55] text-[#8b93a7]">
        {meta.hint}
      </div>
      <label className="block font-plex-sans">
        <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">
          Nome de exibição
        </span>
        <div className="mt-1.5 flex gap-2">
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="flex-1 rounded-md border border-[#272c3a] bg-[#12151d] px-3 py-2 text-[13px] text-[#e2e6f0] outline-none focus:border-blue-500"
          />
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="rounded-md border border-[#272c3a] px-3.5 py-2 font-plex-sans text-xs font-medium text-[#8b93a7] transition-colors hover:border-blue-500 hover:text-[#c6cddc] disabled:opacity-60"
          >
            {save.isPending ? "…" : saved ? "Salvo ✓" : "Salvar"}
          </button>
        </div>
      </label>
    </section>
  );
}

function ChangePasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);

  const mismatch = next.length > 0 && confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < 8;
  const ok = current.length > 0 && next.length >= 8 && next === confirm;

  const change = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: (session) => {
      storeSession(session);
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    },
  });

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-[18px] py-[18px]">
      <span className="font-plex-sans text-[13px] font-semibold text-[#c6cddc]">Alterar senha</span>
      {done ? (
        <div className="flex flex-col gap-1.5 rounded-md border border-status-ok/30 bg-status-ok/[.08] px-3.5 py-3">
          <span className="font-plex-sans text-xs font-medium text-emerald-400">
            ✓ Senha alterada com sucesso
          </span>
          <span className="text-[11.5px] leading-[1.5] text-[#8b93a7]">
            As demais sessões abertas foram encerradas por segurança.
          </span>
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          <label className="block font-plex-sans">
            <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">Senha atual</span>
            <input
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className="mt-1.5 w-full rounded-md border border-[#272c3a] bg-[#12151d] px-3 py-2 font-plex-mono text-[13px] text-[#e2e6f0] outline-none focus:border-blue-500"
            />
          </label>
          <label className="block font-plex-sans">
            <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">Nova senha</span>
            <input
              type="password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              className={`mt-1.5 w-full rounded-md border bg-[#12151d] px-3 py-2 font-plex-mono text-[13px] text-[#e2e6f0] outline-none focus:border-blue-500 ${tooShort ? "border-status-warn/50" : "border-[#272c3a]"}`}
            />
            <span className={`mt-1 block text-[10.5px] ${tooShort ? "text-amber-400" : "text-[#5b6274]"}`}>
              {tooShort ? `Ainda faltam ${8 - next.length} caracteres.` : "Mínimo de 8 caracteres."}
            </span>
          </label>
          <label className="block font-plex-sans">
            <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">Confirme a nova senha</span>
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={`mt-1.5 w-full rounded-md border bg-[#12151d] px-3 py-2 font-plex-mono text-[13px] text-[#e2e6f0] outline-none focus:border-blue-500 ${mismatch ? "border-status-crit/50" : "border-[#272c3a]"}`}
            />
            {mismatch && <span className="mt-1 block text-[10.5px] text-red-400">As senhas não coincidem.</span>}
          </label>
          <div className="mt-0.5 flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => change.mutate()}
              disabled={!ok || change.isPending}
              className={`rounded-md px-[18px] py-2 font-plex-sans text-[12.5px] font-semibold text-white transition-colors ${ok ? "bg-blue-500 hover:bg-blue-600" : "cursor-not-allowed bg-[#272c3a]"}`}
            >
              {change.isPending ? "Salvando…" : "Alterar senha"}
            </button>
            <span className="text-[11px] text-[#5b6274]">encerra as outras sessões ao salvar</span>
          </div>
          {change.isError && <span className="text-xs text-status-crit">Senha atual incorreta.</span>}
        </div>
      )}
    </section>
  );
}

function SessionsCard() {
  const queryClient = useQueryClient();
  const { data: sessions } = useQuery<SessionOut[]>({
    queryKey: ["sessions"],
    queryFn: listSessions,
  });

  const revoke = useMutation({
    mutationFn: (id: number) => revokeSession(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });

  return (
    <section className="flex flex-col gap-2 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-[18px] py-[18px]">
      <span className="font-plex-sans text-[13px] font-semibold text-[#c6cddc]">Sessões ativas</span>
      {!sessions ? (
        <div className="flex items-center gap-2 py-3 text-xs text-[#5b6274]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Carregando…
        </div>
      ) : (
        sessions.map((s) => (
          <div key={s.id} className="flex items-center gap-2.5 border-b border-[#1f2432] py-2 last:border-0">
            <span className={`h-[7px] w-[7px] flex-none rounded-full ${s.is_current ? "bg-status-ok" : "bg-status-offline"}`} />
            <span className="font-plex-mono text-xs text-[#c6cddc]">sessão #{s.id}</span>
            <span className="text-[11.5px] text-[#5b6274]">
              {s.is_current ? "esta sessão · " : ""}
              iniciada {relativeTime(s.created_at)}
            </span>
            {!s.is_current && (
              <button
                type="button"
                onClick={() => revoke.mutate(s.id)}
                disabled={revoke.isPending}
                className="ml-auto rounded-md border border-[#272c3a] px-2.5 py-1 font-plex-sans text-[11px] font-medium text-[#8b93a7] transition-colors hover:border-red-400/60 hover:text-red-400 disabled:opacity-50"
              >
                Encerrar
              </button>
            )}
          </div>
        ))
      )}
    </section>
  );
}

const TABS = [
  { key: "conta", label: "Minha conta" },
  { key: "usuarios", label: "Gestão de usuários" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export function Account() {
  const [tab, setTab] = useState<TabKey>("conta");
  const { data: overview } = useQuery<OverviewOut>({
    queryKey: ["overview"],
    queryFn: () => api<OverviewOut>("/api/v1/overview"),
    refetchInterval: 30_000,
  });

  return (
    <div className="flex h-screen bg-[#0a0c11] font-plex-sans text-[#e2e6f0]">
      <Sidebar alertCounts={{ crit: overview?.kpis.crit ?? 0, warn: overview?.kpis.warn ?? 0 }} />
      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-[26px] py-[22px]">
        <h1 className="m-0 text-[19px] font-semibold tracking-[-0.01em] text-[#e2e6f0]">Minha conta</h1>

        <div className="flex items-center gap-1.5 border-b border-[#232836]">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`-mb-px border-b-2 px-4 py-2.5 font-plex-sans text-[13px] transition-colors ${
                tab === t.key
                  ? "border-blue-500 font-semibold text-[#e2e6f0]"
                  : "border-transparent text-[#8b93a7] hover:text-[#e2e6f0]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "conta" ? (
          <div className="flex items-start gap-4">
            <div className="flex w-[440px] flex-none flex-col gap-3.5">
              <ProfileCard />
              <ChangePasswordCard />
            </div>
            <div className="min-w-0 flex-1">
              <SessionsCard />
            </div>
          </div>
        ) : (
          <UsersPanel />
        )}
      </main>
    </div>
  );
}
