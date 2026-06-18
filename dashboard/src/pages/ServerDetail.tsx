import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Settings } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import { AlertList } from "../components/AlertList";
import { FindingsTable } from "../components/FindingsTable";
import { StatusBadge } from "../components/StatusBadge";
import { TopBar } from "../components/TopBar";
import type {
  BackupMetrics,
  FindingsMetrics,
  MetricOut,
  MetricPage,
  OperacionalMetrics,
  ServerHealthOut,
} from "../types";
import { PILAR_LABEL, formatPct, relativeTime } from "../utils";

const PERIODS = { "1h": 1, "24h": 24, "7d": 24 * 7 } as const;
type Period = keyof typeof PERIODS;

// ── seções por pilar ──────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg bg-surface-raised p-5">
      <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-slate-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Gauge({ label, pct }: { label: string; pct: number | undefined }) {
  const value = typeof pct === "number" ? Math.min(pct, 100) : 0;
  const tone =
    value >= 90 ? "bg-status-crit" : value >= 75 ? "bg-status-warn" : "bg-status-ok";
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-slate-500">{label}</span>
        <span className="tnum text-lg font-semibold text-slate-100">{formatPct(pct)}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-border">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function OperacionalSection({ metrics }: { metrics: OperacionalMetrics }) {
  const services = metrics.services ?? [];
  return (
    <Section title="Operacional">
      <div className="grid gap-5 sm:grid-cols-2">
        <Gauge label="CPU" pct={metrics.cpu?.usage_pct} />
        <Gauge label="Memória" pct={metrics.memory?.usage_pct} />
      </div>

      {(metrics.disk ?? []).length > 0 && (
        <div className="mt-5 space-y-3">
          {(metrics.disk ?? []).map((disk, i) => (
            <Gauge
              key={i}
              label={`Disco ${disk.mount ?? "?"} (${disk.free_gb?.toFixed(0) ?? "?"} GB livres)`}
              pct={disk.usage_pct}
            />
          ))}
        </div>
      )}

      {services.length > 0 && (
        <table className="mt-5 w-full text-left text-sm">
          <thead>
            <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2 font-medium">Serviço crítico</th>
              <th className="py-2 font-medium">Estado</th>
            </tr>
          </thead>
          <tbody>
            {services.map((svc, i) => {
              const running = ["running", "active"].includes(
                String(svc.status ?? "").toLowerCase(),
              );
              return (
                <tr key={i} className="border-b border-surface-border/50">
                  <td className="py-2 font-mono text-xs text-slate-300">{svc.name}</td>
                  <td className="py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        running
                          ? "bg-status-ok/15 text-status-ok"
                          : "bg-status-crit/15 text-status-crit"
                      }`}
                    >
                      {svc.status}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function BackupSection({ metrics }: { metrics: BackupMetrics }) {
  const backup = metrics.backup ?? {};
  const statusTone: Record<string, string> = {
    OK: "bg-status-ok/15 text-status-ok",
    WARN: "bg-status-warn/15 text-status-warn",
  };
  const tone = statusTone[backup.status ?? ""] ?? "bg-status-crit/15 text-status-crit";

  return (
    <Section title="Backup">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`rounded-full px-3 py-1 text-sm font-medium ${tone}`}>
          {backup.status ?? "SEM DADOS"}
        </span>
        {typeof backup.age_hours === "number" && (
          <span className="text-sm text-slate-400">
            último backup há <strong className="tnum text-slate-200">{backup.age_hours}h</strong>
            {typeof backup.sla_hours === "number" && ` (SLA: ${backup.sla_hours}h)`}
          </span>
        )}
      </div>
      <dl className="mt-4 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
        <div className="flex justify-between border-b border-surface-border/50 py-1.5">
          <dt className="text-slate-500">Arquivo</dt>
          <dd className="max-w-[60%] truncate font-mono text-xs text-slate-300">
            {backup.path ?? "—"}
          </dd>
        </div>
        <div className="flex justify-between border-b border-surface-border/50 py-1.5">
          <dt className="text-slate-500">Tamanho</dt>
          <dd className="tnum text-slate-300">
            {typeof backup.size_mb === "number" ? `${backup.size_mb} MB` : "—"}
          </dd>
        </div>
        <div className="flex justify-between border-b border-surface-border/50 py-1.5">
          <dt className="text-slate-500">Integridade</dt>
          <dd className="text-slate-300">{backup.integrity?.integrity_check ?? "—"}</dd>
        </div>
        <div className="flex justify-between border-b border-surface-border/50 py-1.5">
          <dt className="text-slate-500">Log de execução</dt>
          <dd className="text-slate-300">
            {backup.log?.log_found ? (backup.log?.last_status ?? "encontrado") : "não encontrado"}
          </dd>
        </div>
      </dl>
    </Section>
  );
}

function FindingsSection({
  title,
  metrics,
}: {
  title: string;
  metrics: FindingsMetrics;
}) {
  const summary = metrics.summary ?? {};
  return (
    <Section title={title}>
      <div className="mb-4 flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-status-ok/15 px-2.5 py-1 text-status-ok">
          OK {summary.ok ?? 0}
        </span>
        <span className="rounded-full bg-status-warn/15 px-2.5 py-1 text-status-warn">
          Avisos {summary.warning ?? 0}
        </span>
        <span className="rounded-full bg-status-crit/15 px-2.5 py-1 text-status-crit">
          Erros {summary.error ?? 0}
        </span>
        <span className="rounded-full bg-slate-500/15 px-2.5 py-1 text-slate-400">
          Info {summary.info ?? 0}
        </span>
      </div>
      <FindingsTable findings={metrics.findings ?? []} />
    </Section>
  );
}

// ── gráfico histórico ─────────────────────────────────────────────────────────

function HistoryChart({ serverId }: { serverId: number }) {
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
      const metrics = m.metrics as OperacionalMetrics;
      return {
        time: new Date(m.collected_at).toLocaleTimeString("pt-BR", {
          hour: "2-digit",
          minute: "2-digit",
        }),
        cpu: metrics.cpu?.usage_pct ?? null,
        mem: metrics.memory?.usage_pct ?? null,
      };
    })
    .reverse();

  return (
    <Section title="Histórico — CPU e memória">
      <div className="mb-3 flex gap-1.5">
        {(Object.keys(PERIODS) as Period[]).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
              period === p
                ? "bg-surface-border text-slate-100"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {p}
          </button>
        ))}
      </div>
      {points.length < 2 ? (
        <p className="py-8 text-center text-sm text-slate-500">
          Ainda não há histórico suficiente neste período.
        </p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points}>
              <CartesianGrid stroke="#1E2A3F" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#475569" fontSize={11} />
              <YAxis domain={[0, 100]} stroke="#475569" fontSize={11} unit="%" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#111B2E",
                  border: "1px solid #1E2A3F",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="cpu" name="CPU %" stroke="#10B981" dot={false} strokeWidth={2} connectNulls />
              <Line type="monotone" dataKey="mem" name="Memória %" stroke="#60A5FA" dot={false} strokeWidth={2} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Section>
  );
}

// ── página ────────────────────────────────────────────────────────────────────

export function ServerDetail() {
  const { id } = useParams();
  const serverId = Number(id);

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

  if (isLoading || !health) {
    return (
      <div>
        <TopBar />
        <div className="flex items-center justify-center gap-2 py-24 text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          Carregando servidor…
        </div>
      </div>
    );
  }

  const byPilar = Object.fromEntries((latest ?? []).map((m) => [m.pilar, m]));

  return (
    <div>
      <TopBar />
      <main className="mx-auto max-w-5xl px-6 py-6">
        <Link
          to="/"
          className="mb-4 inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Visão geral
        </Link>

        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-100">{health.hostname}</h1>
          <StatusBadge status={health.status} />
          <span className="text-xs text-slate-500">
            coletado {relativeTime(health.last_seen_at)}
            {health.agent_version && ` · agente ${health.agent_version}`}
          </span>
          <Link
            to={`/servers/${serverId}/config`}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-status-ok/60 hover:text-slate-100"
          >
            <Settings className="h-3.5 w-3.5" aria-hidden /> Configurar
          </Link>
        </div>

        {health.alerts.length > 0 && (
          <div className="mt-4">
            <AlertList alerts={health.alerts} />
          </div>
        )}

        <div className="mt-6 space-y-5">
          {byPilar.operacional && (
            <OperacionalSection metrics={byPilar.operacional.metrics as OperacionalMetrics} />
          )}
          <HistoryChart serverId={serverId} />
          {byPilar.backup && (
            <BackupSection metrics={byPilar.backup.metrics as BackupMetrics} />
          )}
          {byPilar.acesso && (
            <FindingsSection
              title={PILAR_LABEL.acesso}
              metrics={byPilar.acesso.metrics as FindingsMetrics}
            />
          )}
          {byPilar.logs && (
            <FindingsSection
              title={PILAR_LABEL.logs}
              metrics={byPilar.logs.metrics as FindingsMetrics}
            />
          )}
          {(latest ?? []).length === 0 && (
            <p className="rounded-lg border border-dashed border-surface-border py-12 text-center text-sm text-slate-500">
              Este servidor ainda não enviou nenhum payload.
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
