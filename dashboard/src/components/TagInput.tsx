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
    <div className="font-plex-sans">
      <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">
        {label}
      </span>
      <div className="mt-1.5 flex flex-wrap gap-2 rounded-md border border-[#272c3a] bg-[#12151d] p-2">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-1 font-plex-mono text-xs text-[#93bbfd]"
          >
            {v}
            <button
              type="button"
              onClick={() => remove(v)}
              className="text-[#5b6274] hover:text-status-crit"
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
          className="min-w-[8rem] flex-1 bg-transparent px-1 py-1 font-plex-mono text-sm text-[#e2e6f0] outline-none placeholder:text-[#3b4254]"
        />
      </div>
      {hint && <span className="mt-1 block text-[10.5px] text-[#5b6274]">{hint}</span>}
    </div>
  );
}
