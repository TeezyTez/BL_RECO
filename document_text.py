from __future__ import annotations

from dataclasses import dataclass, field
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

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")

    text = "\n".join(pages).strip()
    warnings: list[str] = []
    if not text:
        warnings.append("PDF 未提取到文本，可能是扫描件。请安装 OCR 引擎或粘贴 OCR 文本。")
    return ExtractionResult(text=text, warnings=warnings)


def _extract_image_text(path: Path) -> ExtractionResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ExtractionResult(
            text="",
            warnings=["当前环境未安装图片 OCR 依赖。可安装 Tesseract 与 pytesseract，或粘贴图片 OCR 文本。"],
        )

    try:
        text = pytesseract.image_to_string(Image.open(path), lang="eng+chi_sim")
    except Exception as exc:
        return ExtractionResult(text="", warnings=[f"图片 OCR 未完成：{exc}"])

    return ExtractionResult(text=text.strip())
