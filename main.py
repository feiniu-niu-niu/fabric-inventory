"""布料出入库桌面程序。"""

import calendar
import tkinter as tk
import tkinter.font as tkfont
from datetime import date
from tkinter import filedialog, messagebox, ttk

# 界面字号：通用 12，页签 13，表格 12
UI_FONT_SIZE = 12
TAB_FONT_SIZE = 13
TABLE_FONT_SIZE = 12

from database import (
    INDEX_LABEL,
    PRODUCT_FIELDS,
    QTY_LABEL,
    STOCK_LABEL,
    Database,
    InventoryError,
    format_number,
)
from export import export_excel, export_products, export_summary, export_transactions


def ask_error(err):
    messagebox.showerror("提示", str(err))


def center_on_parent(window, parent):
    """把弹窗放到主窗口正中间。"""
    window.update_idletasks()
    if parent is None:
        return
    parent.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    x = px + max((pw - width) // 2, 0)
    y = py + max((ph - height) // 2, 0)
    window.geometry(f"+{x}+{y}")


def focusable_of(widget):
    """取可聚焦的输入控件（兼容 DatePicker 等包装）。"""
    entry = getattr(widget, "entry", None)
    if entry is not None:
        return entry
    return widget


def _focus_input(target):
    target.focus_set()
    try:
        if isinstance(target, (ttk.Entry, tk.Entry, ttk.Combobox)):
            target.select_range(0, "end")
            target.icursor("end")
    except tk.TclError:
        pass


def bind_field_nav(widgets):
    """弹框里按 ↓ / ↑ 在输入框间跳转；鼠标点击仍可随意聚焦。"""
    focusables = [focusable_of(w) for w in widgets if w is not None]

    def make_handler(idx, step):
        def handler(_event):
            nxt = idx + step
            if nxt < 0 or nxt >= len(focusables):
                return None
            _focus_input(focusables[nxt])
            return "break"

        return handler

    for i, widget in enumerate(focusables):
        widget.bind("<Down>", make_handler(i, 1), add="+")
        widget.bind("<Up>", make_handler(i, -1), add="+")


def apply_ui_style(root):
    """统一字号，并让 Notebook 选中页签更醒目。"""
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            font = tkfont.nametofont(name)
            font.configure(size=UI_FONT_SIZE)
        except tk.TclError:
            pass

    style = ttk.Style(root)
    # clam 才能稳定改页签底色/文字色（Windows 默认主题几乎改不动）
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TLabel", font=("", UI_FONT_SIZE))
    style.configure("TButton", font=("", UI_FONT_SIZE))
    style.configure("TCheckbutton", font=("", UI_FONT_SIZE))
    style.configure("TRadiobutton", font=("", UI_FONT_SIZE))
    style.configure("TEntry", font=("", UI_FONT_SIZE))
    style.configure("TCombobox", font=("", UI_FONT_SIZE))
    style.configure("TLabelframe.Label", font=("", UI_FONT_SIZE))
    style.configure("TNotebook", background="#f0f0f0", borderwidth=1)
    style.configure(
        "TNotebook.Tab",
        padding=(16, 8),
        font=("", TAB_FONT_SIZE),
        background="#e6e6e6",
        foreground="#666666",
        borderwidth=1,
        lightcolor="#e6e6e6",
        darkcolor="#c8c8c8",
        bordercolor="#c8c8c8",
    )
    style.map(
        "TNotebook.Tab",
        # 关掉 clam 默认的选中增高，保证高度一致
        expand=[("selected", (0, 0, 0, 0))],
        background=[("selected", "#dbe8ff"), ("active", "#eeeeee")],
        foreground=[("selected", "#0b57d0"), ("active", "#333333")],
        lightcolor=[("selected", "#dbe8ff"), ("!selected", "#e6e6e6")],
        darkcolor=[("selected", "#dbe8ff"), ("!selected", "#c8c8c8")],
        bordercolor=[("selected", "#8ab4f8"), ("!selected", "#c8c8c8")],
    )


class GridTable(ttk.Frame):
    """自绘表格：真正的单元格网格线（Treeview 本身画不了格子）。"""

    HEADER_BG = "#e8e8e8"
    ROW_BG = "#ffffff"
    SELECT_BG = "#cfe2ff"
    LINE = "#8a8a8a"
    TEXT = "#222222"
    HEADER_H = 34
    ROW_H = 32

    def __init__(self, master, columns=(), height=12, **_kwargs):
        super().__init__(master)
        self._columns = list(columns)
        self._col_meta = {
            col: {"text": col, "width": 110, "anchor": "center", "stretch": True, "minwidth": 40}
            for col in self._columns
        }
        self._rows = []  # [{"iid": str, "values": tuple}]
        self._iid_index = {}
        self._selected = None
        self._bindings = {}

        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0, bd=0)
        self.ybar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.xbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.ybar.set, xscrollcommand=self.xbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.ybar.grid(row=0, column=1, sticky="ns")
        self.xbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    # --- Treeview 兼容接口 ---
    def __setitem__(self, key, value):
        if key == "columns":
            self._columns = list(value)
            for col in self._columns:
                self._col_meta.setdefault(
                    col,
                    {"text": col, "width": 110, "anchor": "center", "stretch": True, "minwidth": 40},
                )
            self._redraw()
        else:
            raise KeyError(key)

    def __getitem__(self, key):
        if key == "columns":
            return tuple(self._columns)
        raise KeyError(key)

    def heading(self, column, **kwargs):
        meta = self._col_meta.setdefault(
            column,
            {"text": column, "width": 110, "anchor": "center", "stretch": True, "minwidth": 40},
        )
        if "text" in kwargs:
            meta["text"] = kwargs["text"]
        self._redraw()

    def column(self, column, option=None, **kwargs):
        meta = self._col_meta.setdefault(
            column,
            {"text": column, "width": 110, "anchor": "center", "stretch": True, "minwidth": 40},
        )
        if option is not None and not kwargs:
            return meta.get(option)
        if "width" in kwargs:
            meta["width"] = int(kwargs["width"])
        if "minwidth" in kwargs:
            meta["minwidth"] = int(kwargs["minwidth"])
        if "anchor" in kwargs:
            meta["anchor"] = kwargs["anchor"]
        if "stretch" in kwargs:
            meta["stretch"] = bool(kwargs["stretch"])
        self._redraw()

    def get_children(self):
        return tuple(row["iid"] for row in self._rows)

    def insert(self, _parent, _index, iid=None, values=(), **_kwargs):
        iid = str(iid if iid is not None else len(self._rows) + 1)
        if iid in self._iid_index:
            raise ValueError(f"Item {iid} already exists")
        row = {"iid": iid, "values": tuple("" if v is None else v for v in values)}
        self._rows.append(row)
        self._iid_index[iid] = row
        self._redraw()
        return iid

    def delete(self, *items):
        if not items:
            return
        remove = {str(i) for i in items}
        self._rows = [row for row in self._rows if row["iid"] not in remove]
        for iid in remove:
            self._iid_index.pop(iid, None)
            if self._selected == iid:
                self._selected = None
        self._redraw()

    def selection(self):
        return (self._selected,) if self._selected else ()

    def selection_set(self, *items):
        self._selected = str(items[0]) if items else None
        self._redraw()

    def set(self, item, column=None, value=None):
        row = self._iid_index.get(str(item))
        if row is None:
            return ""
        if column is None:
            return {col: row["values"][i] if i < len(row["values"]) else "" for i, col in enumerate(self._columns)}
        try:
            idx = self._columns.index(column)
        except ValueError:
            return ""
        if value is None:
            return row["values"][idx] if idx < len(row["values"]) else ""
        vals = list(row["values"])
        while len(vals) <= idx:
            vals.append("")
        vals[idx] = value
        row["values"] = tuple(vals)
        self._redraw()
        return value

    def bind(self, sequence=None, func=None, add=None):
        if sequence in ("<Double-1>", "<Double-Button-1>"):
            self._bindings["<<Double>>"] = func
            return
        return super().bind(sequence, func, add)

    def yview(self, *args):
        return self.canvas.yview(*args)

    def xview(self, *args):
        return self.canvas.xview(*args)

    # --- 绘制 ---
    def _col_widths(self, view_w):
        widths = []
        flex = []
        fixed_total = 0
        for i, col in enumerate(self._columns):
            meta = self._col_meta[col]
            w = max(int(meta["width"]), int(meta["minwidth"]))
            widths.append(w)
            if meta.get("stretch", True):
                flex.append(i)
            else:
                fixed_total += w
        total = sum(widths)
        if view_w > total and flex:
            extra = view_w - total
            add = extra // len(flex)
            rem = extra % len(flex)
            for j, idx in enumerate(flex):
                widths[idx] += add + (1 if j < rem else 0)
        return widths

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        if not self._columns:
            return
        view_w = max(c.winfo_width(), 1)
        widths = self._col_widths(view_w)
        table_w = max(sum(widths), view_w)
        table_h = self.HEADER_H + self.ROW_H * len(self._rows)

        # 表头
        x = 0
        for col, w in zip(self._columns, widths):
            c.create_rectangle(
                x, 0, x + w, self.HEADER_H, fill=self.HEADER_BG, outline=self.LINE, width=1
            )
            c.create_text(
                x + w / 2,
                self.HEADER_H / 2,
                text=self._col_meta[col]["text"],
                fill=self.TEXT,
                font=("", TABLE_FONT_SIZE, "bold"),
                anchor="center",
            )
            x += w

        # 数据行（只画有数据的行，空白区不拖线）
        for r, row in enumerate(self._rows):
            y0 = self.HEADER_H + r * self.ROW_H
            y1 = y0 + self.ROW_H
            bg = self.SELECT_BG if row["iid"] == self._selected else self.ROW_BG
            x = 0
            for i, w in enumerate(widths):
                c.create_rectangle(x, y0, x + w, y1, fill=bg, outline=self.LINE, width=1)
                text = row["values"][i] if i < len(row["values"]) else ""
                c.create_text(
                    x + w / 2,
                    (y0 + y1) / 2,
                    text=str(text),
                    fill=self.TEXT,
                    font=("", TABLE_FONT_SIZE),
                    anchor="center",
                )
                x += w

        c.configure(scrollregion=(0, 0, table_w, max(table_h, c.winfo_height())))

    def _row_at(self, y):
        if y < self.HEADER_H:
            return None
        idx = int((y - self.HEADER_H) // self.ROW_H)
        if 0 <= idx < len(self._rows):
            return self._rows[idx]["iid"]
        return None

    def _on_click(self, event):
        y = self.canvas.canvasy(event.y)
        iid = self._row_at(y)
        if iid:
            self._selected = iid
            self._redraw()

    def _on_double(self, event):
        y = self.canvas.canvasy(event.y)
        iid = self._row_at(y)
        if iid:
            self._selected = iid
            self._redraw()
            handler = self._bindings.get("<<Double>>")
            if handler:
                handler(event)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class DatePicker(ttk.Frame):
    """日期输入框 + 点选日历。"""

    def __init__(self, master, textvariable, width=12):
        super().__init__(master)
        self.var = textvariable
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left")
        ttk.Button(self, text="选", width=3, command=self._open).pack(side="left", padx=(4, 0))

    def _open(self):
        CalendarDialog(self.winfo_toplevel(), self.var, anchor=self)


class CalendarDialog(tk.Toplevel):
    def __init__(self, master, textvariable, anchor=None):
        super().__init__(master)
        self.var = textvariable
        self.title("选择日期")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        try:
            current = date.fromisoformat((textvariable.get() or "").strip())
        except ValueError:
            current = date.today()
        self.year = current.year
        self.month = current.month
        self.selected = current

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="‹", width=3, command=self._prev).pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Label(top, textvariable=self.title_var, width=14, anchor="center").pack(
            side="left", expand=True
        )
        ttk.Button(top, text="›", width=3, command=self._next).pack(side="right")

        self.grid_frame = ttk.Frame(self, padding=(8, 0, 8, 8))
        self.grid_frame.pack()
        self._draw()
        self.update_idletasks()
        if anchor is not None:
            ax = anchor.winfo_rootx()
            ay = anchor.winfo_rooty() + anchor.winfo_height()
            self.geometry(f"+{ax}+{ay}")
        else:
            center_on_parent(self, master)

    def _prev(self):
        if self.month == 1:
            self.year -= 1
            self.month = 12
        else:
            self.month -= 1
        self._draw()

    def _next(self):
        if self.month == 12:
            self.year += 1
            self.month = 1
        else:
            self.month += 1
        self._draw()

    def _draw(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.title_var.set(f"{self.year} 年 {self.month} 月")
        for i, name in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            ttk.Label(self.grid_frame, text=name, width=4, anchor="center").grid(
                row=0, column=i, padx=1, pady=1
            )
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        for r, week in enumerate(weeks, start=1):
            for c, day in enumerate(week):
                if day == 0:
                    ttk.Label(self.grid_frame, text="", width=4).grid(row=r, column=c)
                    continue
                value = date(self.year, self.month, day)
                btn = ttk.Button(
                    self.grid_frame,
                    text=str(day),
                    width=4,
                    command=lambda d=value: self._pick(d),
                )
                btn.grid(row=r, column=c, padx=1, pady=1)

    def _pick(self, value):
        self.var.set(value.isoformat())
        self.destroy()


class ExtraFieldsFrame(ttk.Frame):
    def __init__(self, master, fields):
        super().__init__(master)
        self.vars = {}
        self.entries = []
        for i, field in enumerate(fields):
            ttk.Label(self, text=field["label"]).grid(row=i, column=0, sticky="e", padx=4, pady=3)
            var = tk.StringVar()
            self.vars[field["field_key"]] = var
            entry = ttk.Entry(self, textvariable=var, width=28)
            entry.grid(row=i, column=1, sticky="we", padx=4, pady=3)
            self.entries.append(entry)

    def get(self):
        return {key: var.get() for key, var in self.vars.items()}

    def set(self, extra):
        extra = extra or {}
        for key, var in self.vars.items():
            value = extra.get(key)
            if isinstance(value, (int, float)):
                var.set(format_number(value))
            else:
                var.set("" if value is None else str(value))


class ProductDialog(tk.Toplevel):
    def __init__(self, master, db, product=None, on_saved=None):
        super().__init__(master)
        self.db = db
        self.product = product
        self.on_saved = on_saved
        self.is_new = product is None
        self.title("修改布料" if product else "新增布料")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.vars = {}
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        nav_widgets = []
        for i, (key, label, _, _) in enumerate(PRODUCT_FIELDS):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="e", padx=4, pady=4)
            var = tk.StringVar()
            self.vars[key] = var
            entry = ttk.Entry(body, textvariable=var, width=32)
            entry.grid(row=i, column=1, sticky="we", padx=4, pady=4)
            nav_widgets.append(entry)
        row = len(PRODUCT_FIELDS)
        self.extra = ExtraFieldsFrame(body, db.custom_fields("product"))
        self.extra.grid(row=row, column=0, columnspan=2, sticky="we")
        nav_widgets.extend(self.extra.entries)
        row += 1

        self.stock_in_var = tk.BooleanVar(value=False)
        self.stock_date_var = tk.StringVar(value=date.today().isoformat())
        self.stock_qty_var = tk.StringVar()
        self.stock_frame = None
        self.stock_date_picker = None
        self.stock_qty_entry = None
        if self.is_new:
            ttk.Checkbutton(
                body,
                text="同时入库",
                variable=self.stock_in_var,
                command=self._toggle_stock_in,
            ).grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 2))
            row += 1
            self.stock_frame = ttk.Frame(body)
            self.stock_frame.grid(row=row, column=0, columnspan=2, sticky="we")
            ttk.Label(self.stock_frame, text="入库日期").grid(
                row=0, column=0, sticky="e", padx=4, pady=4
            )
            self.stock_date_picker = DatePicker(
                self.stock_frame, self.stock_date_var, width=28
            )
            self.stock_date_picker.grid(row=0, column=1, sticky="we", padx=4, pady=4)
            ttk.Label(self.stock_frame, text=QTY_LABEL).grid(
                row=1, column=0, sticky="e", padx=4, pady=4
            )
            self.stock_qty_entry = ttk.Entry(
                self.stock_frame, textvariable=self.stock_qty_var, width=32
            )
            self.stock_qty_entry.grid(row=1, column=1, sticky="we", padx=4, pady=4)
            self.stock_frame.grid_remove()
            row += 1

        if product:
            for key, _, data_type, _ in PRODUCT_FIELDS:
                value = product.get(key)
                if data_type == "number":
                    self.vars[key].set(format_number(value))
                else:
                    self.vars[key].set("" if value is None else str(value))
            self.extra.set(product.get("extra"))

        btns = ttk.Frame(body)
        btns.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="保存", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda _e: self.save())
        self._nav_base = nav_widgets
        self._rebind_nav()
        if nav_widgets:
            nav_widgets[0].focus_set()
        center_on_parent(self, master)

    def _toggle_stock_in(self):
        if self.stock_frame is None:
            return
        if self.stock_in_var.get():
            self.stock_frame.grid()
            if not self.stock_date_var.get().strip():
                self.stock_date_var.set(date.today().isoformat())
            if self.stock_qty_entry is not None:
                self.stock_qty_entry.focus_set()
        else:
            self.stock_frame.grid_remove()
        self._rebind_nav()
        center_on_parent(self, self.master)

    def _rebind_nav(self):
        widgets = list(self._nav_base)
        if self.is_new and self.stock_in_var.get():
            if self.stock_date_picker is not None:
                widgets.append(self.stock_date_picker)
            if self.stock_qty_entry is not None:
                widgets.append(self.stock_qty_entry)
        bind_field_nav(widgets)

    def save(self):
        data = {key: var.get() for key, var in self.vars.items()}
        data["extra"] = self.extra.get()
        do_stock_in = self.is_new and self.stock_in_var.get()
        try:
            product_id = self.db.save_product(
                data, None if self.product is None else self.product["id"]
            )
        except InventoryError as err:
            ask_error(err)
            return
        if do_stock_in:
            try:
                self.db.save_transaction(
                    {
                        "txn_date": self.stock_date_var.get(),
                        "io_type": "入库",
                        "product_id": product_id,
                        "unit_price": data.get("unit_price"),
                        "quantity": self.stock_qty_var.get(),
                        "remark": "",
                        "txn_extra": {},
                    }
                )
            except InventoryError as err:
                ask_error(f"布料已保存，但入库失败：{err}\n请到「新增入库」补记。")
                if self.on_saved:
                    self.on_saved()
                self.destroy()
                return
        if self.on_saved:
            self.on_saved()
        self.destroy()


