import { Eye, EyeOff } from "lucide-react";
import type { Finding } from "../types";

const FINDING_STYLE: Record<string, string> = {
  ok: "bg-status-ok/15 text-status-ok",
  warning: "bg-status-warn/15 text-status-warn",
  error: "bg-status-crit/15 text-status-crit",
  info: "bg-slate-500/15 text-slate-400",
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

interface Props {
  findings: Finding[];
  // Quando fornecidos, habilita ignorar/reativar achados por servidor.
  ignored?: Set<string>;
  onToggle?: (item: string) => void;
  busy?: boolean;
}

export function FindingsTable({ findings, ignored, onToggle, busy }: Props) {
  if (findings.length === 0) {
    return <p className="py-4 text-sm text-slate-500">Nenhum achado coletado.</p>;
  }
  const canToggle = typeof onToggle === "function";

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
            <th className="py-2 pr-4 font-medium">Item</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Detalhe</th>
            <th className="py-2 pr-4 font-medium">Valor</th>
            {canToggle && <th className="py-2 font-medium text-right">Ação</th>}
          </tr>
        </thead>
        <tbody>
          {findings.map((finding, index) => {
            const item = finding.item ?? "—";
            const isIgnored = ignored?.has(item) ?? false;
            return (
              <tr
                key={index}
                className={`border-b border-surface-border/50 ${isIgnored ? "opacity-40" : ""}`}
              >
                <td className="py-2 pr-4 font-mono text-xs text-slate-300">{item}</td>
                <td className="py-2 pr-4">
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      isIgnored ? "bg-slate-500/15 text-slate-400" : FINDING_STYLE[finding.status ?? "info"]
                    }`}
                  >
                    {isIgnored ? "ignorado" : finding.status ?? "info"}
                  </span>
                </td>
                <td className="max-w-md py-2 pr-4 text-xs text-slate-400">
                  {finding.detail || "—"}
                </td>
                <td className="max-w-xs truncate py-2 pr-4 font-mono text-[11px] text-slate-500">
                  {formatValue(finding.value)}
                </td>
                {canToggle && (
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onToggle!(item)}
                      title={isIgnored ? "Voltar a alertar" : "Ignorar este achado neste servidor"}
                      className="inline-flex items-center gap-1 text-xs text-slate-500 transition hover:text-slate-200 disabled:opacity-50"
                    >
                      {isIgnored
                        ? <><Eye className="h-3.5 w-3.5" aria-hidden /> Reativar</>
                        : <><EyeOff className="h-3.5 w-3.5" aria-hidden /> Ignorar</>}
                    </button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
