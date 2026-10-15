// Utilitários de apresentação: metadados de status e tempo relativo.

import type { Role, StatusValue } from "./types";

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

export const ROLE_META: Record<Role, { label: string; badge: string; hint: string }> = {
  admin: {
    label: "Admin",
    badge: "bg-status-crit/15 text-status-crit",
    hint: "Gerencia usuários e servidores (acesso total).",
  },
  operator: {
    label: "Operador",
    badge: "bg-status-warn/15 text-status-warn",
    hint: "Edita e remove servidores/config, mas não gerencia usuários.",
  },
  viewer: {
    label: "Visualizador",
    badge: "bg-status-unknown/15 text-status-unknown",
    hint: "Somente leitura — sem permissão para alterar nada.",
  },
};

export const PILAR_LABEL: Record<string, string> = {
  operacional: "Operacional",
  backup: "Backup",
  acesso: "Acesso",
  logs: "Logs",
};

export const PILAR_ABBR: Record<string, string> = {
  operacional: "OP",
  backup: "BK",
  acesso: "AC",
  logs: "LG",
};

/** Ordem de severidade p/ ordenar cards do dashboard: crítico primeiro, saudável por último. */
export const STATUS_RANK: Record<StatusValue, number> = {
  crit: 0,
  offline: 1,
  warn: 2,
  unknown: 3,
  ok: 4,
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

/** "128d 6h", "6h 12min", "45min" — legível para operador, sem casas decimais. */
export function formatUptime(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || seconds < 0) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h`;
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}min`;
  return `${minutes}min`;
}

/** Converte uma série de valores em pontos de polyline normalizados ao viewBox. */
export function sparklinePoints(values: number[], width = 84, height = 26): string {
  if (values.length === 0) return "";
  if (values.length === 1) {
    const y = (height - 3) / 2;
    return `0,${y.toFixed(1)} ${width},${y.toFixed(1)}`;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values
    .map((v, i) => {
      const x = (i * width) / (values.length - 1);
      const y = height - 3 - ((v - min) / range) * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}
