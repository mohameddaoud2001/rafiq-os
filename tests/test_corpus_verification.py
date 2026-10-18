import re
import sys

sys.path.insert(0, "src")


def _fresh_corpus():
    import pathlib
    import tempfile

    from rafiq.core import analytics
    from rafiq.rag import verify_corpus
    from rafiq.rag.madhhab_stores import load_seed_data

    tmp = pathlib.Path(tempfile.mkdtemp())
    verify_corpus.VERIFICATIONS_PATH = tmp / "verifications.jsonl"
    analytics.HITS_PATH = tmp / "unsigned_hits.jsonl"
    load_seed_data()


def _login_sheikh(client, username="corpus_sheikh", role="sheikh"):
    from rafiq.api import auth

    auth.AUTH_DB.unlink(missing_ok=True)
    auth.init_db()
    auth.create_user(username, "corpus-pass-12345", role)
    from rafiq.api import main

    main._login_limiter.reset()
    r = client.post(
        "/auth/login",
        data={"username": username, "password": "corpus-pass-12345"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    return r


def test_requires_verified_is_inert_after_owner_decision():
    from rafiq.config import Settings

    # owner decision 2026-10-18: sign-off removed as a serving requirement;
    # flags are kept inert so old deployments do not change behaviour.
    assert Settings(RAFIQ_ENV="dev").requires_verified() is False
    assert Settings(RAFIQ_ENV="dev", RAFIQ_REQUIRE_VERIFIED=True).requires_verified() is False
    prod = Settings(
        RAFIQ_ENV="prod", RAFIQ_AMIN_SECRET="x" * 48, RAFIQ_TRUSTED_HOSTS="rafiq.example"
    )
    assert prod.requires_verified() is False
    strict = Settings(
        RAFIQ_ENV="prod",
        RAFIQ_AMIN_SECRET="x" * 48,
        RAFIQ_TRUSTED_HOSTS="rafiq.example",
        RAFIQ_REQUIRE_VERIFIED=True,
        RAFIQ_PILOT_UNVERIFIED=False,
    )
    assert strict.requires_verified() is False


def test_ask_returns_labelled_unsigned_citations():
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.core.messages import BANNERS
    from rafiq.rag.madhhab_stores import sync_candidates

    _fresh_corpus()
    sync_candidates()
    client = TestClient(app)
    r = client.post("/ask", json={"query": "ما حكم من ترك الوضوء؟", "madhhab": "maliki"})
    assert r.status_code == 200
    data = r.json()
    assert data["dossier"] is not None
    assert data["citations"], "unsigned excerpts must be returned in pilot/dev"
    findings = [f for c in data["citations"] for f in c["findings"]]
    assert any(not f["verified"] for f in findings)
    f = next(f for f in findings if not f["verified"])
    assert f["source_id"]
    assert (f["provenance"] or "").startswith("OpenITI:"), "dev placeholders must never be served"
    assert BANNERS["unsigned_citations"] in data["banners"]
    assert BANNERS["pending_review"] in data["banners"]
    assert any(not f["verified"] and f["label"] == "منقول من الكتب" for f in findings)
    fatwa = data["fatwa"]
    assert fatwa is not None, "a ruling question served from books gets an extractive answer"
    assert "ليست فتوى مفتٍ" in fatwa["text"]
    assert fatwa["based_on"], "the answer must carry its corpus citations"
    assert "«" in fatwa["text"], "answers are verbatim quotes with template glue only"


def test_ask_serves_book_based_answer_labelled_in_prod(monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.config import settings
    from rafiq.core.messages import BANNERS
    from rafiq.rag.madhhab_stores import sync_candidates

    _fresh_corpus()
    sync_candidates()
    client = TestClient(app)

    monkeypatch.setattr(settings, "RAFIQ_ENV", "prod")
    data = client.post("/ask", json={"query": "ما حكم من ترك الوضوء؟", "madhhab": "maliki"}).json()
    assert data["citations"], "book text must be served in prod too (no sign-off requirement)"
    findings = [f for c in data["citations"] for f in c["findings"]]
    assert any(not f["verified"] for f in findings)
    assert all((f["provenance"] or "").startswith("OpenITI:") for f in findings)
    assert any(b.startswith("منقول من الكتب - بلا توقيع مفتٍ - المصدر:") for b in data["banners"])
    assert BANNERS["book_based_answer"] in data["banners"]
    assert data["fatwa"] and BANNERS["book_based_answer"] in data["fatwa"]["text"]


def test_faqih_serves_real_book_text_in_all_envs(monkeypatch):
    from rafiq.agents.faqih import faqih_agent
    from rafiq.config import settings
    from rafiq.rag.madhhab_stores import sync_candidates

    _fresh_corpus()
    sync_candidates()
    out = faqih_agent("ما حكم من ترك الوضوء؟", madhhab="maliki")
    assert out.status == "ok"
    assert out.findings
    assert all((f.provenance or "").startswith("OpenITI:") for f in out.findings)

    monkeypatch.setattr(settings, "RAFIQ_ENV", "prod")
    out = faqih_agent("ما حكم من ترك الوضوء؟", madhhab="maliki")
    assert out.status == "ok", "no sign-off gate may block retrieval"
    assert out.findings
    assert all((f.provenance or "").startswith("OpenITI:") for f in out.findings)


def test_sign_off_promotes_passage():
    from rafiq.rag.madhhab_stores import list_passages, search_passages
    from rafiq.rag.verify_corpus import (
        latest_verification,
        sign_off,
        text_sha256,
        verify_check,
    )

    _fresh_corpus()
    pending = list_passages("maliki", verified=False)
    assert pending, "seed must have unverified passages"
    p = pending[0]
    assert search_passages("maliki", "الوقوف بعرفة", verified_only=True) == []

    updated = sign_off(
        "maliki",
        p.id,
        "sheikh_uthman",
        {
            "work": "مختصر خليل",
            "edition": "دار الفكر",
            "volume": 1,
            "page": 42,
            "provenance": "shamela-export-v2 sha256:abc123",
            "license": "CC-BY-4.0",
        },
        note="طابقته على النسخة المطبوعة",
    )
    assert updated.verified is True
    assert updated.verified_by == "sheikh_uthman"
    assert updated.page == 42

    rec = latest_verification(p.id, "maliki")
    assert rec["text_sha256"] == text_sha256(p.text)
    assert rec["license"] == "CC-BY-4.0"

    hits = search_passages("maliki", "الوقوف بعرفة", verified_only=True)
    assert any(h.id == p.id for h in hits)

    check = verify_check()
    assert check["ok"] is True
    assert check["checked"] >= 1


def test_verify_check_detects_text_tampering():
    from rafiq.rag.madhhab_stores import insert_passage, list_passages
    from rafiq.rag.verify_corpus import sign_off, verify_check

    _fresh_corpus()
    p = list_passages("maliki", verified=False)[0]
    sign_off(
        "maliki",
        p.id,
        "sheikh_a",
        {
            "work": p.work or "كتاب",
            "edition": "طبعة",
            "volume": 1,
            "page": 1,
            "provenance": "seed",
            "license": "CC-BY-4.0",
        },
    )
    assert verify_check()["ok"] is True

    tampered = p.model_copy(update={"text": p.text + " (تعديل لاحق)", "verified": True})
    insert_passage("maliki", tampered)
    check = verify_check()
    assert check["ok"] is False
    assert any("text changed" in m["reason"] for m in check["mismatches"])


def test_sign_off_validation():
    import pytest

    from rafiq.rag.madhhab_stores import list_passages
    from rafiq.rag.verify_corpus import sign_off

    _fresh_corpus()
    p = list_passages("maliki", verified=False)[0]
    good = {
        "work": "كتاب",
        "edition": "طبعة",
        "volume": 1,
        "page": 1,
        "provenance": "src",
        "license": "CC-BY-4.0",
    }
    with pytest.raises(ValueError):
        sign_off("maliki", p.id, "", good)
    with pytest.raises(ValueError):
        sign_off("maliki", p.id, "sheikh_a", {**good, "license": ""})
    with pytest.raises(ValueError):
        sign_off("maliki", p.id, "sheikh_a", {**good, "volume": "ليس رقما"})
    with pytest.raises(ValueError):
        sign_off("maliki", p.id, "sheikh_a", {**good, "page": 0})
    with pytest.raises(ValueError):
        sign_off("maliki", "no_such_passage", "sheikh_a", good)


def test_corpus_api_signoff_flow():
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.rag.madhhab_stores import get_passage

    _fresh_corpus()
    client = TestClient(app)
    _login_sheikh(client)

    r = client.get("/dashboard/corpus")
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    pid = re.search(r'/dashboard/corpus/maliki/([^/"]+)/verify', r.text).group(1)

    r = client.post(
        f"/dashboard/corpus/maliki/{pid}/verify",
        data={
            "csrf": csrf,
            "work": "مختصر خليل",
            "edition": "دار الفكر",
            "volume": "2",
            "page": "17",
            "provenance": "shamela-export-v2 sha256:def456",
            "license": "CC-BY-4.0",
            "note": "موثق عبر الواجهة",
        },
    )
    assert r.status_code == 200
    p = get_passage("maliki", pid)
    assert p.verified is True
    assert p.verified_by == "corpus_sheikh"
    assert p.page == 17

    # missing csrf rejected
    page = client.get("/dashboard/corpus").text
    pid2 = re.search(r'/dashboard/corpus/maliki/([^/"]+)/verify', page).group(1)
    r = client.post(
        f"/dashboard/corpus/maliki/{pid2}/verify",
        data={
            "work": "x",
            "edition": "y",
            "volume": "1",
            "page": "1",
            "provenance": "z",
            "license": "l",
        },
    )
    assert r.status_code == 403
    assert get_passage("maliki", pid2).verified is False


def test_corpus_api_role_and_anon_checks():
    from fastapi.testclient import TestClient

    from rafiq.api.main import app

    _fresh_corpus()
    client = TestClient(app)

    # anonymous: redirected to login
    r = client.get("/dashboard/corpus", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    # plain user role: also refused
    _login_sheikh(client, username="plain_user", role="user")
    r = client.get("/dashboard/corpus", follow_redirects=False)
    assert r.status_code == 303

    # anonymous POST: 403
    r = client.post("/dashboard/corpus/maliki/maliki_arafat_1/verify", data={"work": "x"})
    assert r.status_code == 403
