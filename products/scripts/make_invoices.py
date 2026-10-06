"""Turn UCI Online Retail II into the invoice totals ledger-brain reconciles.

Run once. The source is a 45 MB spreadsheet; what this product needs from it is
one row per invoice, so the committed artefact is ~1 MB of CSV and the product
itself reads it with the standard library.

    python scripts/make_invoices.py

Amounts are in minor units (pence). Floats do not belong in money, and the
equal-amount question this product exists to ask is exactly the one that a
rounding difference would quietly answer for you.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "online_retail_ii.zip"
OUT = ROOT / "data" / "invoices.csv"


def main() -> int:
    try:
        import openpyxl
    except ImportError:
        print("openpyxl is needed for this one-off conversion: uv pip install openpyxl")
        return 1

    if not SOURCE.exists():
        print(f"{SOURCE} is missing")
        return 1

    import zipfile

    with zipfile.ZipFile(SOURCE) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".xlsx"))
        extracted = ROOT / "data" / "_online_retail.xlsx"
        extracted.write_bytes(zf.read(name))

    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    meta: dict[tuple[str, str], tuple[str, str, str]] = {}
    lines: dict[tuple[str, str], int] = defaultdict(int)

    book = openpyxl.load_workbook(extracted, read_only=True, data_only=True)
    for sheet in book.worksheets:
        rows = sheet.iter_rows(values_only=True)
        header = [str(h).strip() if h else "" for h in next(rows)]
        idx = {h.lower().replace(" ", ""): i for i, h in enumerate(header)}
        c_inv = idx.get("invoice", idx.get("invoiceno", 0))
        c_qty = idx.get("quantity", 3)
        c_price = idx.get("price", idx.get("unitprice", 5))
        c_date = idx.get("invoicedate", 4)
        c_cust = idx.get("customerid", 6)
        c_country = idx.get("country", 7)

        for row in rows:
            invoice = str(row[c_inv]).strip() if row[c_inv] is not None else ""
            if not invoice:
                continue
            key = (sheet.title, invoice)
            try:
                qty = int(row[c_qty] or 0)
                price = Decimal(str(row[c_price] or 0))
            except (TypeError, ValueError, ArithmeticError):
                continue
            totals[key] += Decimal(qty) * price
            lines[key] += 1
            if key not in meta:
                meta[key] = (
                    str(row[c_date])[:19],
                    str(row[c_cust] or "").split(".")[0],
                    str(row[c_country] or ""),
                )
    book.close()
    extracted.unlink()

    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["sheet", "invoice", "amount_minor", "lines", "date", "customer", "country"]
        )
        for key in sorted(totals):
            date, customer, country = meta[key]
            minor = int((totals[key] * 100).to_integral_value())
            writer.writerow([key[0], key[1], minor, lines[key], date, customer, country])

    print(f"wrote {OUT} — {len(totals):,} invoices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
