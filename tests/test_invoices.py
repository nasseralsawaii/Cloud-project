"""اختبارات منطق الفواتير والمدفوعات والعزل بين المشتركين."""

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omanbill import auth, db, invoices, reports, store
from omanbill.store import ValidationError


class BaseCase(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        db.close()
        self.conn = db.init_db(self.db_path)

        user = auth.register(self.conn, "owner@shop.om", "password123", "مؤسسة النور")
        self.org_id = user["org_id"]
        self.user_id = user["id"]
        self.customer = store.create_customer(
            self.conn, self.org_id, {"name": "شركة الخليج", "vat_number": "OM1100112233"}
        )

    def tearDown(self):
        db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def make_invoice(self, **overrides):
        data = {
            "customer_id": self.customer["id"],
            "issue_date": date.today().isoformat(),
            "status": "sent",
            "lines": [
                {"description": "خدمة تصميم", "quantity": "1", "unit_price": "100.000"},
            ],
        }
        data.update(overrides)
        return invoices.create_invoice(self.conn, self.org_id, data)


class InvoiceCreationTests(BaseCase):
    def test_totals_are_computed_by_the_server(self):
        invoice = self.make_invoice()
        self.assertEqual(invoice["taxable_total"], 100000)
        self.assertEqual(invoice["vat_total"], 5000)
        self.assertEqual(invoice["grand_total"], 105000)

    def test_client_supplied_totals_are_ignored(self):
        # محاولة تمرير مجاميع مزوّرة من الواجهة يجب ألا تؤثر إطلاقًا
        invoice = self.make_invoice(grand_total=1, vat_total=0, taxable_total=1)
        self.assertEqual(invoice["vat_total"], 5000)
        self.assertEqual(invoice["grand_total"], 105000)

    def test_numbers_are_sequential_and_unique(self):
        numbers = [self.make_invoice()["number"] for _ in range(3)]
        self.assertEqual(numbers, ["INV-00001", "INV-00002", "INV-00003"])
        self.assertEqual(len(set(numbers)), 3)

    def test_number_uses_org_prefix(self):
        store.update_org(self.conn, self.org_id, {"name": "مؤسسة النور", "invoice_prefix": "NOOR"})
        self.assertTrue(self.make_invoice()["number"].startswith("NOOR-"))

    def test_invoice_requires_at_least_one_line(self):
        with self.assertRaises(ValidationError):
            self.make_invoice(lines=[])

    def test_line_needs_description_and_positive_quantity(self):
        with self.assertRaises(ValidationError):
            self.make_invoice(lines=[{"description": "", "quantity": "1", "unit_price": "5"}])
        with self.assertRaises(ValidationError):
            self.make_invoice(lines=[{"description": "س", "quantity": "0", "unit_price": "5"}])

    def test_rejects_bad_dates(self):
        with self.assertRaises(ValidationError):
            self.make_invoice(issue_date="15-01-2026")
        with self.assertRaises(ValidationError):
            self.make_invoice(issue_date="2026-02-30")

    def test_due_date_cannot_precede_issue_date(self):
        with self.assertRaises(ValidationError):
            self.make_invoice(issue_date="2026-03-10", due_date="2026-03-01")

    def test_mixed_vat_categories_are_broken_down(self):
        invoice = self.make_invoice(lines=[
            {"description": "سلعة", "quantity": "1", "unit_price": "100.000",
             "vat_category": "standard"},
            {"description": "تصدير", "quantity": "1", "unit_price": "50.000",
             "vat_category": "zero"},
        ])
        self.assertEqual(invoice["vat_total"], 5000)
        self.assertEqual(invoice["grand_total"], 155000)
        self.assertEqual(len(invoice["vat_breakdown"]), 2)

    def test_rejects_unknown_vat_category(self):
        with self.assertRaises(ValidationError):
            self.make_invoice(lines=[
                {"description": "س", "quantity": "1", "unit_price": "5", "vat_category": "made_up"}
            ])


class TenantIsolationTests(BaseCase):
    def setUp(self):
        super().setUp()
        other = auth.register(self.conn, "rival@other.om", "password123", "منشأة أخرى")
        self.other_org_id = other["org_id"]

    def test_cannot_read_another_orgs_invoice(self):
        invoice = self.make_invoice()
        with self.assertRaises(ValidationError):
            invoices.get_invoice(self.conn, self.other_org_id, invoice["id"])

    def test_cannot_attach_another_orgs_customer(self):
        with self.assertRaises(ValidationError):
            invoices.create_invoice(self.conn, self.other_org_id, {
                "customer_id": self.customer["id"],
                "issue_date": date.today().isoformat(),
                "lines": [{"description": "س", "quantity": "1", "unit_price": "1"}],
            })

    def test_listing_is_scoped_to_the_org(self):
        self.make_invoice()
        self.assertEqual(len(invoices.list_invoices(self.conn, self.org_id)), 1)
        self.assertEqual(len(invoices.list_invoices(self.conn, self.other_org_id)), 0)

    def test_each_org_has_its_own_numbering(self):
        self.make_invoice()
        other_invoice = invoices.create_invoice(self.conn, self.other_org_id, {
            "issue_date": date.today().isoformat(),
            "lines": [{"description": "س", "quantity": "1", "unit_price": "1"}],
        })
        self.assertEqual(other_invoice["number"], "INV-00001")


class PaymentTests(BaseCase):
    def test_partial_then_full_payment(self):
        invoice = self.make_invoice()
        invoice = invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "50.000"})
        self.assertEqual(invoice["balance"], 55000)
        self.assertEqual(invoice["status"], "sent")

        invoice = invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "55.000"})
        self.assertEqual(invoice["balance"], 0)
        self.assertEqual(invoice["status"], "paid")

    def test_overpayment_rejected(self):
        invoice = self.make_invoice()
        with self.assertRaises(ValidationError):
            invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "200.000"})

    def test_zero_or_negative_payment_rejected(self):
        invoice = self.make_invoice()
        with self.assertRaises(ValidationError):
            invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "0"})

    def test_deleting_payment_reopens_invoice(self):
        invoice = self.make_invoice()
        invoice = invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "105.000"})
        self.assertEqual(invoice["status"], "paid")

        payment_id = invoice["payments"][0]["id"]
        invoice = invoices.delete_payment(self.conn, self.org_id, invoice["id"], payment_id)
        self.assertEqual(invoice["status"], "sent")
        self.assertEqual(invoice["balance"], 105000)

    def test_cannot_pay_cancelled_invoice(self):
        invoice = self.make_invoice()
        invoices.set_status(self.conn, self.org_id, invoice["id"], "cancelled")
        with self.assertRaises(ValidationError):
            invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "1.000"})


