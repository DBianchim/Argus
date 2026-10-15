import { Link } from "react-router-dom";
import type { ServerOverview, StatusValue } from "../types";
import { PILAR_ABBR, STATUS_META, formatUptime, relativeTime, sparklinePoints } from "../utils";

const METRICS: { key: "cpu_pct" | "mem_pct" | "disk_pct"; label: string }[] = [
  { key: "cpu_pct", label: "CPU" },
  { key: "mem_pct", label: "MEM" },
  { key: "disk_pct", label: "DISCO" },
];

const PILARES = ["operacional", "backup", "acesso", "logs"] as const;

const STATUS_TEXT_CLASS: Record<StatusValue, string> = {
  ok: "text-status-ok",
  warn: "text-status-warn",
  crit: "text-status-crit",
  offline: "text-status-offline",
  unknown: "text-status-unknown",
};

const PILAR_CHIP_CLASS: Record<StatusValue, string> = {
  ok: "bg-status-ok/10 text-emerald-400 border-status-ok/25",
  warn: "bg-status-warn/[.12] text-amber-400 border-status-warn/30",
  crit: "bg-status-crit/[.14] text-red-400 border-status-crit/35",
  offline: "bg-status-offline/[.12] text-slate-500 border-status-offline/25",
  unknown: "bg-status-unknown/[.12] text-slate-400 border-status-unknown/25",
};

function metricValueClass(v: number | null): string {
  if (v === null) return "text-[#5b6274]";
  if (v >= 90) return "text-status-crit";
  if (v >= 80) return "text-status-warn";
  return "text-[#c6cddc]";
}

function sparkColor(status: StatusValue): string {
  if (status === "offline") return "#3b4254";
  if (status === "crit") return "#ef4444";
  if (status === "warn") return "#f59e0b";
  return "#3b82f6";
}

export function ServerCard({ server }: { server: ServerOverview }) {
  const meta = STATUS_META[server.status] ?? STATUS_META.unknown;
  const cardBorder =
    server.status === "crit"
      ? "border-status-crit/45"
      : server.status === "warn"
        ? "border-status-warn/30"
        : "border-[#272c3a]";

  return (
    <Link
      to={`/servers/${server.id}`}
      className={`flex flex-col gap-2.5 rounded-lg border bg-[#1a1d27] px-3.5 py-[13px] transition-colors hover:border-blue-500 ${cardBorder} ${
        server.status === "offline" ? "opacity-[.55]" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`h-[9px] w-[9px] flex-none rounded-full ${meta.dot} ${
            server.status === "crit" ? "animate-status-pulse" : ""
          }`}
        />
        <span className="truncate font-plex-sans text-[13.5px] font-semibold text-[#e2e6f0]">
          {server.display_name ?? server.hostname}
        </span>
        <span className="ml-auto flex-none rounded border border-[#272c3a] bg-[#12151d] px-1.5 py-0.5 font-plex-mono text-[10px] font-medium text-[#8b93a7]">
          {server.os_family === "linux" ? "LINUX" : "WINDOWS"}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <span className="font-plex-mono text-[11.5px] text-[#5b6274]">
          coletado {relativeTime(server.last_seen_at)}
        </span>
        <span
          className={`ml-auto flex-none font-plex-sans text-[10.5px] font-semibold tracking-[0.05em] ${STATUS_TEXT_CLASS[server.status]}`}
        >
          {meta.label}
        </span>
      </div>

      <div className="flex items-end gap-3.5">
        {METRICS.map((m) => {
          const v = server[m.key];
          return (
            <div key={m.key} className="flex flex-col leading-tight">
              <span className="font-plex-sans text-[9.5px] tracking-[0.07em] text-[#5b6274]">
                {m.label}
              </span>
              <span className={`tnum font-plex-mono text-[13px] font-medium ${metricValueClass(v)}`}>
                {v === null ? "—" : `${Math.round(v)}%`}
              </span>
            </div>
          );
        })}
        <svg width={84} height={26} viewBox="0 0 84 26" className="ml-auto flex-none">
          <polyline
            points={sparklinePoints(server.cpu_history)}
            fill="none"
            stroke={sparkColor(server.status)}
            strokeWidth={1.5}
            strokeLinejoin="round"
          />
        </svg>
      </div>

      <div className="flex items-center gap-1.5 border-t border-[#232836] pt-[9px]">
        {PILARES.map((p) => {
          const st = server.pilar_statuses[p] ?? "unknown";
          return (
            <span
              key={p}
              className={`rounded border px-[7px] py-0.5 font-plex-mono text-[9.5px] font-semibold ${PILAR_CHIP_CLASS[st] ?? PILAR_CHIP_CLASS.unknown}`}
            >
              {PILAR_ABBR[p]}
            </span>
          );
        })}
        <span className="ml-auto flex-none font-plex-mono text-[10.5px] text-[#5b6274]">
          up {formatUptime(server.uptime_seconds)}
        </span>
      </div>
    </Link>
  );
}
