"""Authentication for pilot use: SQLite user store, scrypt password hashing,
opaque session tokens (stored hashed), per-session CSRF token.

No default accounts are ever created. Provision the first sheikh with:
    rafiq auth add-user <username> --role sheikh
"""

import hashlib
import hmac
import pathlib
import secrets
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple

AUTH_DB = pathlib.Path("data/auth.db")
SESSION_COOKIE = "rafiq_session"
CSRF_HEADER = "x-csrf-token"

ROLES = {"user", "sheikh", "admin"}
REVIEW_ROLES = {"sheikh", "admin"}

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_MIN_PASSWORD_LEN = 10
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUTH_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at REAL NOT NULL,
                disabled INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                csrf TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)


def _validate_username(username: str) -> None:
    if not username or len(username) < 3 or len(username) > 32:
        raise ValueError("username must be 3-32 chars")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if any(c not in allowed for c in username):
        raise ValueError("username may only contain letters, digits, _ . -")


def _validate_password(password: str) -> None:
    if not password or len(password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LEN} chars")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(hash_hex) // 2,
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


def create_user(username: str, password: str, role: str = "user") -> None:
    _validate_username(username)
    _validate_password(password)
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    init_db()
    with _lock, _conn() as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at, disabled) "
                "VALUES (?,?,?,?,0)",
                (username, hash_password(password), role, time.time()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"user already exists: {username}")


def set_password(username: str, password: str) -> None:
    _validate_password(password)
    init_db()
    with _lock, _conn() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            (hash_password(password), username),
        )
        if cur.rowcount == 0:
            raise ValueError(f"user not found: {username}")


def set_disabled(username: str, disabled: bool) -> None:
    init_db()
    with _lock, _conn() as conn:
        cur = conn.execute(
            "UPDATE users SET disabled=? WHERE username=?", (1 if disabled else 0, username)
        )
        if cur.rowcount == 0:
            raise ValueError(f"user not found: {username}")


def list_users() -> List[Dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT username, role, created_at, disabled FROM users ORDER BY username"
        ).fetchall()
    return [dict(r) for r in rows]


def authenticate(username: str, password: str) -> Optional[Dict]:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or row["disabled"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {"username": row["username"], "role": row["role"]}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(username: str, ttl_hours: float = 12) -> Tuple[str, str]:
    init_db()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = time.time()
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, username, csrf, created_at, expires_at) "
            "VALUES (?,?,?,?,?)",
            (_token_hash(token), username, csrf, now, now + ttl_hours * 3600),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return token, csrf


def resolve_session(token: str) -> Optional[Dict]:
    if not token:
        return None
    init_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash=?", (_token_hash(token),)
        ).fetchone()
        if not row or row["expires_at"] < time.time():
            return None
        user = conn.execute(
            "SELECT username, role, disabled FROM users WHERE username=?", (row["username"],)
        ).fetchone()
    if not user or user["disabled"]:
        return None
    return {"username": user["username"], "role": user["role"], "csrf": row["csrf"]}


def revoke_session(token: str) -> None:
    if not token:
        return
    init_db()
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


init_db()
