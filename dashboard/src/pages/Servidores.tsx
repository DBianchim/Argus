import { useQuery } from "@tanstack/react-query";
import { Loader2, ServerOff } from "lucide-react";
import { api } from "../api/client";
import { ServerCard } from "../components/ServerCard";
import { ServerFilterChips } from "../components/ServerFilterChips";
import { Sidebar } from "../components/Sidebar";
import { useServerFilters } from "../hooks/useServerFilters";
import type { OverviewOut } from "../types";

export function Servidores() {
  const { data, isLoading } = useQuery<OverviewOut>({
    queryKey: ["overview"],
    queryFn: () => api<OverviewOut>("/api/v1/overview"),
    refetchInterval: 30_000,
  });

  const servers = data?.servers ?? [];
  const { os, setOs, pilar, setPilar, filtered: filteredServers } = useServerFilters(servers);

  return (
    <div className="flex h-screen bg-[#0a0c11] font-plex-sans text-[#e2e6f0]">
      <Sidebar alertCounts={{ crit: data?.kpis.crit ?? 0, warn: data?.kpis.warn ?? 0 }} />
      <main className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-[26px] py-[22px]">
        {isLoading || !data ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-[#5b6274]">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            Carregando a frota…
          </div>
        ) : data.servers.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-[#5b6274]">
            <ServerOff className="h-8 w-8" aria-hidden />
            <p className="text-sm">Nenhum servidor registrado ainda.</p>
            <p className="font-plex-mono text-xs">
              Registre com: <span className="text-[#8b93a7]">python manage.py create-server</span>
            </p>
          </div>
        ) : (
          <>
            <h1 className="m-0 text-[19px] font-semibold tracking-[-0.01em] text-[#e2e6f0]">
              Servidores
            </h1>

            <div className="flex flex-wrap items-center gap-2">
              <ServerFilterChips os={os} setOs={setOs} pilar={pilar} setPilar={setPilar} />
              <span className="ml-auto font-plex-mono text-[11.5px] text-[#5b6274]">
                {filteredServers.length} de {servers.length} servidores
              </span>
            </div>

            {filteredServers.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#272c3a] p-12 text-center text-[13px] text-[#5b6274]">
                Nenhum servidor corresponde aos filtros.{" "}
                <button
                  type="button"
                  onClick={() => {
                    setOs("all");
                    setPilar("all");
                  }}
                  className="text-blue-400 hover:underline"
                >
                  Limpar filtros
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(295px,1fr))] gap-3">
                {filteredServers.map((s) => (
                  <ServerCard key={s.id} server={s} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
