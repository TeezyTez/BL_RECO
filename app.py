from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.utils import secure_filename

from bl_parser import (
    EDI_STANDARD,
    BillOfLading,
    Container,
    Party,
    parse_bill_of_lading,
    to_edifact_ifcsum,
    to_flat_edi,
)
from document_text import extract_text_from_file
from storage import JobStore
from vision_recognizer import recognize_bill_of_lading_with_vision


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
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
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


_load_env_file()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
UPLOAD_DIR.mkdir(exist_ok=True)
STORE = JobStore(DATA_DIR / "jobs.sqlite3")


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_exc: RequestEntityTooLarge):
    return jsonify({"error": "文件超过 25MB，请压缩后再上传。"}), 413


@app.errorhandler(HTTPException)
def http_error(exc: HTTPException):
    return jsonify({"error": exc.description or exc.name}), exc.code or 500


@app.errorhandler(Exception)
def unexpected_error(exc: Exception):
    app.logger.exception("Unhandled application error")
    return jsonify({"error": f"服务内部错误：{exc}"}), 500


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


def _package_result(
    *,
    source: str,
    engine: str,
    text: str,
    parsed: BillOfLading,
    warnings: list[str],
) -> dict[str, Any]:
    all_warnings = warnings + parsed.warnings
    return {
        "source": source,
        "engine": engine,
        "text": text,
        "fields": parsed.to_dict(),
        "quality": parsed.quality(),
        "edi": {"flat": to_flat_edi(parsed), "edifact_ifcsum": to_edifact_ifcsum(parsed)},
        "warnings": all_warnings,
    }


def _party(value: Any) -> Party:
    if not isinstance(value, dict):
        return Party()
    return Party(name=str(value.get("name", "") or ""), address=str(value.get("address", "") or ""))


def _container(value: Any) -> Container:
    if not isinstance(value, dict):
        return Container()
    return Container(
        container_no=str(value.get("container_no", "") or ""),
        container_type=str(value.get("container_type", "") or ""),
        seal_no=str(value.get("seal_no", "") or ""),
        packages=str(value.get("packages", "") or ""),
        gross_weight=str(value.get("gross_weight", "") or ""),
        measurement=str(value.get("measurement", "") or ""),
    )


def _warnings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    if value and all(isinstance(item, str) and len(item) == 1 for item in value):
        joined = "".join(value).strip()
        return [joined] if joined else []
    return [str(item).strip() for item in value if str(item).strip()]


def _bill_from_fields(payload: dict[str, Any]) -> BillOfLading:
    return BillOfLading(
        booking_no=str(payload.get("booking_no", "") or ""),
        bill_of_lading_no=str(payload.get("bill_of_lading_no", "") or ""),
        shipper=_party(payload.get("shipper")),
        consignee=_party(payload.get("consignee")),
        notify_party=_party(payload.get("notify_party")),
        carrier=str(payload.get("carrier", "") or ""),
        vessel=str(payload.get("vessel", "") or ""),
        voyage=str(payload.get("voyage", "") or ""),
        place_of_receipt=str(payload.get("place_of_receipt", "") or ""),
        port_of_loading=str(payload.get("port_of_loading", "") or ""),
        port_of_discharge=str(payload.get("port_of_discharge", "") or ""),
        place_of_delivery=str(payload.get("place_of_delivery", "") or ""),
        container_no=str(payload.get("container_no", "") or ""),
        seal_no=str(payload.get("seal_no", "") or ""),
        packages=str(payload.get("packages", "") or ""),
        gross_weight=str(payload.get("gross_weight", "") or ""),
        measurement=str(payload.get("measurement", "") or ""),
        freight_terms=str(payload.get("freight_terms", "") or ""),
        goods_description=str(payload.get("goods_description", "") or ""),
        marks_and_nos=str(payload.get("marks_and_nos", "") or ""),
        containers=[_container(item) for item in payload.get("containers", []) if isinstance(item, dict)],
        warnings=_warnings(payload.get("warnings", [])),
    )


