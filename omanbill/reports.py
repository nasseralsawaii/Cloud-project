"""التقارير: لوحة المؤشرات، المبيعات الشهرية، وملخص الإقرار الضريبي.

المسودات والفواتير الملغاة مستبعدة من كل الأرقام المالية — المسودة لم تصدر
للعميل بعد، والملغاة لا أثر لها محاسبيًا.
"""

import csv
import io
from datetime import date

from . import db
from .invoices import COUNTED_STATUSES
from .money import format_amount

_COUNTED = ", ".join(f"'{status}'" for status in COUNTED_STATUSES)


def dashboard(conn, org_id: int) -> dict:
    """مؤشرات الصفحة الرئيسية."""
    today = date.today().isoformat()
    month = today[:7]

    month_row = db.query_one(
        conn,
        f"""SELECT COALESCE(SUM(taxable_total), 0) AS taxable,
                   COALESCE(SUM(vat_total), 0)     AS vat,
                   COALESCE(SUM(grand_total), 0)   AS total,
                   COUNT(*)                        AS count
            FROM invoices
            WHERE org_id = ? AND substr(issue_date, 1, 7) = ? AND status IN ({_COUNTED})""",
        (org_id, month),
    )

    # المتبقي على العملاء: إجمالي الفواتير الصادرة ناقص ما سُدّد منها
    outstanding_row = db.query_one(
        conn,
        """SELECT COALESCE(SUM(i.grand_total), 0) - COALESCE(SUM(
                      (SELECT COALESCE(SUM(p.amount), 0) FROM payments p WHERE p.invoice_id = i.id)
                  ), 0) AS balance,
                  COUNT(*) AS count
           FROM invoices i
           WHERE i.org_id = ? AND i.status = 'sent'""",
        (org_id,),
    )

    overdue_row = db.query_one(
        conn,
        """SELECT COUNT(*) AS count,
                  COALESCE(SUM(i.grand_total -
                      (SELECT COALESCE(SUM(p.amount), 0) FROM payments p WHERE p.invoice_id = i.id)
                  ), 0) AS balance
           FROM invoices i
           WHERE i.org_id = ? AND i.status = 'sent'
             AND i.due_date != '' AND i.due_date < ?""",
        (org_id, today),
    )

    drafts = db.query_one(
        conn,
        "SELECT COUNT(*) AS count FROM invoices WHERE org_id = ? AND status = 'draft'",
        (org_id,),
    )["count"]

    return {
        "month": month,
        "month_sales_taxable": month_row["taxable"],
        "month_sales_vat": month_row["vat"],
        "month_sales_total": month_row["total"],
        "month_invoice_count": month_row["count"],
        "outstanding_balance": outstanding_row["balance"],
        "outstanding_count": outstanding_row["count"],
        "overdue_count": overdue_row["count"],
        "overdue_balance": overdue_row["balance"],
        "draft_count": drafts,
    }


def monthly_sales(conn, org_id: int, months: int = 12) -> list:
    """المبيعات لكل شهر، بترتيب تصاعدي، لآخر عدد من الأشهر."""
    rows = db.query(
        conn,
        f"""SELECT substr(issue_date, 1, 7) AS month,
                   COALESCE(SUM(taxable_total), 0) AS taxable,
                   COALESCE(SUM(vat_total), 0)     AS vat,
                   COALESCE(SUM(grand_total), 0)   AS total,
                   COUNT(*)                        AS count
            FROM invoices
            WHERE org_id = ? AND status IN ({_COUNTED})
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?""",
        (org_id, max(1, min(int(months), 60))),
    )
    return [dict(row) for row in reversed(rows)]


def vat_return(conn, org_id: int, date_from: str, date_to: str) -> dict:
    """ملخص يُستخدم في تعبئة الإقرار الضريبي عن فترة محددة.

    يفصّل الوعاء الضريبي والضريبة حسب النسبة، لأن الإقرار يطلب المبيعات
    الخاضعة للنسبة الأساسية والصفرية والمعفاة كل على حدة.
    """
    rows = db.query(
        conn,
        f"""SELECT l.vat_rate_bp AS rate_bp,
                   l.vat_category AS category,
                   COALESCE(SUM(l.taxable), 0)    AS taxable,
                   COALESCE(SUM(l.vat_amount), 0) AS vat
            FROM invoice_lines l
            JOIN invoices i ON i.id = l.invoice_id
            WHERE i.org_id = ? AND i.status IN ({_COUNTED})
              AND i.issue_date >= ? AND i.issue_date <= ?
            GROUP BY l.vat_rate_bp, l.vat_category
            ORDER BY l.vat_rate_bp DESC""",
        (org_id, date_from, date_to),
    )

    breakdown = [dict(row) for row in rows]
    invoice_count = db.query_one(
        conn,
        f"""SELECT COUNT(*) AS c FROM invoices
            WHERE org_id = ? AND status IN ({_COUNTED})
              AND issue_date >= ? AND issue_date <= ?""",
        (org_id, date_from, date_to),
    )["c"]

    return {
        "date_from": date_from,
        "date_to": date_to,
        "invoice_count": invoice_count,
        "breakdown": breakdown,
        "total_taxable": sum(item["taxable"] for item in breakdown),
        "total_vat": sum(item["vat"] for item in breakdown),
    }


def top_customers(conn, org_id: int, limit: int = 10) -> list:
    rows = db.query(
        conn,
        f"""SELECT c.id, c.name,
                   COUNT(i.id) AS invoice_count,
                   COALESCE(SUM(i.grand_total), 0) AS total
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = ? AND i.status IN ({_COUNTED})
            GROUP BY c.id, c.name
            ORDER BY total DESC
            LIMIT ?""",
        (org_id, max(1, min(int(limit), 100))),
    )
    return [dict(row) for row in rows]


def invoices_csv(conn, org_id: int, date_from: str, date_to: str) -> str:
    """يصدّر الفواتير كملف CSV يفتح في Excel.

    يُكتب بترميز UTF-8 مع BOM، وإلا فتح Excel على ويندوز الأسماء العربية
    كرموز غير مقروءة.
    """
    rows = db.query(
        conn,
        """SELECT i.number, i.issue_date, i.due_date, i.status,
                  COALESCE(c.name, '') AS customer_name,
                  COALESCE(c.vat_number, '') AS customer_vat,
                  i.taxable_total, i.vat_total, i.grand_total,
                  COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = i.id), 0)
                      AS paid_total
           FROM invoices i
           LEFT JOIN customers c ON c.id = i.customer_id
           WHERE i.org_id = ? AND i.issue_date >= ? AND i.issue_date <= ?
           ORDER BY i.issue_date, i.id""",
        (org_id, date_from, date_to),
    )

    status_labels = {
        "draft": "مسودة", "sent": "صادرة", "paid": "مدفوعة", "cancelled": "ملغاة",
    }

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "رقم الفاتورة", "تاريخ الإصدار", "تاريخ الاستحقاق", "الحالة", "العميل",
        "الرقم الضريبي للعميل", "المبلغ قبل الضريبة", "ضريبة القيمة المضافة",
        "الإجمالي", "المسدّد", "المتبقي",
    ])
    for row in rows:
        writer.writerow([
            row["number"], row["issue_date"], row["due_date"],
            status_labels.get(row["status"], row["status"]),
            row["customer_name"], row["customer_vat"],
            format_amount(row["taxable_total"]),
            format_amount(row["vat_total"]),
            format_amount(row["grand_total"]),
            format_amount(row["paid_total"]),
            format_amount(row["grand_total"] - row["paid_total"]),
        ])

    return "﻿" + buffer.getvalue()
