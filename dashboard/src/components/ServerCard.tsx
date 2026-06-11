import { Monitor, Server as ServerIcon } from "lucide-react";
import { Link } from "react-router-dom";
import type { ServerOverview } from "../types";
import { PILAR_LABEL, STATUS_META, relativeTime } from "../utils";
import { StatusBadge, StatusDot } from "./StatusBadge";

const PILARES = ["operacional", "backup", "acesso", "logs"] as const;

export function ServerCard({ server }: { server: ServerOverview }) {
  const meta = STATUS_META[server.status] ?? STATUS_META.unknown;
  const OsIcon = server.os_family === "windows" ? Monitor : ServerIcon;
  const dimmed = server.status === "offline" ? "opacity-75" : "";

  return (
    <Link
      to={`/servers/${server.id}`}
      className={`block rounded-lg border-l-[3px] bg-surface-raised p-4 transition hover:bg-surface-border/40 ${meta.border} ${dimmed}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 truncate">
          <OsIcon className="h-4 w-4 shrink-0 text-slate-500" aria-hidden />
          <span className="truncate text-sm font-medium text-slate-100">
            {server.display_name ?? server.hostname}
          </span>
        </div>
        <StatusBadge status={server.status} />
      </div>

      {server.status === "offline" ? (
        <p className="mt-3 text-xs text-slate-500">sem contato com o agente</p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
          {PILARES.map((pilar) => (
            <span
              key={pilar}
              className="flex items-center gap-1.5 text-[11px] text-slate-400"
            >
              <StatusDot status={server.pilar_statuses[pilar] ?? "unknown"} />
              {PILAR_LABEL[pilar]}
            </span>
          ))}
        </div>
      )}

      <p className="mt-2.5 text-[11px] text-slate-500">
        coletado {relativeTime(server.last_seen_at)}
        {server.agent_version && ` · agente ${server.agent_version}`}
      </p>
    </Link>
  );
}
