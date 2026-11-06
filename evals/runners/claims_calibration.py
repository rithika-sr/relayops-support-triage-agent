"""Score the claim checker (typed rules, then the configured local verifier) on claims_v1.

Writes evals/results/claims-<stamp>.json and .md with the confusion matrix, the method used per item,
and the model identity. Typed rules run first, exactly as in production. Unavailable verdicts are counted
separately, never as correct.

    cd backend && uv run python ../evals/runners/claims_calibration.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from relayops.agents import claims
from relayops.domain.policies import entitlements_for

ROOT = Path(__file__).resolve().parents[1]
VERDICTS = ("supported", "contradicted", "insufficient_evidence")


def main() -> None:
    items = [json.loads(x) for x in (ROOT / "datasets" / "claims_calibration.jsonl").read_text().splitlines() if x]
    provider, info = claims.verifier()
    ents = entitlements_for("business")
    rows = []
    for it in items:
        out = claims.check_reply(it["sentence"], entitlements=ents, spans=it["spans"], provider=provider)
        c = out[0]
        rows.append({"item_id": it["item_id"], "gold": it["gold"], "verdict": c.verdict, "method": c.method,
                     "evidence_ids": c.evidence_ids, "detail": c.detail})
        print(f"{it['item_id']} gold={it['gold']:<22} got={c.verdict:<22} via {c.method}")
    confusion = {g: {v: sum(1 for r in rows if r["gold"] == g and r["verdict"] == v)
                     for v in (*VERDICTS, "unavailable", "not_a_claim")} for g in VERDICTS}
    answered = [r for r in rows if r["verdict"] in VERDICTS]
    summary = {
        "items": len(rows), "answered": len(answered),
        "accuracy_on_answered": round(sum(r["gold"] == r["verdict"] for r in answered) / len(answered), 3) if answered else None,
        "contradiction_recall": round(confusion["contradicted"]["contradicted"] / max(1, sum(confusion["contradicted"].values())), 3),
        "false_supported": sum(1 for r in rows if r["verdict"] == "supported" and r["gold"] != "supported"),
        "by_method": {m: sum(1 for r in rows if r["method"] == m) for m in {r["method"] for r in rows}},
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    report = {"dataset": "claims_v1 (author-labeled, synthetic, 28 items; development set, not held out)", "verifier": info, "summary": summary,
              "confusion": confusion, "rows": rows, "generated_at": stamp}
    out_dir = ROOT / "results"
    (out_dir / f"claims-{stamp}.json").write_text(json.dumps(report, indent=2) + "\n")
    md = [f"# Claim verifier calibration ({stamp})", "", f"Verifier: `{json.dumps(info)}`",
          "Dataset: claims_v1, 28 author-labeled synthetic items. Small, and used while developing the typed rules (not held out); read as a sanity check, not a general rate.", "",
          "| gold \\ got | " + " | ".join((*VERDICTS, "unavailable")) + " |", "|---" * 5 + "|"]
    md += [f"| {g} | " + " | ".join(str(confusion[g][v]) for v in (*VERDICTS, "unavailable")) + " |" for g in VERDICTS]
    md += ["", "```json", json.dumps(summary, indent=2), "```"]
    (out_dir / f"claims-{stamp}.md").write_text("\n".join(md) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
