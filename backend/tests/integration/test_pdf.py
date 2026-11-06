"""PDF ingestion (text layer and OCR) and controlled PDF export."""

from __future__ import annotations

import io

import pypdf
import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from relayops.core.clock import utcnow
from relayops.services import pdf
from tests.factories import build_world, client_for

FORM = {"slug": "pdf-guide", "title": "Export guide", "kind": "article", "visibility": "public"}
TEXT = "Large exports over 25,000 rows should use Prepare in background. The link arrives by email."


def text_pdf(lines=(TEXT,), pages=1) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for _ in range(pages):
        y = 800
        for line in lines:
            c.drawString(60, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


def scanned_pdf(text="Rotate the webhook signing secret from Settings") -> bytes:
    img = Image.new("L", (1700, 400), 255)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=56)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    draw.text((60, 150), text, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=200)
    return buf.getvalue()


def test_text_layer_pages_are_read_directly():
    content, pages = pdf.extract(text_pdf(pages=2))
    assert [p.method for p in pages] == ["text_layer", "text_layer"]
    assert "## Page 2" in content and "Prepare in background" in content


@pytest.mark.skipif(not pdf.tesseract_available(), reason="tesseract binary not installed")
def test_image_only_pages_go_through_ocr_and_say_so():
    content, pages = pdf.extract(scanned_pdf())
    assert pages[0].method == "ocr" and pages[0].confidence is not None
    assert "webhook" in content.lower() and "secret" in content.lower()
    rep = pdf.report(pages)
    assert rep["ocr_pages"] == 1 and "tesseract" in rep["engine"]


def test_bad_inputs_are_refused():
    with pytest.raises(pdf.PdfRejected, match="not a PDF"):
        pdf.extract(b"hello")
    w = pypdf.PdfWriter(clone_from=io.BytesIO(text_pdf()))
    w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(pdf.PdfRejected, match="encrypted"):
        pdf.extract(buf.getvalue())
    with pytest.raises(pdf.PdfRejected, match="limit"):
        pdf.extract(text_pdf(pages=pdf.MAX_PAGES + 1))
    with pytest.raises(pdf.PdfRejected, match="unreadable|no pages"):
        pdf.extract(b"%PDF-1.4\n%%EOF")


def test_upload_records_how_each_page_was_read(db):
    build_world(db)
    s = client_for("support@a.test")
    r = s.post("/api/knowledge", data=FORM, files={"file": ("guide.pdf", text_pdf(), "application/pdf")})
    assert r.status_code == 201, r.text
    doc = s.get(f"/api/knowledge/{r.json()['document']['id']}").json()
    v = doc["versions"][0]
    assert v["media_type"] == "application/pdf" and v["extraction"]["pages"][0]["method"] == "text_layer"
    enc = pypdf.PdfWriter(clone_from=io.BytesIO(text_pdf()))
    enc.encrypt("pw")
    buf = io.BytesIO()
    enc.write(buf)
    bad = s.post(
        "/api/knowledge", data={**FORM, "slug": "enc"}, files={"file": ("e.pdf", buf.getvalue(), "application/pdf")}
    )
    assert bad.status_code == 422 and "encrypted" in bad.text


def test_export_template_escapes_content_and_labels_demo_records():
    body = "# Summary\n\n<b>not bold</b> & <script>alert(1)</script>\n\nSecond paragraph."
    out = pdf.render(
        title="Handoff <x>",
        org="Acme",
        meta=[("Kind", "engineering brief")],
        body=body,
        data_class="demo",
        generated_at=utcnow(),
    )
    text = "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(out)).pages)
    assert "<b>not bold</b>" in text and "<script>" in text  # shown literally, never interpreted
    assert "DEMO DATA" in text and "Handoff <x>" in text
    plain = pdf.render(title="T", org="Acme", meta=[], body="x", data_class="operational", generated_at=utcnow())
    assert "DEMO DATA" not in pypdf.PdfReader(io.BytesIO(plain)).pages[0].extract_text()
