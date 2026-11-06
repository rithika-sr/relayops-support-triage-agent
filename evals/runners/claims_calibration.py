"""Score the claim checker (typed rules first, then the configured local verifier) on the claim sets.

Reports each split (dev: used to build the typed rules; validation: written before the verifier first ran) with
denominators: how many items typed rules decided, how many the model decided, how many it abstained on
(insufficient_evidence is a verdict, not an abstention; "unavailable" and "not_a_claim" are abstentions), and
the confusion matrix. Records the verifier identity and per-item claim and evidence hashes. Gold labels were
drafted with AI assistance; this is not human claim review.

    cd backend && uv run python ../evals/runners/claims_calibration.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from relayops.agents import claims
from relayops.domain.policies import entitlements_for

ROOT = Path(__file__).resolve().parents[1]
VERDICTS = ("supported", "contradicted", "insufficient_evidence")
COLS = (*VERDICTS, "unavailable", "not_a_claim")


def _h(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def summarize(rows: list[dict]) -> dict:
    confusion = {g: {v: sum(1 for r in rows if r["gold"] == g and r["verdict"] == v) for v in COLS} for g in VERDICTS}
    answered = [r for r in rows if r["verdict"] in VERDICTS]
    by_method: dict[str, dict[str, int]] = {}
    for r in rows:
        m = by_method.setdefault(r["method"], {"items": 0, "correct": 0})
        m["items"] += 1
        m["correct"] += r["gold"] == r["verdict"]
    contra = [r for r in rows if r["gold"] == "contradicted"]
    return {
        "items": len(rows),
        "answered": len(answered),
        "abstained": len(rows) - len(answered),
        "correct_on_answered": sum(r["gold"] == r["verdict"] for r in answered),
        "contradictions_caught": sum(r["verdict"] == "contradicted" for r in contra),
        "contradictions_total": len(contra),
        "false_supported": sum(1 for r in rows if r["verdict"] == "supported" and r["gold"] != "supported"),
        "false_contradicted": sum(1 for r in rows if r["verdict"] == "contradicted" and r["gold"] != "contradicted"),
        "by_method": by_method,
        "confusion": confusion,
    }


def main() -> int:
    items = [json.loads(x) for x in (ROOT / "datasets" / "claims_calibration.jsonl").read_text().splitlines() if x]
    provider, info = claims.verifier()
    ents = entitlements_for("business")
    rows = []
    for it in items:
        out = claims.check_reply(it["sentence"], entitlements=ents, spans=it["spans"], provider=provider)
        c = out[0]
        rows.append({"item_id": it["item_id"], "split": it["split"], "gold": it["gold"], "verdict": c.verdict,
                     "method": c.method, "evidence_ids": c.evidence_ids, "detail": c.detail[:200],
                     "claim_sha256": hashlib.sha256(it["sentence"].encode()).hexdigest(),
                     "evidence_sha256": _h(it["spans"])})
        print(f"{it['item_id']:13} {it['split']:10} gold={it['gold']:22} got={c.verdict:22} via {c.method}")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    splits = {s: summarize([r for r in rows if r["split"] == s]) for s in ("dev", "validation")}
    report = {"generated_at": stamp, "commit": commit, "verifier": info,
              "dataset": {"file": "evals/datasets/claims_calibration.jsonl", "sha256": _h(items),
                          "labels": items[0]["labeled_by"] if items else None,
                          "dev": "claims_v1: used while building the typed rules (not held out)",
                          "validation": "claims_v1_val: written before the verifier first ran; not used for tuning"},
              "splits": splits, "rows": rows}
    out_dir = ROOT / "results"
    name = f"claims-{stamp}" + ("" if info.get("kind") == "local_model" else f"-{info.get('kind')}")
    (out_dir / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")
    md = [f"# Claim checker calibration ({stamp})", "",
          f"Commit `{commit[:12]}`. Verifier: `{json.dumps(info)}`.",
          f"Labels: {report['dataset']['labels']}. This is not human claim review.", ""]
    for s, sm in splits.items():
        md += [f"## {s} ({report['dataset'][s]})", "",
               f"{sm['items']} items; answered {sm['answered']}, abstained {sm['abstained']} "
               f"(unavailable or not a claim); correct on answered {sm['correct_on_answered']}/{sm['answered']}; "
               f"contradictions caught {sm['contradictions_caught']}/{sm['contradictions_total']}; "
               f"false supported {sm['false_supported']}; false contradicted {sm['false_contradicted']}.", "",
               "| method | items | correct |", "| --- | --- | --- |"]
        md += [f"| {m} | {v['items']} | {v['correct']} |" for m, v in sorted(sm["by_method"].items())]
        md += ["", "| gold \\ got | " + " | ".join(COLS) + " |", "|---" * (len(COLS) + 1) + "|"]
        md += [f"| {g} | " + " | ".join(str(sm["confusion"][g][v]) for v in COLS) + " |" for g in VERDICTS]
        md += [""]
    (out_dir / f"{name}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({s: {k: v for k, v in sm.items() if k != "confusion"} for s, sm in splits.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
