from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any


PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.\[\]-]+)\s*\}\}")

KEY_ALIASES = {
    "blno": "bill_of_lading_no",
    "mbl": "bill_of_lading_no",
    "billofladingno": "bill_of_lading_no",
    "billofladingnumber": "bill_of_lading_no",
    "bookingno": "booking_no",
    "bookingref": "booking_no",
    "bookingnumber": "booking_no",
    "carrier": "carrier",
    "carriername": "carrier",
    "vessel": "vessel",
    "vesselname": "vessel",
    "voyage": "voyage",
    "voyageno": "voyage",
    "pol": "port_of_loading",
    "portofloading": "port_of_loading",
    "pod": "port_of_discharge",
    "portofdischarge": "port_of_discharge",
    "placeofreceipt": "place_of_receipt",
    "placeofdelivery": "place_of_delivery",
    "deliveryplace": "place_of_delivery",
    "containerno": "container_no",
    "containernumber": "container_no",
    "cntr": "container_no",
    "sealno": "seal_no",
    "sealnumber": "seal_no",
    "seal": "seal_no",
    "packages": "packages",
    "pkg": "packages",
    "grossweight": "gross_weight",
    "weight": "gross_weight",
    "measurement": "measurement",
    "cbm": "measurement",
    "freightterms": "freight_terms",
    "freightpayment": "freight_terms",
    "goodsdescription": "goods_description",
    "commodity": "goods_description",
    "marksandnos": "marks_and_nos",
    "marks": "marks_and_nos",
    "shippername": "shipper.name",
    "shipperaddress": "shipper.address",
    "consigneename": "consignee.name",
    "consigneeaddress": "consignee.address",
    "notifypartyname": "notify_party.name",
    "notifypartyaddress": "notify_party.address",
}

COLLECTION_KEYS = {"containers", "containerdetails", "equipments", "equipment", "cntrs"}


def render_json_message(fields: dict[str, Any], sample: Any) -> dict[str, Any]:
    missing: set[str] = set()
    message = _render_node(sample, fields, missing=missing)
    envelope = _build_envelope(message)
    return {
        "mode": "rules",
        "message": message,
        "envelope": envelope,
        "mapping": [],
        "preview": json.dumps(message, ensure_ascii=False, indent=2),
        "envelope_preview": json.dumps(envelope, ensure_ascii=False, indent=2),
        "warnings": [f"以下占位符未匹配到识别字段：{', '.join(sorted(missing))}"] if missing else [],
    }


