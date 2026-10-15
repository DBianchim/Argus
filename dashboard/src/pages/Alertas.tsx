import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ackAlert, api } from "../api/client";
import { Sidebar } from "../components/Sidebar";
import { useNotificationsQuery } from "../hooks/useNotifications";
import type { AlertOut, OverviewOut } from "../types";
import { PILAR_LABEL, relativeTime } from "../utils";

type Kind = "crit" | "warn" | "offline";
type SevFilter = "all" | Kind;
type PilarFilter = "all" | "operacional" | "backup" | "acesso" | "logs";

const SEV_CHIPS: { value: SevFilter; label: string }[] = [
  { value: "all", label: "Todas" },
  { value: "crit", label: "Crítico" },
  { value: "warn", label: "Alerta" },
  { value: "offline", label: "Offline" },
];

const PILAR_CHIPS: { value: PilarFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "operacional", label: "Operacional" },
  { value: "backup", label: "Backup" },
  { value: "acesso", label: "Acesso" },
  { value: "logs", label: "Logs" },
];

const KIND_META: Record<Kind, { fg: string; bg: string; bd: string; dot: string; label: string }> = {
  crit: { fg: "text-red-400", bg: "bg-status-crit/[.14]", bd: "border-status-crit/35", dot: "bg-status-crit", label: "CRÍTICO" },
  warn: { fg: "text-amber-400", bg: "bg-status-warn/[.12]", bd: "border-status-warn/30", dot: "bg-status-warn", label: "ALERTA" },
  offline: { fg: "text-[#94a3b8]", bg: "bg-status-offline/[.14]", bd: "border-status-offline/30", dot: "bg-status-offline", label: "OFFLINE" },
};

function alertKind(a: AlertOut): Kind {
  if (a.pilar === "geral" && a.item === "offline") return "offline";
  return a.severity === "crit" ? "crit" : "warn";
}

function chipClass(active: boolean): string {
  return `rounded-md border px-3.5 py-[5px] font-plex-sans text-[12.5px] font-medium transition-colors hover:border-blue-500 ${
    active
      ? "border-blue-500/50 bg-blue-500/[.16] text-[#93bbfd]"
      : "border-[#272c3a] bg-[#1a1d27] text-[#8b93a7]"
  }`;
}

