import type { OsFilter, PilarFilter } from "../hooks/useServerFilters";

const OS_CHIPS: { value: OsFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "windows", label: "Windows" },
  { value: "linux", label: "Linux" },
];

const PILAR_CHIPS: { value: PilarFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "operacional", label: "Operacional" },
  { value: "backup", label: "Backup" },
  { value: "acesso", label: "Acesso" },
  { value: "logs", label: "Logs" },
];

function chipClass(active: boolean): string {
  return `rounded-md border px-3.5 py-[5px] font-plex-sans text-[12.5px] font-medium transition-colors hover:border-blue-500 ${
    active
      ? "border-blue-500/50 bg-blue-500/[.16] text-[#93bbfd]"
      : "border-[#272c3a] bg-[#1a1d27] text-[#8b93a7]"
  }`;
}

/** Chips SO/pilar — o pai deve envolver em `flex flex-wrap items-center gap-2`. */
export function ServerFilterChips({
  os,
  setOs,
  pilar,
  setPilar,
}: {
  os: OsFilter;
  setOs: (v: OsFilter) => void;
  pilar: PilarFilter;
  setPilar: (v: PilarFilter) => void;
}) {
  return (
    <>
      <span className="text-[11px] font-medium tracking-[0.06em] text-[#5b6274]">SO</span>
      {OS_CHIPS.map((c) => (
        <button key={c.value} type="button" onClick={() => setOs(c.value)} className={chipClass(os === c.value)}>
          {c.label}
        </button>
      ))}
      <span className="mx-1.5 h-[18px] w-px bg-[#272c3a]" />
      <span className="text-[11px] font-medium tracking-[0.06em] text-[#5b6274]">PILAR</span>
      {PILAR_CHIPS.map((c) => (
        <button key={c.value} type="button" onClick={() => setPilar(c.value)} className={chipClass(pilar === c.value)}>
          {c.label}
        </button>
      ))}
    </>
  );
}
