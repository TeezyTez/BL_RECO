from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


EDI_STANDARD = "UN/EDIFACT IFTMCS-inspired shipping instruction subset"


@dataclass
class Party:
    name: str = ""
    address: str = ""


@dataclass
class BillOfLading:
    booking_no: str = ""
    bill_of_lading_no: str = ""
    shipper: Party = field(default_factory=Party)
    consignee: Party = field(default_factory=Party)
    notify_party: Party = field(default_factory=Party)
    carrier: str = ""
    vessel: str = ""
    voyage: str = ""
    port_of_loading: str = ""
    port_of_discharge: str = ""
    place_of_delivery: str = ""
    container_no: str = ""
    seal_no: str = ""
    packages: str = ""
    gross_weight: str = ""
    measurement: str = ""
    freight_terms: str = ""
    goods_description: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def quality(self) -> dict:
        required = [
            "bill_of_lading_no",
            "shipper",
            "consignee",
            "vessel",
            "voyage",
            "port_of_loading",
            "port_of_discharge",
            "container_no",
            "packages",
            "gross_weight",
        ]
        values = self.to_dict()
        found = 0
        missing: list[str] = []
        for key in required:
            value = values.get(key)
            present = bool(value.get("name")) if isinstance(value, dict) else bool(value)
            if present:
                found += 1
            else:
                missing.append(key)
        return {"score": round(found / len(required), 2), "found": found, "total": len(required), "missing": missing}


FIELD_ALIASES = {
    "booking_no": [r"booking\s*(?:no|number|ref)\.?", r"订舱号"],
    "bill_of_lading_no": [r"(?:bill\s*of\s*lading|b\/l|bl)\s*(?:no|number)\.?", r"提单号"],
    "carrier": [r"carrier", r"船公司", r"承运人"],
    "vessel": [r"vessel(?:\s*name)?", r"船名"],
    "voyage": [r"voyage(?:\s*no)?\.?", r"航次"],
    "port_of_loading": [r"port\s*of\s*loading", r"pol", r"装货港"],
    "port_of_discharge": [r"port\s*of\s*discharge", r"pod", r"卸货港"],
    "place_of_delivery": [r"place\s*of\s*delivery", r"delivery\s*place", r"目的地", r"交货地"],
    "container_no": [r"container\s*(?:no|number)\.?", r"cntr\s*no\.?", r"箱号"],
    "seal_no": [r"seal\s*(?:no|number)\.?", r"铅封号"],
    "packages": [r"(?:no\.?\s*of\s*)?packages?", r"件数", r"包装"],
    "gross_weight": [r"gross\s*weight", r"g\.?w\.?", r"毛重"],
    "measurement": [r"measurement", r"measure", r"cbm", r"体积"],
    "freight_terms": [r"freight\s*(?:terms|payable|prepaid|collect)", r"运费条款"],
}

PARTY_ALIASES = {
    "shipper": [r"shipper", r"发货人"],
    "consignee": [r"consignee", r"收货人"],
    "notify_party": [r"notify\s*party", r"通知方"],
}

SECTION_STOP_WORDS = [
    "shipper",
    "consignee",
    "notify party",
    "carrier",
    "vessel",
    "voyage",
    "port of loading",
    "port of discharge",
    "place of delivery",
    "container",
    "seal",
    "gross weight",
    "measurement",
    "description",
    "marks",
    "freight",
    "发货人",
    "收货人",
    "通知方",
    "船名",
    "航次",
    "装货港",
    "卸货港",
    "箱号",
    "毛重",
]


