import { Eye, LogOut, RefreshCw } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { getStoredUser, logout } from "../api/client";
import { relativeTime } from "../utils";
import { NotificationsBell } from "./NotificationsBell";

export function TopBar({ updatedAt }: { updatedAt?: string }) {
  const navigate = useNavigate();
  const user = getStoredUser();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <header className="flex items-center justify-between border-b border-surface-border px-6 py-3">
      <Link to="/" className="flex items-center gap-2.5">
        <Eye className="h-5 w-5 text-status-ok" aria-hidden />
        <span className="text-base font-semibold tracking-[0.2em] text-slate-100">
          ARGUS
        </span>
        <span className="hidden text-xs text-slate-500 sm:inline">
          monitoramento de infraestrutura
        </span>
      </Link>

      <div className="flex items-center gap-4">
        {updatedAt && (
          <span className="flex items-center gap-1.5 text-xs text-slate-500">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            atualizado {relativeTime(updatedAt)}
          </span>
        )}
        <NotificationsBell />
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-border text-xs font-medium text-slate-300">
            {(user?.display_name ?? user?.username ?? "?")
              .slice(0, 2)
              .toUpperCase()}
          </div>
          <button
            onClick={handleLogout}
            title="Sair"
            className="rounded p-1.5 text-slate-500 hover:bg-surface-raised hover:text-slate-300"
          >
            <LogOut className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </div>
    </header>
  );
}
