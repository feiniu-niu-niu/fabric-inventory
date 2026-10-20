"""布料库存：商品、出入库、汇总，以及可扩展字段。"""

import json
import os
import sqlite3
import sys
from datetime import datetime


def app_dir():
    """程序数据目录：开发时为源码目录；打包后为 exe/.app 所在文件夹。"""
    if getattr(sys, "frozen", False):
        path = os.path.dirname(sys.executable)
        # macOS .app → 把数据放在 .app 旁边，避免写进应用包内部
        if sys.platform == "darwin" and path.endswith("MacOS"):
            return os.path.dirname(os.path.dirname(os.path.dirname(path)))
        return path
    return os.path.dirname(os.path.abspath(__file__))


def db_path():
    return os.path.join(app_dir(), "库存数据.db")


PRODUCT_FIELDS = [
    ("product_model", "产品型号", "text", True),
    ("color", "颜色", "text", False),
    ("unit_price", "单价", "number", False),
]

QTY_LABEL = "数量（米）"
STOCK_LABEL = "当前库存（米）"
SUMMARY_PRICE_LABEL = "单价"
INDEX_LABEL = "序号"


class InventoryError(Exception):
    pass


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _loads(text):
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dumps(data):
    return json.dumps(data or {}, ensure_ascii=False)


def format_number(value):
    if value is None or value == "":
        return ""
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return text


def parse_number(value, label, required=False):
    text = "" if value is None else str(value).strip()
    if text == "":
        if required:
            raise InventoryError(f"请填写{label}")
        return None
    try:
        number = float(text)
    except ValueError:
        raise InventoryError(f"{label}请填写数字")
    return number


def _join_model_parts(*parts):
    return " ".join(part.strip() for part in parts if part and str(part).strip())


