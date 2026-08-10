"""اختبارات حسابات المال والضريبة."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omanbill.money import (
    MoneyError,
    apply_percentage,
    format_amount,
    invoice_totals,
    line_totals,
    parse_amount,
    parse_quantity,
    round_half_up,
    vat_rate_for,
)


class RoundHalfUpTests(unittest.TestCase):
    def test_rounds_half_away_from_zero(self):
        # التقريب المصرفي كان سيُرجع 2 للحالتين، وهو ما نتجنبه
        self.assertEqual(round_half_up(5, 2), 3)
        self.assertEqual(round_half_up(7, 2), 4)

    def test_rounds_down_below_half(self):
        self.assertEqual(round_half_up(4, 3), 1)
        self.assertEqual(round_half_up(1, 3), 0)

    def test_negative_values_round_away_from_zero(self):
        self.assertEqual(round_half_up(-5, 2), -3)
        self.assertEqual(round_half_up(-1, 3), 0)

    def test_division_by_zero_rejected(self):
        with self.assertRaises(MoneyError):
            round_half_up(1, 0)


class ParseAmountTests(unittest.TestCase):
    def test_parses_three_decimals(self):
        self.assertEqual(parse_amount("12.750"), 12750)
        self.assertEqual(parse_amount("0.005"), 5)
        self.assertEqual(parse_amount("1"), 1000)

    def test_parses_integers_and_blanks(self):
        self.assertEqual(parse_amount(5), 5000)
        self.assertEqual(parse_amount(""), 0)
        self.assertEqual(parse_amount(None), 0)

    def test_strips_thousand_separators(self):
        self.assertEqual(parse_amount("1,250.500"), 1250500)

    def test_accepts_arabic_eastern_digits(self):
        self.assertEqual(parse_amount("١٢٫٧٥٠"), 12750)

    def test_rounds_sub_baisa_input(self):
        # أصغر من البيسة: يُقرَّب لأقرب بيسة بدل أن يُبتلع بصمت
        self.assertEqual(parse_amount("0.0004"), 0)
        self.assertEqual(parse_amount("0.0006"), 1)

    def test_rejects_garbage(self):
        with self.assertRaises(MoneyError):
            parse_amount("كذا")
        with self.assertRaises(MoneyError):
            parse_amount(True)


class ParseQuantityTests(unittest.TestCase):
    def test_parses_fractional_quantity(self):
        self.assertEqual(parse_quantity("2.5"), 2500)
        self.assertEqual(parse_quantity(3), 3000)

    def test_rejects_garbage(self):
        with self.assertRaises(MoneyError):
            parse_quantity("abc")


class FormatAmountTests(unittest.TestCase):
    def test_always_shows_three_decimals(self):
        self.assertEqual(format_amount(12750), "12.750")
        self.assertEqual(format_amount(5), "0.005")
        self.assertEqual(format_amount(1000), "1.000")

    def test_groups_thousands_and_keeps_sign(self):
        self.assertEqual(format_amount(1250500), "1,250.500")
        self.assertEqual(format_amount(-2500), "-2.500")

    def test_round_trips_with_parse(self):
        for text in ("0.001", "99.999", "1,000.000"):
            self.assertEqual(format_amount(parse_amount(text)), text)


class VatTests(unittest.TestCase):
    def test_standard_rate_is_five_percent(self):
        self.assertEqual(vat_rate_for("standard"), 500)
        self.assertEqual(vat_rate_for("zero"), 0)
        self.assertEqual(vat_rate_for("exempt"), 0)

    def test_unknown_category_rejected(self):
        with self.assertRaises(MoneyError):
            vat_rate_for("whatever")

    def test_five_percent_of_common_amounts(self):
        self.assertEqual(apply_percentage(100000, 500), 5000)   # 100 -> 5
        self.assertEqual(apply_percentage(12750, 500), 638)     # 12.750 -> 0.6375 -> 0.638
        self.assertEqual(apply_percentage(1, 500), 0)           # 0.001 -> 0.00005 -> 0


class LineTotalsTests(unittest.TestCase):
    def test_simple_line(self):
        result = line_totals(unit_price_baisa=10000, quantity_milli=2000, vat_rate_bp=500)
        self.assertEqual(result["gross"], 20000)
        self.assertEqual(result["taxable"], 20000)
        self.assertEqual(result["vat"], 1000)
        self.assertEqual(result["total"], 21000)

    def test_fractional_quantity(self):
        # 2.5 ساعة × 7.500 ر.ع = 18.750
        result = line_totals(unit_price_baisa=7500, quantity_milli=2500, vat_rate_bp=500)
        self.assertEqual(result["gross"], 18750)
        self.assertEqual(result["vat"], 938)  # 0.9375 -> 0.938
        self.assertEqual(result["total"], 19688)

    def test_vat_is_charged_after_discount(self):
        result = line_totals(
            unit_price_baisa=100000, quantity_milli=1000, vat_rate_bp=500, discount_baisa=10000
        )
        self.assertEqual(result["taxable"], 90000)
        self.assertEqual(result["vat"], 4500)  # 5% من 90 لا من 100
        self.assertEqual(result["total"], 94500)

    def test_discount_cannot_exceed_line_value(self):
        result = line_totals(
            unit_price_baisa=10000, quantity_milli=1000, vat_rate_bp=500, discount_baisa=99000
        )
        self.assertEqual(result["discount"], 10000)
        self.assertEqual(result["taxable"], 0)
        self.assertEqual(result["total"], 0)

    def test_exempt_line_has_no_vat(self):
        result = line_totals(unit_price_baisa=50000, quantity_milli=1000, vat_rate_bp=0)
        self.assertEqual(result["vat"], 0)
        self.assertEqual(result["total"], 50000)

    def test_negative_inputs_rejected(self):
        with self.assertRaises(MoneyError):
            line_totals(unit_price_baisa=-1, quantity_milli=1000, vat_rate_bp=500)
        with self.assertRaises(MoneyError):
            line_totals(unit_price_baisa=1000, quantity_milli=-1, vat_rate_bp=500)


class InvoiceTotalsTests(unittest.TestCase):
    def test_sums_lines(self):
        totals = invoice_totals([
            {"unit_price": 10000, "quantity": 2000, "vat_rate_bp": 500},
            {"unit_price": 5000, "quantity": 1000, "vat_rate_bp": 500},
        ])
        self.assertEqual(totals["taxable"], 25000)
        self.assertEqual(totals["vat"], 1250)
        self.assertEqual(totals["total"], 26250)

    def test_displayed_lines_sum_exactly_to_total(self):
        # ثلاثة بنود ينتج كل منها كسر بيسة عند حساب الضريبة.
        # الضريبة تُقرَّب لكل بند ثم تُجمع، فلا يظهر فرق بين مجموع
        # الأسطر المطبوعة وإجمالي الفاتورة.
        lines = [{"unit_price": 12750, "quantity": 1000, "vat_rate_bp": 500}] * 3
        totals = invoice_totals(lines)
        self.assertEqual(totals["vat"], 638 * 3)
        self.assertEqual(totals["total"], (12750 + 638) * 3)

    def test_mixed_rates_are_broken_down(self):
        totals = invoice_totals([
            {"unit_price": 100000, "quantity": 1000, "vat_rate_bp": 500},
            {"unit_price": 50000, "quantity": 1000, "vat_rate_bp": 0},
        ])
        self.assertEqual(totals["vat"], 5000)
        self.assertEqual(totals["total"], 155000)
        self.assertEqual(totals["vat_breakdown"][500], {"taxable": 100000, "vat": 5000})
        self.assertEqual(totals["vat_breakdown"][0], {"taxable": 50000, "vat": 0})

    def test_empty_invoice(self):
        totals = invoice_totals([])
        self.assertEqual(totals["total"], 0)
        self.assertEqual(totals["vat_breakdown"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
