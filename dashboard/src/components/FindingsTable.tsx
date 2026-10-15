import { Eye, EyeOff } from "lucide-react";
import type { Finding } from "../types";

const FINDING_STYLE: Record<string, string> = {
  ok: "bg-status-ok/[.12] text-emerald-400",
  warning: "bg-status-warn/[.12] text-amber-400",
  error: "bg-status-crit/[.14] text-red-400",
  info: "bg-status-offline/[.14] text-[#8b93a7]",
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
    return <p className="py-4 font-plex-sans text-sm text-[#5b6274]">Nenhum achado coletado.</p>;
  }
  const canToggle = typeof onToggle === "function";

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left font-plex-sans text-sm">
        <thead>
          <tr className="border-b border-[#232836] text-[10.5px] font-semibold uppercase tracking-wide text-[#5b6274]">
            <th className="py-2 pr-4 font-semibold">Item</th>
            <th className="py-2 pr-4 font-semibold">Status</th>
            <th className="py-2 pr-4 font-semibold">Detalhe</th>
            <th className="py-2 pr-4 font-semibold">Valor</th>
            {canToggle && <th className="py-2 text-right font-semibold">Ação</th>}
          </tr>
        </thead>
        <tbody>
          {findings.map((finding, index) => {
            const item = finding.item ?? "—";
            const isIgnored = ignored?.has(item) ?? false;
            return (
              <tr
                key={index}
                className={`border-b border-[#1f2432] ${isIgnored ? "opacity-40" : ""}`}
              >
                <td className="py-2 pr-4 font-plex-mono text-xs text-[#c6cddc]">{item}</td>
                <td className="py-2 pr-4">
                  <span
                    className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                      isIgnored ? "bg-status-offline/[.14] text-[#8b93a7]" : FINDING_STYLE[finding.status ?? "info"]
                    }`}
                  >
                    {isIgnored ? "ignorado" : finding.status ?? "info"}
                  </span>
                </td>
                <td className="max-w-md py-2 pr-4 text-xs text-[#8b93a7]">
                  {finding.detail || "—"}
                </td>
                <td className="max-w-xs truncate py-2 pr-4 font-plex-mono text-[11px] text-[#5b6274]">
                  {formatValue(finding.value)}
                </td>
                {canToggle && (
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onToggle!(item)}
                      title={isIgnored ? "Voltar a alertar" : "Ignorar este achado neste servidor"}
                      className="inline-flex items-center gap-1 text-xs text-[#5b6274] transition hover:text-[#c6cddc] disabled:opacity-50"
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
