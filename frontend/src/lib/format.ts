export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtDateUTC(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function relative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(diff);
  const units: [number, string][] = [
    [86400, "d"],
    [3600, "h"],
    [60, "m"],
  ];
  for (const [secs, label] of units) {
    if (abs >= secs) {
      const n = Math.floor(abs / secs);
      return diff < 0 ? `${n}${label} ago` : `in ${n}${label}`;
    }
  }
  return diff < 0 ? "just now" : "in <1m";
}

/** Countdown text for a response target, e.g. "3h 12m left" or "breached 2h ago". */
export function countdown(dueIso: string | null | undefined, now: number = Date.now()): string {
  if (!dueIso) return "no target";
  const secs = Math.round((new Date(dueIso).getTime() - now) / 1000);
  const abs = Math.abs(secs);
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const span = h > 0 ? `${h}h ${m}m` : `${m}m`;
  return secs >= 0 ? `${span} left` : `breached ${span} ago`;
}

export function label(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ");
}

export function shortHash(h: string | null | undefined): string {
  return h ? h.slice(0, 10) : "—";
}