class LifecycleTests(BaseCase):
    def test_paid_invoice_cannot_be_edited(self):
        invoice = self.make_invoice()
        invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "105.000"})
        with self.assertRaises(ValidationError):
            invoices.update_invoice(self.conn, self.org_id, invoice["id"], {
                "lines": [{"description": "تعديل", "quantity": "1", "unit_price": "1.000"}],
            })

    def test_issued_invoice_cannot_be_deleted(self):
        invoice = self.make_invoice(status="sent")
        with self.assertRaises(ValidationError):
            invoices.delete_invoice(self.conn, self.org_id, invoice["id"])

    def test_draft_can_be_deleted(self):
        invoice = self.make_invoice(status="draft")
        invoices.delete_invoice(self.conn, self.org_id, invoice["id"])
        with self.assertRaises(ValidationError):
            invoices.get_invoice(self.conn, self.org_id, invoice["id"])

    def test_overdue_detection(self):
        past = (date.today() - timedelta(days=5)).isoformat()
        invoice = self.make_invoice(issue_date=past, due_date=past, status="sent")
        self.assertTrue(invoice["is_overdue"])

        invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "105.000"})
        self.assertFalse(invoices.get_invoice(self.conn, self.org_id, invoice["id"])["is_overdue"])


class PlanLimitTests(BaseCase):
    def test_free_plan_caps_monthly_invoices(self):
        limit = store.PLAN_LIMITS["free"]["invoices_per_month"]
        for _ in range(limit):
            self.make_invoice()
        with self.assertRaises(ValidationError):
            self.make_invoice()

    def test_pro_plan_removes_the_cap(self):
        store.set_plan(self.conn, self.org_id, "pro")
        limit = store.PLAN_LIMITS["free"]["invoices_per_month"]
        for _ in range(limit + 3):
            self.make_invoice()
        self.assertEqual(len(invoices.list_invoices(self.conn, self.org_id, limit=500)), limit + 3)


