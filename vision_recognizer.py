from __future__ import annotations

import base64
import json
import os
from dataclasses import fields
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from bl_parser import BillOfLading, Container, Party


DEFAULT_VISION_MODEL = "gpt-4.1"
MAX_PAGES = 3


JSON_SCHEMA: dict[str, Any] = {
    "name": "bill_of_lading_extraction",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "booking_no": {"type": "string"},
            "bill_of_lading_no": {"type": "string"},
            "shipper": {"$ref": "#/$defs/party"},
            "consignee": {"$ref": "#/$defs/party"},
            "notify_party": {"$ref": "#/$defs/party"},
            "carrier": {"type": "string"},
            "vessel": {"type": "string"},
            "voyage": {"type": "string"},
            "place_of_receipt": {"type": "string"},
            "port_of_loading": {"type": "string"},
            "port_of_discharge": {"type": "string"},
            "place_of_delivery": {"type": "string"},
            "container_no": {"type": "string"},
            "seal_no": {"type": "string"},
            "packages": {"type": "string"},
            "gross_weight": {"type": "string"},
            "measurement": {"type": "string"},
            "freight_terms": {"type": "string"},
            "goods_description": {"type": "string"},
            "marks_and_nos": {"type": "string"},
            "containers": {
                "type": "array",
                "items": {"$ref": "#/$defs/container"},
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
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
            "warnings",
        ],
        "$defs": {
            "party": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["name", "address"],
            },
            "container": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "container_no": {"type": "string"},
                    "container_type": {"type": "string"},
                    "seal_no": {"type": "string"},
                    "packages": {"type": "string"},
                    "gross_weight": {"type": "string"},
                    "measurement": {"type": "string"},
                },
                "required": [
                    "container_no",
                    "container_type",
                    "seal_no",
                    "packages",
                    "gross_weight",
                    "measurement",
                ],
            },
        },
    },
    "strict": True,
}


PROMPT = """You are extracting data from ocean bill of lading documents.

Return only the requested JSON schema. Use the document image as the source of truth, including layout, tables, stamps, and small text. Preserve values exactly as shown where practical.

Rules:
- Identify field labels visually, not only by text order.
- For "TO ORDER" consignee, put that phrase in consignee.name.
- If notify party says SAME AS CONSIGNEE, copy the consignee party into notify_party.
- Extract all container rows. Include container no, type, seal no, packages, gross weight, and measurement when present.
- If the document is LCL or has no standard container number, leave container_no empty and use marks_and_nos for marks/shipping bill/PO references.
- Normalize units but do not invent missing values. Examples: "4,147.000 KGS", "5.217 CBM", "44 PACKAGES".
- Put freight payment terms such as FREIGHT PREPAID or FREIGHT COLLECT in freight_terms. Do not confuse service type like CFS-CFS with freight_terms.
- If a field is absent or unreadable, use an empty string and add a short warning.
"""


def recognize_bill_of_lading_with_vision(path: Path, extra_text: str = "") -> BillOfLading:
    provider = os.environ.get("VISION_PROVIDER", "openai").strip().lower()
    api_key = os.environ.get("VISION_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 VISION_API_KEY 或 OPENAI_API_KEY，无法启用多模态大模型识别。")

    base_url = os.environ.get("VISION_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if provider != "openai" and not base_url:
        raise RuntimeError(f"VISION_PROVIDER={provider} 需要配置 VISION_BASE_URL。")

    from openai import OpenAI

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    model = os.environ.get("VISION_MODEL") or os.environ.get("OPENAI_MODEL") or DEFAULT_VISION_MODEL
    style = os.environ.get("VISION_API_STYLE", "responses").strip().lower()

    if style == "chat":
        return _recognize_with_chat_completions(client, model, path, extra_text)

    if provider != "openai":
        raise RuntimeError("第三方 OpenAI-compatible 服务通常需要 VISION_API_STYLE=chat；当前配置为 responses。")

    content: list[dict[str, Any]] = [{"type": "input_text", "text": _build_prompt(extra_text)}]
    for data_url in _file_to_image_data_urls(path):
        content.append({"type": "input_image", "image_url": data_url})

    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": JSON_SCHEMA["name"],
                "schema": JSON_SCHEMA["schema"],
                "strict": JSON_SCHEMA["strict"],
            }
        },
    )
    payload = json.loads(response.output_text)
    return bill_from_dict(payload)


def _recognize_with_chat_completions(client, model: str, path: Path, extra_text: str) -> BillOfLading:
    content: list[dict[str, Any]] = [{"type": "text", "text": _chat_prompt(extra_text)}]
    for data_url in _file_to_image_data_urls(path):
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    text = response.choices[0].message.content or "{}"
    payload = json.loads(_strip_json_fences(text))
    return bill_from_dict(payload)


def bill_from_dict(payload: dict[str, Any]) -> BillOfLading:
    data = {field.name: payload.get(field.name, "") for field in fields(BillOfLading)}
    data["shipper"] = _party(payload.get("shipper"))
    data["consignee"] = _party(payload.get("consignee"))
    data["notify_party"] = _party(payload.get("notify_party"))
    data["containers"] = [_container(item) for item in payload.get("containers", []) if isinstance(item, dict)]
    data["warnings"] = [str(item) for item in payload.get("warnings", []) if str(item).strip()]
    return BillOfLading(**data)


def _party(value: Any) -> Party:
    if not isinstance(value, dict):
        return Party()
    return Party(name=str(value.get("name", "") or ""), address=str(value.get("address", "") or ""))


def _container(value: dict[str, Any]) -> Container:
    return Container(
        container_no=str(value.get("container_no", "") or ""),
        container_type=str(value.get("container_type", "") or ""),
        seal_no=str(value.get("seal_no", "") or ""),
        packages=str(value.get("packages", "") or ""),
        gross_weight=str(value.get("gross_weight", "") or ""),
        measurement=str(value.get("measurement", "") or ""),
    )


def _build_prompt(extra_text: str) -> str:
    if not extra_text.strip():
        return PROMPT
    return PROMPT + "\nAdditional OCR/text layer from the same document:\n" + extra_text[:8000]


def _chat_prompt(extra_text: str) -> str:
    schema_keys = ", ".join(JSON_SCHEMA["schema"]["required"])
    prompt = (
        PROMPT
        + "\nReturn a single valid JSON object. Do not include markdown fences."
        + "\nThe JSON object must include these top-level keys: "
        + schema_keys
        + "\nParty fields must be objects with name and address. containers must be an array of objects."
    )
    if extra_text.strip():
        prompt += "\nAdditional OCR/text layer from the same document:\n" + extra_text[:8000]
    return prompt


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _file_to_image_data_urls(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_to_image_data_urls(path)
    return [_image_path_to_data_url(path)]


def _pdf_to_image_data_urls(path: Path) -> list[str]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    urls: list[str] = []
    for page_index in range(min(len(pdf), MAX_PAGES)):
        bitmap = pdf[page_index].render(scale=2)
        image = bitmap.to_pil()
        urls.append(_pil_to_data_url(image))
    return urls


def _image_path_to_data_url(path: Path) -> str:
    with Image.open(path) as image:
        return _pil_to_data_url(image)


def _pil_to_data_url(image: Image.Image) -> str:
    image = image.convert("RGB")
    image.thumbnail((1800, 1800))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
