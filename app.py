#!/usr/bin/env python3
"""نقطة تشغيل نظام الفوترة.

    python3 app.py                  # يعمل على http://127.0.0.1:8000
    python3 app.py --port 9000
    python3 app.py --host 0.0.0.0   # للوصول من أجهزة أخرى في نفس الشبكة
"""

import argparse
import sys

from omanbill.server import run


def main():
    parser = argparse.ArgumentParser(description="نظام فوترة للمنشآت الصغيرة في عُمان")
    parser.add_argument("--host", default="127.0.0.1", help="عنوان الاستماع")
    parser.add_argument("--port", type=int, default=8000, help="المنفذ")
    parser.add_argument("--db", default=None, help="مسار ملف قاعدة البيانات")
    args = parser.parse_args()

    if args.host == "0.0.0.0":
        print("تنبيه: الخادم مفتوح لكل الشبكة. لا تستخدم هذا الوضع على شبكة عامة")
        print("       قبل وضع البرنامج خلف HTTPS.\n")

    try:
        run(host=args.host, port=args.port, db_path=args.db)
    except OSError as exc:
        print(f"تعذّر تشغيل الخادم: {exc}", file=sys.stderr)
        print(f"جرّب منفذًا آخر:  python3 app.py --port {args.port + 1}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
