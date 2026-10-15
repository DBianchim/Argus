import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, registerServer } from "../api/client";
import { FormField } from "../components/FormField";
import { Modal } from "../components/Modal";
import { Sidebar } from "../components/Sidebar";
import { TagInput } from "../components/TagInput";
import type { OverviewOut, ServerConfigBlob, ServerConfigOut, ServerOut } from "../types";
import { relativeTime } from "../utils";

const numOr = (v: string, fallback: number) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

// `inline-block` é essencial aqui: um <span> é inline por padrão, então
// width/height explícitos são ignorados — com o único filho em position:absolute
// (fora do fluxo), o pill colapsava para 0×0 e só o círculo branco escapava, solto.
function TogglePill({ on }: { on: boolean }) {
  return (
    <span
      className={`relative inline-block h-5 w-9 flex-none rounded-full transition-colors ${on ? "bg-blue-500" : "bg-[#2c3549]"}`}
    >
      <span
        className="absolute top-[3px] inline-block h-[14px] w-[14px] rounded-full bg-white shadow-sm transition-[left] duration-150"
        style={{ left: on ? 18 : 3 }}
      />
    </span>
  );
}

function Toggle({
  on,
  onClick,
  labels,
  className = "",
}: {
  on: boolean;
  onClick: () => void;
  /** [rótulo quando ativo, rótulo quando inativo] — omitido = pill sozinho, compacto. */
  labels?: [string, string];
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 ${className}`}
    >
      {labels && (
        <span
          className={`font-plex-sans text-[11px] font-semibold ${on ? "text-emerald-400" : "text-[#5b6274]"}`}
        >
          {on ? labels[0] : labels[1]}
        </span>
      )}
      <TogglePill on={on} />
    </button>
  );
}

function AddServerForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [hostname, setHostname] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [osFamily, setOsFamily] = useState<"linux" | "windows">("linux");
  const [result, setResult] = useState<{ token: string } | null>(null);

  const save = useMutation({
    mutationFn: () =>
      registerServer({ hostname, os_family: osFamily, display_name: displayName || null }),
    onSuccess: (out) => {
      queryClient.invalidateQueries({ queryKey: ["servers"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      setResult({ token: out.token });
      navigator.clipboard?.writeText(out.token).catch(() => {});
    },
  });

  return (
    <section className="flex flex-col gap-3.5 rounded-lg border border-blue-500/40 bg-[#1a1d27] px-[18px] py-4">
      <div className="flex items-center gap-2">
        <span className="font-plex-sans text-[13px] font-semibold text-[#c6cddc]">Adicionar servidor</span>
        <span className="text-[11.5px] text-[#5b6274]">o agente se autentica com o token gerado ao salvar</span>
      </div>
      <div className="grid grid-cols-[1fr_1fr_180px] gap-3">
        <FormField label="Nome de exibição" value={displayName} onChange={setDisplayName} placeholder="ex: ERP Produção" />
        <FormField label="Hostname" mono value={hostname} onChange={setHostname} placeholder="srv-novo-01" />
        <label className="block font-plex-sans">
          <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">Sistema</span>
          <select
            value={osFamily}
            onChange={(e) => setOsFamily(e.target.value as "linux" | "windows")}
            className="mt-1.5 w-full rounded-md border border-[#272c3a] bg-[#12151d] px-3 py-2 text-[13px] text-[#e2e6f0] outline-none focus:border-blue-500"
          >
            <option value="linux">Linux</option>
            <option value="windows">Windows</option>
          </select>
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || !hostname || !!result}
          className="rounded-md bg-blue-500 px-[18px] py-2 font-plex-sans text-[12.5px] font-semibold text-white transition-colors hover:bg-blue-600 disabled:opacity-50"
        >
          {save.isPending ? "Salvando…" : "Salvar e gerar token"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-[#272c3a] px-3.5 py-2 font-plex-sans text-xs font-medium text-[#8b93a7] hover:text-[#c6cddc]"
        >
          {result ? "Fechar" : "Cancelar"}
        </button>
        {save.isError && <span className="text-xs text-status-crit">Falha ao cadastrar — host já existe?</span>}
      </div>
      {result && (
        <div className="flex flex-col gap-1.5 rounded-md border border-status-ok/30 bg-status-ok/[.08] px-3.5 py-3">
          <span className="font-plex-sans text-xs font-medium text-emerald-400">
            ✓ Servidor cadastrado — token copiado para a área de transferência
          </span>
          <code className="break-all font-plex-mono text-[11px] text-[#c6cddc]">{result.token}</code>
          <span className="text-[10.5px] text-[#5b6274]">
            Defina no servidor monitorado: AGENT_API_TOKEN=&lt;token acima&gt; — não será exibido de novo.
          </span>
        </div>
      )}
    </section>
  );
}

function ServerConfigPanel({ serverId, servers }: { serverId: number; servers: ServerOut[] }) {
  const queryClient = useQueryClient();
  const server = servers.find((s) => s.id === serverId);

  const { data: cfg } = useQuery<ServerConfigOut>({
    queryKey: ["server-config", serverId],
    queryFn: () => api<ServerConfigOut>(`/api/v1/servers/${serverId}/config`),
  });

  const [interval, setIntervalSec] = useState(300);
  const [opEnabled, setOpEnabled] = useState(true);
  const [services, setServices] = useState<string[]>([]);
  const [th, setTh] = useState({ cpu_warn: 75, cpu_crit: 90, mem_warn: 80, mem_crit: 90, disk_warn: 80, disk_crit: 90 });
  const [backupEnabled, setBackupEnabled] = useState(true);
  const [paths, setPaths] = useState<string[]>([]);
  const [extensions, setExtensions] = useState<string[]>([]);
  const [slaHours, setSlaHours] = useState(24);
  const [minSizeMb, setMinSizeMb] = useState(5);
  const [acessoEnabled, setAcessoEnabled] = useState(true);
  const [failedLoginTh, setFailedLoginTh] = useState(10);
  const [alertAccountChange, setAlertAccountChange] = useState(true);
  const [logsEnabled, setLogsEnabled] = useState(true);
  const [maxLogAge, setMaxLogAge] = useState(24);
  const [minRetention, setMinRetention] = useState(90);
  const [minChannelMb, setMinChannelMb] = useState(256);
  const [showDelete, setShowDelete] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!cfg) return;
    const c = cfg.config;
    const op = c.operacional ?? {};
    setIntervalSec(c.interval_seconds ?? 300);
    setOpEnabled(op.enabled ?? true);
    setServices(op.critical_services ?? []);
    setTh({
      cpu_warn: op.cpu_warn ?? 75, cpu_crit: op.cpu_crit ?? 90,
      mem_warn: op.mem_warn ?? 80, mem_crit: op.mem_crit ?? 90,
      disk_warn: op.disk_warn ?? 80, disk_crit: op.disk_crit ?? 90,
    });
    const bk = c.backup ?? {};
    setBackupEnabled(bk.enabled ?? true);
    setPaths(bk.paths ?? []);
    setExtensions(bk.extensions ?? []);
    setSlaHours(bk.sla_hours ?? 24);
    setMinSizeMb(bk.min_size_mb ?? 5);
    const ac = c.acesso ?? {};
    setAcessoEnabled(ac.enabled ?? true);
    setFailedLoginTh(ac.failed_login_threshold ?? 10);
    setAlertAccountChange(ac.alert_on_account_change ?? true);
    const lg = c.logs ?? {};
    setLogsEnabled(lg.enabled ?? true);
    setMaxLogAge(lg.max_log_age_hours ?? 24);
    setMinRetention(lg.min_retention_rotations ?? 90);
    setMinChannelMb(lg.min_channel_size_mb ?? 256);
  }, [cfg]);

  const saveConfig = useMutation({
    mutationFn: () => {
      const base: ServerConfigBlob = cfg?.config ?? {};
      const body: ServerConfigBlob = {
        ...base,
        interval_seconds: interval,
        // enabled por pilar: um servidor sem backup (ou sem AD, etc.) pode desligar
        // só aquele pilar — o pilar ausente vira "unknown" na análise, nunca "crit".
        operacional: { ...(base.operacional ?? {}), enabled: opEnabled, critical_services: services, ...th },
        backup: { ...(base.backup ?? {}), enabled: backupEnabled, paths, extensions, sla_hours: slaHours, min_size_mb: minSizeMb },
        acesso: { ...(base.acesso ?? {}), enabled: acessoEnabled, failed_login_threshold: failedLoginTh, alert_on_account_change: alertAccountChange },
        logs: { ...(base.logs ?? {}), enabled: logsEnabled, max_log_age_hours: maxLogAge, min_retention_rotations: minRetention, min_channel_size_mb: minChannelMb },
      };
      return api(`/api/v1/servers/${serverId}/config`, { method: "PUT", body: JSON.stringify({ config: body }) });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["server-config", serverId] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["health", serverId] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  const removeServer = useMutation({
    mutationFn: () => api(`/api/v1/servers/${serverId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["servers"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  // Colapsável + toggle de enabled: um servidor sem backup (ou sem pilar de
  // acesso/logs aplicável) desliga só aquele pilar, sem precisar desativar o
  // servidor inteiro. Pilar desligado = agente para de coletar = a central
  // trata como "unknown", nunca gera alerta crítico por dado ausente.
  function PilarCard({
    title, hint, children, enabled, onToggleEnabled,
  }: {
    title: string;
    hint: string;
    children?: React.ReactNode;
    enabled: boolean;
    onToggleEnabled: () => void;
  }) {
    const [collapsed, setCollapsed] = useState(false);
    return (
      <div className={`flex flex-col gap-3 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-[17px] py-3.5 ${enabled ? "" : "opacity-60"}`}>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            className="flex flex-1 items-center gap-2.5 text-left"
          >
            <span className="font-plex-sans text-[13px] font-semibold text-[#c6cddc]">{title}</span>
            <span className="text-[11px] text-[#5b6274]">{hint}</span>
            <ChevronDown
              className={`h-4 w-4 flex-none text-[#5b6274] transition-transform duration-150 ${collapsed ? "-rotate-90" : ""}`}
              aria-hidden
            />
          </button>
          <Toggle
            on={enabled}
            onClick={onToggleEnabled}
            labels={["monitorando", "desligado"]}
          />
        </div>
        {!collapsed && (enabled ? children : (
          <p className="text-[11.5px] text-[#5b6274]">
            Pilar desligado — o agente não coleta este pilar e ele não afeta o status do servidor.
          </p>
        ))}
      </div>
    );
  }

  return (
    <section className="flex w-[560px] flex-none flex-col gap-3">
      <div className="flex items-center gap-3.5 rounded-lg border border-[#272c3a] bg-[#1a1d27] px-[17px] py-3.5">
        <span className="font-plex-mono text-sm font-semibold text-[#93bbfd]">
          {server?.display_name ?? server?.hostname ?? `Servidor ${serverId}`}
        </span>
        <label className="flex items-center gap-2 text-[11.5px] text-[#8b93a7]">
          Intervalo de coleta
          <select
            value={interval}
            onChange={(e) => setIntervalSec(Number(e.target.value))}
            className="rounded border border-[#272c3a] bg-[#12151d] px-2 py-1 font-plex-mono text-xs text-[#c6cddc] outline-none"
          >
            <option value={30}>30 s</option>
            <option value={60}>60 s</option>
            <option value={300}>300 s</option>
          </select>
        </label>
      </div>

      <PilarCard title="Operacional" hint="CPU · memória · disco · serviços" enabled={opEnabled} onToggleEnabled={() => setOpEnabled((v) => !v)}>
        <div className="flex flex-col gap-3">
          {([["CPU", "cpu"], ["Memória", "mem"], ["Disco", "disk"]] as const).map(([label, key]) => (
            <div key={key} className="flex items-center gap-2.5">
              <span className="w-[60px] flex-none font-plex-sans text-xs font-medium text-[#c6cddc]">{label}</span>
              <div className="relative h-2 flex-1 overflow-hidden rounded bg-[#12151d]">
                <div className="absolute inset-y-0 left-0 bg-status-ok/35" style={{ width: `${th[`${key}_warn` as const]}%` }} />
                <div
                  className="absolute inset-y-0 bg-status-warn/45"
                  style={{ left: `${th[`${key}_warn` as const]}%`, width: `${th[`${key}_crit` as const] - th[`${key}_warn` as const]}%` }}
                />
                <div className="absolute inset-y-0 right-0 bg-status-crit/50" style={{ left: `${th[`${key}_crit` as const]}%` }} />
              </div>
              <input
                type="number" min={1} max={100}
                value={th[`${key}_warn` as const]}
                onChange={(e) => setTh((t) => ({ ...t, [`${key}_warn`]: numOr(e.target.value, 75) }))}
                className="w-10 rounded border border-status-warn/30 bg-[#12151d] py-1 text-center font-plex-mono text-[11.5px] text-amber-400 outline-none"
              />
              <input
                type="number" min={1} max={100}
                value={th[`${key}_crit` as const]}
                onChange={(e) => setTh((t) => ({ ...t, [`${key}_crit`]: numOr(e.target.value, 90) }))}
                className="w-10 rounded border border-status-crit/35 bg-[#12151d] py-1 text-center font-plex-mono text-[11.5px] text-red-400 outline-none"
              />
            </div>
          ))}
          <TagInput label="Serviços críticos monitorados" values={services} onChange={setServices} placeholder="ex.: W3SVC" />
        </div>
      </PilarCard>

      <PilarCard title="Backup" hint="presença · idade · tamanho · integridade" enabled={backupEnabled} onToggleEnabled={() => setBackupEnabled((v) => !v)}>
        <div className="flex flex-col gap-3">
          <TagInput label="Caminhos" values={paths} onChange={setPaths} placeholder="ex.: D:\Backups" />
          <TagInput label="Extensões aceitas" values={extensions} onChange={setExtensions} placeholder="ex.: .zip" />
          <div className="flex gap-5">
            <FormField label="SLA (h)" type="number" mono className="w-24" value={slaHours} onChange={(v) => setSlaHours(numOr(v, 24))} />
            <FormField label="Tam. mínimo (MB)" type="number" mono className="w-28" value={minSizeMb} onChange={(v) => setMinSizeMb(numOr(v, 5))} />
          </div>
        </div>
      </PilarCard>

      <PilarCard title="Acesso" hint="logins falhos · mudanças de conta" enabled={acessoEnabled} onToggleEnabled={() => setAcessoEnabled((v) => !v)}>
        <div className="flex items-center gap-5">
          <FormField label="Alerta após (logins)" type="number" mono className="w-28" value={failedLoginTh} onChange={(v) => setFailedLoginTh(numOr(v, 10))} />
          <button
            type="button"
            onClick={() => setAlertAccountChange((v) => !v)}
            className="flex items-center gap-2 pt-4 font-plex-sans text-[11.5px] text-[#8b93a7]"
          >
            <TogglePill on={alertAccountChange} />
            alertar mudança em contas/grupos
          </button>
        </div>
      </PilarCard>

      <PilarCard title="Logs" hint="idade · retenção · canal de eventos" enabled={logsEnabled} onToggleEnabled={() => setLogsEnabled((v) => !v)}>
        <div className="flex gap-5">
          <FormField label="Idade máx. (h)" type="number" mono className="w-24" value={maxLogAge} onChange={(v) => setMaxLogAge(numOr(v, 24))} />
          <FormField label="Retenção mín." type="number" mono className="w-24" value={minRetention} onChange={(v) => setMinRetention(numOr(v, 90))} />
          <FormField label="Canal mín. (MB)" type="number" mono className="w-28" value={minChannelMb} onChange={(v) => setMinChannelMb(numOr(v, 256))} />
        </div>
      </PilarCard>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => saveConfig.mutate()}
          disabled={saveConfig.isPending}
          className="rounded-md bg-blue-500 px-[18px] py-2 font-plex-sans text-[12.5px] font-semibold text-white transition-colors hover:bg-blue-600 disabled:opacity-60"
        >
          {saveConfig.isPending ? "Salvando…" : "Salvar configuração"}
        </button>
        <span className="text-[11px] text-[#5b6274]">aplica no próximo ciclo de coleta</span>
        {saved && <span className="text-xs text-status-ok">Salvo ✓</span>}
        <button
          type="button"
          onClick={() => setShowDelete(true)}
          className="ml-auto rounded-md border border-status-crit/35 px-3.5 py-2 font-plex-sans text-xs font-medium text-red-400 transition-colors hover:bg-status-crit/10"
        >
          Remover servidor…
        </button>
      </div>

      {showDelete && (
        <Modal
          title="Remover servidor"
          onClose={() => setShowDelete(false)}
          footer={
            <>
              <button type="button" onClick={() => setShowDelete(false)} className="rounded-md px-4 py-2 text-sm text-[#8b93a7] hover:text-[#c6cddc]">
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => removeServer.mutate()}
                disabled={removeServer.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-status-crit px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-600 disabled:opacity-60"
              >
                {removeServer.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
                Remover definitivamente
              </button>
            </>
          }
        >
          Isto remove <strong>{server?.display_name ?? server?.hostname}</strong> e todo o
          histórico de métricas dele. Esta ação não pode ser desfeita.
        </Modal>
      )}
    </section>
  );
}

export function Settings() {
  const [params, setParams] = useSearchParams();
  const [showAdd, setShowAdd] = useState(false);
  const selectedId = params.get("server") ? Number(params.get("server")) : null;

  const { data: servers, isLoading } = useQuery<ServerOut[]>({
    queryKey: ["servers"],
    queryFn: () => api<ServerOut[]>("/api/v1/servers"),
  });
  const { data: overview } = useQuery<OverviewOut>({
    queryKey: ["overview"],
    queryFn: () => api<OverviewOut>("/api/v1/overview"),
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (!selectedId && servers && servers.length > 0) {
      setParams({ server: String(servers[0].id) }, { replace: true });
    }
  }, [selectedId, servers, setParams]);

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      api(`/api/v1/servers/${id}`, { method: "PATCH", body: JSON.stringify({ is_active }) }),
  });
  const queryClient = useQueryClient();

  return (
    <div className="flex h-screen bg-[#0a0c11] font-plex-sans text-[#e2e6f0]">
      <Sidebar alertCounts={{ crit: overview?.kpis.crit ?? 0, warn: overview?.kpis.warn ?? 0 }} />
      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-[26px] py-[22px]">
        <div className="flex items-center gap-3.5">
          <h1 className="m-0 text-[19px] font-semibold tracking-[-0.01em] text-[#e2e6f0]">
            Configurações
          </h1>
          <span className="font-plex-mono text-[11.5px] text-[#5b6274]">
            {servers?.length ?? "…"} servidores
          </span>
          <button
            type="button"
            onClick={() => setShowAdd((v) => !v)}
            className="ml-auto rounded-md bg-blue-500 px-4 py-2 font-plex-sans text-[12.5px] font-semibold text-white transition-colors hover:bg-blue-600"
          >
            {showAdd ? "Fechar formulário" : "+ Adicionar servidor"}
          </button>
        </div>

        <div className="flex flex-col gap-4">
          {showAdd && <AddServerForm onClose={() => setShowAdd(false)} />}
          <div className="flex items-start gap-4">
            <section className="min-w-0 flex-1 overflow-hidden rounded-lg border border-[#272c3a] bg-[#1a1d27]">
              <div className="flex items-center gap-2 border-b border-[#232836] px-4 py-3">
                <span className="font-plex-sans text-[12.5px] font-semibold text-[#c6cddc]">Servidores cadastrados</span>
                <span className="ml-auto font-plex-mono text-[11px] text-[#5b6274]">
                  {(servers ?? []).filter((s) => s.is_active).length} ativos
                </span>
              </div>
              <div className="grid grid-cols-[44px_1fr_120px_80px] gap-2.5 border-b border-[#232836] px-4 py-2.5 font-plex-sans text-[10.5px] font-semibold tracking-[0.07em] text-[#5b6274]">
                <span /><span>SERVIDOR</span><span>ÚLTIMO CONTATO</span><span>SO</span>
              </div>
              {isLoading ? (
                <div className="flex items-center justify-center gap-2 py-12 text-sm text-[#5b6274]">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Carregando…
                </div>
              ) : (
                (servers ?? []).map((s) => (
                  <div
                    key={s.id}
                    onClick={() => setParams({ server: String(s.id) })}
                    className={`grid grid-cols-[44px_1fr_120px_80px] items-center gap-2.5 border-b border-[#1f2432] px-4 py-2.5 last:border-0 hover:bg-[#1e2230] ${
                      selectedId === s.id ? "bg-blue-500/[.08]" : ""
                    } ${s.is_active ? "" : "opacity-50"} cursor-pointer`}
                  >
                    <span onClick={(e) => e.stopPropagation()}>
                      <Toggle on={s.is_active} onClick={() => toggleActive.mutate({ id: s.id, is_active: !s.is_active }, {
                        onSuccess: () => {
                          queryClient.invalidateQueries({ queryKey: ["servers"] });
                          queryClient.invalidateQueries({ queryKey: ["overview"] });
                        },
                      })} />
                    </span>
                    <span className="min-w-0 truncate font-plex-sans text-[13px] font-medium" style={{ color: selectedId === s.id ? "#93bbfd" : "#c6cddc" }}>
                      {s.display_name ?? s.hostname}
                    </span>
                    <span className="font-plex-mono text-xs text-[#8b93a7]">{relativeTime(s.last_seen_at)}</span>
                    <span className="font-plex-mono text-[10px] font-medium text-[#8b93a7]">
                      {s.os_family === "linux" ? "LINUX" : "WINDOWS"}
                    </span>
                  </div>
                ))
              )}
              {!isLoading && (servers ?? []).length === 0 && (
                <p className="px-4 py-8 text-center text-sm text-[#5b6274]">
                  Nenhum servidor registrado. Use "+ Adicionar servidor" acima.
                </p>
              )}
            </section>

            {selectedId && servers && (
              <ServerConfigPanel key={selectedId} serverId={selectedId} servers={servers} />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
