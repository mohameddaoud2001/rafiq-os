import json
import sys

sys.path.insert(0, "src")


def _fresh_auth():
    from rafiq.api import auth

    auth.AUTH_DB.unlink(missing_ok=True)
    auth.init_db()
    return auth


def test_password_hash_roundtrip():
    from rafiq.api import auth

    h = auth.hash_password("s3cret-pass-123")
    assert h.startswith("scrypt$")
    assert auth.verify_password("s3cret-pass-123", h) is True
    assert auth.verify_password("wrong-password", h) is False
    assert auth.verify_password("x", "garbage") is False


def test_create_user_validation():
    auth = _fresh_auth()
    import pytest

    with pytest.raises(ValueError):
        auth.create_user("ab", "long-enough-pass", "user")
    with pytest.raises(ValueError):
        auth.create_user("bad name!", "long-enough-pass", "user")
    with pytest.raises(ValueError):
        auth.create_user("okname", "short", "user")
    with pytest.raises(ValueError):
        auth.create_user("okname", "long-enough-pass", "wizard")
    auth.create_user("okname", "long-enough-pass", "user")
    with pytest.raises(ValueError):
        auth.create_user("okname", "long-enough-pass", "user")


def test_authenticate_and_session_lifecycle():
    auth = _fresh_auth()
    auth.create_user("sess_user", "sess-pass-12345", "sheikh")
    assert auth.authenticate("sess_user", "nope") is None
    user = auth.authenticate("sess_user", "sess-pass-12345")
    assert user == {"username": "sess_user", "role": "sheikh"}

    token, csrf = auth.create_session("sess_user", ttl_hours=12)
    s = auth.resolve_session(token)
    assert s and s["username"] == "sess_user" and s["csrf"] == csrf

    auth.revoke_session(token)
    assert auth.resolve_session(token) is None

    expired, _ = auth.create_session("sess_user", ttl_hours=-1)
    assert auth.resolve_session(expired) is None

    auth.set_disabled("sess_user", True)
    assert auth.authenticate("sess_user", "sess-pass-12345") is None
    auth.set_disabled("sess_user", False)
    assert auth.authenticate("sess_user", "sess-pass-12345") is not None


