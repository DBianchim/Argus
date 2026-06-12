import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useNotificationsQuery } from "../hooks/useNotifications";
import type { NotificationOut } from "../types";

const STORAGE_KEY = "argus_last_toast_id";

const SEVERITY_STYLE: Record<string, { box: string; icon: string }> = {
  crit: { box: "border-status-crit/50 bg-status-crit/10", icon: "text-status-crit" },
  warn: { box: "border-status-warn/50 bg-status-warn/10", icon: "text-status-warn" },
  info: { box: "border-status-ok/50 bg-status-ok/10", icon: "text-status-ok" },
};

function fireOsNotification(notif: NotificationOut) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    new Notification("Argus — alerta de monitoramento", {
      body: `${notif.title}${notif.detail ? `\n${notif.detail}` : ""}`,
      tag: `argus-${notif.id}`,
    });
  } catch {
    // Notification API pode falhar em alguns contextos — o toast in-app cobre
  }
}

export function Toaster() {
  const navigate = useNavigate();
  const { data } = useNotificationsQuery();
  const [toasts, setToasts] = useState<NotificationOut[]>([]);
  const lastIdRef = useRef<number | null>(null);

  // Pede permissão para o pop-up do SO uma vez (após carregar logado)
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    const stored = sessionStorage.getItem(STORAGE_KEY);
    lastIdRef.current = stored ? Number(stored) : null;
  }, []);

  useEffect(() => {
    const items = data?.items ?? [];
    if (items.length === 0) return;

    const maxId = items[0].id; // ordenado por id desc

    // Primeira carga da sessão: não dispara o histórico inteiro, só marca o ponto
    if (lastIdRef.current === null) {
      lastIdRef.current = maxId;
      sessionStorage.setItem(STORAGE_KEY, String(maxId));
      return;
    }

    const fresh = items
      .filter((n) => n.id > (lastIdRef.current ?? 0))
      .sort((a, b) => a.id - b.id);

    if (fresh.length === 0) return;

    lastIdRef.current = maxId;
    sessionStorage.setItem(STORAGE_KEY, String(maxId));

    setToasts((prev) => [...prev, ...fresh].slice(-4));
    fresh.forEach(fireOsNotification);

    // Auto-dismiss após 8s
    fresh.forEach((n) => {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== n.id));
      }, 8000);
    });
  }, [data]);

  function dismiss(id: number) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((toast) => {
        const style = SEVERITY_STYLE[toast.severity] ?? SEVERITY_STYLE.info;
        const Icon = toast.severity === "info" ? CheckCircle2 : AlertTriangle;
        return (
          <div
            key={toast.id}
            onClick={() => {
              dismiss(toast.id);
              navigate(`/servers/${toast.server_id}`);
            }}
            className={`cursor-pointer rounded-lg border p-3 ${style.box} backdrop-blur transition hover:brightness-125`}
          >
            <div className="flex items-start gap-2.5">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${style.icon}`} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-100">
                  {toast.title}
                </p>
                {toast.detail && (
                  <p className="mt-0.5 line-clamp-2 text-xs text-slate-400">
                    {toast.detail}
                  </p>
                )}
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  dismiss(toast.id);
                }}
                className="text-slate-500 hover:text-slate-300"
                aria-label="Dispensar"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