class TransactionDialog(tk.Toplevel):
    def __init__(self, master, db, txn=None, default_io="入库", on_saved=None):
        super().__init__(master)
        self.db = db
        self.txn = txn
        self.on_saved = on_saved
        self.products = db.list_products()
        self.title("修改出入库" if txn else "新增出入库")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self.date_var = tk.StringVar(value=date.today().isoformat())
        self.io_var = tk.StringVar(value=default_io)
        self.product_var = tk.StringVar()
        self.price_var = tk.StringVar()
        self.qty_var = tk.StringVar()
        self.remark_var = tk.StringVar()
        self.all_products = []
        self.filtered_products = []

        date_picker = DatePicker(body, self.date_var, width=28)
        io_box = ttk.Combobox(
            body,
            textvariable=self.io_var,
            values=["入库", "出库"],
            state="readonly",
            width=29,
        )
        # 可输入筛选：布料很多时打型号/颜色就能缩小列表
        self.product_box = ttk.Combobox(body, textvariable=self.product_var, width=29)
        self._reload_products()
        price_entry = ttk.Entry(body, textvariable=self.price_var, width=32)
        qty_entry = ttk.Entry(body, textvariable=self.qty_var, width=32)
        remark_entry = ttk.Entry(body, textvariable=self.remark_var, width=32)
        rows = [
            ("日期", date_picker),
            ("类型", io_box),
            ("布料（可输入筛选）", self.product_box),
            ("单价（可空）", price_entry),
            (QTY_LABEL, qty_entry),
            ("备注", remark_entry),
        ]

        for i, (label, widget) in enumerate(rows):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="e", padx=4, pady=4)
            widget.grid(row=i, column=1, sticky="we", padx=4, pady=4)

        self.txn_extra = ExtraFieldsFrame(body, db.custom_fields("txn"))
        self.txn_extra.grid(row=len(rows), column=0, columnspan=2, sticky="we")

        self.product_box.bind("<<ComboboxSelected>>", self._on_product)
        self.product_box.bind("<KeyRelease>", self._filter_products)
        if txn:
            self.date_var.set(txn["txn_date"])
            self.io_var.set(txn["io_type"])
            self.price_var.set(format_number(txn.get("unit_price")))
            self.qty_var.set(format_number(txn.get("quantity")))
            self.remark_var.set(txn.get("remark") or "")
            self.txn_extra.set(
                {
                    key: txn.get("extra", {}).get(key)
                    for key in [f["field_key"] for f in db.custom_fields("txn")]
                }
            )
            for product in self.all_products:
                if product["id"] == txn.get("product_id"):
                    self.product_var.set(self.db.product_label(product))
                    self.filtered_products = [product]
                    self.product_box["values"] = [self.db.product_label(product)]
                    break
        elif self.filtered_products:
            self.product_var.set(self.db.product_label(self.filtered_products[0]))
            self._on_product()

        btns = ttk.Frame(body)
        btns.grid(row=len(rows) + 1, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="保存", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)
        nav_widgets = [
            date_picker,
            io_box,
            self.product_box,
            price_entry,
            qty_entry,
            remark_entry,
            *self.txn_extra.entries,
        ]
        bind_field_nav(nav_widgets)
        date_picker.entry.focus_set()
        center_on_parent(self, master)

    def _reload_products(self):
        self.all_products = self.db.list_products()
        self.filtered_products = list(self.all_products)
        self.product_box["values"] = [self.db.product_label(p) for p in self.filtered_products]

    def _filter_products(self, _event=None):
        keyword = self.product_var.get().strip().lower()
        if not keyword:
            self.filtered_products = list(self.all_products)
        else:
            self.filtered_products = [
                p
                for p in self.all_products
                if keyword in self.db.product_label(p).lower()
                or keyword in self.db.product_text(p).lower()
            ]
        self.product_box["values"] = [self.db.product_label(p) for p in self.filtered_products]

    def _selected_product(self):
        text = self.product_var.get().strip()
        for product in self.filtered_products:
            if self.db.product_label(product) == text:
                return product
        for product in self.all_products:
            if self.db.product_label(product) == text:
                return product
        idx = self.product_box.current()
        if 0 <= idx < len(self.filtered_products):
            return self.filtered_products[idx]
        return None

    def _on_product(self, _event=None):
        product = self._selected_product()
        if product is None:
            return
        if not self.price_var.get().strip():
            self.price_var.set(format_number(product.get("unit_price")))

    def save(self):
        product = self._selected_product()
        if product is None:
            ask_error("请先选择布料（可输入型号/颜色筛选；没有的话请先到「商品基础信息」里新增）")
            return
        data = {
            "txn_date": self.date_var.get(),
            "io_type": self.io_var.get(),
            "product_id": product["id"],
            "unit_price": self.price_var.get(),
            "quantity": self.qty_var.get(),
            "remark": self.remark_var.get(),
            "txn_extra": self.txn_extra.get(),
        }
        try:
            self.db.save_transaction(data, None if self.txn is None else self.txn["id"])
        except InventoryError as err:
            ask_error(err)
            return
        if self.on_saved:
            self.on_saved()
        self.destroy()


