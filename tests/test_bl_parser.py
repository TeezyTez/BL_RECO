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


def test_parse_hunicorn_layout_hints_and_container_rows():
    text = """HUNICORN SHIPPING CO.,LTD
EMIVCHNXIM016879X
SHIPPER'S LOAD & COUNT
PDF LAYOUT HINTS
B/L NO:
EMIVCHNXIM016879X
SHIPPER:
HUNICORN SHIPPING CO.,LTD
RM2703,JINLONG BUILDING CAIWUWEI,139
HONGBAO ROAD,LUOHU,SHENZHEN,CHINA
CONSIGNEE:
BFL BRANDFOLIO FZCO
C/O RETAIL LOGISTICS LLC
P.O BOX 61274
JEBEL ALI FREE ZONE
DUBAI UAE
NOTIFY PARTY:
BFL BRANDFOLIO FZCO
C/O RETAIL LOGISTICS LLC
VESSEL AND VOYAGE:
ESL SANA 02615W
PORT OF LOADING:
XIAMEN,CHINA
PORT OF DISCHARGE:
KHOR FAKKAN,UAE
PLACE OF DELIVERY:
JEBEL ALI FREEZONE, UAE
GROSS WEIGHT:
31058.740(KGS)
MEASUREMENT:
343.696(CBM)
FREIGHT TERMS:
FREIGHT COLLECT
DESCRIPTION OF GOODS:
FOOTWEAR
4764
CARTONS
ESDU4400368 40'HQ D2708385 1x40'HQ s.t.c. 930CARTONS CY-CY 5498.500 65.290
ESDU4041761 40'HQ D2610534 1x40'HQ s.t.c. 859CARTONS CY-CY 6145.680 64.570"""

    bill = parse_bill_of_lading(text)

    assert bill.bill_of_lading_no == "EMIVCHNXIM016879X"
    assert bill.shipper.name == "HUNICORN SHIPPING CO.,LTD"
    assert bill.consignee.name == "BFL BRANDFOLIO FZCO"
    assert bill.vessel == "ESL SANA"
    assert bill.voyage == "02615W"
    assert bill.packages == "4764 CARTONS"
    assert bill.gross_weight == "31058.740 KGS"
    assert bill.measurement == "343.696 CBM"
    assert bill.goods_description == "FOOTWEAR"
    assert len(bill.containers) == 2
    assert bill.containers[0].seal_no == "D2708385"
    assert bill.quality()["score"] == 1.0


def test_parse_star_concord_layout_hints_without_container_number():
    text = """NON-NEGOTIABLE
CICL20250124
PDF LAYOUT HINTS
TEMPLATE: STAR CONCORD
B/L NO:
CICL20250124
SHIPPER:
CJPACK PTE. LTD
CO.REG. NO: 201600908D
140 PAYA LEBAR ROAD # 10-09
AZ@PAYA LEBAR SINGAPORE 409015
CONSIGNEE:
PT. PERTAMINA LUBRICANTS
GEDUNG GRHA PERTAMINA, PERTAMAX TOWER
15-17 FLOOR, JL. MEDAN MERDEKA TIMUR NO.
11-13, GAMBIR, GAMBIR, JAKARTA PUSAT
10110 INDONESIA NPWP: 0032653230051000
NOTIFY PARTY:
SAME AS CONSIGNEE
VESSEL AND VOYAGE:
SURABAYA VOYAGER 2504S
PLACE OF RECEIPT:
BUSAN PORT, CFS
PORT OF LOADING:
BUSAN PORT, KOREA
PORT OF DISCHARGE:
TANJUNG PRIOK, JAKARTA, INDONESIA
PLACE OF DELIVERY:
TANJUNG PRIOK, JAKARTA, CFS
MARKS AND NOS:
AP 9016, AP 90773
PERTAMINA UNIT
PRODUKSI
PELUMAS JAKARTA
INDONESIA
PACKAGES:
1 PALLET
DESCRIPTION OF GOODS:
SEE ATTACHMENT
GROSS WEIGHT:
495.000(KGS)
MEASUREMENT:
1.283(CBM)
FREIGHT TERMS:
FREIGHT PREPAID"""

    bill = parse_bill_of_lading(text)

    assert bill.bill_of_lading_no == "CICL20250124"
    assert bill.shipper.name == "CJPACK PTE. LTD"
    assert bill.consignee.name == "PT. PERTAMINA LUBRICANTS"
    assert bill.notify_party.name == "PT. PERTAMINA LUBRICANTS"
    assert bill.vessel == "SURABAYA VOYAGER"
    assert bill.voyage == "2504S"
    assert bill.place_of_receipt == "BUSAN PORT, CFS"
    assert bill.port_of_discharge == "TANJUNG PRIOK, JAKARTA, INDONESIA"
    assert bill.packages == "1 PALLET"
    assert bill.gross_weight == "495.000 KGS"
    assert bill.measurement == "1.283 CBM"
    assert bill.freight_terms == "FREIGHT PREPAID"
    assert "AP 9016" in bill.marks_and_nos
    assert bill.container_no == ""
    assert bill.quality()["score"] == 1.0