def render_json_message_with_llm(fields: dict[str, Any], sample: Any) -> dict[str, Any]:
    api_key = os.environ.get("MAPPING_API_KEY") or os.environ.get("VISION_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 MAPPING_API_KEY / VISION_API_KEY，无法启用 AI 智能填充。")

    from openai import OpenAI

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    base_url = os.environ.get("MAPPING_BASE_URL") or os.environ.get("VISION_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    model = os.environ.get("MAPPING_MODEL") or os.environ.get("VISION_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4.1"

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an enterprise EDI JSON mapping engine. "
                    "Fill a target JSON sample using extracted bill of lading fields. "
                    "Preserve the target JSON structure, key names, object nesting, and data types as much as possible. "
                    "Infer target field meanings from names such as mbl, blNo, booking, shipperInfo, consignee, route.from, "
                    "pol, pod, cntr, equipment, seal, weight, cbm, cargo, marks. "
                    "Do not invent values. If a value is unavailable, keep an empty string/null matching the sample. "
                    "If the sample contains one container/equipment object and source has multiple containers, expand the array. "
                    "Return only valid JSON with keys: message, mapping, warnings. "
                    "mapping items must contain target_path, source_field, confidence, reason."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "extracted_fields": fields,
                        "target_json_sample": sample,
                        "required_output_shape": {
                            "message": "filled target JSON object",
                            "mapping": [
                                {
                                    "target_path": "path in generated message",
                                    "source_field": "source field path used",
                                    "confidence": 0.0,
                                    "reason": "short reason",
                                }
                            ],
                            "warnings": ["missing or uncertain mappings"],
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )

    text = response.choices[0].message.content or "{}"
    payload = json.loads(_strip_json_fences(text))
    message = payload.get("message")
    if not isinstance(message, (dict, list)):
        raise RuntimeError("AI 智能填充返回结果缺少 message 对象。")

    envelope = _build_envelope(message)
    mapping = payload.get("mapping", [])
    warnings = payload.get("warnings", [])
    return {
        "mode": "llm",
        "model": model,
        "message": message,
        "envelope": envelope,
        "mapping": mapping if isinstance(mapping, list) else [],
        "preview": json.dumps(message, ensure_ascii=False, indent=2),
        "envelope_preview": json.dumps(envelope, ensure_ascii=False, indent=2),
        "warnings": _normalize_warnings(warnings),
    }


def simulate_transmit(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "ack_id": "ACK" + uuid.uuid4().hex[:12].upper(),
        "interchange_id": envelope.get("interchange_id", ""),
        "status": "ACCEPTED",
        "received_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "receiver": envelope.get("receiver", "TARGET_SYSTEM"),
        "message": "EDI JSON message accepted by simulated partner endpoint.",
    }


def default_sample() -> dict[str, Any]:
    return {
        "messageType": "IFTMCS_JSON",
        "sender": "LOCALAPP",
        "receiver": "TMS_OR_ERP",
        "shipment": {
            "mbl": "",
            "bookingRef": "",
            "carrierName": "",
            "vesselName": "",
            "voyageNo": "",
            "route": {"from": "", "to": "", "deliveryPlace": ""},
            "freightPayment": "",
        },
        "parties": {
            "shipperInfo": {"company": "", "addr": ""},
            "consigneeInfo": {"company": "", "addr": ""},
            "notify": {"company": "", "addr": ""},
        },
        "cargo": {
            "pkg": "",
            "weight": "",
            "cbm": "",
            "commodity": "",
            "marks": "",
        },
        "equipments": [
            {
                "cntr": "",
                "type": "",
                "seal": "",
                "pkg": "",
                "weight": "",
                "cbm": "",
            }
        ],
    }


def _build_envelope(message: Any) -> dict[str, Any]:
    return {
        "interchange_id": uuid.uuid4().hex[:14].upper(),
        "message_type": _message_type(message),
        "sender": _pick(message, "sender", "LOCALAPP"),
        "receiver": _pick(message, "receiver", "TARGET_SYSTEM"),
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "payload_format": "application/json",
        "payload": message,
    }


def _normalize_warnings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _render_node(node: Any, fields: dict[str, Any], *, missing: set[str], item: dict[str, Any] | None = None, key: str = "") -> Any:
    if isinstance(node, dict):
        return {child_key: _render_node(value, fields, missing=missing, item=item, key=child_key) for child_key, value in node.items()}
    if isinstance(node, list):
        collection = _collection_for_key(key, fields)
        if collection and len(node) == 1 and isinstance(node[0], dict):
            return [_render_node(node[0], fields, missing=missing, item=entry, key=key) for entry in collection]
        return [_render_node(value, fields, missing=missing, item=item, key=key) for value in node]
    if isinstance(node, str):
        return _render_string(node, fields, key=key, item=item, missing=missing)
    if node is None:
        return _auto_value(key, fields, item=item, missing=missing)
    return node


def _render_string(value: str, fields: dict[str, Any], *, key: str, item: dict[str, Any] | None, missing: set[str]) -> str:
    if not value:
        return _auto_value(key, fields, item=item, missing=missing)

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        found = _lookup(path, fields, item=item)
        if found is None:
            missing.add(path)
            return ""
        return _stringify(found)

    rendered = PLACEHOLDER_RE.sub(replace, value)
    return rendered


def _auto_value(key: str, fields: dict[str, Any], *, item: dict[str, Any] | None, missing: set[str]) -> str:
    normalized = _normalize_key(key)
    path = KEY_ALIASES.get(normalized)
    if not path:
        return ""
    found = _lookup(path, fields, item=item)
    if found is None:
        missing.add(path)
        return ""
    return _stringify(found)


def _lookup(path: str, fields: dict[str, Any], *, item: dict[str, Any] | None = None) -> Any:
    clean_path = path.replace("[]", "")
    parts = clean_path.split(".")
    if item and parts[0] in item:
        current: Any = item
    else:
        current = fields
    for part in parts:
        if part == "item":
            current = item or {}
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None
    if current == "":
        return None
    return current


def _collection_for_key(key: str, fields: dict[str, Any]) -> list[dict[str, Any]]:
    if _normalize_key(key) not in COLLECTION_KEYS:
        return []
    containers = fields.get("containers")
    if isinstance(containers, list) and containers:
        return [item for item in containers if isinstance(item, dict)]
    fallback = {
        "container_no": fields.get("container_no", ""),
        "seal_no": fields.get("seal_no", ""),
        "packages": fields.get("packages", ""),
        "gross_weight": fields.get("gross_weight", ""),
        "measurement": fields.get("measurement", ""),
    }
    return [fallback] if any(fallback.values()) else []


def _message_type(message: Any) -> str:
    if not isinstance(message, dict):
        return "JSON_EDI"
    for key in ("messageType", "message_type", "type"):
        if message.get(key):
            return str(message[key])
    return "JSON_EDI"


def _pick(message: Any, key: str, default: str) -> str:
    return str(message.get(key) or default) if isinstance(message, dict) else default


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
