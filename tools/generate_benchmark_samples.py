"""Generate deterministic benchmark sample fixtures."""

from __future__ import annotations

import json
import random
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeAlias, cast

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "benchmarks"

PLANTS = ["PLANT-01", "PLANT-02", "PLANT-03", "PLANT-04"]
LINES = ["LINE-A", "LINE-B", "LINE-C"]
WORK_CENTERS = ["WC-100", "WC-200", "WC-300"]
MATERIALS = ["MAT-1000", "MAT-2000", "MAT-3000", "MAT-4000"]
STATUSES = ["REL", "CRTD"]
UNITS = ["EA", "DZ"]
BATCHES = ["BATCH-001", "BATCH-002", "BATCH-003"]
TIMEZONES = ["Z", "-04:00", "+01:00"]

JsonObject: TypeAlias = dict[str, object]
SampleGenerator: TypeAlias = Callable[[random.Random, int], JsonObject]


def _iso(day: int, tz: str) -> str:
    dt = datetime(2026, 8, 11, 8, 30, 0, tzinfo=UTC) + timedelta(days=day, hours=day % 5)
    if tz == "Z":
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    offset = int(tz[1:3]) * 60 + int(tz[4:6])
    delta = timedelta(minutes=offset)
    local = dt - delta if tz[0] == "+" else dt + delta
    return local.strftime("%Y-%m-%dT%H:%M:%S.000") + tz