def parse_bill_of_lading(text: str) -> BillOfLading:
    normalized = _normalize_text(text)
    result = BillOfLading()

    _parse_vessel_voyage_combo(normalized, result)
    for field_name, aliases in FIELD_ALIASES.items():
        if getattr(result, field_name, ""):
            continue
        value = _find_labeled_value(normalized, aliases)
        if value:
            setattr(result, field_name, value)

    _parse_container_combo(normalized, result)

    for party_name, aliases in PARTY_ALIASES.items():
        party_text = _find_section(normalized, aliases)
        if party_text:
            setattr(result, party_name, _party_from_text(party_text))

    result.goods_description = _find_goods_description(normalized)
    result.warnings = _build_warnings(result)
    return result


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_labeled_value(text: str, aliases: list[str]) -> str:
    label = "|".join(aliases)
    patterns = [
        rf"(?im)^\s*(?:{label})\s*[:：#-]?\s*(.+)$",
        rf"(?is)(?:{label})\s*[:：#-]\s*([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_value(match.group(1))
    return ""


def _find_section(text: str, aliases: list[str]) -> str:
    label = "|".join(aliases)
    stops = "|".join(re.escape(word) for word in SECTION_STOP_WORDS)
    pattern = rf"(?is)(?:^|\n)\s*(?:{label})\s*[:：]?\s*\n?(.*?)(?=\n\s*(?:{stops})\b\s*[:：]?|\Z)"
    match = re.search(pattern, text)
    if not match:
        return ""
    lines = [_clean_value(line) for line in match.group(1).splitlines()]
    lines = [line for line in lines if line and not _looks_like_label(line)]
    return "\n".join(lines[:5])


def _party_from_text(text: str) -> Party:
    lines = [line.strip(" ,;") for line in text.splitlines() if line.strip(" ,;")]
    if not lines:
        return Party()
    return Party(name=lines[0], address=", ".join(lines[1:]))


def _find_goods_description(text: str) -> str:
    aliases = [r"description\s*of\s*goods", r"goods\s*description", r"品名", r"货物描述"]
    section = _find_section(text, aliases)
    if section:
        return section[:600]
    return ""


def _parse_vessel_voyage_combo(text: str, result: BillOfLading) -> None:
    match = re.search(r"(?im)^\s*vessel\s*/\s*voyage\s*[:：]?\s*(.+?)\s*/\s*(.+?)\s*$", text)
    if match:
        result.vessel = _clean_value(match.group(1))
        result.voyage = _clean_value(match.group(2))


def _parse_container_combo(text: str, result: BillOfLading) -> None:
    if not result.container_no:
        match = re.search(r"\b([A-Z]{4}\s?\d{7})\b", text)
        if match:
            result.container_no = match.group(1).replace(" ", "")
    if not result.seal_no:
        match = re.search(r"(?im)\bseal\s*(?:no|number)?\.?\s*[:：#-]?\s*([A-Z0-9-]{5,})", text)
        if match:
            result.seal_no = _clean_value(match.group(1))


def _looks_like_label(value: str) -> bool:
    compact = value.lower().strip(" :：")
    return any(re.fullmatch(word, compact) for word in SECTION_STOP_WORDS)


def _clean_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t:：;|")
    return value[:300]


def _build_warnings(result: BillOfLading) -> list[str]:
    missing = result.quality()["missing"]
    if not missing:
        return []
    names = ", ".join(missing)
    return [f"以下关键字段未识别或置信度不足：{names}。可补充模板规则或人工校对。"]


def to_flat_edi(bl: BillOfLading) -> str:
    rows = [
        ("BGM", "705", bl.bill_of_lading_no),
        ("RFF+BN", bl.booking_no),
        ("NAD+CZ", bl.shipper.name, bl.shipper.address),
        ("NAD+CN", bl.consignee.name, bl.consignee.address),
        ("NAD+N1", bl.notify_party.name, bl.notify_party.address),
        ("TDT+20", bl.vessel, bl.voyage, bl.carrier),
        ("LOC+9", bl.port_of_loading),
        ("LOC+11", bl.port_of_discharge),
        ("LOC+7", bl.place_of_delivery),
        ("EQD+CN", bl.container_no),
        ("SEL", bl.seal_no),
        ("GID", bl.packages),
        ("MEA+AAE+G", bl.gross_weight),
        ("MEA+AAE+AAW", bl.measurement),
        ("FTX+AAA", bl.goods_description),
        ("FTX+PMD", bl.freight_terms),
    ]
    return "\n".join(_edi_row(*row) for row in rows if any(row[1:]))


def to_edifact_ifcsum(bl: BillOfLading) -> str:
    control = datetime.now(UTC).strftime("%y%m%d%H%M")
    segments = [
        "UNB+UNOA:2+LOCALAPP+FORWARDER+" + control + "+1'",
        "UNH+1+IFTMCS:D:99B:UN'",
        _segment("BGM", "705", bl.bill_of_lading_no or "UNKNOWN", "9"),
        _segment("RFF", "BN:" + bl.booking_no) if bl.booking_no else "",
        _segment("NAD", "CZ", _party_token(bl.shipper)) if bl.shipper.name else "",
        _segment("NAD", "CN", _party_token(bl.consignee)) if bl.consignee.name else "",
        _segment("NAD", "N1", _party_token(bl.notify_party)) if bl.notify_party.name else "",
        _segment("TDT", "20", bl.voyage, "", "", "", bl.carrier, "", bl.vessel) if bl.vessel or bl.voyage else "",
        _segment("LOC", "9", bl.port_of_loading) if bl.port_of_loading else "",
        _segment("LOC", "11", bl.port_of_discharge) if bl.port_of_discharge else "",
        _segment("LOC", "7", bl.place_of_delivery) if bl.place_of_delivery else "",
        _segment("EQD", "CN", bl.container_no) if bl.container_no else "",
        _segment("SEL", bl.seal_no) if bl.seal_no else "",
        _segment("GID", "1", bl.packages) if bl.packages else "",
        _segment("MEA", "AAE", "G", bl.gross_weight) if bl.gross_weight else "",
        _segment("MEA", "AAE", "AAW", bl.measurement) if bl.measurement else "",
        _segment("FTX", "AAA", "", "", _escape(bl.goods_description)) if bl.goods_description else "",
        _segment("FTX", "PMD", "", "", _escape(bl.freight_terms)) if bl.freight_terms else "",
    ]
    body = [segment for segment in segments if segment]
    body.append(f"UNT+{len(body) + 2}+1'")
    body.append("UNZ+1+1'")
    return "\n".join(body)


def _edi_row(*parts: str) -> str:
    return "+".join(_escape(part) for part in parts if part)


def _segment(tag: str, *parts: str) -> str:
    return tag + "+" + "+".join(_escape(part) for part in parts) + "'"


def _party_token(party: Party) -> str:
    return (party.name + ":::" + party.address).strip(":")


def _escape(value: str) -> str:
    return str(value or "").replace("'", "?").replace("\n", " ").strip()
