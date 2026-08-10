"""خادم HTTP وواجهة JSON.

مبني على مكتبة بايثون القياسية فقط، بلا أي اعتماديات خارجية، حتى يعمل
البرنامج بأمر واحد على أي جهاز فيه بايثون.
"""

import json
import mimetypes
import os
import posixpath
import re
from datetime import date
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import auth, db, invoices, reports, store
from .money import VAT_CATEGORIES
from .store import ValidationError

WEB_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
SESSION_COOKIE = "omanbill_session"

# الحد الأقصى لحجم الطلب — يمنع استنزاف الذاكرة بطلب ضخم
MAX_BODY_BYTES = 1_000_000


class ApiError(Exception):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = status


class Router:
    """موجّه بسيط يربط (الطريقة، النمط) بدالة معالجة."""

    def __init__(self):
        self.routes = []

    def add(self, method: str, pattern: str, handler, auth_required: bool = True):
        regex = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$")
        self.routes.append((method, regex, handler, auth_required))

    def match(self, method: str, path: str):
        allowed = False
        for route_method, regex, handler, auth_required in self.routes:
            match = regex.match(path)
            if match:
                if route_method == method:
                    return handler, match.groupdict(), auth_required
                allowed = True
        if allowed:
            raise ApiError("طريقة الطلب غير مسموحة", HTTPStatus.METHOD_NOT_ALLOWED)
        return None, None, None


router = Router()


# ---------------------------------------------------------------- المصادقة

def handle_register(ctx):
    data = ctx["body"]
    try:
        user = auth.register(
            ctx["conn"],
            data.get("email"),
            data.get("password"),
            data.get("org_name"),
            data.get("name", ""),
        )
    except auth.AuthError as exc:
        raise ApiError(str(exc))
    token = auth.create_session(ctx["conn"], user["id"])
    ctx["set_session"] = token
    return {"user": user, "org": store.get_org(ctx["conn"], user["org_id"])}


def handle_login(ctx):
    data = ctx["body"]
    try:
        user = auth.login(ctx["conn"], data.get("email"), data.get("password"))
    except auth.AuthError as exc:
        raise ApiError(str(exc), HTTPStatus.UNAUTHORIZED)
    token = auth.create_session(ctx["conn"], user["id"])
    ctx["set_session"] = token
    return {"user": user, "org": store.get_org(ctx["conn"], user["org_id"])}


def handle_logout(ctx):
    auth.destroy_session(ctx["conn"], ctx["token"])
    ctx["clear_session"] = True
    return {"ok": True}


def handle_me(ctx):
    return {
        "user": ctx["user"],
        "org": store.get_org(ctx["conn"], ctx["org_id"]),
        "vat_categories": [
            {"value": key, "rate_bp": rate} for key, rate in VAT_CATEGORIES.items()
        ],
    }


# ---------------------------------------------------------------- الإعدادات

def handle_update_org(ctx):
    return {"org": store.update_org(ctx["conn"], ctx["org_id"], ctx["body"])}


def handle_set_plan(ctx):
    return {"org": store.set_plan(ctx["conn"], ctx["org_id"], ctx["body"].get("plan", "free"))}


# ---------------------------------------------------------------- العملاء

def handle_list_customers(ctx):
    include = ctx["query"].get("archived", ["0"])[0] == "1"
    return {"customers": store.list_customers(ctx["conn"], ctx["org_id"], include)}


def handle_create_customer(ctx):
    return {"customer": store.create_customer(ctx["conn"], ctx["org_id"], ctx["body"])}


def handle_update_customer(ctx):
    customer_id = _int_param(ctx, "id")
    return {"customer": store.update_customer(ctx["conn"], ctx["org_id"], customer_id, ctx["body"])}


def handle_archive_customer(ctx):
    store.archive_customer(ctx["conn"], ctx["org_id"], _int_param(ctx, "id"))
    return {"ok": True}


# ---------------------------------------------------------------- الأصناف

def handle_list_items(ctx):
    include = ctx["query"].get("archived", ["0"])[0] == "1"
    return {"items": store.list_items(ctx["conn"], ctx["org_id"], include)}


def handle_create_item(ctx):
    return {"item": store.create_item(ctx["conn"], ctx["org_id"], ctx["body"])}


def handle_update_item(ctx):
    return {"item": store.update_item(ctx["conn"], ctx["org_id"], _int_param(ctx, "id"), ctx["body"])}


def handle_archive_item(ctx):
    store.archive_item(ctx["conn"], ctx["org_id"], _int_param(ctx, "id"))
    return {"ok": True}


