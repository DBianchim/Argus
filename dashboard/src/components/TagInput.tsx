// Editor de lista de strings (ex.: serviços críticos, caminhos de backup).
// Enter ou vírgula adiciona; X remove. Tema NOC.

import { X } from "lucide-react";
import { useState } from "react";

interface Props {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  hint?: string;
}

export function TagInput({ label, values, onChange, placeholder, hint }: Props) {
  const [draft, setDraft] = useState("");

  function add() {
    const v = draft.trim();
    if (v && !values.includes(v)) {
      onChange([...values, v]);
    }
    setDraft("");
  }

  function remove(value: string) {
    onChange(values.filter((v) => v !== value));
  }

  return (
    <div>
      <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
        {label}
      </span>
      <div className="mt-1.5 flex flex-wrap gap-2 rounded-lg border border-surface-border bg-surface p-2">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded-md bg-surface-border px-2 py-1 text-xs text-slate-200"
          >
            {v}
            <button
              type="button"
              onClick={() => remove(v)}
              className="text-slate-500 hover:text-status-crit"
              aria-label={`Remover ${v}`}
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            }
          }}
          onBlur={add}
          placeholder={placeholder ?? "Adicionar…"}
          className="min-w-[8rem] flex-1 bg-transparent px-1 py-1 text-sm text-slate-100 outline-none placeholder:text-slate-600"
        />
      </div>
      {hint && <span className="mt-1 block text-xs text-slate-600">{hint}</span>}
    </div>
  );
}
