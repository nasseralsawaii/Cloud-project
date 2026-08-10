"""إنشاء الفواتير الضريبية وتحصيل المدفوعات.

قاعدة أساسية: المجاميع لا تُقبل من الواجهة إطلاقًا. الخادم يستقبل البنود
(الوصف، الكمية، السعر، الفئة الضريبية) ويحسب كل المجاميع بنفسه، وإلا
لأمكن لأي شخص إرسال فاتورة بضريبة صفر عبر تعديل الطلب.
"""

import re
from datetime import date, datetime

from . import db, store
from .auth import now_iso
from .money import (
    MoneyError,
    invoice_totals,
    line_totals,
    parse_amount,
    parse_quantity,
    vat_rate_for,
)
from .store import ValidationError

STATUSES = ("draft", "sent", "paid", "cancelled")

# الحالات التي تُحتسب ضمن المبيعات والإقرار الضريبي.
# المسودة لم تصدر بعد، والملغاة لا أثر لها.
COUNTED_STATUSES = ("sent", "paid")

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(value, field: str, required: bool = True) -> str:
    text = (str(value).strip() if value is not None else "")
    if not text:
        if required:
            raise ValidationError(f"{field} مطلوب")
        return ""
    if not DATE_PATTERN.match(text):
        raise ValidationError(f"صيغة {field} يجب أن تكون YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"{field} تاريخ غير صحيح")
    return text


def _next_invoice_number(conn, org_id: int) -> str:
    """يحجز رقم الفاتورة التالي ويزيد العدّاد في نفس المعاملة.

    الترقيم يجب أن يكون متسلسلًا وغير مكرر — وهو مطلب في الفاتورة الضريبية.
    تحديث العدّاد بجملة UPDATE واحدة يمنع تكرار الرقم عند إنشاء فاتورتين
    في نفس اللحظة من جهازين.
    """
    conn.execute("UPDATE orgs SET next_invoice_no = next_invoice_no + 1 WHERE id = ?", (org_id,))
    row = conn.execute(
        "SELECT invoice_prefix, next_invoice_no FROM orgs WHERE id = ?", (org_id,)
    ).fetchone()
    sequence = row["next_invoice_no"] - 1
    return f"{row['invoice_prefix']}-{sequence:05d}"


def _check_monthly_limit(conn, org_id: int, issue_date: str):
    """يمنع تجاوز حد الباقة المجانية لعدد الفواتير في الشهر."""
    limit = store.get_org(conn, org_id)["plan_limits"]["invoices_per_month"]
    if limit is None:
        return

    month = issue_date[:7]
    count = db.query_one(
        conn,
        """SELECT COUNT(*) AS c FROM invoices
           WHERE org_id = ? AND substr(issue_date, 1, 7) = ? AND status != 'cancelled'""",
        (org_id, month),
    )["c"]
    if count >= limit:
        raise ValidationError(
            f"الباقة المجانية تسمح بـ {limit} فواتير شهريًا. "
            "رقّ إلى الباقة الاحترافية لإصدار فواتير بلا حد."
        )


def _prepare_lines(raw_lines) -> list:
    """يتحقق من البنود ويحسب مجاميع كل بند."""
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValidationError("الفاتورة يجب أن تحتوي على بند واحد على الأقل")

    prepared = []
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise ValidationError(f"البند رقم {index} غير صالح")

        description = (str(raw.get("description") or "")).strip()
        if not description:
            raise ValidationError(f"وصف البند رقم {index} مطلوب")

        category = (str(raw.get("vat_category") or "standard")).strip() or "standard"
        try:
            rate_bp = vat_rate_for(category)
            quantity = parse_quantity(raw.get("quantity"))
            unit_price = parse_amount(raw.get("unit_price"))
            discount = parse_amount(raw.get("discount"))
        except MoneyError as exc:
            raise ValidationError(f"البند رقم {index}: {exc}")

        if quantity <= 0:
            raise ValidationError(f"كمية البند رقم {index} يجب أن تكون أكبر من صفر")

        try:
            computed = line_totals(unit_price, quantity, rate_bp, discount)
        except MoneyError as exc:
            raise ValidationError(f"البند رقم {index}: {exc}")

        prepared.append({
            "description": description,
            "unit": (str(raw.get("unit") or "قطعة")).strip() or "قطعة",
            "quantity": quantity,
            "unit_price": unit_price,
            "discount": computed["discount"],
            "vat_category": category,
            "vat_rate_bp": rate_bp,
            "taxable": computed["taxable"],
            "vat_amount": computed["vat"],
            "line_total": computed["total"],
        })
    return prepared


def _write_lines(conn, invoice_id: int, lines: list):
    conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
    for position, line in enumerate(lines):
        conn.execute(
            """INSERT INTO invoice_lines
               (invoice_id, position, description, unit, quantity, unit_price, discount,
                vat_category, vat_rate_bp, taxable, vat_amount, line_total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                invoice_id, position, line["description"], line["unit"], line["quantity"],
                line["unit_price"], line["discount"], line["vat_category"], line["vat_rate_bp"],
                line["taxable"], line["vat_amount"], line["line_total"],
            ),
        )


def _resolve_customer(conn, org_id: int, customer_id):
    if customer_id in (None, "", 0):
        return None
    store.get_customer(conn, org_id, int(customer_id))  # يتحقق من الملكية
    return int(customer_id)


def create_invoice(conn, org_id: int, data: dict) -> dict:
    issue_date = _validate_date(data.get("issue_date") or date.today().isoformat(), "تاريخ الإصدار")
    due_date = _validate_date(data.get("due_date"), "تاريخ الاستحقاق", required=False)
    if due_date and due_date < issue_date:
        raise ValidationError("تاريخ الاستحقاق لا يمكن أن يسبق تاريخ الإصدار")

    status = (str(data.get("status") or "draft")).strip()
    if status not in STATUSES:
        raise ValidationError("حالة الفاتورة غير معروفة")

    customer_id = _resolve_customer(conn, org_id, data.get("customer_id"))
    lines = _prepare_lines(data.get("lines"))
    _check_monthly_limit(conn, org_id, issue_date)

    totals = invoice_totals([
        {
            "unit_price": line["unit_price"],
            "quantity": line["quantity"],
            "vat_rate_bp": line["vat_rate_bp"],
            "discount": line["discount"],
        }
        for line in lines
    ])

    timestamp = now_iso()
    try:
        number = _next_invoice_number(conn, org_id)
        cursor = conn.execute(
            """INSERT INTO invoices
               (org_id, customer_id, number, issue_date, due_date, status, notes,
                gross_total, discount_total, taxable_total, vat_total, grand_total,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                org_id, customer_id, number, issue_date, due_date, status,
                (str(data.get("notes") or "")).strip(),
                totals["gross"], totals["discount"], totals["taxable"],
                totals["vat"], totals["total"], timestamp, timestamp,
            ),
        )
        invoice_id = cursor.lastrowid
        _write_lines(conn, invoice_id, lines)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return get_invoice(conn, org_id, invoice_id)


def update_invoice(conn, org_id: int, invoice_id: int, data: dict) -> dict:
    """يعدّل فاتورة قائمة.

    الفاتورة المدفوعة أو الملغاة لا تُعدَّل: تعديل مستند صدر للعميل وسُجّل في
    الإقرار الضريبي يفسد السجل المحاسبي. الحل السليم إشعار دائن، وهو مدرج
    في خارطة التطوير.
    """
    invoice = get_invoice(conn, org_id, invoice_id)
    if invoice["status"] in ("paid", "cancelled"):
        raise ValidationError("لا يمكن تعديل فاتورة مدفوعة أو ملغاة")

    issue_date = _validate_date(data.get("issue_date") or invoice["issue_date"], "تاريخ الإصدار")
    due_date = _validate_date(data.get("due_date"), "تاريخ الاستحقاق", required=False)
    if due_date and due_date < issue_date:
        raise ValidationError("تاريخ الاستحقاق لا يمكن أن يسبق تاريخ الإصدار")

    status = (str(data.get("status") or invoice["status"])).strip()
    if status not in STATUSES:
        raise ValidationError("حالة الفاتورة غير معروفة")

    customer_id = _resolve_customer(conn, org_id, data.get("customer_id"))
    lines = _prepare_lines(data.get("lines"))
    totals = invoice_totals([
        {
            "unit_price": line["unit_price"],
            "quantity": line["quantity"],
            "vat_rate_bp": line["vat_rate_bp"],
            "discount": line["discount"],
        }
        for line in lines
    ])

    try:
        conn.execute(
            """UPDATE invoices SET customer_id = ?, issue_date = ?, due_date = ?, status = ?,
                                   notes = ?, gross_total = ?, discount_total = ?,
                                   taxable_total = ?, vat_total = ?, grand_total = ?, updated_at = ?
               WHERE id = ? AND org_id = ?""",
            (
                customer_id, issue_date, due_date, status,
                (str(data.get("notes") or "")).strip(),
                totals["gross"], totals["discount"], totals["taxable"],
                totals["vat"], totals["total"], now_iso(), invoice_id, org_id,
            ),
        )
        _write_lines(conn, invoice_id, lines)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return get_invoice(conn, org_id, invoice_id)


def set_status(conn, org_id: int, invoice_id: int, status: str) -> dict:
    invoice = get_invoice(conn, org_id, invoice_id)
    if status not in STATUSES:
        raise ValidationError("حالة الفاتورة غير معروفة")
    if invoice["status"] == status:
        return invoice

    db.execute(
        conn,
        "UPDATE invoices SET status = ?, updated_at = ? WHERE id = ? AND org_id = ?",
        (status, now_iso(), invoice_id, org_id),
    )
    return get_invoice(conn, org_id, invoice_id)


def delete_invoice(conn, org_id: int, invoice_id: int):
    """يحذف المسودات فقط. الفاتورة الصادرة تُلغى ولا تُحذف، حتى يبقى
    التسلسل الرقمي كاملًا وقابلًا للتدقيق."""
    invoice = get_invoice(conn, org_id, invoice_id)
    if invoice["status"] != "draft":
        raise ValidationError("لا يمكن حذف فاتورة صادرة — استخدم الإلغاء بدلًا من ذلك")
    db.execute(conn, "DELETE FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id))


def get_invoice(conn, org_id: int, invoice_id: int) -> dict:
    row = db.query_one(
        conn, "SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)
    )
    if row is None:
        raise ValidationError("الفاتورة غير موجودة")

    invoice = dict(row)
    invoice["lines"] = [
        dict(line)
        for line in db.query(
            conn,
            "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY position",
            (invoice_id,),
        )
    ]
    invoice["payments"] = [
        dict(payment)
        for payment in db.query(
            conn,
            "SELECT * FROM payments WHERE invoice_id = ? ORDER BY paid_on, id",
            (invoice_id,),
        )
    ]
    invoice["paid_total"] = sum(p["amount"] for p in invoice["payments"])
    invoice["balance"] = invoice["grand_total"] - invoice["paid_total"]

    if invoice["customer_id"]:
        customer = db.query_one(
            conn,
            "SELECT * FROM customers WHERE id = ? AND org_id = ?",
            (invoice["customer_id"], org_id),
        )
        invoice["customer"] = dict(customer) if customer else None
    else:
        invoice["customer"] = None

    # تفصيل الضريبة حسب النسبة، مطلوب في الفاتورة الضريبية عند اختلاف الفئات
    breakdown = {}
    for line in invoice["lines"]:
        bucket = breakdown.setdefault(line["vat_rate_bp"], {"taxable": 0, "vat": 0})
        bucket["taxable"] += line["taxable"]
        bucket["vat"] += line["vat_amount"]
    invoice["vat_breakdown"] = [
        {"rate_bp": rate, "taxable": values["taxable"], "vat": values["vat"]}
        for rate, values in sorted(breakdown.items(), reverse=True)
    ]
    invoice["is_overdue"] = is_overdue(invoice)
    return invoice


def is_overdue(invoice: dict) -> bool:
    """الفاتورة متأخرة إذا صدرت ولم تُسدَّد بالكامل وتجاوزت تاريخ استحقاقها."""
    if invoice["status"] != "sent" or not invoice["due_date"]:
        return False
    if invoice.get("balance", invoice["grand_total"]) <= 0:
        return False
    return invoice["due_date"] < date.today().isoformat()


def list_invoices(conn, org_id: int, status: str = None, customer_id: int = None,
                  search: str = None, limit: int = 100, offset: int = 0) -> list:
    sql = """SELECT i.*, c.name AS customer_name,
                    COALESCE((SELECT SUM(amount) FROM payments p WHERE p.invoice_id = i.id), 0)
                        AS paid_total
             FROM invoices i
             LEFT JOIN customers c ON c.id = i.customer_id
             WHERE i.org_id = ?"""
    params = [org_id]

    if status in STATUSES:
        sql += " AND i.status = ?"
        params.append(status)
    if customer_id:
        sql += " AND i.customer_id = ?"
        params.append(int(customer_id))
    if search:
        sql += " AND (i.number LIKE ? OR c.name LIKE ?)"
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern])

    sql += " ORDER BY i.issue_date DESC, i.id DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])

    results = []
    for row in db.query(conn, sql, params):
        invoice = dict(row)
        invoice["balance"] = invoice["grand_total"] - invoice["paid_total"]
        invoice["is_overdue"] = is_overdue(invoice)
        results.append(invoice)
    return results


