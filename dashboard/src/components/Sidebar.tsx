import {
  AlertTriangle,
  LayoutGrid,
  LogOut,
  Server as ServerIcon,
  Settings,
} from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getStoredUser, logout } from "../api/client";
import type { StatusValue } from "../types";
import { ROLE_META } from "../utils";
import { StatusDot } from "./StatusBadge";

const COLLAPSE_KEY = "argus_sidebar_collapsed";

const NAV_ITEMS: { label: string; Icon: typeof LayoutGrid; to?: string; activeOn: (path: string) => boolean }[] = [
  { label: "Dashboard", Icon: LayoutGrid, to: "/", activeOn: (p) => p === "/" },
  // Também acende no detalhe de um servidor específico (/servers/:id).
  { label: "Servidores", Icon: ServerIcon, to: "/servers", activeOn: (p) => p.startsWith("/servers") },
  { label: "Alertas", Icon: AlertTriangle, to: "/alerts", activeOn: (p) => p.startsWith("/alerts") },
  { label: "Configurações", Icon: Settings, to: "/settings", activeOn: (p) => p.startsWith("/settings") },
];

const PILARES: { key: "operacional" | "backup" | "acesso" | "logs"; label: string }[] = [
  { key: "operacional", label: "Operacional" },
  { key: "backup", label: "Backup" },
  { key: "acesso", label: "Acesso" },
  { key: "logs", label: "Logs" },
];

export function Sidebar({
  alertCounts,
  pilarStatus,
}: {
  alertCounts: { crit: number; warn: number };
  // Só o Dashboard mostra o resumo por pilar — demais telas omitem a seção.
  pilarStatus?: Record<"operacional" | "backup" | "acesso" | "logs", StatusValue>;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const user = getStoredUser();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        // localStorage indisponível (ex.: navegação privada) — só em memória
      }
      return next;
    });
  }

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  const displayName = user?.display_name ?? user?.username ?? "?";
  const initials = displayName.slice(0, 2).toUpperCase();
  const roleLabel = user ? ROLE_META[user.role].label.toLowerCase() : "";
  const onAccount = location.pathname === "/account";

  const itemClass = (active: boolean) =>
    `flex items-center gap-2.5 rounded-md px-2.5 py-2 font-plex-sans text-[13px] font-medium transition-colors ${
      active ? "bg-blue-500/[.14] text-[#e2e6f0]" : "text-[#8b93a7] hover:bg-[#1a1f2b]"
    }`;

  return (
    <nav
      className={`flex flex-none flex-col gap-0.5 overflow-hidden border-r border-[#1f2432] bg-[#12151d] px-2.5 py-3.5 transition-[width] duration-200 ease-out ${
        collapsed ? "w-[62px]" : "w-[216px]"
      }`}
    >
      <div className="flex items-center gap-2.5 px-1.5 pb-4 pt-1.5">
        <img src="/argus-eye.svg" width={26} height={26} alt="Argus" className="flex-none" />
        {!collapsed && (
          <>
            <span className="font-plex-sans text-base font-semibold tracking-[0.04em] text-[#e2e6f0]">
              ARGUS
            </span>
            <span className="ml-auto font-plex-mono text-[10px] font-medium text-[#5b6274]">
              v1.0
            </span>
          </>
        )}
      </div>

      {NAV_ITEMS.map((item) => {
        const active = item.activeOn(location.pathname);
        const showBadges =
          item.label === "Alertas" && (alertCounts.crit > 0 || alertCounts.warn > 0);
        const inner = (
          <>
            <item.Icon className="h-[17px] w-[17px] flex-none" strokeWidth={1.8} aria-hidden />
            {!collapsed && <span className="whitespace-nowrap">{item.label}</span>}
            {!collapsed && showBadges && (
              <span className="ml-auto flex items-center gap-1">
                {alertCounts.crit > 0 && (
                  <span className="rounded-[5px] border border-status-crit/35 bg-status-crit/[.18] px-1.5 py-px font-plex-mono text-[10.5px] font-semibold text-red-400">
                    {alertCounts.crit}
                  </span>
                )}
                {alertCounts.warn > 0 && (
                  <span className="rounded-[5px] border border-status-warn/30 bg-status-warn/[.14] px-1.5 py-px font-plex-mono text-[10.5px] font-semibold text-amber-400">
                    {alertCounts.warn}
                  </span>
                )}
              </span>
            )}
          </>
        );
        return item.to ? (
          <Link key={item.label} to={item.to} className={itemClass(active)}>
            {inner}
          </Link>
        ) : (
          <div key={item.label} className={`${itemClass(active)} cursor-default`} title="Em breve">
            {inner}
          </div>
        );
      })}

      {pilarStatus && (
        <>
          {!collapsed && (
            <div className="px-2.5 pb-1.5 pt-4 font-plex-sans text-[10px] font-semibold tracking-[0.1em] text-[#5b6274]">
              PILARES
            </div>
          )}
          {PILARES.map((p) => (
            <div
              key={p.key}
              className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 font-plex-sans text-[12.5px] text-[#8b93a7] hover:bg-[#1a1f2b]"
            >
              <span className="mx-[5px] flex-none">
                <StatusDot status={pilarStatus[p.key]} />
              </span>
              {!collapsed && <span className="whitespace-nowrap">{p.label}</span>}
            </div>
          ))}
        </>
      )}

      <div className="mt-auto flex flex-col gap-[2px]">
        <button
          type="button"
          onClick={toggleCollapsed}
          className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] font-plex-sans text-xs font-medium text-[#5b6274] hover:bg-[#1a1f2b] hover:text-[#8b93a7]"
        >
          <span className="w-[17px] flex-none text-center font-plex-mono text-[13px] font-semibold">
            {collapsed ? "»" : "«"}
          </span>
          {!collapsed && <span className="whitespace-nowrap">Recolher menu</span>}
        </button>

        <Link
          to="/account"
          className={`flex items-center gap-2.5 rounded-md border-t border-[#1f2432] px-1.5 py-2 ${
            onAccount ? "bg-blue-500/[.14]" : "hover:bg-[#1a1f2b]"
          }`}
        >
          <span className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-full border border-[#2c3549] bg-[#1e2738] font-plex-sans text-[10px] font-semibold text-[#9fb3d9]">
            {initials}
          </span>
          {!collapsed && (
            <span className="flex min-w-0 flex-col items-start leading-tight">
              <span className="truncate font-plex-sans text-xs font-medium text-[#e2e6f0]">
                {displayName}
              </span>
              <span className="font-plex-mono text-[10.5px] text-[#5b6274]">{roleLabel}</span>
            </span>
          )}
          {!collapsed && <span className="ml-auto font-plex-mono text-xs text-[#5b6274]">›</span>}
        </Link>
        <button
          type="button"
          onClick={handleLogout}
          className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] font-plex-sans text-xs font-medium text-[#5b6274] hover:bg-[#1a1f2b] hover:text-[#8b93a7]"
        >
          <LogOut className="h-[15px] w-[15px] flex-none" strokeWidth={1.8} aria-hidden />
          {!collapsed && <span className="whitespace-nowrap">Sair</span>}
        </button>
      </div>
    </nav>
  );
}
