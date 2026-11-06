"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Field, Input, Loading, Notice, PageHeader, Select, Textarea, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useMe } from "@/lib/session";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DAY_NAMES: Record<string, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

interface Version { id: string; ref: string; version: number; timezone: string; weekly: Record<string, [string, string][]>; holidays: string[]; applies_to_urgent: boolean; active: boolean; created_at: string }
interface Listing { active: string | null; versions: Version[]; zones: string[] }
interface Preview { calendar: string | null; due_at: string; due_local?: string; basis: string }

type Hours = Record<string, { open: boolean; start: string; end: string }>;

function initialHours(v?: Version): Hours {
  return Object.fromEntries(DAYS.map((d) => {
    const w = v?.weekly[d]?.[0];
    return [d, { open: v ? !!w : !["sat", "sun"].includes(d), start: w?.[0] ?? "09:00", end: w?.[1] ?? "17:00" }];
  }));
}

export function CalendarsPage() {
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["calendars"], queryFn: () => api.get<Listing>("/settings/calendars") });
  const current = q.data?.versions.find((v) => v.active);
  const [tz, setTz] = useState<string | null>(null);
  const [hours, setHours] = useState<Hours | null>(null);
  const [holidays, setHolidays] = useState<string | null>(null);
  const [urgent, setUrgent] = useState<boolean | null>(null);
  const h = hours ?? initialHours(current);
  const zone = tz ?? current?.timezone ?? "America/New_York";
  const holidayText = holidays ?? (current?.holidays ?? []).join("\n");

  const save = useMutation<Version, ApiError>({
    mutationFn: () => api.post("/settings/calendars", {
      timezone: zone,
      weekly: Object.fromEntries(DAYS.filter((d) => h[d].open).map((d) => [d, [[h[d].start, h[d].end]]])),
      holidays: holidayText.split(/\s+/).filter(Boolean),
      applies_to_urgent: urgent ?? current?.applies_to_urgent ?? false,
    }),
    onSuccess: (v) => { toast(`Saved ${v.ref}. New tickets use it; existing tickets keep their targets.`); setHours(null); setTz(null); setHolidays(null); setUrgent(null); qc.invalidateQueries({ queryKey: ["calendars"] }); },
  });
  const off = useMutation<unknown, ApiError>({
    mutationFn: () => api.post("/settings/calendars/deactivate", {}),
    onSuccess: () => { toast("Targets are 24/7 again for new tickets."); qc.invalidateQueries({ queryKey: ["calendars"] }); },
  });
  const [start, setStart] = useState("");
  const [prevHours, setPrevHours] = useState("4");
  const preview = useMutation<Preview, ApiError>({
    mutationFn: () => api.post("/settings/calendars/preview", { start: new Date(start).toISOString(), hours: Number(prevHours) }),
  });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const data = q.data!;

  return (
    <div>
      <PageHeader title="Service hours" subtitle="First-response targets count only service hours in this time zone. Without a calendar, targets are 24/7." crumbs={[{ label: "Settings", href: "/app/settings" }, { label: "Service hours" }]} />
      <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
        <Card title={current ? <span className="flex items-center gap-2">Calendar <Badge tone="ok">{current.ref} active</Badge></span> : "Calendar"}>
          {!isAdmin ? <Notice>Only admins can change service hours.</Notice> : null}
          <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <Field id="tz" label="Time zone" hint="IANA name. Windows stay in local time across daylight-saving changes.">
              <Select id="tz" value={zone} onChange={(e) => setTz(e.target.value)} disabled={!isAdmin}>
                {data.zones.map((z) => <option key={z}>{z}</option>)}
              </Select>
            </Field>
            <fieldset className="flex flex-col gap-2" disabled={!isAdmin}>
              <legend className="mb-1 text-sm font-medium">Weekly hours</legend>
              {DAYS.map((d) => (
                <div key={d} className="flex flex-wrap items-center gap-2 text-sm">
                  <label className="flex w-32 items-center gap-2">
                    <input type="checkbox" checked={h[d].open} onChange={(e) => setHours({ ...h, [d]: { ...h[d], open: e.target.checked } })} />
                    {DAY_NAMES[d]}
                  </label>
                  {h[d].open ? (
                    <>
                      <Input aria-label={`${DAY_NAMES[d]} opens`} type="time" value={h[d].start} onChange={(e) => setHours({ ...h, [d]: { ...h[d], start: e.target.value } })} className="w-32" />
                      <span className="text-muted">to</span>
                      <Input aria-label={`${DAY_NAMES[d]} closes`} type="time" value={h[d].end} onChange={(e) => setHours({ ...h, [d]: { ...h[d], end: e.target.value } })} className="w-32" />
                    </>
                  ) : <span className="text-muted">closed</span>}
                </div>
              ))}
            </fieldset>
            <Field id="holidays" label="Holidays" hint="One date per line, YYYY-MM-DD, in the calendar's local time.">
              <Textarea id="holidays" value={holidayText} onChange={(e) => setHolidays(e.target.value)} readOnly={!isAdmin} className="min-h-20 font-mono text-[13px]" />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={urgent ?? current?.applies_to_urgent ?? false} onChange={(e) => setUrgent(e.target.checked)} disabled={!isAdmin} />
              Apply to urgent tickets too (otherwise urgent targets stay 24/7)
            </label>
            {save.error ? <Notice tone="danger">{save.error.detail}</Notice> : null}
            {isAdmin ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" type="submit" busy={save.isPending}>Save as version {(data.versions[0]?.version ?? 0) + 1}</Button>
                {current ? <Button variant="danger" type="button" busy={off.isPending} onClick={() => off.mutate()}>Use 24/7 targets</Button> : null}
              </div>
            ) : null}
          </form>
        </Card>
        <div className="flex flex-col gap-5">
          <Card title="Check a due time">
            <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); preview.mutate(); }}>
              <Field id="pv-start" label="Ticket received (your local time)"><Input id="pv-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required /></Field>
              <Field id="pv-hours" label="Target hours"><Input id="pv-hours" type="number" min="0.25" step="0.25" value={prevHours} onChange={(e) => setPrevHours(e.target.value)} /></Field>
              <Button type="submit" busy={preview.isPending}>Calculate</Button>
              {preview.data ? (
                <p className="text-sm">Due <span className="font-medium">{fmtDate(preview.data.due_at)}</span>{preview.data.due_local ? ` (${preview.data.due_local.slice(0, 16).replace("T", " ")} ${current?.timezone})` : ""} · {preview.data.basis}{preview.data.calendar ? `, ${preview.data.calendar}` : ""}</p>
              ) : null}
              {preview.error ? <Notice tone="danger">{preview.error.detail}</Notice> : null}
            </form>
          </Card>
          <Card title="Versions">
            {!data.versions.length ? <Empty title="No calendar yet">Targets are 24/7 elapsed hours.</Empty> : (
              <ul className="divide-y divide-line text-sm">
                {data.versions.map((v) => (
                  <li key={v.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span><span className="font-medium">{v.ref}</span> <span className="text-muted">{v.timezone}</span></span>
                    <span className="text-muted">{v.active ? <Badge tone="ok">active</Badge> : null} {fmtDate(v.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-muted">Versions are never edited. Each ticket records the version that set its target.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