def _erp_mes_sample(rng: random.Random, index: int) -> JsonObject:
    batch = None if index % 10 == 9 else BATCHES[index % len(BATCHES)]
    input_doc: JsonObject = {
        "manufacturingOrder": f"MO-{index + 1:05d}",
        "material": MATERIALS[index % len(MATERIALS)],
        "plant": PLANTS[index % len(PLANTS)],
        "workCenter": WORK_CENTERS[index % len(WORK_CENTERS)],
        "productionLine": LINES[index % len(LINES)],
        "plannedQuantity": {
            "value": 1 + index % 50,
            "unit": "DZ" if index < 20 else "EA",
        },
        "systemStatus": STATUSES[index % len(STATUSES)],
        "scheduledStart": _iso(index, TIMEZONES[index % len(TIMEZONES)]),
    }
    if batch is not None:
        input_doc["batch"] = batch
    planned_quantity = cast(JsonObject, input_doc["plannedQuantity"])
    unit = cast(str, planned_quantity["unit"])
    factor = 12 if unit == "DZ" else 1
    scheduled_text = cast(str, input_doc["scheduledStart"])
    scheduled = datetime.fromisoformat(scheduled_text.replace("Z", "+00:00"))
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=UTC)
    expected = {
        "jobNumber": input_doc["manufacturingOrder"],
        "partNumber": input_doc["material"],
        "facility": input_doc["plant"],
        "line": input_doc["productionLine"],
        "quantity": cast(int, planned_quantity["value"]) * factor,
        "status": "Released" if input_doc["systemStatus"] == "REL" else "Pending",
        "scheduledStartUtc": scheduled.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    expected["lotNumber"] = batch
    return {"id": f"erp-mes-{index + 1:03d}", "input": input_doc, "expected": expected}


def _material_part_sample(rng: random.Random, index: int) -> JsonObject:
    units = ["KG"] * 30 + ["LB"] * 30
    weight_unit = "KG" if index == 0 else "LB" if index == 1 else units[index % len(units)]
    factor = 2.2046226218 if weight_unit == "KG" else 1.0
    plants = [f"P{index % 4 + 1}", f"P{(index + 2) % 4 + 1}"]
    if index % 3 == 0:
        plants.append(f"P{(index + 1) % 4 + 1}")
    facilities: list[dict[str, str]] = []
    for plant_index, plant in enumerate(plants, start=1):
        facilities.append(
            {
                "plant": plant,
                "status": "Active" if (plant_index + index) % 3 else "Inactive",
            }
        )
    input_doc: JsonObject = {
        "materialNumber": f"MP-{index + 1:05d}",
        "materialDescription": f"Material {index + 1}",
        "partDescription": f"Legacy part narrative {index + 1}",
        "baseUnit": "KG" if weight_unit == "KG" else "LB",
        "grossWeight": {
            "value": 10.0
            if index == 0
            else 22.046226
            if index == 1
            else round(10.0 + index * 0.5, 3),
            "unit": weight_unit,
        },
        "plantData": [
            {"plant": item["plant"], "status": "ACT" if item["status"] == "Active" else "INA"}
            for item in facilities
        ],
    }
    gross_weight = cast(JsonObject, input_doc["grossWeight"])
    weight = round(cast(float, gross_weight["value"]) * factor, 6)
    if weight.is_integer():
        weight = int(weight)
    expected = {
        "partNumber": input_doc["materialNumber"],
        "description": input_doc["materialDescription"],
        "inventoryUnit": "Kilogram" if weight_unit == "KG" else "Pound",
        "weightLb": weight,
        "facilities": facilities,
    }
    sample_id = (
        "material-part-equivalent-kg"
        if index == 0
        else "material-part-equivalent-lb"
        if index == 1
        else f"material-part-{index + 1:03d}"
    )
    return {"id": sample_id, "input": input_doc, "expected": expected}


def _crm_erp_sample(rng: random.Random, index: int) -> JsonObject:
    def address(role: str) -> dict[str, str]:
        return {
            "street": f"{index + 1} {role} Street",
            "city": f"City{index % 5}",
            "region": f"Region{index % 3}",
            "postalCode": f"{10000 + index:05d}",
            "country": "US",
        }

    input_doc = {
        "customerId": f"CUS-{index + 1:05d}",
        "name": f"Customer {index + 1}",
        "soldToAddress": address("SoldTo"),
        "shipToAddress": address("ShipTo"),
        "billToAddress": address("BillTo"),
        "payerId": f"PAY-{index + 1:05d}",
        "email": f"customer{index + 1}@example.com",
    }
    expected = {
        "businessPartnerId": input_doc["customerId"],
        "displayName": input_doc["name"],
        "primaryAddress": input_doc["shipToAddress"],
        "billingAddress": input_doc["billToAddress"],
        "contactEmail": input_doc["email"],
        "payerBusinessPartnerId": input_doc["payerId"],
    }
    return {"id": f"crm-erp-{index + 1:03d}", "input": input_doc, "expected": expected}


def _account_segment_sample(rng: random.Random, index: int) -> JsonObject:
    segments = [f"{rng.randint(0, 999999):06d}" for _ in range(10)]
    if index == 0:
        segments = [f"{item:06d}" for item in range(1, 11)]
    input_doc = {
        "segments": {f"segment{i + 1:02d}": segments[i] for i in range(10)},
        "effectiveDate": "2026-08-11",
        "currency": "USD",
    }
    expected = {
        "company": segments[0],
        "costCenter": f"{segments[3]}-{segments[4]}",
        "account": segments[6] + segments[7] + segments[8],
        "effectiveDate": input_doc["effectiveDate"],
        "currency": input_doc["currency"],
    }
    sample_id = (
        "account-segments-leading-zero" if index == 0 else f"account-segments-{index + 1:03d}"
    )
    return {"id": sample_id, "input": input_doc, "expected": expected}


def _order_fulfillment_sample(rng: random.Random, index: int) -> JsonObject:
    line_count = 1 + index % 20
    lines: list[JsonObject] = []
    for line_index in range(line_count):
        unit = "DZ" if (line_index + index) % 3 == 0 else "EA"
        lines.append(
            {
                "lineNumber": line_index + 1,
                "sku": f"SKU-{rng.randint(1000, 9999)}",
                "orderedQuantity": 1 + (line_index + index) % 24,
                "unit": unit,
                "warehouse": f"WH-{line_index % 4 + 1}",
            }
        )
    input_doc = {
        "orderNumber": f"SO-{index + 1:05d}",
        "customer": {"id": f"CUST-{index % 20 + 1:04d}"},
        "requestedShipDate": _iso(index, "Z"),
        "items": lines,
    }
    expected_lines = [
        {
            "lineNumber": line["lineNumber"],
            "partNumber": line["sku"],
            "quantityEach": cast(int, line["orderedQuantity"])
            * (12 if line["unit"] == "DZ" else 1),
            "facility": line["warehouse"],
        }
        for line in lines
    ]
    expected = {
        "requestId": input_doc["orderNumber"],
        "customerId": cast(JsonObject, input_doc["customer"])["id"],
        "shipDate": input_doc["requestedShipDate"],
        "lines": expected_lines,
    }
    return {"id": f"order-fulfillment-{index + 1:03d}", "input": input_doc, "expected": expected}


GENERATORS: dict[str, tuple[SampleGenerator, int, int]] = {
    "erp-mes": (_erp_mes_sample, 100, 20260811),
    "material-part": (_material_part_sample, 60, 20260812),
    "crm-erp": (_crm_erp_sample, 50, 20260813),
    "account-segments": (_account_segment_sample, 80, 20260814),
    "order-fulfillment": (_order_fulfillment_sample, 70, 20260815),
}


def _material_part_negatives() -> list[JsonObject]:
    return [
        {
            "id": "material-part-unsupported-unit",
            "input": {
                "materialNumber": "MP-UNSUPPORTED",
                "materialDescription": "Unsupported unit",
                "partDescription": "Unsupported legacy unit",
                "baseUnit": "OZ",
                "grossWeight": {"value": 1, "unit": "OZ"},
                "plantData": [
                    {"plant": "P1", "status": "ACT"},
                    {"plant": "P2", "status": "INA"},
                ],
            },
            "expected_error": "SOURCE_SCHEMA_VALIDATION",
        }
    ]


def _account_segment_negatives() -> list[JsonObject]:
    base = {f"segment{item:02d}": f"{item:06d}" for item in range(1, 11)}
    missing = dict(base)
    del missing["segment10"]
    malformed = dict(base)
    malformed["segment01"] = "12345"
    return [
        {
            "id": "account-segments-missing-segment",
            "input": {"segments": missing, "effectiveDate": "2026-08-11", "currency": "USD"},
            "expected_error": "SOURCE_SCHEMA_VALIDATION",
        },
        {
            "id": "account-segments-malformed-length",
            "input": {"segments": malformed, "effectiveDate": "2026-08-11", "currency": "USD"},
            "expected_error": "SOURCE_SCHEMA_VALIDATION",
        },
    ]


def _order_line(line_number: int) -> JsonObject:
    return {
        "lineNumber": line_number,
        "sku": f"SKU-{line_number:05d}",
        "orderedQuantity": 1,
        "unit": "EA",
        "warehouse": "WH-1",
    }


def _order_fulfillment_negatives() -> list[JsonObject]:
    common = {
        "customer": {"id": "CUST-NEG"},
        "requestedShipDate": "2026-08-11T08:30:00.000Z",
    }
    return [
        {
            "id": "order-fulfillment-array-limit",
            "input": {
                **common,
                "orderNumber": "SO-LIMIT",
                "items": [_order_line(item) for item in range(1, 10_002)],
            },
            "expected_error": "EVALUATION_LIMIT_EXCEEDED",
        },
        {
            "id": "order-fulfillment-duplicate-line",
            "input": {
                **common,
                "orderNumber": "SO-DUPLICATE",
                "items": [_order_line(1), _order_line(1)],
            },
            "expected_error": "INVARIANT_FAILED",
        },
    ]


NEGATIVE_GENERATORS: dict[str, Callable[[], list[JsonObject]]] = {
    "material-part": _material_part_negatives,
    "account-segments": _account_segment_negatives,
    "order-fulfillment": _order_fulfillment_negatives,
}


def render_samples(benchmark: str) -> str:
    generator, count, seed = GENERATORS[benchmark]
    rng = random.Random(seed)
    samples = [generator(rng, index) for index in range(count)]
    if benchmark in NEGATIVE_GENERATORS:
        samples.extend(NEGATIVE_GENERATORS[benchmark]())
    return "".join(
        json.dumps(sample, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for sample in samples
    )


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "--benchmark":
        print("usage: generate_benchmark_samples.py --benchmark NAME [--check]", file=sys.stderr)
        return 2
    benchmark = sys.argv[2]
    if benchmark not in GENERATORS:
        print(f"unknown benchmark {benchmark!r}", file=sys.stderr)
        return 2
    content = render_samples(benchmark)
    path = BENCHMARK_ROOT / benchmark / "samples.jsonl"
    if "--check" in sys.argv:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            print(f"{path}: mismatch", file=sys.stderr)
            return 1
        print(f"{path}: ok")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
