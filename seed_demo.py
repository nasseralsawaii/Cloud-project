#!/usr/bin/env python3
"""يعبّئ حسابًا تجريبيًا ببيانات واقعية، لعرض البرنامج على عميل محتمل.

    python3 seed_demo.py

بيانات الدخول بعد التشغيل:
    البريد : demo@omanbill.om
    المرور : demo12345
"""

import random
import sys
from datetime import date, timedelta

from omanbill import auth, db, invoices, store

DEMO_EMAIL = "demo@omanbill.om"
DEMO_PASSWORD = "demo12345"

CUSTOMERS = [
    {"name": "شركة الخليج للمقاولات", "vat_number": "OM1100998877", "phone": "99887766",
     "address": "الخوير، مسقط"},
    {"name": "مؤسسة البحر الأزرق", "vat_number": "OM1100445566", "phone": "95441122",
     "address": "صحار"},
    {"name": "مكتب الرؤية للاستشارات", "vat_number": "OM1100223344", "phone": "91223344",
     "address": "روي، مسقط"},
    {"name": "بقالة الوادي", "phone": "92556677", "address": "نزوى"},
]

ITEMS = [
    {"name": "استشارة هندسية", "unit": "ساعة", "unit_price": "12.750"},
    {"name": "تصميم هوية بصرية", "unit": "مشروع", "unit_price": "250.000"},
    {"name": "صيانة دورية", "unit": "زيارة", "unit_price": "35.500"},
    {"name": "توريد أثاث مكتبي", "unit": "قطعة", "unit_price": "45.500"},
    {"name": "خدمة تصدير", "unit": "شحنة", "unit_price": "500.000", "vat_category": "zero"},
]


def main():
    conn = db.init_db()

    existing = db.query_one(conn, "SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,))
    if existing:
        print("الحساب التجريبي موجود مسبقًا.")
        print(f"  البريد: {DEMO_EMAIL}\n  المرور: {DEMO_PASSWORD}")
        return 0

    user = auth.register(conn, DEMO_EMAIL, DEMO_PASSWORD, "مؤسسة النور للتجارة", "ناصر")
    org_id = user["org_id"]

    store.update_org(conn, org_id, {
        "name": "مؤسسة النور للتجارة",
        "vat_number": "OM1100234567",
        "cr_number": "1234567",
        "phone": "92345678",
        "email": "info@alnoor.om",
        "address": "روي، مسقط، سلطنة عُمان",
        "invoice_prefix": "NOOR",
    })
    # الباقة الاحترافية حتى لا يصطدم العرض التجريبي بحد الفواتير المجاني
    store.set_plan(conn, org_id, "pro")

    customers = [store.create_customer(conn, org_id, data) for data in CUSTOMERS]
    items = [store.create_item(conn, org_id, data) for data in ITEMS]

    random.seed(7)  # نتيجة ثابتة عند كل تشغيل
    created = 0

    for months_ago in range(5, -1, -1):
        first = (date.today().replace(day=1) - timedelta(days=months_ago * 30)).replace(day=1)
        for _ in range(random.randint(3, 7)):
            issue = first + timedelta(days=random.randint(0, 25))
            if issue > date.today():
                continue

            lines = []
            for item in random.sample(items, random.randint(1, 3)):
                lines.append({
                    "description": item["name"],
                    "unit": item["unit"],
                    "quantity": str(random.choice([1, 1, 2, 3, "2.5"])),
                    "unit_price": f"{item['unit_price'] / 1000:.3f}",
                    "vat_category": item["vat_category"],
                })

            invoice = invoices.create_invoice(conn, org_id, {
                "customer_id": random.choice(customers)["id"],
                "issue_date": issue.isoformat(),
                "due_date": (issue + timedelta(days=30)).isoformat(),
                "status": "sent",
                "notes": "الدفع خلال 30 يومًا من تاريخ الفاتورة.",
                "lines": lines,
            })
            created += 1

            # أغلب الفواتير القديمة سُدّدت، وبعض الحديثة ما زالت معلّقة
            roll = random.random()
            if months_ago > 0 and roll < 0.8:
                invoices.add_payment(conn, org_id, invoice["id"], {
                    "amount": f"{invoice['grand_total'] / 1000:.3f}",
                    "paid_on": (issue + timedelta(days=random.randint(1, 25))).isoformat(),
                    "method": random.choice(["cash", "bank", "cheque"]),
                })
            elif roll < 0.9:
                invoices.add_payment(conn, org_id, invoice["id"], {
                    "amount": f"{invoice['grand_total'] // 2000:.3f}",
                    "paid_on": (issue + timedelta(days=5)).isoformat(),
                    "method": "bank",
                })

    print(f"تم إنشاء حساب تجريبي فيه {created} فاتورة.")
    print(f"  البريد: {DEMO_EMAIL}\n  المرور: {DEMO_PASSWORD}")
    print("\nشغّل البرنامج الآن:  python3 app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