def test_dev_header_auth_toggle(monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api import main
    from rafiq.api.main import app
    from rafiq.config import settings

    main._login_limiter.reset()
    client = TestClient(app)
    headers = {"X-Role": "sheikh", "X-Reviewer": "devuser"}

    # disabled by default in dev
    r = client.post(
        "/dashboard/mufti/nonexistent/decision", headers=headers, data={"decision": "APPROVED"}
    )
    assert r.status_code == 403

    # enabled explicitly in dev: auth passes, dossier lookup 404s
    monkeypatch.setattr(settings, "RAFIQ_DEV_AUTH", True)
    r = client.post(
        "/dashboard/mufti/nonexistent/decision", headers=headers, data={"decision": "APPROVED"}
    )
    assert r.status_code == 404


def test_production_config_validation(monkeypatch):
    import pytest

    from rafiq.config import DEFAULT_AMIN_SECRET, Settings

    # default secret rejected in prod
    s = Settings(
        RAFIQ_ENV="prod", RAFIQ_AMIN_SECRET=DEFAULT_AMIN_SECRET, RAFIQ_TRUSTED_HOSTS="rafiq.example"
    )
    with pytest.raises(RuntimeError):
        s.validate_production()

    # short secret rejected
    s = Settings(RAFIQ_ENV="prod", RAFIQ_AMIN_SECRET="short", RAFIQ_TRUSTED_HOSTS="rafiq.example")
    with pytest.raises(RuntimeError):
        s.validate_production()

    # dev auth rejected in prod
    s = Settings(
        RAFIQ_ENV="prod",
        RAFIQ_AMIN_SECRET="x" * 48,
        RAFIQ_TRUSTED_HOSTS="rafiq.example",
        RAFIQ_DEV_AUTH=True,
    )
    with pytest.raises(RuntimeError):
        s.validate_production()

    # missing trusted hosts rejected in prod
    s = Settings(RAFIQ_ENV="prod", RAFIQ_AMIN_SECRET="x" * 48, RAFIQ_TRUSTED_HOSTS="")
    with pytest.raises(RuntimeError):
        s.validate_production()

    # valid prod config passes
    s = Settings(RAFIQ_ENV="prod", RAFIQ_AMIN_SECRET="x" * 48, RAFIQ_TRUSTED_HOSTS="rafiq.example")
    s.validate_production()
    assert s.cookie_secure() is True

    # dev defaults pass
    d = Settings(RAFIQ_ENV="dev")
    d.validate_production()
    assert d.cookie_secure() is False


def test_ingest_license_gate():
    import pytest

    from rafiq.rag.ingest import validate_passage

    base = {
        "id": "v1",
        "madhhab": "maliki",
        "text": "نص",
        "work": "w",
        "edition": "e",
        "volume": 1,
        "page": 2,
        "provenance": "p",
        "verified": True,
    }
    # verified:true without license/verifier must be rejected
    with pytest.raises(ValueError):
        validate_passage(base)

    full = {**base, "license": "CC-BY-4.0", "verified_by": "sheikh1", "verified_at": "2026-01-01"}
    p = validate_passage(full)
    assert p.verified is True
    assert p.license == "CC-BY-4.0"


def test_corpus_check_report(tmp_path):
    from rafiq.rag.ingest import check_corpus_file

    good = {
        "id": "g1",
        "madhhab": "maliki",
        "text": "نص",
        "verified": False,
        "volume": None,
        "page": None,
        "provenance": "seed",
    }
    bad = {"id": "b1", "madhhab": "maliki", "text": "نص", "verified": True, "volume": 1, "page": 2}

    f = tmp_path / "corpus.jsonl"
    f.write_text(
        json.dumps(good, ensure_ascii=False)
        + "\n"
        + json.dumps(bad, ensure_ascii=False)
        + "\nnot-json\n",
        encoding="utf-8",
    )
    report = check_corpus_file(f)
    assert report["total"] == 3
    assert report["ok"] is False
    assert report["unverified"] == 1
    assert len(report["errors"]) == 2

    f2 = tmp_path / "good.jsonl"
    f2.write_text(json.dumps(good, ensure_ascii=False) + "\n", encoding="utf-8")
    report2 = check_corpus_file(f2)
    assert report2["ok"] is True
    assert report2["unverified"] == 1


def test_quorum_flow(monkeypatch):
    import pytest

    from rafiq.config import settings
    from rafiq.core import dossier as dmod

    monkeypatch.setattr(settings, "RAFIQ_QUORUM", 2)
    d = dmod.create_dossier("مسألة اختبار", {}, {}, {}, [])
    d3 = None
    try:
        d1 = dmod.add_decision(d.id, "sh1", "APPROVED", "ok")
        assert d1.status == "AWAITING_QUORUM"
        # same reviewer again does not satisfy quorum
        d1b = dmod.add_decision(d.id, "sh1", "APPROVED", "again")
        assert d1b.status == "AWAITING_QUORUM"
        d2 = dmod.add_decision(d.id, "sh2", "APPROVED", "ok")
        assert d2.status == "APPROVED"
        # decided dossier rejects further decisions
        with pytest.raises(ValueError):
            dmod.add_decision(d.id, "sh3", "REJECTED")
        # invalid decision value rejected
        d3 = dmod.create_dossier("مسألة 2", {}, {}, {}, [])
        with pytest.raises(ValueError):
            dmod.add_decision(d3.id, "sh1", "MAYBE")
    finally:
        (dmod.DOSSIER_DIR / f"{d.id}.json").unlink(missing_ok=True)
        if d3:
            (dmod.DOSSIER_DIR / f"{d3.id}.json").unlink(missing_ok=True)


def test_decision_records_auto_flag(monkeypatch):
    from rafiq.core import dossier as dmod

    d = dmod.create_dossier("مسألة آلية", {}, {}, {}, [])
    try:
        d1 = dmod.add_decision(d.id, "demo_auto_sheikh", "APPROVED", "auto", auto=True)
        assert d1.decisions[0]["auto"] is True
    finally:
        (dmod.DOSSIER_DIR / f"{d.id}.json").unlink(missing_ok=True)


def test_security_headers():
    from fastapi.testclient import TestClient

    from rafiq.api.main import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    r = client.get("/login")
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text
    assert "Content-Security-Policy" in r.headers


def test_rate_limiter_unit():
    from rafiq.api.security import RateLimiter

    rl = RateLimiter(max_per_window=2, window_seconds=60)
    assert rl.allow("a") is True
    assert rl.allow("a") is True
    assert rl.allow("a") is False
    assert rl.allow("b") is True
    rl.reset()
    assert rl.allow("a") is True


def test_login_wrong_password():
    from fastapi.testclient import TestClient

    from rafiq.api import main
    from rafiq.api.main import app

    auth = _fresh_auth()
    auth.create_user("login_user", "login-pass-12345", "sheikh")
    main._login_limiter.reset()
    client = TestClient(app)
    r = client.post("/auth/login", data={"username": "login_user", "password": "wrong-pass-12345"})
    assert r.status_code == 401
    r = client.post(
        "/auth/login",
        data={"username": "login_user", "password": "login-pass-12345"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # logout revokes session
    r = client.post("/auth/logout", follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/dashboard/mufti", follow_redirects=False)
    assert r.status_code == 303