export function Alertas() {
  const [sev, setSev] = useState<SevFilter>("all");
  const [pilar, setPilar] = useState<PilarFilter>("all");
  const [server, setServer] = useState<string>("all");
  const queryClient = useQueryClient();

  const { data, isLoading, dataUpdatedAt } = useQuery<OverviewOut>({
    queryKey: ["overview"],
    queryFn: () => api<OverviewOut>("/api/v1/overview"),
    refetchInterval: 30_000,
  });
  const { data: notifData } = useNotificationsQuery();

  const [ackingKey, setAckingKey] = useState<string | null>(null);
  const ack = useMutation({
    mutationFn: ({ serverId, pilar: p, item }: { serverId: number; pilar: string; item: string }) =>
      ackAlert(serverId, p, item),
    onMutate: ({ serverId, pilar: p, item }) => setAckingKey(`${serverId}|${p}|${item}`),
    onSettled: () => setAckingKey(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["overview"] }),
  });

  const allAlerts = data?.alerts ?? [];
  const servers = data?.servers ?? [];

  const filtered = useMemo(() => {
    return allAlerts
      .filter((a) => sev === "all" || alertKind(a) === sev)
      .filter((a) => pilar === "all" || a.pilar === pilar)
      .filter((a) => server === "all" || String(a.server_id) === server);
  }, [allAlerts, sev, pilar, server]);

  const stats = useMemo(() => {
    const kinds = allAlerts.map(alertKind);
    return {
      crit: kinds.filter((k) => k === "crit").length,
      warn: kinds.filter((k) => k === "warn").length,
      offline: kinds.filter((k) => k === "offline").length,
    };
  }, [allAlerts]);

  const today = new Date().toDateString();
  const resolvedToday = (notifData?.items ?? [])
    .filter((n) => n.status_to === "ok" && new Date(n.created_at).toDateString() === today)
    .slice(0, 10);

  const clock = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
    : "—";

  return (
    <div className="flex h-screen bg-[#0a0c11] font-plex-sans text-[#e2e6f0]">
      <Sidebar alertCounts={{ crit: stats.crit, warn: stats.warn }} />
      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-[26px] py-[22px]">
        {isLoading || !data ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-[#5b6274]">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> Carregando alertas…
          </div>
        ) : (
          <>
            <div className="flex items-baseline gap-3.5">
              <h1 className="m-0 text-[19px] font-semibold tracking-[-0.01em] text-[#e2e6f0]">
                Alertas
              </h1>
              <span className="font-plex-mono text-[11.5px] text-[#5b6274]">
                atualizado às {clock}
              </span>
              <div className="ml-auto flex gap-3">
                {([
                  { key: "crit", label: "críticos" },
                  { key: "warn", label: "alertas" },
                  { key: "offline", label: "offline" },
                ] as const).map((s) => (
                  <div
                    key={s.key}
                    className="flex items-center gap-2 rounded-md border border-[#272c3a] bg-[#1a1d27] px-3 py-[7px]"
                  >
                    <span className={`h-2 w-2 rounded-full ${KIND_META[s.key].dot}`} />
                    <span className={`font-plex-mono text-[15px] font-semibold ${stats[s.key] ? KIND_META[s.key].fg : "text-[#5b6274]"}`}>
                      {stats[s.key]}
                    </span>
                    <span className="text-[11.5px] text-[#8b93a7]">{s.label}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-medium tracking-[0.06em] text-[#5b6274]">SEVERIDADE</span>
              {SEV_CHIPS.map((c) => (
                <button key={c.value} type="button" onClick={() => setSev(c.value)} className={chipClass(sev === c.value)}>
                  {c.label}
                </button>
              ))}
              <span className="mx-1.5 h-[18px] w-px bg-[#272c3a]" />
              <span className="text-[11px] font-medium tracking-[0.06em] text-[#5b6274]">PILAR</span>
              {PILAR_CHIPS.map((c) => (
                <button key={c.value} type="button" onClick={() => setPilar(c.value)} className={chipClass(pilar === c.value)}>
                  {c.label}
                </button>
              ))}
              <span className="mx-1.5 h-[18px] w-px bg-[#272c3a]" />
              <select
                value={server}
                onChange={(e) => setServer(e.target.value)}
                className="rounded-md border border-[#272c3a] bg-[#1a1d27] px-2.5 py-[5px] font-plex-sans text-[12.5px] text-[#8b93a7] outline-none"
              >
                <option value="all">Todos os servidores</option>
                {servers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.display_name ?? s.hostname}
                  </option>
                ))}
              </select>
              <span className="ml-auto font-plex-mono text-[11.5px] text-[#5b6274]">
                {filtered.length === 1 ? "1 alerta ativo" : `${filtered.length} alertas ativos`}
              </span>
            </div>

            {allAlerts.length === 0 ? (
              <section className="flex flex-col items-center gap-3.5 rounded-lg border border-dashed border-[#272c3a] px-10 py-16 text-center">
                <span className="flex h-[52px] w-[52px] items-center justify-center rounded-full border border-status-ok/35 bg-status-ok/[.12] text-[22px] font-semibold text-status-ok">
                  ✓
                </span>
                <span className="text-base font-semibold text-[#c6cddc]">Nenhum alerta ativo</span>
                <span className="max-w-[420px] text-[13px] leading-[1.6] text-[#8b93a7]">
                  Todos os {servers.length} servidores estão saudáveis e reportando normalmente.
                </span>
                <Link to="/" className="text-[12.5px] font-medium">
                  Ver visão geral do parque →
                </Link>
              </section>
            ) : filtered.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#272c3a] p-12 text-center text-[13px] text-[#5b6274]">
                Nenhum alerta corresponde aos filtros.{" "}
                <button
                  type="button"
                  onClick={() => {
                    setSev("all");
                    setPilar("all");
                    setServer("all");
                  }}
                  className="text-blue-400 hover:underline"
                >
                  Limpar filtros
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {filtered.map((a) => {
                  const kind = alertKind(a);
                  const meta = KIND_META[kind];
                  const key = `${a.server_id}|${a.pilar}|${a.item}`;
                  const isAcking = ackingKey === key;
                  const isAcked = !!a.acked_by;
                  return (
                    <article
                      key={key}
                      className={`flex items-center gap-3.5 rounded-lg border bg-[#1a1d27] px-4 py-[13px] ${isAcked ? "border-[#272c3a] opacity-[.75]" : meta.bd}`}
                    >
                      <span
                        className={`h-[9px] w-[9px] flex-none rounded-full ${meta.dot} ${kind === "crit" && !isAcked ? "animate-status-pulse" : ""}`}
                      />
                      <span className={`w-[68px] flex-none rounded border py-[3px] text-center font-plex-sans text-[9.5px] font-semibold tracking-[0.05em] ${meta.fg} ${meta.bg} ${meta.bd}`}>
                        {meta.label}
                      </span>
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <div className="flex items-baseline gap-2.5">
                          <span className="font-plex-sans text-[13.5px] font-semibold text-[#e2e6f0]">{a.title}</span>
                          <span className="rounded-[3px] bg-[#12151d] px-1.5 py-px font-plex-mono text-[9.5px] font-semibold text-[#5b6274]">
                            {(PILAR_LABEL[a.pilar] ?? a.pilar).toUpperCase()}
                          </span>
                        </div>
                        {a.detail && <span className="text-xs leading-[1.45] text-[#8b93a7]">{a.detail}</span>}
                      </div>
                      <div className="flex flex-none flex-col items-end gap-0.5 leading-tight">
                        <Link to={`/servers/${a.server_id}`} className="font-plex-mono text-xs font-medium text-[#93bbfd]">
                          {a.hostname}
                        </Link>
                        <span className="font-plex-mono text-[11px] text-[#5b6274]">
                          {a.since ? relativeTime(a.since) : "detectado agora"}
                        </span>
                      </div>
                      {isAcked ? (
                        <span className="w-32 flex-none text-center font-plex-sans text-[11.5px] font-medium text-status-ok">
                          ✓ visto · {a.acked_by}
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => ack.mutate({ serverId: a.server_id, pilar: a.pilar, item: a.item })}
                          disabled={isAcking}
                          className="w-32 flex-none rounded-md border border-[#2c3549] bg-[#1e2738] px-3.5 py-[7px] font-plex-sans text-xs font-medium text-[#c6cddc] transition-colors hover:border-blue-500 hover:text-white disabled:opacity-60"
                        >
                          {isAcking ? "Marcando…" : "Marcar como visto"}
                        </button>
                      )}
                    </article>
                  );
                })}
              </div>
            )}

            <div className="flex items-center gap-2">
              <span className="text-[11px] text-[#5b6274]">
                Reconhecer não silencia — o alerta continua na lista até a métrica normalizar,
                apenas marcado como visto.
              </span>
            </div>

            {resolvedToday.length > 0 && (
              <div className="mt-2 flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold tracking-[0.08em] text-[#5b6274]">
                    RESOLVIDOS HOJE · {resolvedToday.length}
                  </span>
                  <span className="h-px flex-1 bg-[#1f2432]" />
                </div>
                {resolvedToday.map((n) => (
                  <article
                    key={n.id}
                    className="flex items-center gap-3.5 rounded-lg border border-[#1f2432] px-4 py-[11px] opacity-60"
                  >
                    <span className="h-[9px] w-[9px] flex-none rounded-full bg-status-ok" />
                    <span className="w-[68px] flex-none rounded border border-status-ok/20 bg-status-ok/[.08] py-[3px] text-center font-plex-sans text-[9.5px] font-semibold tracking-[0.05em] text-emerald-400">
                      RESOLVIDO
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="font-plex-sans text-[13px] font-medium text-[#8b93a7] line-through">
                        {n.title}
                      </span>
                      {n.detail && <span className="text-[11.5px] text-[#5b6274]">{n.detail}</span>}
                    </div>
                    <span className="flex-none font-plex-mono text-[11px] text-[#5b6274]">
                      {new Date(n.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </article>
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
