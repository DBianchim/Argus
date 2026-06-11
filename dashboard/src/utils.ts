// Utilitários de apresentação: metadados de status e tempo relativo.

import type { StatusValue } from "./types";

export const STATUS_META: Record<
  StatusValue,
  { label: string; dot: string; badge: string; border: string }
> = {
  ok: {
    label: "OK",
    dot: "bg-status-ok",
    badge: "bg-status-ok/15 text-status-ok",
    border: "border-l-status-ok",
  },
  warn: {
    label: "AVISO",
    dot: "bg-status-warn",
    badge: "bg-status-warn/15 text-status-warn",
    border: "border-l-status-warn",
  },
  crit: {
    label: "CRÍTICO",
    dot: "bg-status-crit",
    badge: "bg-status-crit/15 text-status-crit",
    border: "border-l-status-crit",
  },
  offline: {
    label: "OFFLINE",
    dot: "bg-status-offline",
    badge: "bg-status-offline/15 text-status-offline",
    border: "border-l-status-offline",
  },
  unknown: {
    label: "SEM DADOS",
    dot: "bg-status-unknown",
    badge: "bg-status-unknown/15 text-status-unknown",
    border: "border-l-status-unknown",
  },
};

export const PILAR_LABEL: Record<string, string> = {
  operacional: "Operacional",
  backup: "Backup",
  acesso: "Acesso",
  logs: "Logs",
};

/** "há 2 min", "há 3 h", "agora" — sinal de confiança em todo dado exibido. */
export function relativeTime(iso: string | null): string {
  if (!iso) return "nunca";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 10) return "agora";
  if (seconds < 60) return `há ${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `há ${hours} h`;
  return `há ${Math.round(hours / 24)} dias`;
}

export function formatPct(value: number | undefined | null): string {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "—";
}
