"""Add one synthetic scanned PDF to the *demo* knowledge base, so the PDF/OCR path can be seen in the UI.

The page is an image (no text layer), so ingestion must use OCR. Refuses any instance that is not in demo mode.

    python3 scripts/demo_pdf.py [--api http://localhost:8030] [--web http://localhost:3030]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from worked_example import SUPPORT, Client, login  # noqa: E402

LINES = [
    "TaskFlow Cloud - Export guide (scanned copy)",
    "SYNTHETIC DEMO DOCUMENT",
    "",
    "Exports larger than 25,000 rows should use",
    "Export > Prepare in background.",
    "The download link is emailed when the file is ready.",
]


def scanned_pdf() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (1700, 2200), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=52)
    for i, line in enumerate(LINES):
        draw.text((140, 220 + i * 110), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=200)
    return buf.getvalue()


def main() -> int:
    import urllib.request

    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8030")
    ap.add_argument("--web", default="http://localhost:3030")
    a = ap.parse_args()
    if Client(a.api, a.web).call("GET", "/instance")["data_mode"] != "demo":
        raise SystemExit("refusing: not a demo instance")
    creds = json.loads((ROOT / ".local" / "demo-credentials.json").read_text())
    c = login(a.api, a.web, SUPPORT, creds)
    boundary = "relayopsdemo"
    fields = {"slug": "scanned-export-guide", "title": "Export guide (scanned PDF, synthetic)", "kind": "article",
              "visibility": "public", "component": "exports", "product_versions": "2.4,2.5"}
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"export-guide-scan.pdf\"\r\n"
             "Content-Type: application/pdf\r\n\r\n").encode() + scanned_pdf() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{a.api}/api/knowledge", data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}", "Origin": a.web, "X-CSRF-Token": c._csrf()})
    with c.opener.open(req, timeout=180) as r:
        out = json.loads(r.read())
    doc = out["document"]
    print(f"document {doc['id']} version {doc['current_version']} changed={out['changed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
