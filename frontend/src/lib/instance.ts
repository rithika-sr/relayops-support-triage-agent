"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface InstanceInfo {
  data_mode: "operational" | "demo" | "test";
  banner: string | null;
}

/** The server decides the data mode; the browser only displays it. */
export function useInstance() {
  return useQuery({ queryKey: ["instance"], queryFn: () => api.get<InstanceInfo>("/instance"), staleTime: 300_000 });
}
