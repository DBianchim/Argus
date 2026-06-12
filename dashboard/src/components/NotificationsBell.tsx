import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useNotificationsQuery } from "../hooks/useNotifications";
import { relativeTime } from "../utils";

const STORAGE_KEY = "argus_last_seen_bell_id";

const DOT: Record<string, string> = {
  crit: "bg-status-crit",
  warn: "bg-status-warn",
  info: "bg-status-ok",
};

export function NotificationsBell() {
  const navigate = useNavigate();
  const { data } = useNotificationsQuery();
  const [open, setOpen] = useState(false);
  const [lastSeenId, setLastSeenId] = useState<number>(() =>
    Number(sessionStorage.getItem(STORAGE_KEY) ?? 0),
  );
  const ref = useRef<HTMLDivElement>(null);

  const items = data?.items ?? [];
  const unseen = items.filter((n) => n.id > lastSeenId).length;

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && items.length > 0) {
      const maxId = items[0].id;
      setLastSeenId(maxId);
      sessionStorage.setItem(STORAGE_KEY, String(maxId));
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={toggle}
        className="relative rounded p-1.5 text-slate-500 hover:bg-surface-raised hover:text-slate-300"
        aria-label="Notificações"
      >
        <Bell className="h-4 w-4" aria-hidden />
        {unseen > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-status-crit px-1 text-[10px] font-medium text-white">
            {unseen > 9 ? "9+" : unseen}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 rounded-lg border border-surface-border bg-surface-raised shadow-xl">
          <div className="border-b border-surface-border px-3 py-2 text-xs font-medium uppercase tracking-wide text-slate-500">
            Notificações
          </div>
          {items.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-slate-500">
              Nenhuma notificação ainda.
            </p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.slice(0, 15).map((n) => (
                <li
                  key={n.id}
                  onClick={() => {
                    setOpen(false);
                    navigate(`/servers/${n.server_id}`);
                  }}
                  className="flex cursor-pointer gap-2.5 border-b border-surface-border/50 px-3 py-2.5 hover:bg-surface-border/40"
                >
                  <span
                    className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[n.severity] ?? "bg-slate-500"}`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-slate-200">{n.title}</p>
                    {n.detail && (
                      <p className="truncate text-xs text-slate-500">{n.detail}</p>
                    )}
                    <p className="mt-0.5 text-[11px] text-slate-600">
                      {relativeTime(n.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
