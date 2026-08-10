"""بيانات المنشأة: الإعدادات، العملاء، وكتالوج السلع والخدمات.

كل دالة هنا تأخذ org_id وتستخدمه في شرط الاستعلام، فلا يمكن لمشترك
الوصول إلى سجل مشترك آخر حتى لو خمّن المعرّف.
"""

from . import db
from .auth import now_iso
from .money import VAT_CATEGORIES, MoneyError, parse_amount

# حدود الباقة المجانية — نقطة التحويل إلى الاشتراك المدفوع
PLAN_LIMITS = {
    "free": {"invoices_per_month": 10, "customers": 25, "label": "المجانية"},
    "pro": {"invoices_per_month": None, "customers": None, "label": "الاحترافية"},
}


class ValidationError(ValueError):
    """بيانات مدخلة غير صالحة."""


def _clean(value, default="") -> str:
    return (str(value).strip() if value is not None else default)


# ---------------------------------------------------------------- المنشأة

def get_org(conn, org_id: int) -> dict:
    row = db.query_one(conn, "SELECT * FROM orgs WHERE id = ?", (org_id,))
    if row is None:
        raise ValidationError("المنشأة غير موجودة")
    org = dict(row)
    org["plan_limits"] = PLAN_LIMITS.get(org["plan"], PLAN_LIMITS["free"])
    return org


def update_org(conn, org_id: int, data: dict) -> dict:
    """يحدّث بيانات المنشأة التي تظهر على الفاتورة الضريبية."""
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("اسم المنشأة مطلوب")

    prefix = _clean(data.get("invoice_prefix"), "INV") or "INV"
    if len(prefix) > 10:
        raise ValidationError("بادئة رقم الفاتورة طويلة جدًا")

    db.execute(
        conn,
        """UPDATE orgs SET name = ?, vat_number = ?, cr_number = ?, address = ?,
                           phone = ?, email = ?, invoice_prefix = ?
           WHERE id = ?""",
        (
            name,
            _clean(data.get("vat_number")),
            _clean(data.get("cr_number")),
            _clean(data.get("address")),
            _clean(data.get("phone")),
            _clean(data.get("email")),
            prefix,
            org_id,
        ),
    )
    return get_org(conn, org_id)


def set_plan(conn, org_id: int, plan: str) -> dict:
    if plan not in PLAN_LIMITS:
        raise ValidationError("باقة غير معروفة")
    db.execute(conn, "UPDATE orgs SET plan = ? WHERE id = ?", (plan, org_id))
    return get_org(conn, org_id)


# ---------------------------------------------------------------- العملاء

def list_customers(conn, org_id: int, include_archived: bool = False) -> list:
    sql = "SELECT * FROM customers WHERE org_id = ?"
    params = [org_id]
    if not include_archived:
        sql += " AND archived = 0"
    sql += " ORDER BY name COLLATE NOCASE"
    return [dict(row) for row in db.query(conn, sql, params)]


def get_customer(conn, org_id: int, customer_id: int) -> dict:
    row = db.query_one(
        conn, "SELECT * FROM customers WHERE id = ? AND org_id = ?", (customer_id, org_id)
    )
    if row is None:
        raise ValidationError("العميل غير موجود")
    return dict(row)


def create_customer(conn, org_id: int, data: dict) -> dict:
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("اسم العميل مطلوب")

    limit = get_org(conn, org_id)["plan_limits"]["customers"]
    if limit is not None:
        count = db.query_one(
            conn, "SELECT COUNT(*) AS c FROM customers WHERE org_id = ? AND archived = 0", (org_id,)
        )["c"]
        if count >= limit:
            raise ValidationError(
                f"الباقة المجانية تسمح بـ {limit} عميلًا. رقّ إلى الباقة الاحترافية للمزيد."
            )

    cursor = db.execute(
        conn,
        """INSERT INTO customers (org_id, name, vat_number, phone, email, address, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            org_id,
            name,
            _clean(data.get("vat_number")),
            _clean(data.get("phone")),
            _clean(data.get("email")),
            _clean(data.get("address")),
            _clean(data.get("notes")),
            now_iso(),
        ),
    )
    return get_customer(conn, org_id, cursor.lastrowid)


def update_customer(conn, org_id: int, customer_id: int, data: dict) -> dict:
    get_customer(conn, org_id, customer_id)  # يتحقق من الملكية
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("اسم العميل مطلوب")

    db.execute(
        conn,
        """UPDATE customers SET name = ?, vat_number = ?, phone = ?, email = ?,
                                address = ?, notes = ?
           WHERE id = ? AND org_id = ?""",
        (
            name,
            _clean(data.get("vat_number")),
            _clean(data.get("phone")),
            _clean(data.get("email")),
            _clean(data.get("address")),
            _clean(data.get("notes")),
            customer_id,
            org_id,
        ),
    )
    return get_customer(conn, org_id, customer_id)


def archive_customer(conn, org_id: int, customer_id: int):
    """يؤرشف العميل بدل حذفه، حتى تبقى فواتيره السابقة مرتبطة بسجل صحيح."""
    get_customer(conn, org_id, customer_id)
    db.execute(
        conn, "UPDATE customers SET archived = 1 WHERE id = ? AND org_id = ?", (customer_id, org_id)
    )


# ---------------------------------------------------------------- الكتالوج

def list_items(conn, org_id: int, include_archived: bool = False) -> list:
    sql = "SELECT * FROM items WHERE org_id = ?"
    params = [org_id]
    if not include_archived:
        sql += " AND archived = 0"
    sql += " ORDER BY name COLLATE NOCASE"
    return [dict(row) for row in db.query(conn, sql, params)]


def get_item(conn, org_id: int, item_id: int) -> dict:
    row = db.query_one(conn, "SELECT * FROM items WHERE id = ? AND org_id = ?", (item_id, org_id))
    if row is None:
        raise ValidationError("الصنف غير موجود")
    return dict(row)


def _item_fields(data: dict):
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("اسم الصنف مطلوب")

    category = _clean(data.get("vat_category"), "standard") or "standard"
    if category not in VAT_CATEGORIES:
        raise ValidationError("الفئة الضريبية غير معروفة")

    try:
        price = parse_amount(data.get("unit_price"))
    except MoneyError as exc:
        raise ValidationError(str(exc))
    if price < 0:
        raise ValidationError("السعر لا يمكن أن يكون سالبًا")

    return name, _clean(data.get("unit"), "قطعة") or "قطعة", price, category


def create_item(conn, org_id: int, data: dict) -> dict:
    name, unit, price, category = _item_fields(data)
    cursor = db.execute(
        conn,
        """INSERT INTO items (org_id, name, unit, unit_price, vat_category, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (org_id, name, unit, price, category, now_iso()),
    )
    return get_item(conn, org_id, cursor.lastrowid)


def update_item(conn, org_id: int, item_id: int, data: dict) -> dict:
    get_item(conn, org_id, item_id)
    name, unit, price, category = _item_fields(data)
    db.execute(
        conn,
        """UPDATE items SET name = ?, unit = ?, unit_price = ?, vat_category = ?
           WHERE id = ? AND org_id = ?""",
        (name, unit, price, category, item_id, org_id),
    )
    return get_item(conn, org_id, item_id)


def archive_item(conn, org_id: int, item_id: int):
    get_item(conn, org_id, item_id)
    db.execute(conn, "UPDATE items SET archived = 1 WHERE id = ? AND org_id = ?", (item_id, org_id))