class Database:
    def __init__(self, path=None):
        self.path = path or db_path()
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self):
        self.conn.close()

    def _table_columns(self, table):
        return {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def _ensure_column(self, table, column, decl):
        if column not in self._table_columns(table):
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def _migrate(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                product_model TEXT NOT NULL DEFAULT '',
                product_type TEXT NOT NULL DEFAULT '',
                product_code TEXT NOT NULL DEFAULT '',
                length TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '',
                unit_price REAL,
                extra TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                txn_date TEXT NOT NULL,
                io_type TEXT NOT NULL,
                product_id INTEGER,
                product_model TEXT NOT NULL DEFAULT '',
                product_type TEXT NOT NULL DEFAULT '',
                product_code TEXT NOT NULL DEFAULT '',
                length TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '',
                unit_price REAL,
                quantity REAL NOT NULL,
                remark TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS field_defs (
                id INTEGER PRIMARY KEY,
                scope TEXT NOT NULL,
                field_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                data_type TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # 兼容旧库：补齐产品型号列，并从「类型+编号」合并
        self._ensure_column("products", "product_model", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("transactions", "product_model", "TEXT NOT NULL DEFAULT ''")
        self._migrate_product_model_data()
        self.conn.execute("DROP INDEX IF EXISTS idx_product_identity")
        self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_product_identity
            ON products(product_model, color)
            """
        )
        self.conn.commit()

    def _migrate_product_model_data(self):
        for row in self.conn.execute(
            "SELECT id, product_model, product_type, product_code FROM products"
        ):
            if (row["product_model"] or "").strip():
                continue
            model = _join_model_parts(row["product_type"], row["product_code"])
            if model:
                self.conn.execute(
                    "UPDATE products SET product_model = ? WHERE id = ?",
                    (model, row["id"]),
                )
        for row in self.conn.execute(
            """
            SELECT id, product_model, product_type, product_code, product_id
            FROM transactions
            """
        ):
            if (row["product_model"] or "").strip():
                continue
            model = _join_model_parts(row["product_type"], row["product_code"])
            if not model and row["product_id"]:
                prod = self.conn.execute(
                    "SELECT product_model FROM products WHERE id = ?",
                    (row["product_id"],),
                ).fetchone()
                if prod:
                    model = prod["product_model"] or ""
            if model:
                self.conn.execute(
                    "UPDATE transactions SET product_model = ? WHERE id = ?",
                    (model, row["id"]),
                )

    def custom_fields(self, scope=None):
        sql = "SELECT * FROM field_defs"
        args = []
        if scope:
            sql += " WHERE scope = ?"
            args.append(scope)
        sql += " ORDER BY sort_order, id"
        return [dict(row) for row in self.conn.execute(sql, args)]

    def add_field(self, scope, label, data_type):
        label = (label or "").strip()
        if scope not in ("product", "txn"):
            raise InventoryError("字段要加在商品或出入库上")
        if data_type not in ("text", "number"):
            raise InventoryError("字段类型只能是文本或数字")
        if not label:
            raise InventoryError("请填写字段名称")
        builtin = {item[1] for item in PRODUCT_FIELDS}
        builtin.update(
            {
                "日期",
                "类型",
                "类型（入库/出库）",
                "产品型号",
                "单价",
                "数量",
                QTY_LABEL,
                "备注",
                "当前库存数",
                STOCK_LABEL,
                INDEX_LABEL,
            }
        )
        if label in builtin:
            raise InventoryError("这个名称和现有列重复")
        exists = self.conn.execute(
            "SELECT 1 FROM field_defs WHERE label = ? AND scope = ?",
            (label, scope),
        ).fetchone()
        if exists:
            raise InventoryError("已经有同名的自定义列")
        order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM field_defs WHERE scope = ?",
            (scope,),
        ).fetchone()[0]
        cur = self.conn.execute(
            """
            INSERT INTO field_defs(scope, field_key, label, data_type, sort_order, created_at)
            VALUES (?, '', ?, ?, ?, ?)
            """,
            (scope, label, data_type, order, _now()),
        )
        field_key = f"c{cur.lastrowid}"
        self.conn.execute(
            "UPDATE field_defs SET field_key = ? WHERE id = ?",
            (field_key, cur.lastrowid),
        )
        self.conn.commit()
        return field_key

    def rename_field(self, field_id, label):
        label = (label or "").strip()
        if not label:
            raise InventoryError("请填写字段名称")
        row = self.conn.execute(
            "SELECT * FROM field_defs WHERE id = ?", (field_id,)
        ).fetchone()
        if row is None:
            raise InventoryError("找不到这个字段")
        exists = self.conn.execute(
            "SELECT 1 FROM field_defs WHERE label = ? AND scope = ? AND id <> ?",
            (label, row["scope"], field_id),
        ).fetchone()
        if exists:
            raise InventoryError("已经有同名的自定义列")
        self.conn.execute(
            "UPDATE field_defs SET label = ? WHERE id = ?", (label, field_id)
        )
        self.conn.commit()

    def delete_field(self, field_id):
        self.conn.execute("DELETE FROM field_defs WHERE id = ?", (field_id,))
        self.conn.commit()

    def move_field(self, field_id, direction):
        row = self.conn.execute(
            "SELECT * FROM field_defs WHERE id = ?", (field_id,)
        ).fetchone()
        if row is None:
            return
        if direction < 0:
            other = self.conn.execute(
                """
                SELECT * FROM field_defs
                WHERE scope = ? AND sort_order < ?
                ORDER BY sort_order DESC, id DESC LIMIT 1
                """,
                (row["scope"], row["sort_order"]),
            ).fetchone()
        else:
            other = self.conn.execute(
                """
                SELECT * FROM field_defs
                WHERE scope = ? AND sort_order > ?
                ORDER BY sort_order, id LIMIT 1
                """,
                (row["scope"], row["sort_order"]),
            ).fetchone()
        if other is None:
            return
        self.conn.execute(
            "UPDATE field_defs SET sort_order = ? WHERE id = ?",
            (other["sort_order"], row["id"]),
        )
        self.conn.execute(
            "UPDATE field_defs SET sort_order = ? WHERE id = ?",
            (row["sort_order"], other["id"]),
        )
        self.conn.commit()

    def _clean_extra(self, raw, fields):
        extra = {}
        source = raw or {}
        for field in fields:
            key = field["field_key"]
            value = source.get(key, "")
            if field["data_type"] == "number":
                extra[key] = parse_number(value, field["label"], required=False)
            else:
                extra[key] = "" if value is None else str(value).strip()
        return extra

    def _product_payload(self, data):
        payload = {}
        for key, label, data_type, required in PRODUCT_FIELDS:
            value = data.get(key, "")
            if data_type == "number":
                payload[key] = parse_number(value, label, required=required)
            else:
                text = "" if value is None else str(value).strip()
                if required and not text:
                    raise InventoryError(f"请填写{label}")
                payload[key] = text
        payload["extra"] = self._clean_extra(data.get("extra"), self.custom_fields("product"))
        return payload

    def _sync_transactions_from_product(self, product_id, payload):
        rows = self.conn.execute(
            "SELECT id, extra FROM transactions WHERE product_id = ?",
            (product_id,),
        ).fetchall()
        product_keys = {field["field_key"] for field in self.custom_fields("product")}
        for row in rows:
            old = _loads(row["extra"])
            kept = {key: value for key, value in old.items() if key not in product_keys}
            kept.update(payload["extra"])
            self.conn.execute(
                """
                UPDATE transactions
                SET product_model = ?, color = ?, extra = ?
                WHERE id = ?
                """,
                (
                    payload["product_model"],
                    payload["color"],
                    _dumps(kept),
                    row["id"],
                ),
            )

    def save_product(self, data, product_id=None):
        payload = self._product_payload(data)
        identity = (payload["product_model"], payload["color"])
        dup_sql = """
            SELECT id FROM products
            WHERE product_model = ? AND color = ?
        """
        args = list(identity)
        if product_id:
            dup_sql += " AND id <> ?"
            args.append(product_id)
        if self.conn.execute(dup_sql, args).fetchone():
            raise InventoryError("已有相同的产品型号、颜色")
        values = (
            payload["product_model"],
            payload["color"],
            payload["unit_price"],
            _dumps(payload["extra"]),
        )
        if product_id:
            self.conn.execute(
                """
                UPDATE products
                SET product_model = ?, color = ?, unit_price = ?, extra = ?
                WHERE id = ?
                """,
                (*values, product_id),
            )
            self._sync_transactions_from_product(product_id, payload)
        else:
            cur = self.conn.execute(
                """
                INSERT INTO products(
                    product_model, color, unit_price, extra, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (*values, _now()),
            )
            product_id = cur.lastrowid
        self.conn.commit()
        return product_id

    def delete_product(self, product_id):
        used = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE product_id = ?",
            (product_id,),
        ).fetchone()[0]
        if used:
            raise InventoryError("这件布料已有出入库记录，不能删除")
        self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.conn.commit()

    def get_product(self, product_id):
        row = self.conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return self._product_dict(row) if row else None

    def _product_dict(self, row):
        item = dict(row)
        item["extra"] = _loads(item.get("extra"))
        if not (item.get("product_model") or "").strip():
            item["product_model"] = _join_model_parts(
                item.get("product_type"), item.get("product_code")
            )
        return item

    def list_products(self, keyword=""):
        keyword = (keyword or "").strip()
        rows = self.conn.execute(
            """
            SELECT * FROM products
            ORDER BY product_model, color, id
            """
        ).fetchall()
        items = [self._product_dict(row) for row in rows]
        if not keyword:
            return items
        return [item for item in items if keyword in self.product_text(item)]

    def product_text(self, product):
        parts = [
            product.get("product_model") or "",
            product.get("color") or "",
        ]
        for field in self.custom_fields("product"):
            parts.append(self.extra_text(product.get("extra"), field))
        return " ".join(part for part in parts if part)

    def product_label(self, product):
        parts = [
            product.get("product_model") or "",
            product.get("color") or "",
        ]
        return " / ".join(part if part else "-" for part in parts)

    def extra_text(self, extra, field):
        extra = extra or {}
        value = extra.get(field["field_key"])
        if field["data_type"] == "number":
            return format_number(value)
        return "" if value is None else str(value)

    def _stock_map(self, exclude_txn_id=None):
        sql = """
            SELECT product_id,
                   SUM(CASE WHEN io_type = '入库' THEN quantity ELSE -quantity END) AS stock
            FROM transactions
            WHERE product_id IS NOT NULL
        """
        args = []
        if exclude_txn_id:
            sql += " AND id <> ?"
            args.append(exclude_txn_id)
        sql += " GROUP BY product_id"
        return {
            row["product_id"]: row["stock"] or 0
            for row in self.conn.execute(sql, args)
        }

    def stock_of(self, product_id, exclude_txn_id=None):
        return self._stock_map(exclude_txn_id).get(product_id, 0) or 0

    def list_transactions(self, date_from="", date_to="", io_type="", keyword=""):
        sql = "SELECT * FROM transactions WHERE 1 = 1"
        args = []
        if date_from:
            sql += " AND txn_date >= ?"
            args.append(date_from)
        if date_to:
            sql += " AND txn_date <= ?"
            args.append(date_to)
        if io_type in ("入库", "出库"):
            sql += " AND io_type = ?"
            args.append(io_type)
        sql += " ORDER BY txn_date DESC, id DESC"
        rows = [self._txn_dict(row) for row in self.conn.execute(sql, args)]
        keyword = (keyword or "").strip()
        if not keyword:
            return rows
        result = []
        for item in rows:
            blob = " ".join(
                [
                    item["txn_date"],
                    item["io_type"],
                    item.get("product_model") or "",
                    item["color"],
                    item["remark"] or "",
                    format_number(item["unit_price"]),
                    format_number(item["quantity"]),
                ]
            )
            for field in self.custom_fields():
                blob += " " + self.extra_text(item["extra"], field)
            if keyword in blob:
                result.append(item)
        return result

    def _txn_dict(self, row):
        item = dict(row)
        item["extra"] = _loads(item.get("extra"))
        if not (item.get("product_model") or "").strip():
            item["product_model"] = _join_model_parts(
                item.get("product_type"), item.get("product_code")
            )
        return item

    def get_transaction(self, txn_id):
        row = self.conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        return self._txn_dict(row) if row else None

    def save_transaction(self, data, txn_id=None):
        product = self.get_product(data.get("product_id"))
        if product is None:
            raise InventoryError("请先选择布料")
        txn_date = str(data.get("txn_date") or "").strip()
        if len(txn_date) != 10 or txn_date[4] != "-" or txn_date[7] != "-":
            raise InventoryError("日期请按 年-月-日 填写，例如 2026-10-19")
        try:
            datetime.strptime(txn_date, "%Y-%m-%d")
        except ValueError:
            raise InventoryError("日期不正确")
        io_type = data.get("io_type")
        if io_type not in ("入库", "出库"):
            raise InventoryError("类型请选择入库或出库")
        quantity = parse_number(data.get("quantity"), QTY_LABEL, required=True)
        if quantity <= 0:
            raise InventoryError(f"{QTY_LABEL}要大于 0")
        unit_price = parse_number(data.get("unit_price"), "单价", required=False)
        remark = "" if data.get("remark") is None else str(data.get("remark")).strip()
        txn_extra = self._clean_extra(data.get("txn_extra"), self.custom_fields("txn"))
        extra = dict(product["extra"])
        extra.update(txn_extra)
        available = self.stock_of(product["id"], exclude_txn_id=txn_id)
        if io_type == "出库" and quantity - available > 1e-9:
            raise InventoryError(
                f"库存不够，多半是之前记错了。当前还可出库 {format_number(available)} 米"
            )
        values = (
            txn_date,
            io_type,
            product["id"],
            product["product_model"],
            product["color"],
            unit_price,
            quantity,
            remark,
            _dumps(extra),
        )
        if txn_id:
            self.conn.execute(
                """
                UPDATE transactions
                SET txn_date = ?, io_type = ?, product_id = ?, product_model = ?,
                    color = ?, unit_price = ?, quantity = ?, remark = ?, extra = ?
                WHERE id = ?
                """,
                (*values, txn_id),
            )
        else:
            cur = self.conn.execute(
                """
                INSERT INTO transactions(
                    txn_date, io_type, product_id, product_model, color,
                    unit_price, quantity, remark, extra, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, _now()),
            )
            txn_id = cur.lastrowid
        self.conn.commit()
        return txn_id

    def delete_transaction(self, txn_id):
        row = self.get_transaction(txn_id)
        if row is None:
            return
        if row["io_type"] == "入库" and row["product_id"]:
            remaining = self.stock_of(row["product_id"], exclude_txn_id=txn_id)
            if remaining < -1e-9:
                raise InventoryError("删掉这笔入库后库存会变成负数，请先改出库记录")
        self.conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        self.conn.commit()

    def summary(self, hide_zero=False, keyword=""):
        stocks = self._stock_map()
        rows = []
        for product in self.list_products(keyword):
            stock = stocks.get(product["id"], 0) or 0
            if hide_zero and abs(stock) < 1e-9:
                continue
            item = dict(product)
            item["stock"] = stock
            rows.append(item)
        return rows
