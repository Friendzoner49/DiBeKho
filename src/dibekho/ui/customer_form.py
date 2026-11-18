"""The customer's details in one small window (customer's request 18/11/2026: MST and email were added): 'Sửa thông
tin khách hàng…' in Chi tiết khách hàng, and '＋ Khách hàng mới…' in Phiếu xuất kho."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout

from dibekho.core import catalog
from dibekho.core.text import clean
from dibekho.i18n import t
from dibekho.ui.common import ask, error, fit_window, hint_label, title_label

FIELDS = (("name", "cust.field_name"), ("phone", "col.phone"), ("contact", "col.contact"),
          ("address", "col.address"), ("tax_code", "col.tax_code"), ("email", "col.email"))


class CustomerInfoDialog(QDialog):
    """Every field of a customer. values(): what was typed (cleaned). The caller saves it."""

    def __init__(self, parent, title: str, values: dict | None = None, hint: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        fit_window(self, 620, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(title_label(title))
        if hint:
            lay.addWidget(hint_label(hint))
        form = QFormLayout()
        self.boxes: dict[str, QLineEdit] = {}
        for key, label in FIELDS:
            box = QLineEdit((values or {}).get(key) or "")
            box.setMinimumWidth(380)
            self.boxes[key] = box
            form.addRow(t(label) + (" *" if key == "name" else "") + ":", box)
        self.boxes["email"].setPlaceholderText("ten@congty.vn")
        lay.addLayout(form)
        buttons = QDialogButtonBox()
        buttons.addButton(t("btn.save"), QDialogButtonBox.AcceptRole)
        buttons.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.boxes["name"].setFocus()

    def values(self) -> dict:
        return {key: clean(box.text()) for key, box in self.boxes.items()}

    def _check(self):
        if not self.values()["name"]:
            error(self, t("cust.need_name"))
            self.boxes["name"].setFocus()
            return
        self.accept()


def edit_customer(ctx, parent, customer_id: int) -> bool:
    """'Sửa thông tin khách hàng…': True when something was saved."""
    from dibekho import db

    row = ctx.conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        return False
    before = {key: row[key] or "" for key, _ in FIELDS}
    dlg = CustomerInfoDialog(parent, t("cust.edit_title"), before, t("cust.edit_hint"))
    while True:
        if dlg.exec() != QDialog.Accepted:
            return False
        values = dlg.values()
        if values == before:
            return False
        twin = catalog.customer_owning_phone(ctx.conn, values["phone"], other_than=customer_id)
        if twin is not None and not ask(parent, t("cust.phone_taken", name=twin["name"])):
            continue
        twin = catalog.customer_named(ctx.conn, values["name"], other_than=customer_id)
        if twin is not None and not ask(parent, t("cust.name_taken", name=twin["name"])):
            continue
        break
    ctx.log_action("customer_edited")
    with db.transaction(ctx.conn):
        catalog.update_customer(ctx.conn, customer_id, **values)
    return True