# ---------------------------------------------------------------- المدفوعات

def add_payment(conn, org_id: int, invoice_id: int, data: dict) -> dict:
    """يسجّل دفعة (كاملة أو جزئية) ويحدّث حالة الفاتورة تلقائيًا."""
    invoice = get_invoice(conn, org_id, invoice_id)
    if invoice["status"] == "cancelled":
        raise ValidationError("لا يمكن تسجيل دفعة على فاتورة ملغاة")

    try:
        amount = parse_amount(data.get("amount"))
    except MoneyError as exc:
        raise ValidationError(str(exc))
    if amount <= 0:
        raise ValidationError("مبلغ الدفعة يجب أن يكون أكبر من صفر")
    if amount > invoice["balance"]:
        raise ValidationError("مبلغ الدفعة أكبر من المتبقي على الفاتورة")

    paid_on = _validate_date(data.get("paid_on") or date.today().isoformat(), "تاريخ الدفع")

    try:
        conn.execute(
            """INSERT INTO payments (org_id, invoice_id, amount, paid_on, method, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                org_id, invoice_id, amount, paid_on,
                (str(data.get("method") or "cash")).strip(),
                (str(data.get("note") or "")).strip(),
                now_iso(),
            ),
        )
        # السداد الكامل ينقل الفاتورة إلى "مدفوعة" دون تدخل يدوي
        if invoice["balance"] - amount <= 0:
            conn.execute(
                "UPDATE invoices SET status = 'paid', updated_at = ? WHERE id = ? AND org_id = ?",
                (now_iso(), invoice_id, org_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return get_invoice(conn, org_id, invoice_id)


def delete_payment(conn, org_id: int, invoice_id: int, payment_id: int) -> dict:
    """يحذف دفعة مسجّلة بالخطأ ويعيد حالة الفاتورة إلى "صادرة" إن لزم."""
    get_invoice(conn, org_id, invoice_id)
    payment = db.query_one(
        conn,
        "SELECT * FROM payments WHERE id = ? AND invoice_id = ? AND org_id = ?",
        (payment_id, invoice_id, org_id),
    )
    if payment is None:
        raise ValidationError("الدفعة غير موجودة")

    try:
        conn.execute("DELETE FROM payments WHERE id = ? AND org_id = ?", (payment_id, org_id))
        remaining = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()["total"]
        total = conn.execute(
            "SELECT grand_total, status FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if total["status"] == "paid" and remaining < total["grand_total"]:
            conn.execute(
                "UPDATE invoices SET status = 'sent', updated_at = ? WHERE id = ?",
                (now_iso(), invoice_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return get_invoice(conn, org_id, invoice_id)
