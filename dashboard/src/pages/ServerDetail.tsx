import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Settings as SettingsIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ackAlert, api, getStoredUser } from "../api/client";
import { FindingsTable } from "../components/FindingsTable";
import { Sidebar } from "../components/Sidebar";
import { useNotificationsQuery } from "../hooks/useNotifications";
import type {
  AlertOut,
  BackupMetrics,
  FindingsMetrics,
  MetricOut,
  MetricPage,
  OperacionalMetrics,
  OverviewOut,
  Pilar,
  ServerConfigBlob,
  ServerConfigOut,
  ServerHealthOut,
  StatusValue,
} from "../types";
import { STATUS_META, formatUptime, relativeTime } from "../utils";

const PERIODS = { "1h": 1, "24h": 24, "7d": 24 * 7 } as const;
type Period = keyof typeof PERIODS;
type TabKey = "operacional" | "backup" | "acesso" | "logs";

const TABS: { key: TabKey; label: string }[] = [
  { key: "operacional", label: "Operacional" },
  { key: "backup", label: "Backup" },
  { key: "acesso", label: "Acesso" },
  { key: "logs", label: "Logs" },
];

const NOTIF_COLOR: Record<string, string> = {
  crit: "#ef4444",
  warn: "#f59e0b",
  info: "#10b981",
};

const NOTIF_LABEL: Record<string, string> = {
  ok: "normalizado",
  warn: "alerta",
  crit: "crítico",
  offline: "offline",
  unknown: "sem dados",
};

const SEV_RANK: Record<string, number> = { crit: 0, warn: 1 };

function metricValueClass(v: number | undefined | null): string {
  if (typeof v !== "number") return "text-[#5b6274]";
  if (v >= 90) return "text-status-crit";
  if (v >= 80) return "text-status-warn";
  return "text-[#c6cddc]";
}

function statusBorder(status: StatusValue): string {
  if (status === "crit") return "border-status-crit/45";
  if (status === "warn" || status === "offline") return "border-status-warn/30";
  return "border-[#272c3a]";
}

// ── Seções por pilar ─────────────────────────────────────────────────────────

