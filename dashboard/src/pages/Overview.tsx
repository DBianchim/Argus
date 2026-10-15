import { useQuery } from "@tanstack/react-query";
import { Loader2, ServerOff } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EventsFeed } from "../components/EventsFeed";
import { ServerCard } from "../components/ServerCard";
import { ServerFilterChips } from "../components/ServerFilterChips";
import { Sidebar } from "../components/Sidebar";
import { useNotificationsQuery } from "../hooks/useNotifications";
import { useServerFilters } from "../hooks/useServerFilters";
import type { OverviewOut, ServerOverview, StatusValue } from "../types";
import { STATUS_RANK } from "../utils";

const PILARES = ["operacional", "backup", "acesso", "logs"] as const;
const VISIBLE_COUNT = 6;

const SEGMENTS: { key: StatusValue; className: string }[] = [
  { key: "ok", className: "bg-status-ok" },
  { key: "warn", className: "bg-status-warn" },
  { key: "crit", className: "bg-status-crit" },
  { key: "offline", className: "bg-status-offline" },
  { key: "unknown", className: "bg-status-unknown" },
];

/** Pior status de um pilar entre todos os servidores — alimenta os dots do menu lateral. */
function worstPilarStatus(servers: ServerOverview[], pilar: (typeof PILARES)[number]): StatusValue {
  let worst: StatusValue = "ok";
  for (const s of servers) {
    const st = (s.pilar_statuses[pilar] ?? "unknown") as StatusValue;
    if (STATUS_RANK[st] < STATUS_RANK[worst]) worst = st;
  }
  return worst;
}

