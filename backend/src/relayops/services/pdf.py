"""PDF in and out.

Ingest: each page's text layer is read with pypdf. A page with almost no text is rendered with pypdfium2 and
read by the local `tesseract` binary. Every page records how its text was obtained (text layer, OCR with mean
word confidence, or empty), so OCR text is never presented as if it were the document's own text. Encrypted,
oversized, or malformed files are refused.

Export: a fixed reportlab template. Content is placed as escaped paragraphs; nothing in the content is
interpreted as markup. Demo and test records carry a visible banner on every page.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGES = 60
MIN_TEXT_CHARS = 40
OCR_DPI = 200
OCR_TIMEOUT_SECONDS = 60


class PdfRejected(ValueError):
    pass


@dataclass
class PageText:
    number: int
    method: str  # text_layer | ocr | empty | ocr_unavailable
    chars: int
    confidence: float | None = None


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr(image: Any) -> tuple[str, float | None]:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, input is image bytes
        [shutil.which("tesseract") or "tesseract", "stdin", "stdout", "-l", "eng", "--psm", "3", "tsv"],
        input=buf.getvalue(),
        capture_output=True,
        timeout=OCR_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        raise PdfRejected(f"OCR failed: {proc.stderr.decode(errors='replace')[:200]}")
    words: list[str] = []
    confs: list[float] = []
    lines: dict[tuple[str, str, str], list[str]] = {}
    for row in csv.DictReader(
        io.StringIO(proc.stdout.decode(errors="replace")), delimiter="\t", quoting=csv.QUOTE_NONE
    ):
        text = (row.get("text") or "").strip()
        conf = float(row.get("conf") or -1)
        if text and conf >= 0:
            words.append(text)
            confs.append(conf)
            lines.setdefault((row["block_num"], row["par_num"], row["line_num"]), []).append(text)
    body = "\n".join(" ".join(ws) for ws in lines.values())
    return body, round(sum(confs) / len(confs), 1) if confs else None


def extract(raw: bytes) -> tuple[str, list[PageText]]:
    if len(raw) > MAX_PDF_BYTES:
        raise PdfRejected(f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not raw.startswith(b"%PDF-"):
        raise PdfRejected("not a PDF file")
    import pypdf
    import pypdfium2

    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise PdfRejected("encrypted PDFs are not accepted")
        n = len(reader.pages)
    except pypdf.errors.PdfReadError as exc:
        raise PdfRejected(f"unreadable PDF: {exc}") from exc
    if n == 0:
        raise PdfRejected("PDF has no pages")
    if n > MAX_PAGES:
        raise PdfRejected(f"PDF has {n} pages; the limit is {MAX_PAGES}")
    rendered: Any = None
    sections: list[str] = []
    pages: list[PageText] = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if len(text) >= MIN_TEXT_CHARS:
            pages.append(PageText(i + 1, "text_layer", len(text)))
        elif not tesseract_available():
            pages.append(PageText(i + 1, "ocr_unavailable" if not text else "text_layer", len(text)))
        else:
            if rendered is None:
                rendered = pypdfium2.PdfDocument(raw)
            image = rendered[i].render(scale=OCR_DPI / 72).to_pil().convert("L")
            ocr_text, conf = _ocr(image)
            if len(ocr_text.strip()) > len(text):
                text = ocr_text.strip()
                pages.append(PageText(i + 1, "ocr", len(text), conf))
            else:
                pages.append(PageText(i + 1, "empty" if not text else "text_layer", len(text)))
        if text:
            sections.append(f"## Page {i + 1}\n\n{text}")
    if rendered is not None:
        rendered.close()
    if not sections:
        raise PdfRejected("no text could be read from this PDF")
    return "\n\n".join(sections) + "\n", pages


def report(pages: list[PageText]) -> dict[str, Any]:
    ocr = [p for p in pages if p.method == "ocr"]
    return {
        "pages": [asdict(p) for p in pages],
        "ocr_pages": len(ocr),
        "min_ocr_confidence": min((p.confidence for p in ocr if p.confidence is not None), default=None),
        "engine": "pypdf text layer; tesseract OCR for pages without text" if ocr else "pypdf text layer",
    }


# --- export -------------------------------------------------------------------------------------------------


def render(
    *, title: str, org: str, meta: list[tuple[str, str]], body: str, data_class: str, generated_at: datetime
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    base = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=10, leading=14)
    head = ParagraphStyle("h", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, spaceBefore=8)
    banner = {"demo": "DEMO DATA - synthetic sample records", "test": "TEST DATA"}.get(data_class)

    def chrome(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#475467"))
        canvas.drawString(18 * mm, 10 * mm, f"{org} - RelayOps export - generated {generated_at:%Y-%m-%d %H:%M} UTC")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")
        if banner:
            canvas.setFillColor(colors.HexColor("#b54708"))
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(18 * mm, 287 * mm, banner)
        canvas.restoreState()

    flow: list[Any] = [Paragraph(escape(title), styles["Title"])]
    if meta:
        t = Table([[escape(k), Paragraph(escape(v), base)] for k, v in meta], colWidths=[40 * mm, 130 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e4e7ec")),
                ]
            )
        )
        flow += [t, Spacer(1, 6 * mm)]
    for block in body.split("\n\n"):
        line = block.strip()
        if not line:
            continue
        if line.startswith("#"):
            flow.append(Paragraph(escape(line.lstrip("#").strip()), head))
        else:
            flow.append(Paragraph(escape(line).replace("\n", "<br/>"), base))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="RelayOps",
        subject=f"{data_class} record",
    )
    doc.build(flow, onFirstPage=chrome, onLaterPages=chrome)
    return buf.getvalue()
