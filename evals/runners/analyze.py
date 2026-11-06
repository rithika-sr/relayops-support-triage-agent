"""Markdown tables from a recorded evaluation (a report JSON or a progress JSONL), computed only from executed rows.

    python3 evals/runners/analyze.py evals/results/full-<tag>.json [--label "run 1 @ 9ba4ddb"]

Prints route accuracy with a Wilson 95% interval per system, per slice and category, latency p50/p95, model and
tool calls, and the most common wrong routes. Errors count as wrong and are shown separately.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def wilson(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{max(0, c - h):.2f}–{min(1, c + h):.2f}"


def pct(xs: list[float], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def load(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(x) for x in path.read_text().splitlines() if x]
    return [c for c in json.loads(path.read_text())["cases"] if c.get("split") != "challenge"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    rows = load(Path(a.path))
    systems = list(dict.fromkeys(r["system"] for r in rows))
    out = [f"### {a.label or Path(a.path).name}", "",
           "| System | Slice | Cases | Route correct | 95% interval | Errors | Latency p50 / p95 (s) | Model calls (mean) |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in systems:
        for sl in ("main", "hard_v1"):
            x = [r for r in rows if r["system"] == s and r.get("slice", "main") == sl]
            if not x:
                continue
            k = sum(bool(r["route_correct"]) for r in x)
            lat = [r["latency_ms"] / 1000 for r in x if r.get("latency_ms") is not None]
            mc = [r["model_calls"] for r in x if r.get("model_calls") is not None]
            p50, p95 = pct(lat, 0.5), pct(lat, 0.95)
            out.append(f"| {s} | {sl} | {len(x)} | {k}/{len(x)} ({k / len(x):.2f}) | {wilson(k, len(x))} | "
                       f"{sum(r['status'] == 'error' for r in x)} | "
                       f"{p50:.1f} / {p95:.1f} | {sum(mc) / len(mc):.1f} |" if lat and mc else
                       f"| {s} | {sl} | {len(x)} | {k}/{len(x)} | {wilson(k, len(x))} | "
                       f"{sum(r['status'] == 'error' for r in x)} | n/a | n/a |")
    cats = sorted({(r.get("slice", "main"), r["category"]) for r in rows})
    out += ["", "| Slice / category | " + " | ".join(systems) + " |", "| --- |" + " --- |" * len(systems)]
    for sl, cat in cats:
        cells = []
        for s in systems:
            x = [r for r in rows if r["system"] == s and r.get("slice", "main") == sl and r["category"] == cat]
            cells.append(f"{sum(bool(r['route_correct']) for r in x)}/{len(x)}" if x else "–")
        out.append(f"| {sl} / {cat} | " + " | ".join(cells) + " |")
    out += ["", "Most common wrong routes (expected → actual):", ""]
    for s in systems:
        c = Counter((r["expected_route"], r["actual_route"]) for r in rows if r["system"] == s and not r["route_correct"])
        top = ", ".join(f"{e} → {g} ({n})" for (e, g), n in c.most_common(4)) or "none"
        out.append(f"- **{s}**: {top}")
    by_split = defaultdict(int)
    for r in rows:
        by_split[(r["system"], r["split"])] += 1
    out += ["", "Executed pairs by split: " + ", ".join(f"{s}/{sp} {n}" for (s, sp), n in sorted(by_split.items()))]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