# ---------------------------------------------------------------- الفواتير

def handle_list_invoices(ctx):
    query = ctx["query"]
    return {
        "invoices": invoices.list_invoices(
            ctx["conn"],
            ctx["org_id"],
            status=query.get("status", [None])[0],
            customer_id=query.get("customer_id", [None])[0],
            search=query.get("q", [None])[0],
            limit=int(query.get("limit", ["100"])[0] or 100),
            offset=int(query.get("offset", ["0"])[0] or 0),
        )
    }


def handle_create_invoice(ctx):
    return {"invoice": invoices.create_invoice(ctx["conn"], ctx["org_id"], ctx["body"])}


def handle_get_invoice(ctx):
    return {"invoice": invoices.get_invoice(ctx["conn"], ctx["org_id"], _int_param(ctx, "id"))}


def handle_update_invoice(ctx):
    invoice_id = _int_param(ctx, "id")
    return {"invoice": invoices.update_invoice(ctx["conn"], ctx["org_id"], invoice_id, ctx["body"])}


def handle_invoice_status(ctx):
    invoice_id = _int_param(ctx, "id")
    status = ctx["body"].get("status", "")
    return {"invoice": invoices.set_status(ctx["conn"], ctx["org_id"], invoice_id, status)}


def handle_delete_invoice(ctx):
    invoices.delete_invoice(ctx["conn"], ctx["org_id"], _int_param(ctx, "id"))
    return {"ok": True}


def handle_add_payment(ctx):
    invoice_id = _int_param(ctx, "id")
    return {"invoice": invoices.add_payment(ctx["conn"], ctx["org_id"], invoice_id, ctx["body"])}


def handle_delete_payment(ctx):
    invoice_id = _int_param(ctx, "id")
    payment_id = _int_param(ctx, "payment_id")
    return {
        "invoice": invoices.delete_payment(ctx["conn"], ctx["org_id"], invoice_id, payment_id)
    }


# ---------------------------------------------------------------- التقارير

def handle_dashboard(ctx):
    return {
        "summary": reports.dashboard(ctx["conn"], ctx["org_id"]),
        "monthly": reports.monthly_sales(ctx["conn"], ctx["org_id"]),
        "top_customers": reports.top_customers(ctx["conn"], ctx["org_id"], 5),
        "recent": invoices.list_invoices(ctx["conn"], ctx["org_id"], limit=8),
    }


def _period(ctx):
    today = date.today()
    default_from = today.replace(day=1).isoformat()
    date_from = ctx["query"].get("from", [default_from])[0]
    date_to = ctx["query"].get("to", [today.isoformat()])[0]
    if not invoices.DATE_PATTERN.match(date_from) or not invoices.DATE_PATTERN.match(date_to):
        raise ApiError("صيغة التاريخ يجب أن تكون YYYY-MM-DD")
    return date_from, date_to


def handle_vat_return(ctx):
    date_from, date_to = _period(ctx)
    return {"vat_return": reports.vat_return(ctx["conn"], ctx["org_id"], date_from, date_to)}


def handle_export_csv(ctx):
    date_from, date_to = _period(ctx)
    csv_text = reports.invoices_csv(ctx["conn"], ctx["org_id"], date_from, date_to)
    return {
        "_raw": csv_text.encode("utf-8"),
        "_content_type": "text/csv; charset=utf-8",
        "_filename": f"invoices-{date_from}-to-{date_to}.csv",
    }


def _int_param(ctx, name: str) -> int:
    try:
        return int(ctx["params"][name])
    except (KeyError, TypeError, ValueError):
        raise ApiError("معرّف غير صالح")


router.add("POST", "/api/register", handle_register, auth_required=False)
router.add("POST", "/api/login", handle_login, auth_required=False)
router.add("POST", "/api/logout", handle_logout)
router.add("GET", "/api/me", handle_me)

router.add("PUT", "/api/org", handle_update_org)
router.add("POST", "/api/org/plan", handle_set_plan)

router.add("GET", "/api/customers", handle_list_customers)
router.add("POST", "/api/customers", handle_create_customer)
router.add("PUT", "/api/customers/<id>", handle_update_customer)
router.add("DELETE", "/api/customers/<id>", handle_archive_customer)

router.add("GET", "/api/items", handle_list_items)
router.add("POST", "/api/items", handle_create_item)
router.add("PUT", "/api/items/<id>", handle_update_item)
router.add("DELETE", "/api/items/<id>", handle_archive_item)

