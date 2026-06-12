// Tipos espelhando os schemas da API (api/app/schemas.py).
// Regra aditiva (CONTRATO.md): campos de metrics são sempre opcionais aqui.

export type StatusValue = "ok" | "warn" | "crit" | "offline" | "unknown";
export type Pilar = "operacional" | "backup" | "acesso" | "logs";

export interface UserOut {
  username: string;
  display_name: string | null;
}

export interface LoginOut {
  token: string;
  expires_at: string;
  user: UserOut;
}

export interface AlertOut {
  severity: "warn" | "crit";
  pilar: string;
  item: string;
  title: string;
  detail: string;
  server_id: number;
  hostname: string;
}

export interface ServerOverview {
  id: number;
  hostname: string;
  os_family: "windows" | "linux";
  display_name: string | null;
  status: StatusValue;
  pilar_statuses: Record<string, StatusValue>;
  last_seen_at: string | null;
  agent_version: string | null;
}

export interface OverviewKpis {
  servers_total: number;
  online: number;
  offline: number;
  crit: number;
  warn: number;
  backups_ok_pct: number | null;
}

export interface OverviewOut {
  kpis: OverviewKpis;
  servers: ServerOverview[];
  alerts: AlertOut[];
  generated_at: string;
}

export interface ServerHealthOut {
  id: number;
  hostname: string;
  status: StatusValue;
  pilar_statuses: Record<string, StatusValue>;
  alerts: AlertOut[];
  last_seen_at: string | null;
  agent_version: string | null;
}

export interface MetricOut {
  id: number;
  server_id: number;
  pilar: Pilar;
  os_family: string;
  collected_at: string;
  received_at: string;
  request_id: string | null;
  agent_version: string | null;
  metrics: Record<string, unknown>;
}

export interface MetricPage {
  total: number;
  limit: number;
  offset: number;
  items: MetricOut[];
}

export interface NotificationOut {
  id: number;
  server_id: number;
  severity: "warn" | "crit" | "info";
  pilar: string | null;
  item: string | null;
  title: string;
  detail: string;
  status_from: string | null;
  status_to: string;
  created_at: string;
}

export interface NotificationPage {
  items: NotificationOut[];
}

// Blocos de metrics por pilar (parciais — tolerância a chaves ausentes)

export interface OperacionalMetrics {
  cpu?: { usage_pct?: number; cores?: number; error?: string };
  memory?: { usage_pct?: number; total_mb?: number; used_mb?: number; error?: string };
  disk?: { mount?: string; total_gb?: number; free_gb?: number; usage_pct?: number }[];
  services?: { name?: string; status?: string; start_type?: string; enabled?: string }[];
  uptime_seconds?: number;
}

export interface BackupMetrics {
  backup?: {
    status?: string;
    path?: string | null;
    age_hours?: number;
    size_mb?: number;
    sla_hours?: number;
    sla_ok?: boolean;
    integrity?: { integrity_check?: string; method?: string; detail?: string };
    log?: { log_found?: boolean; last_status?: string | null };
  };
}

export interface Finding {
  timestamp?: string;
  pilar?: string;
  item?: string;
  value?: unknown;
  status?: "ok" | "warning" | "error" | "info";
  detail?: string;
}

export interface FindingsMetrics {
  summary?: { ok?: number; warning?: number; error?: number; info?: number };
  total_findings?: number;
  findings?: Finding[];
  duration_seconds?: number;
}
