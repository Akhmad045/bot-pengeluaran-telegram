"""Isi format Excel bawaan dengan catatan pengguna, tanpa dependensi server tambahan."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("x", NS)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
TEMPLATE = Path(__file__).resolve().parent / "assets" / "rekap-template.xlsx"


def tag(name):
    return "{" + NS + "}" + name


def excel_date(value: date) -> int:
    serial = (value - date(1899, 12, 30)).days
    return serial - 1 if value < date(1900, 3, 1) else serial


def put(cell, value, formula=None):
    for child in list(cell):
        cell.remove(child)
    cell.attrib.pop("t", None)
    if formula is not None:
        ET.SubElement(cell, tag("f")).text = formula.lstrip("=")
        ET.SubElement(cell, tag("v")).text = str(value)
    elif isinstance(value, (int, float)):
        ET.SubElement(cell, tag("v")).text = str(value)
    elif value is not None:
        # inlineStr menjaga keterangan berawalan = / + / @ tetap berupa teks.
        cell.set("t", "inlineStr")
        content = ET.SubElement(ET.SubElement(cell, tag("is")), tag("t"))
        content.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        content.text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", str(value))


def update(root, address, value, formula=None):
    cell = root.find(f".//{tag('c')}[@r='{address}']")
    if cell is None:
        raise ValueError("Format Excel tidak lengkap. Gunakan folder assets dari paket terbaru.")
    put(cell, value, formula)


def clone_row(prototype, number, values, formulas=None):
    row = deepcopy(prototype)
    row.set("r", str(number))
    formulas = formulas or {}
    for cell in row.findall(tag("c")):
        column = re.sub(r"[0-9]", "", cell.get("r"))
        cell.set("r", f"{column}{number}")
        put(cell, values.get(column), formulas.get(column))
    return row


def build_excel(rows, start: date, end: date, period_label: str, zone_name: str) -> bytes:
    if len(rows) > 1048500:
        raise ValueError("Catatan terlalu banyak untuk satu file Excel. Pilih periode lebih pendek.")
    try:
        with ZipFile(TEMPLATE) as source:
            parts = {name: source.read(name) for name in source.namelist()}
    except (OSError, ValueError):
        raise ValueError("Format Excel tidak ditemukan. Salin folder assets dari paket bot terbaru.") from None
    summary = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    detail = ET.fromstring(parts["xl/worksheets/sheet2.xml"])
    update(summary, "A3", period_label)
    update(summary, "D3", f"Zona waktu: {zone_name}")
    update(detail, "A4", period_label)
    last = max(8, 7 + len(rows))
    amount_range = f"'Transaksi'!$E$8:$E${last}"
    total = sum(row["amount"] for row in rows)
    update(summary, "B5", total, f"SUM({amount_range})")
    update(summary, "B6", len(rows), f"COUNT({amount_range})")
    detail_data = detail.find(tag("sheetData"))
    prototype = detail_data.find(f"{tag('row')}[@r='8']")
    for row in list(detail_data):
        if int(row.get("r")) >= 8:
            detail_data.remove(row)
    for index, record in enumerate(rows, 8):
        row = clone_row(prototype, index, {
            "A": str(record["id"]), "B": excel_date(date.fromisoformat(record["spent_on"])),
            "C": record["note"], "D": record["category"], "E": record["amount"],
            "F": record['wallet_name'] if 'wallet_name' in record.keys() else ''})
        row.set("ht", str(max(24, 15 * ((len(record["note"]) + 49)//50),
                              15 * ((len(record["category"]) + 19)//20))))
        row.set("customHeight", "1")
        detail_data.append(row)
    if not rows:
        detail_data.append(clone_row(prototype, 8, {}))
    # Filter hanya mengenai rincian transaksi, tidak termasuk judul dan catatan.
    autofilter = ET.Element(tag("autoFilter"), {"ref": f"A7:F{last}"})
    detail.insert(list(detail).index(detail_data) + 1, autofilter)

    days, categories = defaultdict(int), defaultdict(int)
    for row in rows:
        days[row["spent_on"]] += row["amount"]
        categories[row["category"]] += row["amount"]
    category_items = sorted(categories.items(), key=lambda x: (-x[1], x[0]))
    summary_data = summary.find(tag("sheetData"))
    proto_summary = summary_data.find(f"{tag('row')}[@r='9']")
    for row in list(summary_data):
        if int(row.get("r")) >= 9:
            summary_data.remove(row)
    length = max((end-start).days, len(category_items), 1)
    for index in range(length):
        number = index + 9
        values, formulas = {}, {}
        if index < (end-start).days:
            day = start + timedelta(days=index)
            values.update(A=excel_date(day), B=days[day.isoformat()])
            formulas["B"] = f"SUMIFS({amount_range},'Transaksi'!$B$8:$B${last},A{number})"
        if index < len(category_items):
            name, amount = category_items[index]
            values.update(D=name, E=amount)
            criterion = f'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE(D{number},"~","~~"),"*","~*"),"?","~?")'
            formulas["E"] = f'SUMIFS({amount_range},\'Transaksi\'!$D$8:$D${last},"="&{criterion})'
        elif index == 0 and not category_items:
            values["D"] = "Belum ada catatan"
        summary_data.append(clone_row(proto_summary, number, values, formulas))

    workbook = ET.fromstring(parts["xl/workbook.xml"])
    props = workbook.find(tag("calcPr"))
    if props is None:
        props = ET.SubElement(workbook, tag("calcPr"))
    props.attrib.update(calcMode="auto", fullCalcOnLoad="1", forceFullCalc="1")
    parts["xl/workbook.xml"] = ET.tostring(workbook, encoding="utf-8", xml_declaration=True)
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(summary, encoding="utf-8", xml_declaration=True)
    parts["xl/worksheets/sheet2.xml"] = ET.tostring(detail, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()