router.add("GET", "/api/invoices", handle_list_invoices)
router.add("POST", "/api/invoices", handle_create_invoice)
router.add("GET", "/api/invoices/<id>", handle_get_invoice)
router.add("PUT", "/api/invoices/<id>", handle_update_invoice)
router.add("POST", "/api/invoices/<id>/status", handle_invoice_status)
router.add("DELETE", "/api/invoices/<id>", handle_delete_invoice)
router.add("POST", "/api/invoices/<id>/payments", handle_add_payment)
router.add("DELETE", "/api/invoices/<id>/payments/<payment_id>", handle_delete_payment)

router.add("GET", "/api/reports/dashboard", handle_dashboard)
router.add("GET", "/api/reports/vat", handle_vat_return)
router.add("GET", "/api/reports/export.csv", handle_export_csv)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "OmanBill"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def log_message(self, format, *args):
        if os.environ.get("OMANBILL_VERBOSE"):
            super().log_message(format, *args)

    # ------------------------------------------------------------ التوجيه

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if not path.startswith("/api/"):
            self._serve_static(path)
            return

        try:
            handler, params, auth_required = router.match(method, path)
            if handler is None:
                raise ApiError("المسار غير موجود", HTTPStatus.NOT_FOUND)

            conn = db.connect()
            token = self._read_session_cookie()
            user = auth.resolve_session(conn, token) if token else None

            if auth_required and user is None:
                raise ApiError("يجب تسجيل الدخول", HTTPStatus.UNAUTHORIZED)

            ctx = {
                "conn": conn,
                "user": user,
                "org_id": user["org_id"] if user else None,
                "token": token,
                "params": params,
                "query": parse_qs(parsed.query),
                "body": self._read_json_body() if method in ("POST", "PUT") else {},
            }

            result = handler(ctx)

            if isinstance(result, dict) and "_raw" in result:
                self._send_raw(result)
                return
            self._send_json(HTTPStatus.OK, result, ctx)

        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except ValidationError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - آخر خط دفاع حتى لا يسقط الخادم
            self.log_error("unhandled error: %r", exc)
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "حدث خطأ غير متوقع في الخادم"}
            )

    # ------------------------------------------------------------ الجلسة

    def _read_session_cookie(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ApiError("حجم الطلب كبير جدًا", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

        # اشتراط نوع المحتوى JSON يمنع تزوير الطلبات من موقع آخر عبر نموذج
        # HTML عادي، لأن المتصفح لا يسمح للنماذج بإرسال هذا النوع عبر النطاقات.
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type != "application/json":
            raise ApiError("نوع المحتوى يجب أن يكون application/json",
                           HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("صيغة البيانات المرسلة غير صحيحة")
        if not isinstance(body, dict):
            raise ApiError("صيغة البيانات المرسلة غير صحيحة")
        return body

    # ------------------------------------------------------------ الردود

    def _send_json(self, status, payload, ctx=None):
        payload = {k: v for k, v in payload.items()} if isinstance(payload, dict) else payload
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()

        if ctx and ctx.get("set_session"):
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={ctx['set_session']}; Path=/; HttpOnly; SameSite=Lax; "
                f"Max-Age={auth.SESSION_DAYS * 86400}",
            )
        if ctx and ctx.get("clear_session"):
            self.send_header(
                "Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            )

        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, result):
        body = result["_raw"]
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", result["_content_type"])
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{result["_filename"]}"'
        )
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")

    # ------------------------------------------------------------ الملفات

    def _serve_static(self, path: str):
        if path == "/" or path == "":
            path = "/index.html"

        # منع الخروج من مجلد الويب عبر ../ : نطبّع المسار ثم نتأكد أن الناتج
        # ما زال داخل المجلد فعليًا
        root = os.path.realpath(WEB_ROOT)
        relative = posixpath.normpath(path).lstrip("/")
        file_path = os.path.realpath(os.path.join(root, relative))
        if file_path != root and not file_path.startswith(root + os.sep):
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "غير مسموح"})
            return

        if not os.path.isfile(file_path):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "الصفحة غير موجودة"})
            return

        content_type, _ = mimetypes.guess_type(file_path)
        if content_type and content_type.startswith("text/"):
            content_type += "; charset=utf-8"

        with open(file_path, "rb") as handle:
            body = handle.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8000, db_path: str = None):
    db.init_db(db_path)
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"نظام الفوترة يعمل على  http://{host}:{port}")
    print("للإيقاف: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nتم إيقاف الخادم.")
    finally:
        server.server_close()
