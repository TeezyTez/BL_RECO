from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from bl_parser import EDI_STANDARD, parse_bill_of_lading, to_edifact_ifcsum, to_flat_edi
from document_text import extract_text_from_file
from vision_recognizer import recognize_bill_of_lading_with_vision


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

def _load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
UPLOAD_DIR.mkdir(exist_ok=True)


def _save_upload(file_storage) -> Path:
    original = secure_filename(file_storage.filename or "document")
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("仅支持 PDF 或常见图片格式。")

    fd, temp_name = tempfile.mkstemp(prefix="bl_", suffix=suffix, dir=UPLOAD_DIR)
    os.close(fd)
    path = Path(temp_name)
    file_storage.save(path)
    return path


@app.get("/")
def index():
    return render_template("index.html", edi_standard=EDI_STANDARD)


@app.post("/api/recognize")
def recognize():
    uploaded = request.files.get("document")
    manual_text = request.form.get("text", "").strip()
    use_vision = request.form.get("use_vision") == "1"
    source_name = "手工输入"
    warnings: list[str] = []
    engine = "rules"

    if uploaded and uploaded.filename:
        try:
            path = _save_upload(uploaded)
            source_name = uploaded.filename
            extracted = extract_text_from_file(path)
            warnings.extend(extracted.warnings)
            text = "\n".join(part for part in [extracted.text, manual_text] if part.strip())
            if use_vision:
                try:
                    parsed = recognize_bill_of_lading_with_vision(path, text)
                    engine = "openai_vision"
                    if parsed.warnings:
                        warnings.extend(parsed.warnings)
                except Exception as exc:
                    warnings.append(f"多模态识别未启用或失败，已回退到规则识别：{exc}")
                    parsed = parse_bill_of_lading(text)
            else:
                parsed = parse_bill_of_lading(text)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            if "path" in locals() and path.exists():
                path.unlink(missing_ok=True)
    else:
        text = manual_text

    if not text.strip() and "parsed" not in locals():
        return jsonify({"error": "未获取到可识别文本。请上传文本型 PDF，或粘贴 OCR/提单文本。"}), 400

    if "parsed" not in locals():
        parsed = parse_bill_of_lading(text)
    flat_edi = to_flat_edi(parsed)
    edifact = to_edifact_ifcsum(parsed)

    return jsonify(
        {
            "source": source_name,
            "engine": engine,
            "text": text,
            "fields": parsed.to_dict(),
            "quality": parsed.quality(),
            "edi": {"flat": flat_edi, "edifact_ifcsum": edifact},
            "warnings": warnings + parsed.warnings,
        }
    )


@app.post("/api/parse-text")
def parse_text():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "请输入提单文本。"}), 400

    parsed = parse_bill_of_lading(text)
    return jsonify(
        {
            "fields": parsed.to_dict(),
            "quality": parsed.quality(),
            "edi": {
                "flat": to_flat_edi(parsed),
                "edifact_ifcsum": to_edifact_ifcsum(parsed),
            },
            "warnings": parsed.warnings,
        }
    )


@app.get("/api/schema")
def schema():
    return jsonify(
        {
            "standard": EDI_STANDARD,
            "fields": [
                "booking_no",
                "bill_of_lading_no",
                "shipper",
                "consignee",
                "notify_party",
                "carrier",
                "vessel",
                "voyage",
                "place_of_receipt",
                "port_of_loading",
                "port_of_discharge",
                "place_of_delivery",
                "container_no",
                "seal_no",
                "packages",
                "gross_weight",
                "measurement",
                "freight_terms",
                "goods_description",
                "marks_and_nos",
                "containers",
            ],
        }
    )


@app.template_filter("json_pretty")
def json_pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