export function Overview() {
  const { data, isLoading, isError, dataUpdatedAt } = useQuery<OverviewOut>({
    queryKey: ["overview"],
    queryFn: () => api<OverviewOut>("/api/v1/overview"),
    refetchInterval: 30_000,
  });
  const { data: notifData } = useNotificationsQuery();

  const servers = data?.servers ?? [];
  const { os, setOs, pilar, setPilar, filtered: filteredServers } = useServerFilters(servers);
  const visibleServers = filteredServers.slice(0, VISIBLE_COUNT);

  const statusCounts = useMemo(() => {
    const counts: Record<StatusValue, number> = { ok: 0, warn: 0, crit: 0, offline: 0, unknown: 0 };
    for (const s of servers) counts[s.status]++;
    return counts;
  }, [servers]);

  const pilarStatus = useMemo(() => {
    const entries = PILARES.map(
      (p) => [p, servers.length === 0 ? "unknown" : worstPilarStatus(servers, p)] as const,
    );
    return Object.fromEntries(entries) as Record<(typeof PILARES)[number], StatusValue>;
  }, [servers]);

  const total = servers.length;
  const healthPct = total > 0 ? Math.round((statusCounts.ok / total) * 100) : 0;
  const healthColorClass =
    healthPct === 100 ? "text-status-ok" : healthPct >= 80 ? "text-status-warn" : "text-status-crit";

  const clock = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("pt-BR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      })
    : "—";

  const kpiItems = data
    ? [
        { label: "servidores", v: String(data.kpis.servers_total), cls: "text-[#c6cddc]" },
        { label: "online", v: String(data.kpis.online), cls: "text-[#c6cddc]" },
        {
          label: "críticos",
          v: String(data.kpis.crit),
          cls: data.kpis.crit ? "text-status-crit" : "text-[#5b6274]",
        },
        {
          label: "alertas",
          v: String(data.kpis.warn),
          cls: data.kpis.warn ? "text-status-warn" : "text-[#5b6274]",
        },
        {
          label: "backups ok",
          v: data.kpis.backups_ok_pct !== null ? `${data.kpis.backups_ok_pct}%` : "—",
          cls:
            data.kpis.backups_ok_pct === null
              ? "text-[#5b6274]"
              : data.kpis.backups_ok_pct >= 100
                ? "text-[#c6cddc]"
                : "text-status-warn",
        },
      ]
    : [];

  return (
    <div className="flex h-screen bg-[#0a0c11] font-plex-sans text-[#e2e6f0]">
      <Sidebar
        alertCounts={{ crit: data?.kpis.crit ?? 0, warn: data?.kpis.warn ?? 0 }}
        pilarStatus={pilarStatus}
      />
      <main className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-[26px] py-[22px]">
        {isLoading || !data ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-[#5b6274]">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            Carregando a frota…
          </div>
        ) : data.servers.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-[#5b6274]">
            <ServerOff className="h-8 w-8" aria-hidden />
            <p className="text-sm">Nenhum servidor registrado ainda.</p>
            <p className="font-plex-mono text-xs">
              Registre com: <span className="text-[#8b93a7]">python manage.py create-server</span>
            </p>
          </div>
        ) : (
          <>
            <div className="flex items-baseline gap-3.5">
              <h1 className="m-0 text-[19px] font-semibold tracking-[-0.01em] text-[#e2e6f0]">
                Visão geral do parque
              </h1>
              <span className="font-plex-mono text-[11.5px] text-[#5b6274]">
                atualizado às {clock} · a cada 30s
              </span>
              <div className="ml-auto flex items-center gap-2">
                <span
                  className={`h-[7px] w-[7px] rounded-full ${isError ? "bg-status-crit" : "bg-status-ok"}`}
                />
                <span className="text-xs text-[#8b93a7]">
                  {isError ? "Falha na coleta" : "Coleta ativa"}
                </span>
              </div>
            </div>

            <section className="flex flex-col gap-3 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-[18px] py-4">
              <div className="flex items-center gap-2.5">
                <span className="text-[13px] font-semibold text-[#c6cddc]">Saúde do parque</span>
                <span className={`ml-1.5 font-plex-mono text-xl font-semibold ${healthColorClass}`}>
                  {healthPct}%
                </span>
                <span className="text-xs text-[#8b93a7]">saudáveis</span>
                <div className="ml-auto flex gap-[18px]">
                  {kpiItems.map((item) => (
                    <div key={item.label} className="flex flex-col items-end leading-tight">
                      <span className={`tnum font-plex-mono text-[17px] font-semibold ${item.cls}`}>
                        {item.v}
                      </span>
                      <span className="text-[10.5px] text-[#5b6274]">{item.label}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="flex h-2 overflow-hidden rounded bg-[#12151d]">
                {SEGMENTS.map(
                  (seg) =>
                    statusCounts[seg.key] > 0 && (
                      <div
                        key={seg.key}
                        style={{ width: `${(statusCounts[seg.key] / total) * 100}%` }}
                        className={seg.className}
                      />
                    ),
                )}
              </div>
            </section>

            <div className="flex flex-wrap items-center gap-2">
              <ServerFilterChips os={os} setOs={setOs} pilar={pilar} setPilar={setPilar} />
              <span className="ml-auto font-plex-mono text-[11.5px] text-[#5b6274]">
                {filteredServers.length} de {total} servidores
              </span>
            </div>

            <div className="flex flex-1 items-start gap-[18px]">
              <div className="flex min-w-0 flex-1 flex-col gap-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold tracking-[0.08em] text-[#5b6274]">
                    SERVIDORES · ordenados por severidade
                  </span>
                  {filteredServers.length > VISIBLE_COUNT && (
                    <Link
                      to="/servers"
                      className="ml-auto font-plex-sans text-[11.5px] font-medium text-blue-400 hover:underline"
                    >
                      ver todos os {filteredServers.length} →
                    </Link>
                  )}
                </div>
                {filteredServers.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-[#272c3a] p-12 text-center text-[13px] text-[#5b6274]">
                    Nenhum servidor corresponde aos filtros.{" "}
                    <button
                      type="button"
                      onClick={() => {
                        setOs("all");
                        setPilar("all");
                      }}
                      className="text-blue-400 hover:underline"
                    >
                      Limpar filtros
                    </button>
                  </div>
                ) : (
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(295px,1fr))] gap-3">
                    {visibleServers.map((s) => (
                      <ServerCard key={s.id} server={s} />
                    ))}
                  </div>
                )}
              </div>
              <EventsFeed notifications={notifData?.items ?? []} servers={servers} pilarFilter={pilar} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
