"""Render every ```mermaid block in the docs with a pinned Mermaid CLI; exit non-zero on any failure.

    python3 scripts/render_diagrams.py [out_dir]

Requires `npx` (Node). CI uses this; locally it downloads the pinned CLI and a headless browser on first use.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = "@mermaid-js/mermaid-cli@11.4.2"
BLOCK = re.compile(r"```mermaid\n(.*?)```", re.S)
SOURCES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "docs" / "adr").glob("*.md"))]


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "runtime" / "diagrams"
    out.mkdir(parents=True, exist_ok=True)
    failures = total = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "puppeteer.json"
        cfg.write_text('{"args": ["--no-sandbox"]}')
        for src in SOURCES:
            for i, body in enumerate(BLOCK.findall(src.read_text()), start=1):
                total += 1
                name = f"{src.stem}-{i}"
                mmd = Path(tmp) / f"{name}.mmd"
                mmd.write_text(body)
                r = subprocess.run(["npx", "-y", CLI, "-q", "-p", str(cfg), "-i", str(mmd), "-o", str(out / f"{name}.svg")],
                                   capture_output=True, text=True)
                ok = r.returncode == 0 and (out / f"{name}.svg").exists()
                print(f"{'ok  ' if ok else 'FAIL'} {src.relative_to(ROOT)} #{i}")
                if not ok:
                    failures += 1
                    print((r.stderr or r.stdout)[-800:])
    print(f"{total - failures}/{total} diagrams rendered to {out}")
    return 1 if failures or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
