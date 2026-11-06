"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui";
import { countdown } from "@/lib/format";
import type { Target } from "@/lib/types";

export function TargetBadge({ target }: { target?: Target }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  if (!target || target.state === "none") return <Badge>no target</Badge>;
  if (target.state === "met") return <Badge tone="ok">responded in target</Badge>;
  if (target.state === "missed") return <Badge tone="danger">responded late</Badge>;
  const secs = target.due_at ? (new Date(target.due_at).getTime() - now) / 1000 : 0;
  const tone = secs < 0 ? "danger" : secs < 4 * 3600 ? "amber" : "neutral";
  return (
    <Badge tone={tone} title={`${target.policy.hours}h first-response target (${target.policy.basis}), policy ${target.policy.policy_version}`}>
      {countdown(target.due_at, now)}
    </Badge>
  );
}
