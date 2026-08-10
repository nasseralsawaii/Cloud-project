"""حساب المبالغ بالريال العُماني.

الريال العُماني يتكوّن من 1000 بيسة، أي ثلاث خانات عشرية. كل المبالغ في هذا
النظام تُخزَّن وتُحسب كأعداد صحيحة بالبيسة، ولا تُستخدم الأعداد العشرية (float)
في أي خطوة حسابية، لأن أخطاء التقريب فيها تُنتج فواتير ومبالغ ضريبية خاطئة.

الاصطلاحات:
    - المبالغ: عدد صحيح بالبيسة (1.500 ر.ع = 1500).
    - الكميات: عدد صحيح من أجزاء الألف (2.5 وحدة = 2500).
    - نسب الضريبة: نقاط أساس basis points (5% = 500).
"""

from decimal import Decimal, InvalidOperation

# عدد البيسة في الريال العُماني الواحد
BAISA_PER_RIAL = 1000

# دقة الكميات (أجزاء الألف)
QTY_SCALE = 1000

# نقاط الأساس في 100%
BASIS_POINTS = 10000

# نسبة ضريبة القيمة المضافة القياسية في سلطنة عُمان
STANDARD_VAT_RATE_BP = 500  # 5%

# فئات الضريبة المعتمدة
VAT_CATEGORIES = {
    "standard": STANDARD_VAT_RATE_BP,  # نسبة أساسية 5%
    "zero": 0,                         # نسبة صفرية (صادرات، سلع محددة)
    "exempt": 0,                       # معفاة من الضريبة
}


class MoneyError(ValueError):
    """خطأ في تحويل أو حساب مبلغ."""


def round_half_up(numerator: int, denominator: int) -> int:
    """يقسم عددين صحيحين ويقرّب لأقرب عدد صحيح، والنصف يُقرَّب بعيدًا عن الصفر.

    التقريب المصرفي (banker's rounding) المستخدم افتراضيًا في بايثون يقرّب
    0.5 إلى أقرب عدد زوجي، وهو ليس ما تتوقعه الجهات الضريبية ولا العملاء.
    هذه الدالة تطبّق التقريب الحسابي المعتاد: 0.5 يصعد دائمًا.
    """
    if denominator == 0:
        raise MoneyError("القسمة على صفر غير ممكنة")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator

    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    # للأعداد السالبة نقرّب بعيدًا عن الصفر بنفس المقدار
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def parse_amount(value) -> int:
    """يحوّل مبلغًا مكتوبًا بالريال إلى عدد صحيح بالبيسة.

    يقبل النص ("12.750") أو الأعداد. يرفض ما لا يمكن تحويله بدل أن يُرجع صفرًا
    بصمت، لأن ابتلاع الخطأ هنا يعني فاتورة بمبلغ خاطئ.
    """
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise MoneyError("قيمة المبلغ غير صالحة")
    if isinstance(value, int):
        return value * BAISA_PER_RIAL

    text = str(value).strip()
    # إزالة الفواصل الآلاف والأرقام العربية الشرقية إن وُجدت
    text = text.replace(",", "").replace("٬", "").replace("٫", ".")
    text = text.translate(_ARABIC_DIGITS)
    if not text:
        return 0
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        raise MoneyError(f"قيمة المبلغ غير صالحة: {value}")

    scaled = amount * BAISA_PER_RIAL
    # نرفض الكسور الأصغر من البيسة بدل تقريبها بصمت
    return round_half_up(int(scaled.scaleb(6)), 10 ** 6)


