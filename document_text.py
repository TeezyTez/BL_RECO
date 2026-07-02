from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path


@dataclass
class ExtractionResult:
    text: str
    warnings: list[str] = field(default_factory=list)


def extract_text_from_file(path: Path) -> ExtractionResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return _extract_image_text(path)
    raise ValueError("不支持的文件格式。")


def _extract_pdf_text(path: Path) -> ExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("缺少 pypdf，无法读取 PDF 文本。请先安装 requirements.txt。") from exc

    pdf_bytes = path.read_bytes()
    reader = PdfReader(BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")

    text = "\n".join(pages).strip()
    layout_hints = _extract_pdf_layout_hints(reader, text)
    if layout_hints:
        text = "\n\n".join(part for part in [text, "\n".join(layout_hints)] if part.strip())

    warnings: list[str] = []
    if not text:
        warnings.append("PDF 未提取到文本，可能是扫描件。请安装 OCR 引擎或粘贴 OCR 文本。")
    return ExtractionResult(text=text, warnings=warnings)


def _extract_pdf_layout_hints(reader, raw_text: str) -> list[str]:
    try:
        parts = _positioned_text(reader.pages[0])
    except Exception:
        return []

    text_upper = raw_text.upper()
    if "HUNICORN SHIPPING" in text_upper:
        return _hunicorn_layout_hints(parts, raw_text)
    if _looks_like_star_concord(text_upper):
        return _star_concord_layout_hints(parts, raw_text)
    return []


def _hunicorn_layout_hints(parts: list[tuple[float, float, str]], raw_text: str) -> list[str]:
    def zone(x_min: float, x_max: float, y_min: float, y_max: float) -> str:
        return "\n".join(_layout_lines(parts, x_min, x_max, y_min, y_max))

    bl_no = _first_match(raw_text, r"\b(EMIV[A-Z0-9]{10,})\b")
    vessel_voyage = _first_match(raw_text, r"\b([A-Z][A-Z ]+ V\.\s*[0-9A-Z]{4,})\b")
    if vessel_voyage:
        vessel_voyage = vessel_voyage.replace(" V.", "")

    field_values = [
        ("B/L NO", bl_no),
        ("SHIPPER", zone(0, 285, 785, 825)),
        ("CONSIGNEE", zone(0, 285, 685, 735)),
        ("NOTIFY PARTY", zone(0, 285, 610, 655)),
        ("VESSEL AND VOYAGE", vessel_voyage or zone(0, 145, 545, 565)),
        ("PORT OF LOADING", zone(145, 285, 545, 565)),
        ("PORT OF DISCHARGE", zone(0, 145, 510, 530)),
        ("PLACE OF DELIVERY", zone(145, 285, 510, 530)),
        ("PACKAGES", zone(130, 225, 455, 470)),
        ("GROSS WEIGHT", zone(430, 525, 465, 480)),
        ("MEASUREMENT", zone(525, 595, 465, 480)),
        ("FREIGHT TERMS", _first_match(raw_text, r"\*?\s*(FREIGHT\s+(?:COLLECT|PREPAID|AS\s+ARRANGED))\s*\*?")),
        ("DESCRIPTION OF GOODS", _clean_goods_description(zone(220, 430, 440, 480))),
    ]

    rows = []
    for label, value in field_values:
        value = _clean_layout_block(value)
        if value:
            rows.append(f"{label}:\n{value}")

    if rows:
        hints: list[str] = ["PDF LAYOUT HINTS", "TEMPLATE: HUNICORN"]
        hints.extend(rows)
        return hints
    return []


def _star_concord_layout_hints(parts: list[tuple[float, float, str]], raw_text: str) -> list[str]:
    def zone(x_min: float, x_max: float, y_min: float, y_max: float) -> str:
        return "\n".join(_layout_lines(parts, x_min, x_max, y_min, y_max))

    def inline_zone(x_min: float, x_max: float, y_min: float, y_max: float) -> str:
        return _clean_layout_text(" ".join(_layout_lines(parts, x_min, x_max, y_min, y_max)))

    field_values = [
        ("B/L NO", inline_zone(0, 130, 95, 112)),
        ("SHIPPER", zone(0, 295, 780, 825)),
        ("CONSIGNEE", zone(0, 295, 695, 750)),
        ("NOTIFY PARTY", inline_zone(0, 295, 660, 675)),
        ("VESSEL AND VOYAGE", inline_zone(0, 155, 565, 580)),
        ("PORT OF LOADING", inline_zone(155, 300, 565, 580)),
        ("PORT OF DISCHARGE", inline_zone(0, 155, 535, 555)),
        ("PLACE OF DELIVERY", inline_zone(155, 305, 540, 555)),
        ("MARKS AND NOS", zone(0, 135, 435, 515)),
        ("PACKAGES", inline_zone(135, 200, 500, 515)),
        ("DESCRIPTION OF GOODS", inline_zone(200, 465, 500, 515)),
        ("GROSS WEIGHT", inline_zone(465, 590, 495, 510)),
        ("MEASUREMENT", inline_zone(465, 590, 465, 475)),
        ("FREIGHT TERMS", _first_match(raw_text, r"\b(FREIGHT\s+PREPAID|FREIGHT\s+COLLECT|FREIGHT\s+AS\s+ARRANGED)\b")),
        ("PLACE OF RECEIPT", inline_zone(0, 150, 590, 605)),
        ("FOR DELIVERY OF GOODS PLEASE APPLY TO", zone(0, 300, 25, 85)),
    ]

    rows = []
    for label, value in field_values:
        value = _clean_layout_block(value)
        if value:
            rows.append(f"{label}:\n{value}")

    if rows:
        hints: list[str] = ["PDF LAYOUT HINTS", "TEMPLATE: STAR CONCORD"]
        hints.extend(rows)
        return hints
    return []


def _looks_like_star_concord(text_upper: str) -> bool:
    return (
        "CICL" in text_upper
        and "NON-NEGOTIABLE" in text_upper
        and ("OCEAN FREIGHT" in text_upper or "FREIGHT PREPAID" in text_upper)
    )


def _positioned_text(page) -> list[tuple[float, float, str]]:
    parts: list[tuple[float, float, str]] = []

    def visitor(text, cm, tm, font_dict, font_size):
        value = " ".join(text.split())
        if value:
            parts.append((float(tm[4]), float(tm[5]), value))

    page.extract_text(visitor_text=visitor)
    return parts


def _layout_lines(
    parts: list[tuple[float, float, str]],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> list[str]:
    selected = [(x, y, text) for x, y, text in parts if x_min <= x <= x_max and y_min <= y <= y_max]
    selected.sort(key=lambda item: (-item[1], item[0]))

    rows: list[list[tuple[float, str]]] = []
    current_y: float | None = None
    for x, y, text in selected:
        if current_y is None or abs(y - current_y) > 3:
            rows.append([])
            current_y = y
        rows[-1].append((x, text))

    lines: list[str] = []
    for row in rows:
        row.sort(key=lambda item: item[0])
        line = _clean_layout_text(" ".join(text for _, text in row))
        if line:
            lines.append(line)
    return lines


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I)
    return match.group(1).strip() if match else ""


def _clean_layout_text(text: str) -> str:
    text = re.sub(r"\bJ\s+E\s+BEL\b", "JEBEL", text)
    text = re.sub(r"\(\s*K\s*GS\s*\)", "(KGS)", text)
    text = re.sub(r"\(\s*C\s*BM\s*\)", "(CBM)", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" (CBM)", "(CBM)").replace(" (KGS)", "(KGS)")
    return text.strip(" \t:：;|")


def _clean_layout_block(text: str) -> str:
    lines = [_clean_layout_text(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _clean_goods_description(text: str) -> str:
    ignored = {"AS", "C", "AS C", "SAID TO CONTAIN", "SHIPPER'S LOAD & COUNT"}
    lines = []
    for line in text.splitlines():
        value = _clean_layout_text(line)
        if value and value.upper() not in ignored:
            lines.append(value)
    return "\n".join(lines)


def _extract_image_text(path: Path) -> ExtractionResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ExtractionResult(
            text="",
            warnings=["当前环境未安装图片 OCR 依赖。可安装 Tesseract 与 pytesseract，或粘贴图片 OCR 文本。"],
        )

    _configure_tesseract(pytesseract)

    try:
        with Image.open(path) as image:
            text = pytesseract.image_to_string(image, lang="eng+chi_sim")
    except Exception as exc:
        return ExtractionResult(text="", warnings=[f"图片 OCR 未完成：{exc}"])

    return ExtractionResult(text=text.strip())


def _configure_tesseract(pytesseract) -> None:
    tesseract_cmd = os.environ.get("TESSERACT_CMD")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        return

    candidates = [
        Path("D:/Tools/Tesseract-OCR"),
        Path(__file__).resolve().parent / ".tools" / "Tesseract-OCR",
        Path("C:/Program Files/Tesseract-OCR"),
    ]
    for tesseract_dir in candidates:
        local_cmd = tesseract_dir / "tesseract.exe"
        if local_cmd.exists():
            pytesseract.pytesseract.tesseract_cmd = str(local_cmd)
            os.environ.setdefault("TESSDATA_PREFIX", str(tesseract_dir / "tessdata"))
            return