class FieldDialog(tk.Toplevel):
    def __init__(self, master, db, on_changed=None):
        super().__init__(master)
        self.db = db
        self.on_changed = on_changed
        self.title("扩展列")
        self.geometry("520x360")
        self.transient(master)
        self.grab_set()
        top = ttk.Frame(self, padding=10)
        top.pack(fill="both", expand=True)
        form = ttk.LabelFrame(top, text="新增一列", padding=8)
        form.pack(fill="x")
        self.scope_var = tk.StringVar(value="商品档案")
        self.label_var = tk.StringVar()
        self.type_var = tk.StringVar(value="文字")
        ttk.Label(form, text="加在").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.scope_var,
            values=["商品档案", "出入库"],
            state="readonly",
            width=16,
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="列名").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.label_var, width=20).grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="类型").grid(row=2, column=0, sticky="e", padx=4, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.type_var,
            values=["文字", "数字"],
            state="readonly",
            width=16,
        ).grid(row=2, column=1, sticky="w")
        ttk.Button(form, text="添加", command=self.add_field).grid(row=3, column=1, pady=6, sticky="w")

        self.tree = GridTable(
            top,
            columns=(INDEX_LABEL, "scope", "label", "type"),
            height=8,
        )
        self.tree.heading(INDEX_LABEL, text=INDEX_LABEL)
        self.tree.heading("scope", text="位置")
        self.tree.heading("label", text="列名")
        self.tree.heading("type", text="类型")
        self.tree.column(INDEX_LABEL, width=50, anchor="center", stretch=False)
        self.tree.column("scope", width=100, anchor="center")
        self.tree.column("label", width=180, anchor="center")
        self.tree.column("type", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=8)
        bar = ttk.Frame(top)
        bar.pack(fill="x")
        ttk.Button(bar, text="上移", command=lambda: self.move(-1)).pack(side="left", padx=3)
        ttk.Button(bar, text="下移", command=lambda: self.move(1)).pack(side="left", padx=3)
        ttk.Button(bar, text="改名", command=self.rename).pack(side="left", padx=3)
        ttk.Button(bar, text="删除", command=self.delete).pack(side="left", padx=3)
        ttk.Button(bar, text="关闭", command=self.close).pack(side="right", padx=3)
        self.reload()
        center_on_parent(self, master)

    def reload(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        scope_name = {"product": "商品档案", "txn": "出入库"}
        type_name = {"text": "文字", "number": "数字"}
        for idx, field in enumerate(self.db.custom_fields(), start=1):
            self.tree.insert(
                "",
                "end",
                iid=str(field["id"]),
                values=(
                    idx,
                    scope_name.get(field["scope"], field["scope"]),
                    field["label"],
                    type_name.get(field["data_type"], field["data_type"]),
                ),
            )

    def add_field(self):
        scope = "product" if self.scope_var.get() == "商品档案" else "txn"
        data_type = "number" if self.type_var.get() == "数字" else "text"
        try:
            self.db.add_field(scope, self.label_var.get(), data_type)
        except InventoryError as err:
            ask_error(err)
            return
        self.label_var.set("")
        self.reload()
        if self.on_changed:
            self.on_changed()

    def selected_id(self):
        sel = self.tree.selection()
        if not sel:
            ask_error("请先选中一列")
            return None
        return int(sel[0])

    def move(self, direction):
        field_id = self.selected_id()
        if field_id is None:
            return
        self.db.move_field(field_id, direction)
        self.reload()
        self.tree.selection_set(str(field_id))
        if self.on_changed:
            self.on_changed()

    def rename(self):
        field_id = self.selected_id()
        if field_id is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title("改名")
        dialog.transient(self)
        dialog.grab_set()
        var = tk.StringVar(value=self.tree.set(str(field_id), "label"))
        ttk.Label(dialog, text="新列名").pack(padx=12, pady=(12, 4))
        ttk.Entry(dialog, textvariable=var, width=24).pack(padx=12)
        def ok():
            try:
                self.db.rename_field(field_id, var.get())
            except InventoryError as err:
                ask_error(err)
                return
            dialog.destroy()
            self.reload()
            if self.on_changed:
                self.on_changed()
        ttk.Button(dialog, text="确定", command=ok).pack(pady=12)
        center_on_parent(dialog, self)

    def delete(self):
        field_id = self.selected_id()
        if field_id is None:
            return
        if not messagebox.askyesno("确认", "删除后界面不再显示该列，已填内容会留在数据里。确定删除？"):
            return
        self.db.delete_field(field_id)
        self.reload()
        if self.on_changed:
            self.on_changed()

    def close(self):
        if self.on_changed:
            self.on_changed()
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("亿宝麦")
        self.geometry("1100x680")
        self.minsize(900, 560)
        apply_ui_style(self)
        self.db = Database()
        self._build()
        self.refresh_all()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build(self):
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="新增入库", command=lambda: self.add_txn("入库")).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="新增出库", command=lambda: self.add_txn("出库")).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="新增布料", command=self.add_product).pack(side="left", padx=3)
        ttk.Button(toolbar, text="导出全部", command=self.do_export_all).pack(side="left", padx=3)
        ttk.Button(toolbar, text="扩展列", command=self.manage_fields).pack(side="left", padx=3)
        ttk.Button(toolbar, text="刷新", command=self.refresh_all).pack(side="left", padx=3)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.product_tab = ttk.Frame(self.notebook)
        self.txn_tab = ttk.Frame(self.notebook)
        self.summary_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.product_tab, text="商品基础信息表")
        self.notebook.add(self.txn_tab, text="出入库流水表")
        self.notebook.add(self.summary_tab, text="库存汇总表")

        self._build_product_tab()
        self._build_txn_tab()
        self._build_summary_tab()

    def _make_tree(self, parent, columns):
        tree = GridTable(parent, columns=columns)
        tree.pack(fill="both", expand=True)
        self._apply_columns(tree, columns)
        return tree

    def _apply_columns(self, tree, columns):
        tree["columns"] = columns
        for col in columns:
            tree.heading(col, text=col)
            if col == INDEX_LABEL:
                tree.column(col, width=50, anchor="center", stretch=False, minwidth=40)
            else:
                tree.column(col, width=110, anchor="center", minwidth=60)

    def _build_product_tab(self):
        bar = ttk.Frame(self.product_tab, padding=8)
        bar.pack(fill="x")
        self.product_kw = tk.StringVar()
        ttk.Label(bar, text="搜索").pack(side="left")
        ttk.Entry(bar, textvariable=self.product_kw, width=24).pack(side="left", padx=6)
        ttk.Button(bar, text="查询", command=self.refresh_products).pack(side="left", padx=3)
        ttk.Button(bar, text="导出当前", command=self.export_products_filtered).pack(
            side="left", padx=3
        )
        ttk.Button(bar, text="修改", command=self.edit_product).pack(side="left", padx=3)
        ttk.Button(bar, text="删除", command=self.delete_product).pack(side="left", padx=3)
        self.product_tree = self._make_tree(self.product_tab, self._product_columns())
        self.product_tree.bind("<Double-1>", lambda _e: self.edit_product())

    def _build_txn_tab(self):
        bar = ttk.Frame(self.txn_tab, padding=8)
        bar.pack(fill="x")
        self.txn_from = tk.StringVar()
        self.txn_to = tk.StringVar()
        self.txn_type = tk.StringVar(value="全部")
        self.txn_kw = tk.StringVar()
        ttk.Label(bar, text="从").pack(side="left")
        DatePicker(bar, self.txn_from, width=11).pack(side="left", padx=3)
        ttk.Label(bar, text="到").pack(side="left")
        DatePicker(bar, self.txn_to, width=11).pack(side="left", padx=3)
        ttk.Label(bar, text="类型").pack(side="left", padx=(8, 0))
        ttk.Combobox(
            bar,
            textvariable=self.txn_type,
            values=["全部", "入库", "出库"],
            state="readonly",
            width=8,
        ).pack(side="left", padx=3)
        ttk.Label(bar, text="关键词").pack(side="left", padx=(8, 0))
        ttk.Entry(bar, textvariable=self.txn_kw, width=16).pack(side="left", padx=3)
        ttk.Button(bar, text="查询", command=self.refresh_txns).pack(side="left", padx=3)
        ttk.Button(bar, text="导出当前", command=self.export_txns_filtered).pack(
            side="left", padx=3
        )
        ttk.Button(bar, text="修改", command=self.edit_txn).pack(side="left", padx=3)
        ttk.Button(bar, text="删除", command=self.delete_txn).pack(side="left", padx=3)
        self.txn_tree = self._make_tree(self.txn_tab, self._txn_columns())
        self.txn_tree.bind("<Double-1>", lambda _e: self.edit_txn())

    def _build_summary_tab(self):
        bar = ttk.Frame(self.summary_tab, padding=8)
        bar.pack(fill="x")
        self.hide_zero = tk.BooleanVar(value=False)
        self.summary_kw = tk.StringVar()
        ttk.Label(bar, text="搜索").pack(side="left")
        ttk.Entry(bar, textvariable=self.summary_kw, width=20).pack(side="left", padx=6)
        ttk.Button(bar, text="查询", command=self.refresh_summary).pack(side="left", padx=3)
        ttk.Button(bar, text="导出当前", command=self.export_summary_filtered).pack(
            side="left", padx=3
        )
        ttk.Checkbutton(
            bar,
            text="隐藏库存为 0 的",
            variable=self.hide_zero,
            command=self.refresh_summary,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(bar, text="库存按出入库米数自动汇总").pack(side="left", padx=12)
        self.summary_tree = self._make_tree(self.summary_tab, self._summary_columns())

    def _product_columns(self):
        cols = [INDEX_LABEL] + [label for _, label, _, _ in PRODUCT_FIELDS]
        cols += [f["label"] for f in self.db.custom_fields("product")]
        return cols

    def _txn_columns(self):
        cols = [
            INDEX_LABEL,
            "日期",
            "类型（入库/出库）",
            "产品型号",
            "颜色",
            "单价",
            QTY_LABEL,
            "备注",
        ]
        cols += [f["label"] for f in self.db.custom_fields("product")]
        cols += [f["label"] for f in self.db.custom_fields("txn")]
        return cols

    def _summary_columns(self):
        cols = [INDEX_LABEL, "产品型号", "颜色", STOCK_LABEL, "单价"]
        cols += [f["label"] for f in self.db.custom_fields("product")]
        return cols

    def _reset_tree_columns(self, tree, columns):
        self._apply_columns(tree, columns)

    def refresh_all(self):
        self.refresh_products()
        self.refresh_txns()
        self.refresh_summary()

    def refresh_products(self):
        columns = self._product_columns()
        self._reset_tree_columns(self.product_tree, columns)
        for item in self.product_tree.get_children():
            self.product_tree.delete(item)
        for idx, product in enumerate(self.db.list_products(self.product_kw.get()), start=1):
            values = [idx]
            for key, _, data_type, _ in PRODUCT_FIELDS:
                value = product.get(key)
                values.append(format_number(value) if data_type == "number" else (value or ""))
            for field in self.db.custom_fields("product"):
                values.append(self.db.extra_text(product.get("extra"), field))
            self.product_tree.insert("", "end", iid=str(product["id"]), values=values)

    def refresh_txns(self):
        columns = self._txn_columns()
        self._reset_tree_columns(self.txn_tree, columns)
        for item in self.txn_tree.get_children():
            self.txn_tree.delete(item)
        io_type = self.txn_type.get()
        if io_type == "全部":
            io_type = ""
        product_fields = self.db.custom_fields("product")
        txn_fields = self.db.custom_fields("txn")
        for idx, txn in enumerate(
            self.db.list_transactions(
                self.txn_from.get().strip(),
                self.txn_to.get().strip(),
                io_type,
                self.txn_kw.get(),
            ),
            start=1,
        ):
            values = [
                idx,
                txn["txn_date"],
                txn["io_type"],
                txn.get("product_model") or "",
                txn["color"] or "",
                format_number(txn.get("unit_price")),
                format_number(txn.get("quantity")),
                txn.get("remark") or "",
            ]
            for field in product_fields:
                values.append(self.db.extra_text(txn.get("extra"), field))
            for field in txn_fields:
                values.append(self.db.extra_text(txn.get("extra"), field))
            self.txn_tree.insert("", "end", iid=str(txn["id"]), values=values)

    def refresh_summary(self):
        columns = self._summary_columns()
        self._reset_tree_columns(self.summary_tree, columns)
        for item in self.summary_tree.get_children():
            self.summary_tree.delete(item)
        for idx, row in enumerate(
            self.db.summary(
                hide_zero=self.hide_zero.get(),
                keyword=self.summary_kw.get(),
            ),
            start=1,
        ):
            values = [
                idx,
                row.get("product_model") or "",
                row["color"] or "",
                format_number(row["stock"]),
                format_number(row.get("unit_price")),
            ]
            for field in self.db.custom_fields("product"):
                values.append(self.db.extra_text(row.get("extra"), field))
            self.summary_tree.insert("", "end", iid=str(row["id"]), values=values)

    def add_product(self):
        ProductDialog(self, self.db, on_saved=self.refresh_all)

    def edit_product(self):
        sel = self.product_tree.selection()
        if not sel:
            ask_error("请先选中一条布料")
            return
        product = self.db.get_product(int(sel[0]))
        if product is None:
            ask_error("找不到这条记录")
            return
        ProductDialog(self, self.db, product=product, on_saved=self.refresh_all)

    def delete_product(self):
        sel = self.product_tree.selection()
        if not sel:
            ask_error("请先选中一条布料")
            return
        if not messagebox.askyesno("确认", "确定删除这条布料档案？"):
            return
        try:
            self.db.delete_product(int(sel[0]))
        except InventoryError as err:
            ask_error(err)
            return
        self.refresh_all()

    def add_txn(self, io_type):
        if not self.db.list_products():
            ask_error("请先在「商品基础信息表」里新增布料")
            self.notebook.select(self.product_tab)
            return
        TransactionDialog(self, self.db, default_io=io_type, on_saved=self.refresh_all)

    def edit_txn(self):
        sel = self.txn_tree.selection()
        if not sel:
            ask_error("请先选中一条出入库记录")
            return
        txn = self.db.get_transaction(int(sel[0]))
        if txn is None:
            ask_error("找不到这条记录")
            return
        TransactionDialog(self, self.db, txn=txn, on_saved=self.refresh_all)

    def delete_txn(self):
        sel = self.txn_tree.selection()
        if not sel:
            ask_error("请先选中一条出入库记录")
            return
        if not messagebox.askyesno("确认", "确定删除这条出入库记录？"):
            return
        try:
            self.db.delete_transaction(int(sel[0]))
        except InventoryError as err:
            ask_error(err)
            return
        self.refresh_all()

    def manage_fields(self):
        FieldDialog(self, self.db, on_changed=self.refresh_all)

    def _ask_export_path(self, title, initialfile):
        return filedialog.asksaveasfilename(
            title=title,
            defaultextension=".xlsx",
            filetypes=[("Excel 文件", "*.xlsx")],
            initialfile=initialfile,
        )

    def _finish_export(self, path, exporter):
        if not path:
            return
        try:
            exporter(path)
        except Exception as err:
            ask_error(f"导出失败：{err}")
            return
        messagebox.showinfo("完成", f"已导出到：\n{path}")

    def export_products_filtered(self):
        today = date.today().isoformat()
        path = self._ask_export_path("导出商品表", f"商品基础信息_{today}.xlsx")
        self._finish_export(
            path,
            lambda p: export_products(self.db, p, keyword=self.product_kw.get()),
        )

    def export_txns_filtered(self):
        today = date.today().isoformat()
        path = self._ask_export_path("导出出入库表", f"出入库流水_{today}.xlsx")
        io_type = self.txn_type.get()
        if io_type == "全部":
            io_type = ""
        self._finish_export(
            path,
            lambda p: export_transactions(
                self.db,
                p,
                date_from=self.txn_from.get().strip(),
                date_to=self.txn_to.get().strip(),
                io_type=io_type,
                keyword=self.txn_kw.get(),
            ),
        )

    def export_summary_filtered(self):
        today = date.today().isoformat()
        path = self._ask_export_path("导出库存表", f"库存汇总_{today}.xlsx")
        self._finish_export(
            path,
            lambda p: export_summary(
                self.db,
                p,
                hide_zero=self.hide_zero.get(),
                keyword=self.summary_kw.get(),
            ),
        )

    def do_export_all(self):
        path = self._ask_export_path(
            "导出全部三张表",
            f"布料库存全部_{date.today().isoformat()}.xlsx",
        )
        self._finish_export(path, lambda p: export_excel(self.db, p))

    def on_close(self):
        self.db.close()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
