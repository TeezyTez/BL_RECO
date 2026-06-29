from bl_parser import parse_bill_of_lading, to_edifact_ifcsum


def test_parse_core_bill_of_lading_fields():
    text = """BILL OF LADING NO: COSU6254813900
BOOKING NO: SHABK240001
SHIPPER
NINGBO EVERLIGHT EXPORT CO., LTD.
88 PORT ROAD, NINGBO, CHINA
CONSIGNEE
GLOBAL HOME SUPPLY INC.
1200 MARKET STREET, LOS ANGELES, CA, USA
VESSEL / VOYAGE: COSCO SHIPPING GEMINI / 036E
PORT OF LOADING: NINGBO, CHINA
PORT OF DISCHARGE: LOS ANGELES, USA
CONTAINER NO: CSLU1234567
PACKAGES: 960 CARTONS
GROSS WEIGHT: 18450 KGS"""

    bill = parse_bill_of_lading(text)

    assert bill.bill_of_lading_no == "COSU6254813900"
    assert bill.booking_no == "SHABK240001"
    assert bill.shipper.name == "NINGBO EVERLIGHT EXPORT CO., LTD."
    assert bill.consignee.name == "GLOBAL HOME SUPPLY INC."
    assert bill.vessel == "COSCO SHIPPING GEMINI"
    assert bill.voyage == "036E"
    assert bill.container_no == "CSLU1234567"
    assert bill.quality()["score"] >= 0.8


def test_edifact_contains_core_segments():
    bill = parse_bill_of_lading(
        """B/L NO: TESTBL001
VESSEL / VOYAGE: EVER GIVEN / 012W
PORT OF LOADING: SHANGHAI
PORT OF DISCHARGE: ROTTERDAM
CONTAINER NO: ABCD1234567"""
    )

    edi = to_edifact_ifcsum(bill)

    assert "UNH+1+IFTMCS" in edi
    assert "BGM+705+TESTBL001+9'" in edi
    assert "TDT+20+012W" in edi
    assert "EQD+CN+ABCD1234567'" in edi
