import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";
import type { AlertOut } from "../types";
import { PILAR_LABEL } from "../utils";

export function AlertList({ alerts }: { alerts: AlertOut[] }) {
  if (alerts.length === 0) return null;

  return (
    <div className="space-y-2">
      {alerts.map((alert, index) => {
        const crit = alert.severity === "crit";
        return (
          <Link
            key={`${alert.server_id}-${alert.pilar}-${alert.item}-${index}`}
            to={`/servers/${alert.server_id}`}
            className={`flex items-center gap-3 rounded-lg border px-4 py-2.5 text-sm transition hover:brightness-125 ${
              crit
                ? "border-status-crit/40 bg-status-crit/10 text-red-200"
                : "border-status-warn/40 bg-status-warn/10 text-amber-200"
            }`}
          >
            <AlertTriangle
              className={`h-4 w-4 shrink-0 ${crit ? "text-status-crit" : "text-status-warn"}`}
              aria-hidden
            />
            <span className="truncate">
              <span className="font-medium">{alert.hostname}</span>
              <span className="text-slate-400"> · {PILAR_LABEL[alert.pilar] ?? alert.pilar} — </span>
              {alert.title}
            </span>
            {alert.detail && (
              <span className="ml-auto hidden truncate text-xs text-slate-400 lg:inline">
                {alert.detail}
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}
