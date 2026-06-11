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

export function FindingsTable({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <p className="py-4 text-sm text-slate-500">Nenhum achado coletado.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
            <th className="py-2 pr-4 font-medium">Item</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Detalhe</th>
            <th className="py-2 font-medium">Valor</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding, index) => (
            <tr key={index} className="border-b border-surface-border/50">
              <td className="py-2 pr-4 font-mono text-xs text-slate-300">
                {finding.item ?? "—"}
              </td>
              <td className="py-2 pr-4">
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    FINDING_STYLE[finding.status ?? "info"]
                  }`}
                >
                  {finding.status ?? "info"}
                </span>
              </td>
              <td className="max-w-md py-2 pr-4 text-xs text-slate-400">
                {finding.detail || "—"}
              </td>
              <td className="max-w-xs truncate py-2 font-mono text-[11px] text-slate-500">
                {formatValue(finding.value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
