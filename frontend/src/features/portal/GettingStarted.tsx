"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";

export interface Onboarding { steps: { id: string; label: string; done: boolean; at: string | null; basis: string }[]; completed: number; total: number }

export function OnboardingList({ data }: { data: Onboarding }) {
  return (
    <ol className="flex flex-col gap-1.5 text-sm">
      {data.steps.map((s) => (
        <li key={s.id} className="flex items-center gap-2" title={s.basis}>
          <span aria-hidden className={s.done ? "text-ok-700" : "text-muted"}>{s.done ? "✓" : "○"}</span>
          <span className={s.done ? "" : "text-muted"}>{s.label}</span>
          <span className="sr-only">{s.done ? "done" : "not yet"}</span>
        </li>
      ))}
    </ol>
  );
}

export function GettingStarted() {
  const q = useQuery({ queryKey: ["portal-onboarding"], queryFn: () => api.get<Onboarding>("/portal/onboarding") });
  if (!q.data || q.data.completed === q.data.total) return null;
  return (
    <Card title={`Getting started · ${q.data.completed} of ${q.data.total}`}>
      <OnboardingList data={q.data} />
    </Card>
  );
}
