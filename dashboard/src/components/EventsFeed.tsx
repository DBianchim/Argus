import { Link } from "react-router-dom";
import type { NotificationOut, ServerOverview } from "../types";
import { PILAR_ABBR } from "../utils";

const SEVERITY_COLOR: Record<string, string> = {
  crit: "#ef4444",
  warn: "#f59e0b",
  info: "#10b981",
};

const MAX_EVENTS = 10;

export function EventsFeed({
  notifications,
  servers,
  pilarFilter,
}: {
  notifications: NotificationOut[];
  servers: ServerOverview[];
  pilarFilter: string;
}) {
  const hostById = new Map(servers.map((s) => [s.id, s.display_name ?? s.hostname]));
  const events = notifications
    .filter((n) => pilarFilter === "all" || n.pilar === pilarFilter)
    .slice(0, MAX_EVENTS);

  return (
    <aside className="flex w-80 flex-none flex-col overflow-hidden rounded-lg border border-[#272c3a] bg-[#1a1d27]">
      <div className="flex items-center gap-2 border-b border-[#232836] px-[15px] py-[13px]">
        <span className="font-plex-sans text-[13px] font-semibold text-[#c6cddc]">
          Eventos recentes
        </span>
        <span className="ml-auto font-plex-mono text-[11px] text-[#5b6274]">hoje</span>
      </div>

      {events.length === 0 ? (
        <div className="flex flex-col items-center gap-2.5 px-6 py-11 text-center">
          <span className="flex h-[38px] w-[38px] items-center justify-center rounded-full border border-status-ok/35 bg-status-ok/[.12] font-plex-sans text-[17px] font-semibold text-status-ok">
            ✓
          </span>
          <span className="font-plex-sans text-[13px] font-medium text-[#c6cddc]">
            Nenhum evento {pilarFilter === "all" ? "recente" : "neste pilar"}
          </span>
          <span className="font-plex-sans text-[11.5px] leading-[1.5] text-[#5b6274]">
            Todos os servidores reportando normalmente.
          </span>
        </div>
      ) : (
        <div className="flex flex-col">
          {events.map((e) => (
            <Link
              key={e.id}
              to={`/servers/${e.server_id}`}
              className="flex gap-2.5 border-b border-[#1f2432] px-[15px] py-2.5 transition-colors hover:bg-[#1e2230]"
            >
              <span
                className="mt-[5px] h-[7px] w-[7px] flex-none rounded-full"
                style={{ background: SEVERITY_COLOR[e.severity] ?? "#64748b" }}
              />
              <div className="flex min-w-0 flex-col gap-0.5">
                <div className="flex items-baseline gap-2">
                  <span className="flex-none font-plex-mono text-[11px] font-medium text-[#8b93a7]">
                    {new Date(e.created_at).toLocaleTimeString("pt-BR", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                  <span className="truncate font-plex-sans text-[11.5px] font-semibold text-[#c6cddc]">
                    {hostById.get(e.server_id) ?? `#${e.server_id}`}
                  </span>
                  {e.pilar && (
                    <span className="ml-auto flex-none rounded-[3px] bg-[#12151d] px-[5px] py-px font-plex-mono text-[9px] font-semibold text-[#5b6274]">
                      {PILAR_ABBR[e.pilar] ?? e.pilar}
                    </span>
                  )}
                </div>
                <span className="font-plex-sans text-xs leading-[1.45] text-[#8b93a7]">
                  {e.title}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </aside>
  );
}