class ReportTests(BaseCase):
    def test_drafts_are_excluded_from_sales(self):
        self.make_invoice(status="sent")
        self.make_invoice(status="draft")
        summary = reports.dashboard(self.conn, self.org_id)
        self.assertEqual(summary["month_sales_total"], 105000)
        self.assertEqual(summary["draft_count"], 1)

    def test_cancelled_are_excluded_from_vat_return(self):
        invoice = self.make_invoice(status="sent")
        invoices.set_status(self.conn, self.org_id, invoice["id"], "cancelled")
        result = reports.vat_return(self.conn, self.org_id, "2000-01-01", "2999-12-31")
        self.assertEqual(result["total_vat"], 0)

    def test_vat_return_totals(self):
        self.make_invoice(status="sent")
        self.make_invoice(status="sent")
        result = reports.vat_return(self.conn, self.org_id, "2000-01-01", "2999-12-31")
        self.assertEqual(result["total_taxable"], 200000)
        self.assertEqual(result["total_vat"], 10000)
        self.assertEqual(result["invoice_count"], 2)

    def test_outstanding_balance_accounts_for_partial_payments(self):
        invoice = self.make_invoice(status="sent")
        invoices.add_payment(self.conn, self.org_id, invoice["id"], {"amount": "5.000"})
        summary = reports.dashboard(self.conn, self.org_id)
        self.assertEqual(summary["outstanding_balance"], 100000)

    def test_csv_export_has_bom_and_headers(self):
        self.make_invoice()
        output = reports.invoices_csv(self.conn, self.org_id, "2000-01-01", "2999-12-31")
        self.assertTrue(output.startswith("﻿"))  # حتى يقرأ Excel العربية
        self.assertIn("رقم الفاتورة", output)
        self.assertIn("105.000", output)


class AuthTests(BaseCase):
    def test_login_succeeds_with_correct_password(self):
        user = auth.login(self.conn, "owner@shop.om", "password123")
        self.assertEqual(user["org_id"], self.org_id)

    def test_login_fails_with_wrong_password(self):
        with self.assertRaises(auth.AuthError):
            auth.login(self.conn, "owner@shop.om", "wrong-password")

    def test_login_fails_for_unknown_email(self):
        with self.assertRaises(auth.AuthError):
            auth.login(self.conn, "nobody@shop.om", "password123")

    def test_duplicate_email_rejected(self):
        with self.assertRaises(auth.AuthError):
            auth.register(self.conn, "owner@shop.om", "password123", "منشأة مكررة")

    def test_short_password_rejected(self):
        with self.assertRaises(auth.AuthError):
            auth.register(self.conn, "new@shop.om", "123", "منشأة")

    def test_password_is_not_stored_in_plain_text(self):
        row = db.query_one(self.conn, "SELECT password_hash FROM users WHERE id = ?", (self.user_id,))
        self.assertNotIn("password123", row["password_hash"])
        self.assertTrue(row["password_hash"].startswith("pbkdf2_sha256$"))

    def test_session_round_trip(self):
        token = auth.create_session(self.conn, self.user_id)
        resolved = auth.resolve_session(self.conn, token)
        self.assertEqual(resolved["id"], self.user_id)

        auth.destroy_session(self.conn, token)
        self.assertIsNone(auth.resolve_session(self.conn, token))

    def test_invalid_token_resolves_to_nothing(self):
        self.assertIsNone(auth.resolve_session(self.conn, "not-a-real-token"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
