#!/usr/bin/env python3
"""يجمع الواجهة في ملف HTML واحد يعمل بلا خادم، للعرض التجريبي.

    python3 demo/build_demo.py [مسار الإخراج]

الناتج صفحة واحدة مكتفية بذاتها: نفس ملفات web/ بلا أي تعديل، مضافًا إليها
طبقة demo_backend.js التي تحاكي الخادم داخل المتصفح.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
DEMO = os.path.join(ROOT, "demo")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def body_markup() -> str:
    """يستخرج محتوى <body> من index.html بعد إزالة وسوم <script>.

    الصفحة المنشورة تُغلَّف تلقائيًا بـ head و body، فنأخذ المحتوى وحده.
    """
    html = read(os.path.join(WEB, "index.html"))
    match = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not match:
        raise SystemExit("تعذّر العثور على <body> في index.html")
    markup = match.group(1)
    return re.sub(r"<script\b[^>]*>.*?</script>", "", markup, flags=re.S).strip()


def inline_script(source: str) -> str:
    """يمنع إنهاء وسم <script> مبكرًا لو ظهر النص داخل الكود."""
    return source.replace("</script", "<\\/script")


BANNER = """<div class="demo-badge no-print">
  <strong>نسخة تجريبية</strong>
  البيانات محفوظة في متصفحك فقط، ولا تُرسل إلى أي مكان. جرّب ما تشاء —
  إعادة تحميل الصفحة تعيد كل شيء إلى حالته الأولى.
</div>
"""

EXTRA_CSS = """
/* شارة النسخة التجريبية — داخل الشريط الجانبي حتى لا تحجب أي بيانات */
.demo-badge {
  margin: 10px 12px;
  padding: 11px 13px;
  background: var(--info-soft);
  border: 1px solid #cddef5;
  border-radius: 9px;
  color: #1b4f8a;
  font-size: 12px;
  line-height: 1.65;
}

.demo-badge strong { display: block; margin-bottom: 3px; font-size: 12.5px; }

@media (max-width: 820px) {
  .demo-badge { margin: 0 12px 10px; }
}
"""


def build() -> str:
    # الشارة تُدرج داخل الشريط الجانبي أعلى تذييله، لا كطبقة عائمة فوق الجداول
    markup = body_markup()
    anchor = '<div class="sidebar-footer">'
    if anchor not in markup:
        raise SystemExit("تعذّر العثور على تذييل الشريط الجانبي في index.html")
    markup = markup.replace(anchor, BANNER + "\n    " + anchor, 1)

    return f"""<title>نظام الفوترة — سلطنة عُمان</title>
<style>
{read(os.path.join(WEB, 'styles.css'))}
{EXTRA_CSS}
</style>

{markup}

<script>
// الصفحة المنشورة لا تسمح بضبط سمات <html> مباشرة، فنضبط الاتجاه من الكود
document.documentElement.setAttribute('dir', 'rtl');
document.documentElement.setAttribute('lang', 'ar');
</script>

<script>
{inline_script(read(os.path.join(DEMO, 'demo_backend.js')))}
</script>

<script>
{inline_script(read(os.path.join(WEB, 'app.js')))}
</script>
"""


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DEMO, "demo.html")
    html = build()
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(html)
    print(f"تم إنشاء العرض التجريبي: {target}  ({len(html.encode('utf-8')) / 1024:.0f} كيلوبايت)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