def parse_quantity(value) -> int:
    """يحوّل كمية إلى عدد صحيح من أجزاء الألف (2.5 -> 2500)."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise MoneyError("قيمة الكمية غير صالحة")
    if isinstance(value, int):
        return value * QTY_SCALE

    text = str(value).strip().replace(",", "").replace("٫", ".")
    text = text.translate(_ARABIC_DIGITS)
    if not text:
        return 0
    try:
        qty = Decimal(text)
    except (InvalidOperation, ValueError):
        raise MoneyError(f"قيمة الكمية غير صالحة: {value}")
    return round_half_up(int((qty * QTY_SCALE).scaleb(6)), 10 ** 6)


def format_amount(baisa: int) -> str:
    """يعرض مبلغًا بالبيسة على هيئة نص بثلاث خانات عشرية ("12.750")."""
    sign = "-" if baisa < 0 else ""
    baisa = abs(int(baisa))
    rials, fraction = divmod(baisa, BAISA_PER_RIAL)
    return f"{sign}{rials:,}.{fraction:03d}"


def vat_rate_for(category: str) -> int:
    """يُرجع نسبة الضريبة بنقاط الأساس لفئة ضريبية."""
    if category not in VAT_CATEGORIES:
        raise MoneyError(f"فئة ضريبية غير معروفة: {category}")
    return VAT_CATEGORIES[category]


def apply_percentage(amount_baisa: int, rate_bp: int) -> int:
    """يحسب نسبة مئوية من مبلغ، بنقاط الأساس، مع تقريب نصفي لأعلى."""
    return round_half_up(amount_baisa * rate_bp, BASIS_POINTS)


def line_totals(
    unit_price_baisa: int,
    quantity_milli: int,
    vat_rate_bp: int,
    discount_baisa: int = 0,
) -> dict:
    """يحسب مجاميع بند واحد في الفاتورة.

    الترتيب مهم ضريبيًا: يُطرح الخصم أولًا، ثم تُحسب الضريبة على الصافي بعد
    الخصم — لأن الضريبة تُفرض على المقابل الفعلي المدفوع لا على السعر قبل الخصم.

    يُرجع: gross (قبل الخصم)، discount، taxable (الوعاء الضريبي)،
    vat (مبلغ الضريبة)، total (الإجمالي شامل الضريبة).
    """
    if quantity_milli < 0:
        raise MoneyError("الكمية لا يمكن أن تكون سالبة")
    if unit_price_baisa < 0:
        raise MoneyError("سعر الوحدة لا يمكن أن يكون سالبًا")
    if discount_baisa < 0:
        raise MoneyError("الخصم لا يمكن أن يكون سالبًا")

    gross = round_half_up(unit_price_baisa * quantity_milli, QTY_SCALE)

    # الخصم لا يتجاوز قيمة البند، وإلا لأصبح الوعاء الضريبي سالبًا
    discount = min(discount_baisa, gross)
    taxable = gross - discount
    vat = apply_percentage(taxable, vat_rate_bp)

    return {
        "gross": gross,
        "discount": discount,
        "taxable": taxable,
        "vat": vat,
        "total": taxable + vat,
    }


def invoice_totals(lines: list) -> dict:
    """يجمع مجاميع الفاتورة من بنودها.

    الضريبة تُحسب وتُقرَّب على مستوى كل بند ثم تُجمع، لا تُحسب على الإجمالي.
    هذا يضمن أن مجموع الأسطر المعروضة في الفاتورة يساوي الإجمالي بالضبط،
    فلا تظهر فروق بيسة واحدة يصعب تفسيرها للعميل أو للمدقّق الضريبي.

    كل عنصر في lines قاموس يحتوي: unit_price, quantity, vat_rate_bp, discount.
    """
    totals = {"gross": 0, "discount": 0, "taxable": 0, "vat": 0, "total": 0}
    vat_breakdown = {}

    for line in lines:
        computed = line_totals(
            unit_price_baisa=line["unit_price"],
            quantity_milli=line["quantity"],
            vat_rate_bp=line["vat_rate_bp"],
            discount_baisa=line.get("discount", 0),
        )
        for key in totals:
            totals[key] += computed[key]

        # تفصيل الضريبة حسب النسبة، مطلوب في الفاتورة الضريبية النظامية
        rate = line["vat_rate_bp"]
        bucket = vat_breakdown.setdefault(rate, {"taxable": 0, "vat": 0})
        bucket["taxable"] += computed["taxable"]
        bucket["vat"] += computed["vat"]

    totals["vat_breakdown"] = vat_breakdown
    return totals


# جدول تحويل الأرقام العربية الشرقية والفارسية إلى أرقام لاتينية
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
