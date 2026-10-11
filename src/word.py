"""Lebenslauf als bearbeitbare Word-Datei (.docx)."""
import io
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

from src.config import DATA_DIR
from src.generate import (
    CV_FONTS,
    CV_SIZES,
    CV_TEMPLATES,
    DEFAULT_CV_OPTIONS,
    DEFAULT_TEMPLATE,
    apply_cv_options,
    letter_style,
)

GREY = RGBColor(0x55, 0x55, 0x55)
LABEL_WIDTH = Cm(3.4)
TEXT_WIDTH = Cm(13.6)
_PBDR_SUCCESSORS = (
    "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
    "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid",
    "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
    "w:rPr", "w:sectPr", "w:pPrChange",
)


def _rgb(hex_color: str) -> RGBColor:
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _bottom_border(paragraph, hex_color: str, size: int = 6) -> None:
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for attr, value in (("w:val", "single"), ("w:sz", str(size)), ("w:space", "1"),
                        ("w:color", hex_color.lstrip("#"))):
        bottom.set(qn(attr), value)
    border.append(bottom)
    paragraph._p.get_or_add_pPr().insert_element_before(border, *_PBDR_SUCCESSORS)


def _run(paragraph, text: str, size: float | None = None, bold=False, italic=False, color=None):
    run = paragraph.add_run(text)
    run.bold, run.italic = bold, italic
    if size:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    return run


def _photo_stream(foto: str) -> io.BytesIO | None:
    if not foto:
        return None
    src = Path(foto)
    src = src if src.is_absolute() else DATA_DIR / src
    if not src.exists():
        return None
    img = Image.open(src).convert("RGB")
    img.thumbnail((600, 800))
    stream = io.BytesIO()
    img.save(stream, "JPEG", quality=88)
    stream.seek(0)
    return stream


def _two_col_table(doc, rows: list[tuple[str, object]], scale: float):
    """Tabelle ohne Rahmen: links Label/Zeitraum, rechts Text oder Callback, das die Zelle füllt."""
    table = doc.add_table(rows=0, cols=2)
    table.autofit = False
    for label, content in rows:
        left, right = table.add_row().cells
        left.width, right.width = LABEL_WIDTH, TEXT_WIDTH
        _run(left.paragraphs[0], label, size=9 * scale, color=GREY)
        if callable(content):
            content(right)
        else:
            right.paragraphs[0].add_run(str(content))
    return table


