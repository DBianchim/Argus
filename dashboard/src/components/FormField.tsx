// Campo de formulário (label + input) no tema NOC.

interface Props {
  label: string;
  type?: string;
  value: string | number;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  min?: number;
  max?: number;
  className?: string;
  /** Fontes técnicas (host/IP, números, senhas) usam mono; texto humano usa sans. */
  mono?: boolean;
}

export function FormField({
  label, type = "text", value, onChange, placeholder, hint, min, max, className, mono,
}: Props) {
  return (
    <label className={`block font-plex-sans ${className ?? ""}`}>
      <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">
        {label}
      </span>
      <input
        type={type}
        value={value}
        min={min}
        max={max}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1.5 w-full rounded-md border border-[#272c3a] bg-[#12151d] px-3 py-2 text-[13px] text-[#e2e6f0] outline-none focus:border-blue-500 ${mono ? "font-plex-mono" : "font-plex-sans"}`}
      />
      {hint && <span className="mt-1 block text-[10.5px] text-[#5b6274]">{hint}</span>}
    </label>
  );
}
