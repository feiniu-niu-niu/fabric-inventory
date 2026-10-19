"""导出三张表到 Excel。"""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from database import (
    PRODUCT_FIELDS,
    QTY_LABEL,
    STOCK_LABEL,
    SUMMARY_PRICE_LABEL,
    format_number,
)


def _style_header(ws):
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _autosize(ws):
    for column in ws.columns:
        letter = column[0].column_letter
        width = 10
        for cell in column:
            value = "" if cell.value is None else str(cell.value)
            width = max(width, min(len(value) + 4, 40))
        ws.column_dimensions[letter].width = width


def export_excel(db, path):
    product_customs = db.custom_fields("product")
    txn_customs = db.custom_fields("txn")
    wb = Workbook()

    # 商品基础信息表
    ws1 = wb.active
    ws1.title = "商品基础信息表"
    headers1 = [label for _, label, _, _ in PRODUCT_FIELDS] + [
        f["label"] for f in product_customs
    ]
    ws1.append(headers1)
    for item in db.list_products():
        row = []
        for key, _, data_type, _ in PRODUCT_FIELDS:
            value = item.get(key)
            row.append(format_number(value) if data_type == "number" else (value or ""))
        for field in product_customs:
            row.append(db.extra_text(item.get("extra"), field))
        ws1.append(row)
    _style_header(ws1)
    _autosize(ws1)

    # 出入库流水表
    ws2 = wb.create_sheet("出入库流水表")
    headers2 = [
        "日期",
        "类型（入库/出库）",
        "商品类型",
        "商品编号",
        "长度",
        "颜色",
        "单价",
        QTY_LABEL,
        "备注",
    ]
    headers2 += [f["label"] for f in product_customs]
    headers2 += [f["label"] for f in txn_customs]
    ws2.append(headers2)
    for item in db.list_transactions():
        row = [
            item["txn_date"],
            item["io_type"],
            item["product_type"] or "",
            item["product_code"] or "",
            item["length"] or "",
            item["color"] or "",
            format_number(item["unit_price"]),
            format_number(item["quantity"]),
            item["remark"] or "",
        ]
        for field in product_customs:
            row.append(db.extra_text(item.get("extra"), field))
        for field in txn_customs:
            row.append(db.extra_text(item.get("extra"), field))
        ws2.append(row)
    _style_header(ws2)
    _autosize(ws2)

    # 库存汇总表
    ws3 = wb.create_sheet("库存汇总表")
    headers3 = ["商品类型", "商品编号", "长度", "颜色", STOCK_LABEL, SUMMARY_PRICE_LABEL]
    headers3 += [f["label"] for f in product_customs]
    ws3.append(headers3)
    for item in db.summary(hide_zero=False):
        row = [
            item["product_type"] or "",
            item["product_code"] or "",
            item["length"] or "",
            item["color"] or "",
            format_number(item["stock"]),
            format_number(item.get("unit_price")),
        ]
        for field in product_customs:
            row.append(db.extra_text(item.get("extra"), field))
        ws3.append(row)
    _style_header(ws3)
    _autosize(ws3)

    wb.save(path)
    return path
