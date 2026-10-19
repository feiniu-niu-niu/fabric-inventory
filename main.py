"""布料出入库桌面程序。"""

import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from database import (
    PRODUCT_FIELDS,
    QTY_LABEL,
    STOCK_LABEL,
    Database,
    InventoryError,
    format_number,
)
from export import export_excel


def ask_error(err):
    messagebox.showerror("提示", str(err))


class ExtraFieldsFrame(ttk.Frame):
    def __init__(self, master, fields):
        super().__init__(master)
        self.vars = {}
        for i, field in enumerate(fields):
            ttk.Label(self, text=field["label"]).grid(row=i, column=0, sticky="e", padx=4, pady=3)
            var = tk.StringVar()
            self.vars[field["field_key"]] = var
            ttk.Entry(self, textvariable=var, width=28).grid(
                row=i, column=1, sticky="we", padx=4, pady=3
            )

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
        self.title("修改布料" if product else "新增布料")
        self.resizable(False, False)
        self.grab_set()
        self.vars = {}
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        for i, (key, label, _, _) in enumerate(PRODUCT_FIELDS):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="e", padx=4, pady=4)
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(body, textvariable=var, width=32).grid(
                row=i, column=1, sticky="we", padx=4, pady=4
            )
        self.extra = ExtraFieldsFrame(body, db.custom_fields("product"))
        self.extra.grid(row=len(PRODUCT_FIELDS), column=0, columnspan=2, sticky="we")
        if product:
            for key, _, data_type, _ in PRODUCT_FIELDS:
                value = product.get(key)
                if data_type == "number":
                    self.vars[key].set(format_number(value))
                else:
                    self.vars[key].set("" if value is None else str(value))
            self.extra.set(product.get("extra"))
        btns = ttk.Frame(body)
        btns.grid(row=len(PRODUCT_FIELDS) + 1, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="保存", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda _e: self.save())

    def save(self):
        data = {key: var.get() for key, var in self.vars.items()}
        data["extra"] = self.extra.get()
        try:
            self.db.save_product(data, None if self.product is None else self.product["id"])
        except InventoryError as err:
            ask_error(err)
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
        self.grab_set()
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self.date_var = tk.StringVar(value=date.today().isoformat())
        self.io_var = tk.StringVar(value=default_io)
        self.product_var = tk.StringVar()
        self.price_var = tk.StringVar()
        self.qty_var = tk.StringVar()
        self.remark_var = tk.StringVar()
        self.product_ids = []

        rows = [
            ("日期", ttk.Entry(body, textvariable=self.date_var, width=32)),
            (
                "类型",
                ttk.Combobox(
                    body,
                    textvariable=self.io_var,
                    values=["入库", "出库"],
                    state="readonly",
                    width=29,
                ),
            ),
        ]
        self.product_box = ttk.Combobox(body, textvariable=self.product_var, width=29, state="readonly")
        self._reload_products()
        rows.append(("布料", self.product_box))
        rows.append(("单价（可空）", ttk.Entry(body, textvariable=self.price_var, width=32)))
        rows.append((QTY_LABEL, ttk.Entry(body, textvariable=self.qty_var, width=32)))
        rows.append(("备注", ttk.Entry(body, textvariable=self.remark_var, width=32)))

        for i, (label, widget) in enumerate(rows):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="e", padx=4, pady=4)
            widget.grid(row=i, column=1, sticky="we", padx=4, pady=4)

        self.txn_extra = ExtraFieldsFrame(body, db.custom_fields("txn"))
        self.txn_extra.grid(row=len(rows), column=0, columnspan=2, sticky="we")

        self.product_box.bind("<<ComboboxSelected>>", self._on_product)
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
            for i, pid in enumerate(self.product_ids):
                if pid == txn.get("product_id"):
                    self.product_box.current(i)
                    break
        elif self.product_ids:
            self.product_box.current(0)
            self._on_product()

        btns = ttk.Frame(body)
        btns.grid(row=len(rows) + 1, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="保存", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)

    def _reload_products(self):
        self.products = self.db.list_products()
        labels = [self.db.product_label(p) for p in self.products]
        self.product_ids = [p["id"] for p in self.products]
        self.product_box["values"] = labels

    def _on_product(self, _event=None):
        idx = self.product_box.current()
        if idx < 0 or idx >= len(self.products):
            return
        product = self.products[idx]
        if not self.price_var.get().strip():
            self.price_var.set(format_number(product.get("unit_price")))

    def save(self):
        idx = self.product_box.current()
        if idx < 0 or idx >= len(self.product_ids):
            ask_error("请先选择布料（没有的话请先到「商品基础信息」里新增）")
            return
        data = {
            "txn_date": self.date_var.get(),
            "io_type": self.io_var.get(),
            "product_id": self.product_ids[idx],
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

        self.tree = ttk.Treeview(
            top, columns=("scope", "label", "type"), show="headings", height=8
        )
        self.tree.heading("scope", text="位置")
        self.tree.heading("label", text="列名")
        self.tree.heading("type", text="类型")
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

    def reload(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        scope_name = {"product": "商品档案", "txn": "出入库"}
        type_name = {"text": "文字", "number": "数字"}
        for field in self.db.custom_fields():
            self.tree.insert(
                "",
                "end",
                iid=str(field["id"]),
                values=(
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
        ttk.Button(toolbar, text="导出 Excel", command=self.do_export).pack(side="left", padx=3)
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
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=110, anchor="center")
        return tree

    def _build_product_tab(self):
        bar = ttk.Frame(self.product_tab, padding=8)
        bar.pack(fill="x")
        self.product_kw = tk.StringVar()
        ttk.Label(bar, text="搜索").pack(side="left")
        ttk.Entry(bar, textvariable=self.product_kw, width=24).pack(side="left", padx=6)
        ttk.Button(bar, text="查询", command=self.refresh_products).pack(side="left", padx=3)
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
        ttk.Entry(bar, textvariable=self.txn_from, width=12).pack(side="left", padx=3)
        ttk.Label(bar, text="到").pack(side="left")
        ttk.Entry(bar, textvariable=self.txn_to, width=12).pack(side="left", padx=3)
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
        ttk.Button(bar, text="修改", command=self.edit_txn).pack(side="left", padx=3)
        ttk.Button(bar, text="删除", command=self.delete_txn).pack(side="left", padx=3)
        self.txn_tree = self._make_tree(self.txn_tab, self._txn_columns())
        self.txn_tree.bind("<Double-1>", lambda _e: self.edit_txn())

    def _build_summary_tab(self):
        bar = ttk.Frame(self.summary_tab, padding=8)
        bar.pack(fill="x")
        self.hide_zero = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar,
            text="隐藏库存为 0 的",
            variable=self.hide_zero,
            command=self.refresh_summary,
        ).pack(side="left")
        ttk.Label(bar, text="库存按出入库米数自动汇总").pack(side="left", padx=12)
        self.summary_tree = self._make_tree(self.summary_tab, self._summary_columns())

    def _product_columns(self):
        cols = [label for _, label, _, _ in PRODUCT_FIELDS]
        cols += [f["label"] for f in self.db.custom_fields("product")]
        return cols

    def _txn_columns(self):
        cols = [
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
        cols += [f["label"] for f in self.db.custom_fields("product")]
        cols += [f["label"] for f in self.db.custom_fields("txn")]
        return cols

    def _summary_columns(self):
        cols = ["商品类型", "商品编号", "长度", "颜色", STOCK_LABEL, "单价"]
        cols += [f["label"] for f in self.db.custom_fields("product")]
        return cols

    def _reset_tree_columns(self, tree, columns):
        tree["columns"] = columns
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=110, anchor="center")

    def refresh_all(self):
        self.refresh_products()
        self.refresh_txns()
        self.refresh_summary()

    def refresh_products(self):
        columns = self._product_columns()
        self._reset_tree_columns(self.product_tree, columns)
        for item in self.product_tree.get_children():
            self.product_tree.delete(item)
        for product in self.db.list_products(self.product_kw.get()):
            values = []
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
        for txn in self.db.list_transactions(
            self.txn_from.get().strip(),
            self.txn_to.get().strip(),
            io_type,
            self.txn_kw.get(),
        ):
            values = [
                txn["txn_date"],
                txn["io_type"],
                txn["product_type"] or "",
                txn["product_code"] or "",
                txn["length"] or "",
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
        for row in self.db.summary(hide_zero=self.hide_zero.get()):
            values = [
                row["product_type"] or "",
                row["product_code"] or "",
                row["length"] or "",
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

    def do_export(self):
        path = filedialog.asksaveasfilename(
            title="导出 Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel 文件", "*.xlsx")],
            initialfile=f"布料库存_{date.today().isoformat()}.xlsx",
        )
        if not path:
            return
        try:
            export_excel(self.db, path)
        except Exception as err:
            ask_error(f"导出失败：{err}")
            return
        messagebox.showinfo("完成", f"已导出到：\n{path}")

    def on_close(self):
        self.db.close()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
