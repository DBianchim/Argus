import { useMemo, useState } from "react";
import type { ServerOverview } from "../types";
import { STATUS_RANK } from "../utils";

export type OsFilter = "all" | "windows" | "linux";
export type PilarFilter = "all" | "operacional" | "backup" | "acesso" | "logs";

/** Filtro SO/pilar + ordenação por severidade — compartilhado entre Dashboard e Servidores. */
export function useServerFilters(servers: ServerOverview[]) {
  const [os, setOs] = useState<OsFilter>("all");
  const [pilar, setPilar] = useState<PilarFilter>("all");

  const filtered = useMemo(() => {
    return servers
      .filter(
        (s) =>
          (os === "all" || s.os_family === os) &&
          (pilar === "all" || (s.pilar_statuses[pilar] ?? "unknown") !== "ok"),
      )
      .sort(
        (a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || a.hostname.localeCompare(b.hostname),
      );
  }, [servers, os, pilar]);

  return { os, setOs, pilar, setPilar, filtered };
}
