"""التسجيل والدخول وإدارة الجلسات."""

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from . import db

# عدد دورات PBKDF2. رقم مرتفع عمدًا: يبطئ تخمين كلمات المرور إن تسربت
# قاعدة البيانات، وتكلفته على تسجيل دخول واحد غير محسوسة.
PBKDF2_ROUNDS = 210_000
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 8

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """خطأ في بيانات الدخول أو التسجيل."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    """يشفّر كلمة المرور بـ PBKDF2-SHA256 مع ملح عشوائي لكل مستخدم."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """يتحقق من كلمة المرور بمقارنة ثابتة الزمن."""
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    # compare_digest يمنع استنتاج الهاش من زمن المقارنة
    return hmac.compare_digest(candidate, expected)


def validate_registration(email: str, password: str, org_name: str):
    email = (email or "").strip().lower()
    org_name = (org_name or "").strip()

    if not EMAIL_PATTERN.match(email):
        raise AuthError("البريد الإلكتروني غير صالح")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"كلمة المرور يجب ألا تقل عن {MIN_PASSWORD_LENGTH} أحرف")
    if not org_name:
        raise AuthError("اسم المنشأة مطلوب")
    return email, org_name


def register(conn, email: str, password: str, org_name: str, user_name: str = "") -> dict:
    """ينشئ منشأة جديدة وحساب المستخدم الأول فيها."""
    email, org_name = validate_registration(email, password, org_name)

    existing = db.query_one(conn, "SELECT id FROM users WHERE email = ?", (email,))
    if existing:
        raise AuthError("هذا البريد مسجّل مسبقًا")

    created = now_iso()
    cursor = conn.execute(
        "INSERT INTO orgs (name, created_at) VALUES (?, ?)",
        (org_name, created),
    )
    org_id = cursor.lastrowid

    cursor = conn.execute(
        """INSERT INTO users (org_id, email, name, password_hash, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (org_id, email, (user_name or "").strip(), hash_password(password), created),
    )
    user_id = cursor.lastrowid
    conn.commit()

    return {"id": user_id, "org_id": org_id, "email": email, "name": user_name}


def login(conn, email: str, password: str) -> dict:
    """يتحقق من بيانات الدخول ويُرجع المستخدم."""
    email = (email or "").strip().lower()
    row = db.query_one(conn, "SELECT * FROM users WHERE email = ?", (email,))

    # نتحقق من الهاش حتى مع بريد غير موجود، حتى لا يكشف فرق الزمن
    # أي الحسابات مسجّلة فعلًا
    stored = row["password_hash"] if row else hash_password("dummy-password")
    if not verify_password(password or "", stored) or row is None:
        raise AuthError("البريد الإلكتروني أو كلمة المرور غير صحيحة")

    return {"id": row["id"], "org_id": row["org_id"], "email": row["email"], "name": row["name"]}


def create_session(conn, user_id: int) -> str:
    """ينشئ جلسة جديدة ويُرجع رمزها."""
    token = secrets.token_urlsafe(32)
    created = datetime.now(timezone.utc)
    expires = created + timedelta(days=SESSION_DAYS)
    db.execute(
        conn,
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, created.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")),
    )
    return token


def resolve_session(conn, token: str):
    """يُرجع المستخدم صاحب الجلسة، أو None إذا كان الرمز غير صالح أو منتهيًا."""
    if not token:
        return None
    row = db.query_one(
        conn,
        """SELECT s.expires_at, u.id, u.org_id, u.email, u.name
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token = ?""",
        (token,),
    )
    if row is None:
        return None

    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        destroy_session(conn, token)
        return None

    return {"id": row["id"], "org_id": row["org_id"], "email": row["email"], "name": row["name"]}


def destroy_session(conn, token: str):
    if token:
        db.execute(conn, "DELETE FROM sessions WHERE token = ?", (token,))


def purge_expired_sessions(conn):
    db.execute(conn, "DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
