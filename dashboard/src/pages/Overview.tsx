import { useQuery } from "@tanstack/react-query";
import { Loader2, ServerOff } from "lucide-react";
import { api } from "../api/client";
import { AlertList } from "../components/AlertList";
import { ServerCard } from "../components/ServerCard";
import { TopBar } from "../components/TopBar";
import type { OverviewOut } from "../types";

function Kpi({
  label,
  value,
  tone = "text-slate-100",
}: {
  label: string;
  value: string | number;
  tone?: string;
}) {
  return (
    <div className="rounded-lg bg-surface-raised px-4 py-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`tnum mt-0.5 text-2xl font-semibold ${tone}`}>{value}</p>
    </div>
  );
}

export function Overview() {
  const { data, isLoading, dataUpdatedAt } = useQuery<OverviewOut>({
    queryKey: ["overview"],
    queryFn: () => api<OverviewOut>("/api/v1/overview"),
    refetchInterval: 30_000,
  });

  if (isLoading || !data) {
    return (
      <div>
        <TopBar />
        <div className="flex items-center justify-center gap-2 py-24 text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          Carregando a frota…
        </div>
      </div>
    );
  }

  const { kpis, servers, alerts } = data;

  return (
    <div>
      <TopBar updatedAt={new Date(dataUpdatedAt).toISOString()} />

      <main className="mx-auto max-w-6xl px-6 py-6">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Servidores online" value={`${kpis.online}/${kpis.servers_total}`} />
          <Kpi
            label="Críticos"
            value={kpis.crit}
            tone={kpis.crit > 0 ? "text-status-crit" : "text-slate-100"}
          />
          <Kpi
            label="Avisos"
            value={kpis.warn}
            tone={kpis.warn > 0 ? "text-status-warn" : "text-slate-100"}
          />
          <Kpi
            label="Backups em dia"
            value={kpis.backups_ok_pct !== null ? `${kpis.backups_ok_pct}%` : "—"}
            tone={
              kpis.backups_ok_pct === null
                ? "text-slate-500"
                : kpis.backups_ok_pct >= 100
                  ? "text-status-ok"
                  : "text-status-warn"
            }
          />
        </div>

        {alerts.length > 0 && (
          <section className="mt-6">
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              Alertas ativos ({alerts.length})
            </h2>
            <AlertList alerts={alerts.slice(0, 8)} />
          </section>
        )}

        <section className="mt-6">
          <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
            Servidores
          </h2>
          {servers.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-surface-border py-16 text-slate-500">
              <ServerOff className="h-8 w-8" aria-hidden />
              <p className="text-sm">Nenhum servidor registrado ainda.</p>
              <p className="text-xs">
                Registre com: <code className="text-slate-400">python manage.py create-server</code>
              </p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {servers.map((server) => (
                <ServerCard key={server.id} server={server} />
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
