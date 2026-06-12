import { useQuery } from "@tanstack/react-query";
import { api, getToken } from "../api/client";
import type { NotificationPage } from "../types";

// Poll central das notificações — React Query deduplica por queryKey, então
// Toaster e NotificationsBell compartilham a mesma chamada a cada 30s.
export function useNotificationsQuery() {
  return useQuery<NotificationPage>({
    queryKey: ["notifications"],
    queryFn: () => api<NotificationPage>("/api/v1/notifications?limit=50"),
    refetchInterval: 30_000,
    enabled: !!getToken(),
  });
}
