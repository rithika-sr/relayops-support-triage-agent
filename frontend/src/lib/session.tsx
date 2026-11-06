"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { api, ApiError } from "@/lib/api";
import type { Me, Role } from "@/lib/types";

export function useMe() {
  return useQuery<Me, ApiError>({
    queryKey: ["me"],
    queryFn: () => api.get<Me>("/auth/me"),
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
    staleTime: 60_000,
  });
}

/** Client-side routing guard. The API enforces authorization; this only picks the right screen. */
export function useRequireRole(roles: Role[]) {
  const me = useMe();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) {
      router.replace(`/login?next=${encodeURIComponent(path)}`);
    } else if (me.data && !roles.includes(me.data.role)) {
      router.replace(me.data.role === "customer" ? "/portal" : "/app");
    }
  }, [me.data, me.error, path, roles, router]);
  return me;
}

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      qc.clear();
      router.replace("/login");
    }
  };
}
