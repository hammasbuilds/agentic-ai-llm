"""Extract a product price table from UCI Online Retail II.

Run once, alongside `make_invoices.py`. The same spreadsheet holds every line
item, so the same product appears many times at many prices — which is the real
phenomenon shelf-ops is about: a catalogue does not have "a price", it has a
distribution, and a repricing agent is moving within one.

Amounts are in minor units. The committed artefact is one row per product.
"""

from __future__ import annotations

import csv
import statistics
import zipfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "online_retail_ii.zip"
OUT = ROOT / "data" / "prices.csv"

MIN_SALES = 5  # a product sold four times has no price distribution worth the row


def main() -> int:
    try:
        import openpyxl
    except ImportError:
        print("openpyxl is needed for this one-off conversion: uv pip install openpyxl")
        return 1
    if not SOURCE.exists():
        print(f"{SOURCE} is missing")
        return 1

    with zipfile.ZipFile(SOURCE) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".xlsx"))
        extracted = ROOT / "data" / "_online_retail.xlsx"
        extracted.write_bytes(zf.read(name))

    prices: dict[str, list[int]] = defaultdict(list)
    names: dict[str, str] = {}
    units: dict[str, int] = defaultdict(int)

    book = openpyxl.load_workbook(extracted, read_only=True, data_only=True)
    for sheet in book.worksheets:
        rows = sheet.iter_rows(values_only=True)
        header = [str(h).strip().lower().replace(" ", "") if h else "" for h in next(rows)]
        idx = {h: i for i, h in enumerate(header)}
        c_code = idx.get("stockcode", 1)
        c_desc = idx.get("description", 2)
        c_qty = idx.get("quantity", 3)
        c_price = idx.get("price", idx.get("unitprice", 5))

        for row in rows:
            code = str(row[c_code]).strip() if row[c_code] is not None else ""
            if not code:
                continue
            try:
                qty = int(row[c_qty] or 0)
                price = Decimal(str(row[c_price] or 0))
            except (TypeError, ValueError, ArithmeticError):
                continue
            if qty <= 0 or price <= 0:
                continue  # returns and zero-priced giveaways are not a price point
            prices[code].append(int((price * 100).to_integral_value()))
            units[code] += qty
            if code not in names and row[c_desc]:
                names[code] = str(row[c_desc]).strip()
    book.close()
    extracted.unlink()

    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["code", "description", "sales", "units", "modal", "min", "max", "median"])
        kept = 0
        for code, points in sorted(prices.items()):
            if len(points) < MIN_SALES:
                continue
            writer.writerow(
                [
                    code,
                    names.get(code, ""),
                    len(points),
                    units[code],
                    statistics.mode(points),
                    min(points),
                    max(points),
                    int(statistics.median(points)),
                ]
            )
            kept += 1

    print(f"wrote {OUT} — {kept:,} products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
