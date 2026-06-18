import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { FormField } from "../components/FormField";
import { Modal } from "../components/Modal";
import { TagInput } from "../components/TagInput";
import { TopBar } from "../components/TopBar";
import type { ServerConfigBlob, ServerConfigOut, ServerOut } from "../types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg bg-surface-raised p-5">
      <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-slate-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

const numOr = (v: string, fallback: number) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

export function ServerConfig() {
  const { id } = useParams();
  const serverId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: servers } = useQuery<ServerOut[]>({
    queryKey: ["servers"],
    queryFn: () => api<ServerOut[]>("/api/v1/servers"),
  });
  const server = servers?.find((s) => s.id === serverId);

  const { data: cfg, isLoading } = useQuery<ServerConfigOut>({
    queryKey: ["server-config", serverId],
    queryFn: () => api<ServerConfigOut>(`/api/v1/servers/${serverId}/config`),
  });

  // Estado editável (semeado quando os dados chegam)
  const [displayName, setDisplayName] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [interval, setIntervalSec] = useState(300);
  const [services, setServices] = useState<string[]>([]);
  const [th, setTh] = useState({
    cpu_warn: 75, cpu_crit: 90, mem_warn: 80, mem_crit: 90, disk_warn: 80, disk_crit: 90,
  });
  const [opEnabled, setOpEnabled] = useState(true);
  // Backup
  const [bkEnabled, setBkEnabled] = useState(true);
  const [paths, setPaths] = useState<string[]>([]);
  const [extensions, setExtensions] = useState<string[]>([]);
  const [slaHours, setSlaHours] = useState(24);
  const [minSizeMb, setMinSizeMb] = useState(5);
  // Acesso / Logs
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
    if (server) {
      setDisplayName(server.display_name ?? "");
      setIsActive(server.is_active);
    }
  }, [server]);

  useEffect(() => {
    if (cfg) {
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
      setBkEnabled(bk.enabled ?? true);
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
    }
  }, [cfg]);

  const saveConfig = useMutation({
    mutationFn: () => {
      // Preserva os pilares não editados na Fatia 1 (backup/acesso/logs)
      const base: ServerConfigBlob = cfg?.config ?? {};
      const body: ServerConfigBlob = {
        ...base,
        interval_seconds: interval,
        operacional: {
          ...(base.operacional ?? {}),
          enabled: opEnabled,
          critical_services: services,
          ...th,
        },
        backup: {
          ...(base.backup ?? {}),
          enabled: bkEnabled,
          paths,
          extensions,
          sla_hours: slaHours,
          min_size_mb: minSizeMb,
        },
        acesso: {
          ...(base.acesso ?? {}),
          enabled: acessoEnabled,
          failed_login_threshold: failedLoginTh,
          alert_on_account_change: alertAccountChange,
        },
        logs: {
          ...(base.logs ?? {}),
          enabled: logsEnabled,
          max_log_age_hours: maxLogAge,
          min_retention_rotations: minRetention,
          min_channel_size_mb: minChannelMb,
        },
      };
      return api(`/api/v1/servers/${serverId}/config`, {
        method: "PUT",
        body: JSON.stringify({ config: body }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["server-config", serverId] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["health", serverId] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  const saveMeta = useMutation({
    mutationFn: () =>
      api<ServerOut>(`/api/v1/servers/${serverId}`, {
        method: "PATCH",
        body: JSON.stringify({ display_name: displayName, is_active: isActive }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["servers"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const removeServer = useMutation({
    mutationFn: () => api(`/api/v1/servers/${serverId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["servers"] });
      navigate("/");
    },
  });

  function handleSaveAll() {
    saveMeta.mutate();
    saveConfig.mutate();
  }

  if (isLoading) {
    return (
      <div>
        <TopBar />
        <div className="flex items-center justify-center gap-2 py-24 text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> Carregando configuração…
        </div>
      </div>
    );
  }

  const pending = saveConfig.isPending || saveMeta.isPending;
  const name = server?.display_name || server?.hostname || `Servidor ${serverId}`;

  return (
    <div>
      <TopBar />
      <main className="mx-auto max-w-3xl px-6 py-6">
        <Link
          to={`/servers/${serverId}`}
          className="mb-4 inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Voltar ao servidor
        </Link>

        <h1 className="text-xl font-semibold text-slate-100">Configurar — {name}</h1>
        <p className="mt-1 text-xs text-slate-500">
          As mudanças são aplicadas pelo agente no próximo ciclo (a central sinaliza a
          nova versão da config).
        </p>

        <div className="mt-6 space-y-5">
          <Section title="Servidor">
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                label="Apelido"
                value={displayName}
                onChange={setDisplayName}
                placeholder={server?.hostname}
                hint="Nome amigável exibido no painel."
              />
              <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                  className="h-4 w-4 accent-status-ok"
                />
                Servidor ativo (recebe ingestão)
              </label>
            </div>
          </Section>

          <Section title="Coleta">
            <FormField
              label="Intervalo de coleta (segundos)"
              type="number"
              min={10}
              value={interval}
              onChange={(v) => setIntervalSec(numOr(v, 300))}
              hint="Frequência com que o agente coleta e envia (mínimo 10s)."
              className="max-w-xs"
            />
          </Section>

          <Section title="Operacional">
            <label className="mb-4 flex items-center gap-2 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={opEnabled}
                onChange={(e) => setOpEnabled(e.target.checked)}
                className="h-4 w-4 accent-status-ok"
              />
              Coletar pilar operacional
            </label>

            <TagInput
              label="Serviços críticos monitorados"
              values={services}
              onChange={setServices}
              placeholder="ex.: W3SVC"
              hint="O agente monitora só estes serviços; parado/ausente vira CRÍTICO. Remova os que não se aplicam (ex.: W3SVC numa máquina sem IIS)."
            />

            <div className="mt-5 grid gap-4 sm:grid-cols-3">
              {([
                ["CPU", "cpu"], ["Memória", "mem"], ["Disco", "disk"],
              ] as const).map(([label, key]) => (
                <div key={key} className="space-y-3">
                  <FormField
                    label={`${label} — aviso (%)`}
                    type="number" min={1} max={100}
                    value={th[`${key}_warn` as const]}
                    onChange={(v) => setTh((t) => ({ ...t, [`${key}_warn`]: numOr(v, 75) }))}
                  />
                  <FormField
                    label={`${label} — crítico (%)`}
                    type="number" min={1} max={100}
                    value={th[`${key}_crit` as const]}
                    onChange={(v) => setTh((t) => ({ ...t, [`${key}_crit`]: numOr(v, 90) }))}
                  />
                </div>
              ))}
            </div>
          </Section>

          <Section title="Backup">
            <label className="mb-4 flex items-center gap-2 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={bkEnabled}
                onChange={(e) => setBkEnabled(e.target.checked)}
                className="h-4 w-4 accent-status-ok"
              />
              Coletar pilar backup
            </label>

            <TagInput
              label="Caminhos monitorados"
              values={paths}
              onChange={setPaths}
              placeholder="ex.: D:\\Backups"
              hint="Pastas onde o agente procura os arquivos de backup neste servidor."
            />

            <div className="mt-5">
              <TagInput
                label="Extensões aceitas"
                values={extensions}
                onChange={setExtensions}
                placeholder="ex.: .zip"
                hint="Extensões consideradas como backup (ex.: .zip, .tar.gz, .dump)."
              />
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <FormField
                label="SLA — idade máxima (horas)"
                type="number" min={1}
                value={slaHours}
                onChange={(v) => setSlaHours(numOr(v, 24))}
                hint="Backup mais antigo que isso vira CRÍTICO (SLA estourado)."
              />
              <FormField
                label="Tamanho mínimo (MB)"
                type="number" min={1}
                value={minSizeMb}
                onChange={(v) => setMinSizeMb(numOr(v, 5))}
                hint="Backup menor que isso é suspeito (possível falha)."
              />
            </div>
          </Section>

          <Section title="Acesso">
            <label className="mb-4 flex items-center gap-2 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={acessoEnabled}
                onChange={(e) => setAcessoEnabled(e.target.checked)}
                className="h-4 w-4 accent-status-ok"
              />
              Coletar pilar acesso (logins, sudo, SSH/auditpol)
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                label="Limite de logins falhos"
                type="number" min={1}
                value={failedLoginTh}
                onChange={(v) => setFailedLoginTh(numOr(v, 10))}
                hint="Acima disso, vira AVISO."
              />
              <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={alertAccountChange}
                  onChange={(e) => setAlertAccountChange(e.target.checked)}
                  className="h-4 w-4 accent-status-ok"
                />
                Alertar em mudanças de conta
              </label>
            </div>
            <p className="mt-3 text-xs text-slate-600">
              Achados específicos (ex.: SSH, auditpol) você silencia direto na tabela
              de findings do servidor (botão "Ignorar").
            </p>
          </Section>

          <Section title="Logs">
            <label className="mb-4 flex items-center gap-2 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={logsEnabled}
                onChange={(e) => setLogsEnabled(e.target.checked)}
                className="h-4 w-4 accent-status-ok"
              />
              Coletar pilar logs (integridade/retenção de logs)
            </label>
            <div className="grid gap-4 sm:grid-cols-3">
              <FormField
                label="Idade máx. do log (h)"
                type="number" min={1}
                value={maxLogAge}
                onChange={(v) => setMaxLogAge(numOr(v, 24))}
                hint="Sem evento há mais que isso = AVISO."
              />
              <FormField
                label="Retenção mínima (rotações)"
                type="number" min={1}
                value={minRetention}
                onChange={(v) => setMinRetention(numOr(v, 90))}
                hint="logrotate abaixo disso = AVISO."
              />
              <FormField
                label="Tamanho mín. de canal (MB)"
                type="number" min={1}
                value={minChannelMb}
                onChange={(v) => setMinChannelMb(numOr(v, 256))}
                hint="Canal de log Windows menor = AVISO."
              />
            </div>
          </Section>

          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setShowDelete(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-status-crit/40 px-4 py-2 text-sm font-medium text-status-crit transition hover:bg-status-crit/10"
            >
              <Trash2 className="h-4 w-4" aria-hidden /> Apagar servidor
            </button>

            <div className="flex items-center gap-3">
              {saved && <span className="text-xs text-status-ok">Salvo ✓</span>}
              {(saveConfig.isError || saveMeta.isError) && (
                <span className="text-xs text-status-crit">Falha ao salvar</span>
              )}
              <button
                type="button"
                onClick={handleSaveAll}
                disabled={pending}
                className="inline-flex items-center gap-2 rounded-lg bg-status-ok/90 px-4 py-2 text-sm font-medium text-emerald-950 transition hover:bg-status-ok disabled:opacity-60"
              >
                {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                         : <Save className="h-4 w-4" aria-hidden />}
                Salvar
              </button>
            </div>
          </div>
        </div>
      </main>

      {showDelete && (
        <Modal
          title="Apagar servidor"
          onClose={() => setShowDelete(false)}
          footer={
            <>
              <button
                type="button"
                onClick={() => setShowDelete(false)}
                className="rounded-lg px-4 py-2 text-sm text-slate-300 hover:text-slate-100"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => removeServer.mutate()}
                disabled={removeServer.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-status-crit/90 px-4 py-2 text-sm font-medium text-white transition hover:bg-status-crit disabled:opacity-60"
              >
                {removeServer.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
                Apagar definitivamente
              </button>
            </>
          }
        >
          Isto remove <strong>{name}</strong> e todo o histórico de métricas dele.
          Esta ação não pode ser desfeita. O agente no servidor passará a receber 401
          (a menos que você o reinstale com um novo token).
        </Modal>
      )}
    </div>
  );
}