def _download(text: str, filename: str, content_type: str = "text/plain; charset=utf-8") -> Response:
    response = Response(text, mimetype=content_type)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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
                    provider = os.environ.get("VISION_PROVIDER", "openai").strip().lower()
                    engine = f"{provider}_vision"
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
        if use_vision:
            warnings.append("多模态识别需要上传 PDF 或图片；当前已使用文本规则识别。")

    if not text.strip() and "parsed" not in locals():
        return jsonify({"error": "未获取到可识别文本。请上传文本型 PDF，或粘贴 OCR/提单文本。"}), 400

    if "parsed" not in locals():
        parsed = parse_bill_of_lading(text)
    result = _package_result(source=source_name, engine=engine, text=text, parsed=parsed, warnings=warnings)
    job = STORE.create(
        source=source_name,
        engine=engine,
        text=text,
        fields=result["fields"],
        quality=result["quality"],
        edi=result["edi"],
        warnings=result["warnings"],
    )
    return jsonify({**result, "job": job})


@app.post("/api/parse-text")
def parse_text():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "请输入提单文本。"}), 400

    parsed = parse_bill_of_lading(text)
    return jsonify(_package_result(source="手工输入", engine="rules", text=text, parsed=parsed, warnings=[]))


@app.get("/api/config")
def config():
    return jsonify(
        {
            "vision_provider": os.environ.get("VISION_PROVIDER", "openai"),
            "vision_model": os.environ.get("VISION_MODEL") or os.environ.get("OPENAI_MODEL") or "",
            "vision_base_url": os.environ.get("VISION_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "",
            "vision_api_style": os.environ.get("VISION_API_STYLE", "responses"),
            "vision_configured": bool(os.environ.get("VISION_API_KEY") or os.environ.get("OPENAI_API_KEY")),
            "edi_standard": EDI_STANDARD,
        }
    )


@app.get("/api/jobs")
def list_jobs():
    return jsonify({"jobs": STORE.list(request.args.get("q", ""), limit=120)})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = STORE.get(job_id)
    if not job:
        return jsonify({"error": "记录不存在。"}), 404
    return jsonify(job)


@app.put("/api/jobs/<job_id>")
def update_job(job_id: str):
    job = STORE.get(job_id)
    if not job:
        return jsonify({"error": "记录不存在。"}), 404
    payload = request.get_json(silent=True) or {}
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return jsonify({"error": "fields 必须是对象。"}), 400
    parsed = _bill_from_fields(fields)
    warnings = [item for item in job["warnings"] if "未识别或置信度不足" not in item]
    updated = STORE.update(
        job_id,
        fields=parsed.to_dict(),
        quality=parsed.quality(),
        edi={"flat": to_flat_edi(parsed), "edifact_ifcsum": to_edifact_ifcsum(parsed)},
        warnings=warnings,
        status=str(payload.get("status") or "reviewed"),
    )
    return jsonify(updated)


@app.get("/api/jobs/<job_id>/export/<fmt>")
def export_job(job_id: str, fmt: str):
    job = STORE.get(job_id)
    if not job:
        return jsonify({"error": "记录不存在。"}), 404
    stem = job["fields"].get("bill_of_lading_no") or job["id"]
    safe_stem = secure_filename(str(stem)) or job["id"]
    if fmt == "json":
        return _download(json.dumps(job["fields"], ensure_ascii=False, indent=2), f"{safe_stem}.json", "application/json")
    if fmt == "flat":
        return _download(job["edi"]["flat"], f"{safe_stem}.flat.txt")
    if fmt == "edifact":
        return _download(job["edi"]["edifact_ifcsum"], f"{safe_stem}.edi")
    return jsonify({"error": "导出格式仅支持 json、flat、edifact。"}), 400


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
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes"}
    app.run(host="127.0.0.1", port=5000, debug=debug)