def build_cv_docx(data: dict, template: str = DEFAULT_TEMPLATE, accent: str | None = None,
                  options: dict | None = None) -> bytes:
    opts = {**DEFAULT_CV_OPTIONS, **(options or {})}
    tpl = CV_TEMPLATES.get(template, CV_TEMPLATES[DEFAULT_TEMPLATE])
    d = apply_cv_options(data, opts)
    color_hex = accent or tpl["farbe"]
    color = _rgb(color_hex)
    font = opts["schrift"] if CV_FONTS.get(opts["schrift"]) else tpl["schrift"]
    scale = CV_SIZES.get(opts["groesse"], 1.0)
    p = d.get("persoenlich") or {}

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2)
    section.top_margin = section.bottom_margin = Cm(1.8)
    normal = doc.styles["Normal"]
    normal.font.name = font
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), font)
    normal.font.size = Pt(10 * scale)
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.line_spacing = 1.05
    bullets = doc.styles["List Bullet"].paragraph_format
    bullets.space_after, bullets.line_spacing = Pt(1), 1.0
    doc.core_properties.title = f"Lebenslauf {p.get('name', '')}"

    def heading(title: str) -> None:
        para = doc.add_paragraph()
        _bottom_border(para, color_hex)
        para.paragraph_format.space_before = Pt(12 * d["abstand"])
        para.paragraph_format.space_after = Pt(4)
        para.paragraph_format.keep_with_next = True
        _run(para, title.upper(), size=12 * scale, bold=True, color=color)

    def entry_filler(e: dict):
        def fill(cell):
            _run(cell.paragraphs[0], e.get("titel", ""), bold=True)
            if e.get("untertitel"):
                _run(cell.add_paragraph(), e["untertitel"], italic=True, color=GREY)
            for punkt in e.get("punkte", []):
                cell.add_paragraph(punkt, style="List Bullet")
            cell.paragraphs[-1].paragraph_format.space_after = Pt(6)
        return fill

    # Kopf: Name, Titel, Kontakt – Foto rechts
    header = doc.add_table(rows=1, cols=2)
    header.autofit = False
    left, right = header.rows[0].cells
    photo_width = 3.2 * d["fotofaktor"]
    left.width, right.width = Cm(16.6 - photo_width), Cm(photo_width + 0.4)
    _run(left.paragraphs[0], p.get("name", ""), size=22, bold=True, color=color)
    if p.get("titel"):
        _run(left.add_paragraph(), p["titel"], size=12, color=GREY)
    if d.get("kontaktzeile"):
        _run(left.add_paragraph(), d["kontaktzeile"], size=9)
    if d["angaben_im_kopf"] and d.get("angaben"):
        for i, a in enumerate(d["angaben"]):
            para = left.add_paragraph()
            if i == 0:
                para.paragraph_format.space_before = Pt(6)
            _run(para, f"{a['label']}: ", size=9, color=GREY)
            _run(para, a["text"], size=9)
    if photo := _photo_stream(d.get("foto", "")):
        right.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        right.paragraphs[0].add_run().add_picture(photo, width=Cm(photo_width))
    rule = doc.add_paragraph()
    _bottom_border(rule, color_hex, size=12)

    titles = d.get("ueberschriften") or {}
    if d.get("angaben") and not d["angaben_im_kopf"]:
        heading(titles.get("angaben", "Persönliche Angaben"))
        _two_col_table(doc, [(a["label"], a["text"]) for a in d["angaben"]], scale)
    if d.get("kurzprofil"):
        heading(titles.get("profil", "Profil"))
        doc.add_paragraph(d["kurzprofil"]).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for key, fallback in (("berufserfahrung", "Berufserfahrung"), ("ausbildung", "Ausbildung"),
                          ("projekte", "Projekte")):
        if d.get(key):
            heading(titles.get(key, fallback))
            _two_col_table(doc, [(e.get("zeitraum", ""), entry_filler(e)) for e in d[key]], scale)
    if d.get("kenntnisse"):
        heading(titles.get("kenntnisse", "Kenntnisse"))
        _two_col_table(doc, [(k["label"], k["text"]) for k in d["kenntnisse"]], scale)
    if d.get("referenzen"):
        heading(titles.get("referenzen", "Referenzen"))
        for ref in d["referenzen"]:
            doc.add_paragraph(ref)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def build_letter_docx(data: dict, template: str = DEFAULT_TEMPLATE, accent: str | None = None,
                      options: dict | None = None) -> bytes:
    style = letter_style(template, accent, options)
    color_hex = style["akzent"]
    color = _rgb(color_hex)
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin, section.right_margin = Cm(2.5), Cm(2)
    section.top_margin = section.bottom_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name = style["schrift_name"]
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), style["schrift_name"])
    normal.font.size = Pt(11 * style["groesse"])
    normal.paragraph_format.space_after = Pt(8)
    doc.core_properties.title = data.get("betreff", "")

    head = doc.add_paragraph()
    head.paragraph_format.space_after = Pt(0)
    _run(head, data["absender"]["name"], size=16, bold=True, color=color)
    contact = doc.add_paragraph()
    _bottom_border(contact, color_hex)
    _run(contact, data.get("kontaktzeile", ""), size=9.5, color=GREY)

    recipient = doc.add_paragraph()
    recipient.paragraph_format.space_before = Pt(34)
    for i, line in enumerate(data.get("empfaenger", [])):
        if i:
            recipient.add_run().add_break()
        recipient.add_run(line)
    date = doc.add_paragraph(data.get("ort_datum", ""))
    date.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date.paragraph_format.space_before = Pt(28)
    subject = doc.add_paragraph()
    subject.paragraph_format.space_before = Pt(14)
    _run(subject, data.get("betreff", ""), bold=True, color=color)
    doc.add_paragraph(data.get("anrede", ""))
    for absatz in data.get("absaetze", []):
        doc.add_paragraph(absatz).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    doc.add_paragraph(data.get("gruss", ""))
    signature = doc.add_paragraph(data["absender"]["name"])
    signature.paragraph_format.space_before = Pt(30)
    attachments = doc.add_paragraph()
    attachments.paragraph_format.space_before = Pt(20)
    _run(attachments, data.get("anlagen", ""), size=9.5, color=GREY)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def save_letter_docx(data: dict, path: Path, **style) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_letter_docx(data, **style))
    return path


def save_cv_docx(data: dict, path: Path, **style) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_cv_docx(data, **style))
    return path
