"""Write docs/screenshots.md from the images that actually exist in docs/images.

Each screen gets a caption, its data source, and links to every captured width. Images that are missing are
listed as missing, never linked.

    python3 scripts/build_gallery.py [--compress]   (run with the backend venv for Pillow)
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
WIDTHS = (1440, 1280, 768, 390)
DEMO = "Demo instance (synthetic sample data; the banner is part of the capture)"
OPERATIONAL = "Scratch operational instance, newly registered organization (no sample data)"

SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Support", [
        ("home", "Home: queues that need attention now, with counts computed from tickets and drafts.", DEMO),
        ("inbox", "Inbox: queues, URL filters, sorting, saved views, assignment, and bulk status changes.", DEMO),
        ("ticket", "Ticket: the conversation first, then account context, target, runs, and actions.", DEMO),
    ]),
    ("Investigation and review", [
        ("investigation", "Investigation summary: progress through the graph, route, and the draft under review.", DEMO),
        ("investigation-evidence", "Evidence tab: every source with visibility, version, and hashes.", DEMO),
        ("review", "Review status: sources, policy, claim support (typed rules and a model estimate), and human approval shown separately.", DEMO),
    ]),
    ("Customers", [
        ("portal", "Customer portal: the account's own tickets, Getting started, and Help articles.", DEMO),
        ("portal-help", "Portal Help: search current public articles; contact support with the context carried over.", DEMO),
    ]),
    ("Customer Success and analytics", [
        ("success-accounts", "Accounts: per-account counts and separate friction signals (sample tickets predate event tracking, so activity is honestly zero).", DEMO),
        ("success-retention", "Retention: weekly cohorts; weeks not yet reachable show pending, not 0%.", DEMO),
        ("success-opportunities", "Opportunities: rule-based cards with their evidence, or an empty state when no rule is met.", DEMO),
        ("success-experiments", "Experiments: Help-ranking experiments with pre-registered minimums.", DEMO),
        ("analytics", "Operations analytics: counts only the instance's own data class and says what was excluded.", DEMO),
    ]),
    ("Engineering and knowledge", [
        ("incidents", "Incidents and candidate constellations from ticket signatures.", DEMO),
        ("engineering", "Engineering board: issues, handoffs, and ownership.", DEMO),
        ("knowledge", "Knowledge library with versions, visibility, and retrieval inspection.", DEMO),
        ("knowledge-pdf", "A scanned PDF read by OCR; the version records how each page was read.", DEMO),
        ("playbooks", "Typed playbooks with revisions.", DEMO),
        ("artifacts", "Drafts and exports: immutable versions with hashes, exportable as Markdown, JSON, or PDF.", DEMO),
        ("evaluations", "Model quality: imported evaluation reports with denominators.", DEMO),
    ]),
    ("Settings and integrations", [
        ("settings", "Settings: model health, customer accounts, members, and read-only MCP tokens.", DEMO),
        ("integrations", "Integrations: signed inbound webhooks and the GitHub Issues connector (loopback test service or opt-in api.github.com).", DEMO),
        ("service-hours", "Service hours: versioned calendars in an IANA time zone with a due-time preview.", DEMO),
    ]),
    ("Operational first run", [
        ("op-home", "A new operational organization: empty, no banner, nothing seeded.", OPERATIONAL),
        ("op-inbox", "The empty inbox of a new organization.", OPERATIONAL),
        ("op-settings", "Settings in a new organization: add the first customer account here.", OPERATIONAL),
        ("op-success", "Customer Success with no accounts yet.", OPERATIONAL),
        ("op-analytics", "Analytics counting operational records only.", OPERATIONAL),
    ]),
]


def compress() -> None:
    """Re-encode large captures as palette PNGs (lossless enough for UI text, a fraction of the size)."""
    from PIL import Image

    for f in sorted(IMAGES.glob("*.png")):
        if f.stat().st_size < 250_000:
            continue
        before = f.stat().st_size
        with Image.open(f) as im:
            im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(f, optimize=True)
        print(f"compressed {f.name}: {before // 1024} KB -> {f.stat().st_size // 1024} KB")


def main() -> int:
    import sys

    if "--compress" in sys.argv:
        compress()
    lines = ["# Screenshot gallery", "",
             "Captured with Playwright from the running app (`make screenshots`, and the operational first-run suite "
             "against a scratch operational stack). Widths are CSS pixels. Click any image for the full-size file.", ""]
    missing = []
    for title, screens in SECTIONS:
        lines += [f"## {title}", ""]
        for name, caption, source in screens:
            have = [w for w in WIDTHS if (IMAGES / f"{name}-{w}.png").exists()]
            if not have:
                missing.append(name)
                continue
            main_w = have[0]
            lines += [f"### {caption.split(':')[0]}", "", f"{caption}", "", f"Source: {source}.", "",
                      f"[![{caption.split(':')[0]}](images/{name}-{main_w}.png)](images/{name}-{main_w}.png)", ""]
            mobile = 390 in have and main_w != 390
            sizes = " · ".join(f"[{w} px](images/{name}-{w}.png)" for w in have)
            lines += [f"Widths: {sizes}", ""]
            if mobile:
                lines += [f'<img src="images/{name}-390.png" alt="{caption.split(":")[0]} at 390 px" width="260">', ""]
    if missing:
        lines += ["## Not captured", "", "These screens had no capture in this run: " + ", ".join(missing) + ".", ""]
    (ROOT / "docs" / "screenshots.md").write_text("\n".join(lines))
    print(f"gallery written; {sum(len(s) for _, s in SECTIONS) - len(missing)} screens, missing: {missing or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