function ChartCard({
  title,
  data,
  now,
  warnV,
  critV,
}: {
  title: string;
  data: { time: string; v: number | null }[];
  now: number | undefined;
  warnV: number;
  critV: number;
}) {
  return (
    <section className="flex flex-col gap-2.5 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-4 py-3.5">
      <div className="flex items-baseline gap-2.5">
        <span className="font-plex-sans text-[12.5px] font-semibold text-[#c6cddc]">{title}</span>
        <span className={`font-plex-mono text-[15px] font-semibold ${metricValueClass(now)}`}>
          {typeof now === "number" ? `${now.toFixed(0)}%` : "—"}
        </span>
        <span className="ml-auto font-plex-mono text-[10.5px] text-[#5b6274]">período selecionado</span>
      </div>
      {data.length < 2 ? (
        <p className="py-10 text-center text-xs text-[#5b6274]">
          Ainda não há histórico suficiente neste período.
        </p>
      ) : (
        <div className="h-[150px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <XAxis dataKey="time" hide />
              <YAxis domain={[0, 100]} hide />
              <ReferenceLine y={warnV} stroke="#f59e0b" strokeDasharray="5 4" strokeOpacity={0.55} />
              <ReferenceLine y={critV} stroke="#ef4444" strokeDasharray="5 4" strokeOpacity={0.55} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#12151d",
                  border: "1px solid #272c3a",
                  borderRadius: 6,
                  fontSize: 11,
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
                labelStyle={{ color: "#8b93a7" }}
                formatter={(v: number) => [`${v}%`, title]}
              />
              <Line
                type="monotone"
                dataKey="v"
                stroke="#3b82f6"
                dot={false}
                strokeWidth={1.8}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="flex gap-4 font-plex-sans text-[10.5px] text-[#5b6274]">
        <span className="flex items-center gap-1.5">
          <span className="h-0 w-3.5 border-t border-dashed border-status-warn" /> alerta {warnV}%
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0 w-3.5 border-t border-dashed border-status-crit" /> crítico {critV}%
        </span>
      </div>
    </section>
  );
}

function OperacionalTab({
  metrics,
  serverId,
  th,
}: {
  metrics: OperacionalMetrics;
  serverId: number;
  th: { cpu_warn: number; cpu_crit: number; mem_warn: number; mem_crit: number };
}) {
  const [period, setPeriod] = useState<Period>("24h");
  const since = new Date(Date.now() - PERIODS[period] * 3600_000).toISOString();

  const { data } = useQuery<MetricPage>({
    queryKey: ["history", serverId, period],
    queryFn: () =>
      api<MetricPage>(
        `/api/v1/metrics?server_id=${serverId}&pilar=operacional&since=${since}&limit=500`,
      ),
    refetchInterval: 60_000,
  });

  const points = (data?.items ?? [])
    .map((m) => {
      const mm = m.metrics as OperacionalMetrics;
      return {
        time: new Date(m.collected_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }),
        cpu: mm.cpu?.usage_pct ?? null,
        mem: mm.memory?.usage_pct ?? null,
      };
    })
    .reverse();

  const disks = metrics.disk ?? [];
  const services = metrics.services ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1.5">
        {(Object.keys(PERIODS) as Period[]).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`rounded-md px-2.5 py-1 font-plex-sans text-xs font-medium transition-colors ${
              period === p ? "bg-[#272c3a] text-[#e2e6f0]" : "text-[#5b6274] hover:text-[#8b93a7]"
            }`}
          >
            {p}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ChartCard
          title="CPU"
          data={points.map((p) => ({ time: p.time, v: p.cpu }))}
          now={metrics.cpu?.usage_pct}
          warnV={th.cpu_warn}
          critV={th.cpu_crit}
        />
        <ChartCard
          title="Memória"
          data={points.map((p) => ({ time: p.time, v: p.mem }))}
          now={metrics.memory?.usage_pct}
          warnV={th.mem_warn}
          critV={th.mem_crit}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <section className="flex flex-col gap-3 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-4 py-3.5">
          <span className="font-plex-sans text-[12.5px] font-semibold text-[#c6cddc]">Discos</span>
          {disks.length === 0 ? (
            <p className="text-xs text-[#5b6274]">Nenhum disco reportado.</p>
          ) : (
            disks.map((d, i) => {
              const pct = d.usage_pct ?? 0;
              const color = pct >= 90 ? "#ef4444" : pct >= 80 ? "#f59e0b" : "#3b82f6";
              return (
                <div key={i} className="flex flex-col gap-1.5">
                  <div className="flex items-baseline gap-2">
                    <span className="font-plex-mono text-xs font-medium text-[#c6cddc]">{d.mount ?? "?"}</span>
                    <span className="font-plex-mono text-[11px] text-[#5b6274]">
                      {typeof d.total_gb === "number" ? `${d.total_gb.toFixed(0)} GB` : ""}
                      {typeof d.free_gb === "number" ? ` · ${d.free_gb.toFixed(0)} GB livres` : ""}
                    </span>
                    <span className="ml-auto font-plex-mono text-[12.5px] font-semibold" style={{ color }}>
                      {pct.toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[#12151d]">
                    <div className="h-full" style={{ width: `${pct}%`, background: color }} />
                  </div>
                </div>
              );
            })
          )}
        </section>
        <section className="flex flex-col gap-2 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-4 py-3.5">
          <span className="font-plex-sans text-[12.5px] font-semibold text-[#c6cddc]">Serviços críticos</span>
          {services.length === 0 ? (
            <p className="text-xs text-[#5b6274]">Nenhum serviço configurado.</p>
          ) : (
            services.map((s, i) => {
              const running = ["running", "active"].includes(String(s.status ?? "").toLowerCase());
              return (
                <div key={i} className="flex items-center gap-2.5 border-b border-[#1f2432] py-1.5 last:border-0">
                  <span className={`h-[7px] w-[7px] rounded-full ${running ? "bg-status-ok" : "bg-status-crit"}`} />
                  <span className="font-plex-mono text-[12.5px] text-[#c6cddc]">{s.name}</span>
                  <span className={`ml-auto text-[11px] ${running ? "text-emerald-400" : "text-red-400"}`}>
                    {s.status}
                  </span>
                </div>
              );
            })
          )}
        </section>
      </div>
    </div>
  );
}

function BackupTab({ serverId, metrics }: { serverId: number; metrics: BackupMetrics }) {
  const backup = metrics.backup ?? {};
  const { data } = useQuery<MetricPage>({
    queryKey: ["backup-history", serverId],
    queryFn: () => api<MetricPage>(`/api/v1/metrics?server_id=${serverId}&pilar=backup&limit=10`),
  });
  const rows = data?.items ?? [];

  const cards = [
    {
      label: "Último backup",
      v: backup.status === "OK" && typeof backup.age_hours === "number" ? `há ${backup.age_hours.toFixed(1)}h` : (backup.status ?? "—"),
      c: backup.status === "OK" ? "text-emerald-400" : "text-red-400",
    },
    { label: "SLA", v: typeof backup.sla_hours === "number" ? `${backup.sla_hours}h` : "—", c: "text-[#c6cddc]" },
    {
      label: "SLA cumprido",
      v: backup.sla_ok === true ? "sim" : backup.sla_ok === false ? "não" : "—",
      c: backup.sla_ok === false ? "text-red-400" : "text-emerald-400",
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-4">
        {cards.map((c) => (
          <section key={c.label} className="flex flex-1 flex-col gap-1 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-4 py-3.5">
            <span className="text-[11px] text-[#5b6274]">{c.label}</span>
            <span className={`font-plex-mono text-[17px] font-semibold ${c.c}`}>{c.v}</span>
          </section>
        ))}
      </div>
      <section className="overflow-hidden rounded-lg border border-[#272c3a] bg-[#1a1d27]">
        <div className="grid grid-cols-[130px_1fr_100px_110px_100px] gap-3 border-b border-[#232836] px-4 py-2.5 font-plex-sans text-[10.5px] font-semibold tracking-[0.07em] text-[#5b6274]">
          <span>DATA</span><span>ARQUIVO</span><span>TAMANHO</span><span>INTEGRIDADE</span><span>STATUS</span>
        </div>
        {rows.length === 0 ? (
          <p className="px-4 py-6 text-xs text-[#5b6274]">Sem histórico de backup ainda.</p>
        ) : (
          rows.map((m) => {
            const b = (m.metrics as BackupMetrics).backup ?? {};
            const ok = b.status === "OK";
            return (
              <div
                key={m.id}
                className="grid grid-cols-[130px_1fr_100px_110px_100px] items-center gap-3 border-b border-[#1f2432] px-4 py-2.5 font-plex-mono text-xs text-[#8b93a7] last:border-0"
              >
                <span className="text-[#c6cddc]">
                  {new Date(m.collected_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="truncate">{b.path ?? "—"}</span>
                <span>{typeof b.size_mb === "number" ? `${(b.size_mb / 1024).toFixed(1)} GB` : "—"}</span>
                <span className="text-[#5b6274]">{b.integrity?.integrity_check ?? "—"}</span>
                <span
                  className={`w-fit rounded px-2 py-0.5 font-plex-sans text-[10px] font-semibold tracking-[0.05em] ${
                    ok ? "bg-status-ok/[.1] text-emerald-400" : "bg-status-warn/[.12] text-amber-400"
                  }`}
                >
                  {b.status ?? "—"}
                </span>
              </div>
            );
          })
        )}
      </section>
    </div>
  );
}

// ── página ────────────────────────────────────────────────────────────────────

export function ServerDetail() {
  const { id } = useParams();
  const serverId = Number(id);
  const canEdit = getStoredUser()?.role !== "viewer";
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabKey>("operacional");

  const { data: health } = useQuery<ServerHealthOut>({
    queryKey: ["health", serverId],
    queryFn: () => api<ServerHealthOut>(`/api/v1/servers/${serverId}/health`),
    refetchInterval: 30_000,
  });

  const { data: latest, isLoading } = useQuery<MetricOut[]>({
    queryKey: ["latest", serverId],
    queryFn: () => api<MetricOut[]>(`/api/v1/servers/${serverId}/latest`),
    refetchInterval: 30_000,
  });

  const { data: cfg } = useQuery<ServerConfigOut>({
    queryKey: ["server-config", serverId],
    queryFn: () => api<ServerConfigOut>(`/api/v1/servers/${serverId}/config`),
  });

  const { data: notifData } = useNotificationsQuery();

  // Só para os badges de contagem da sidebar (compartilhados por toda a frota).
  const { data: overview } = useQuery<OverviewOut>({
    queryKey: ["overview"],
    queryFn: () => api<OverviewOut>("/api/v1/overview"),
    refetchInterval: 30_000,
  });

  const [ackingKey, setAckingKey] = useState<string | null>(null);
  const ackMutation = useMutation({
    mutationFn: ({ pilar, item }: { pilar: string; item: string }) => ackAlert(serverId, pilar, item),
    onMutate: ({ pilar, item }) => setAckingKey(`${pilar}|${item}`),
    onSettled: () => setAckingKey(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["health", serverId] }),
  });

  const toggleOverride = useMutation({
    mutationFn: ({ pilar, item }: { pilar: Pilar; item: string }) => {
      const base: ServerConfigBlob = cfg?.config ?? {};
      const section = (base[pilar] ?? {}) as { finding_overrides?: Record<string, string> };
      const overrides = { ...(section.finding_overrides ?? {}) };
      if (overrides[item]) delete overrides[item];
      else overrides[item] = "ignore";
      const body: ServerConfigBlob = { ...base, [pilar]: { ...section, finding_overrides: overrides } };
      return api(`/api/v1/servers/${serverId}/config`, { method: "PUT", body: JSON.stringify({ config: body }) });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["server-config", serverId] });
      queryClient.invalidateQueries({ queryKey: ["health", serverId] });
      queryClient.invalidateQueries({ queryKey: ["latest", serverId] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const ignoredSet = (pilar: Pilar): Set<string> => {
    const section = (cfg?.config?.[pilar] ?? {}) as { finding_overrides?: Record<string, string> };
    return new Set(Object.keys(section.finding_overrides ?? {}));
  };

  const todayNotifs = useMemo(() => {
    const today = new Date().toDateString();
    return (notifData?.items ?? [])
      .filter((n) => n.server_id === serverId && new Date(n.created_at).toDateString() === today)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  }, [notifData, serverId]);

  const topAlert: AlertOut | undefined = useMemo(() => {
    if (!health) return undefined;
    return [...health.alerts].sort((a, b) => (SEV_RANK[a.severity] ?? 2) - (SEV_RANK[b.severity] ?? 2))[0];
  }, [health]);

  if (isLoading || !health) {
    return (
      <div className="flex h-screen bg-[#0a0c11] font-plex-sans text-[#e2e6f0]">
        <Sidebar alertCounts={{ crit: 0, warn: 0 }} />
        <main className="flex flex-1 items-center justify-center gap-2 text-[#5b6274]">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> Carregando servidor…
        </main>
      </div>
    );
  }

  const byPilar = Object.fromEntries((latest ?? []).map((m) => [m.pilar, m]));
  const operacional = (byPilar.operacional?.metrics ?? {}) as OperacionalMetrics;
  const disks = operacional.disk ?? [];
  const diskVals = disks.map((d) => d.usage_pct).filter((v): v is number => typeof v === "number");
  const diskPct = diskVals.length ? Math.max(...diskVals) : undefined;

  const th = {
    cpu_warn: cfg?.config.operacional?.cpu_warn ?? 75,
    cpu_crit: cfg?.config.operacional?.cpu_crit ?? 90,
    mem_warn: cfg?.config.operacional?.mem_warn ?? 80,
    mem_crit: cfg?.config.operacional?.mem_crit ?? 90,
  };

  const meta = STATUS_META[health.status] ?? STATUS_META.unknown;
  const alertCounts = { crit: overview?.kpis.crit ?? 0, warn: overview?.kpis.warn ?? 0 };

  const nowFraction = ((new Date().getHours() * 60 + new Date().getMinutes()) / 1440) * 100;

  return (
    <div className="flex h-screen bg-[#0a0c11] font-plex-sans text-[#e2e6f0]">
      <Sidebar alertCounts={alertCounts} />
      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-[26px] py-5">
        <div className="flex items-center gap-2 font-plex-sans text-xs text-[#5b6274]">
          <Link to="/" className="text-[#8b93a7] hover:text-[#c6cddc]">
            ← Visão geral
          </Link>
          <span>/</span>
          <span className="font-plex-mono text-xs font-medium text-[#c6cddc]">{health.hostname}</span>
        </div>

        <section className={`flex items-center gap-[18px] rounded-lg border bg-[#1a1d27] px-[18px] py-4 ${statusBorder(health.status)}`}>
          <span
            className={`h-[11px] w-[11px] flex-none rounded-full ${meta.dot} ${health.status === "crit" ? "animate-status-pulse" : ""}`}
          />
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2.5">
              <h1 className="m-0 text-[19px] font-semibold tracking-[-0.01em] text-[#e2e6f0]">
                {health.hostname}
              </h1>
              <span className={`rounded px-2 py-0.5 font-plex-sans text-[10.5px] font-semibold tracking-[0.06em] ${meta.badge}`}>
                {meta.label}
              </span>
            </div>
            <div className="flex flex-wrap gap-3.5 font-plex-mono text-[11.5px] text-[#8b93a7]">
              <span>coletado {relativeTime(health.last_seen_at)}</span>
              {health.agent_version && <span>agente {health.agent_version}</span>}
              {typeof operacional.uptime_seconds === "number" && <span>up {formatUptime(operacional.uptime_seconds)}</span>}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-5">
            {[
              { label: "CPU", v: operacional.cpu?.usage_pct },
              { label: "MEM", v: operacional.memory?.usage_pct },
              { label: "DISCO", v: diskPct },
            ].map((s) => (
              <div key={s.label} className="flex flex-col items-end leading-tight">
                <span className={`tnum font-plex-mono text-[18px] font-semibold ${metricValueClass(s.v)}`}>
                  {typeof s.v === "number" ? `${s.v.toFixed(0)}%` : "—"}
                </span>
                <span className="text-[10.5px] text-[#5b6274]">{s.label}</span>
              </div>
            ))}
            {topAlert && (
              <>
                <span className="h-[34px] w-px bg-[#272c3a]" />
                {topAlert.acked_by ? (
                  <span className="flex items-center gap-1.5 rounded-md border border-status-ok/30 bg-status-ok/10 px-3.5 py-2 font-plex-sans text-xs font-medium text-emerald-400">
                    ✓ Reconhecido por {topAlert.acked_by}
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => ackMutation.mutate({ pilar: topAlert.pilar, item: topAlert.item })}
                    disabled={ackingKey === `${topAlert.pilar}|${topAlert.item}`}
                    className="rounded-md bg-blue-500 px-4 py-2 font-plex-sans text-xs font-semibold text-white transition-colors hover:bg-blue-600 disabled:opacity-60"
                  >
                    {ackingKey === `${topAlert.pilar}|${topAlert.item}` ? "Reconhecendo…" : "Reconhecer alerta"}
                  </button>
                )}
              </>
            )}
            {canEdit && (
              <Link
                to={`/settings?server=${serverId}`}
                className="flex items-center gap-1.5 rounded-md border border-[#272c3a] px-3.5 py-2 font-plex-sans text-xs font-medium text-[#8b93a7] transition-colors hover:border-blue-500 hover:text-[#c6cddc]"
              >
                <SettingsIcon className="h-3.5 w-3.5" aria-hidden /> Configurar
              </Link>
            )}
          </div>
        </section>

        {todayNotifs.length > 0 && (
          <section className="flex flex-col gap-3 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-[18px] py-3.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold tracking-[0.08em] text-[#5b6274]">TIMELINE DO DIA</span>
              <span className="ml-auto font-plex-mono text-[11px] text-[#5b6274]">
                {new Date().toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" })} · 00h–24h
              </span>
            </div>

            {/* Só os dots na barra — texto flutuante por evento colidia quando vários
                eventos caem perto no tempo. Detalhe legível vai na lista abaixo. */}
            <div className="relative mx-1.5 h-3">
              <div className="absolute left-0 right-0 top-1 h-1 rounded bg-[#232836]" />
              <div className="absolute left-0 top-1 h-1 rounded bg-blue-500/35" style={{ width: `${nowFraction}%` }} />
              {todayNotifs.map((n) => {
                const x = ((new Date(n.created_at).getHours() * 60 + new Date(n.created_at).getMinutes()) / 1440) * 100;
                const color = NOTIF_COLOR[n.severity] ?? "#64748b";
                const time = new Date(n.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
                return (
                  <span
                    key={n.id}
                    className="absolute top-0 h-[11px] w-[11px] -translate-x-1/2 rounded-full border-2 border-[#1a1d27]"
                    style={{ left: `${x}%`, background: color }}
                    title={`${time} — ${n.title}`}
                  />
                );
              })}
            </div>
            <div className="mx-1.5 flex justify-between font-plex-mono text-[10px] text-[#3b4254]">
              <span>00h</span><span>04h</span><span>08h</span><span>12h</span><span>16h</span><span>20h</span><span>24h</span>
            </div>

            {/* Mais recente primeiro; cada evento em sua própria linha, sem colisão. */}
            <div className="flex flex-col gap-0.5 border-t border-[#232836] pt-2.5">
              {todayNotifs
                .slice()
                .reverse()
                .slice(0, 8)
                .map((n) => {
                  const color = NOTIF_COLOR[n.severity] ?? "#64748b";
                  return (
                    <div key={n.id} className="flex items-center gap-2.5 py-1">
                      <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: color }} />
                      <span className="flex-none font-plex-mono text-[11px] text-[#8b93a7]">
                        {new Date(n.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
                      </span>
                      <span className="min-w-0 truncate font-plex-sans text-[11.5px] text-[#c6cddc]">{n.title}</span>
                      <span className="ml-auto flex-none font-plex-mono text-[9.5px] font-semibold text-[#5b6274]">
                        {(NOTIF_LABEL[n.status_to] ?? n.status_to).toUpperCase()}
                      </span>
                    </div>
                  );
                })}
              {todayNotifs.length > 8 && (
                <span className="pt-1 text-[10.5px] text-[#5b6274]">
                  +{todayNotifs.length - 8} evento{todayNotifs.length - 8 > 1 ? "s" : ""} mais cedo hoje
                </span>
              )}
            </div>
          </section>
        )}

        <div className="flex items-center gap-1.5 border-b border-[#232836]">
          {TABS.map((t) => {
            const dot = STATUS_META[health.pilar_statuses[t.key] ?? "unknown"].dot;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 font-plex-sans text-[13px] transition-colors ${
                  active ? "border-blue-500 font-semibold text-[#e2e6f0]" : "border-transparent font-normal text-[#8b93a7] hover:text-[#e2e6f0]"
                }`}
              >
                <span className={`h-[7px] w-[7px] rounded-full ${dot}`} />
                {t.label}
              </button>
            );
          })}
        </div>

        {tab === "operacional" && <OperacionalTab metrics={operacional} serverId={serverId} th={th} />}
        {tab === "backup" && <BackupTab serverId={serverId} metrics={(byPilar.backup?.metrics ?? {}) as BackupMetrics} />}
        {tab === "acesso" && byPilar.acesso && (
          <section className="rounded-lg border border-[#272c3a] bg-[#1a1d27] px-4 py-3.5">
            <FindingsTable
              findings={(byPilar.acesso.metrics as FindingsMetrics).findings ?? []}
              ignored={ignoredSet("acesso")}
              onToggle={canEdit ? (item) => toggleOverride.mutate({ pilar: "acesso", item }) : undefined}
              busy={toggleOverride.isPending}
            />
          </section>
        )}
        {tab === "logs" && byPilar.logs && (
          <section className="rounded-lg border border-[#272c3a] bg-[#1a1d27] px-4 py-3.5">
            <FindingsTable
              findings={(byPilar.logs.metrics as FindingsMetrics).findings ?? []}
              ignored={ignoredSet("logs")}
              onToggle={canEdit ? (item) => toggleOverride.mutate({ pilar: "logs", item }) : undefined}
              busy={toggleOverride.isPending}
            />
          </section>
        )}
        {(tab === "acesso" && !byPilar.acesso) || (tab === "logs" && !byPilar.logs) ? (
          <p className="rounded-lg border border-dashed border-[#272c3a] py-12 text-center text-sm text-[#5b6274]">
            Este servidor ainda não enviou dados para este pilar.
          </p>
        ) : null}
        {(latest ?? []).length === 0 && (
          <p className="rounded-lg border border-dashed border-[#272c3a] py-12 text-center text-sm text-[#5b6274]">
            Este servidor ainda não enviou nenhum payload.
          </p>
        )}
      </main>
    </div>
  );
}
