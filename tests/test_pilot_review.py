"""Book-based answers + /review sign-off tooling tests.

Safety invariants covered:
  - every served quote is real book text; unsigned pages carry the mandatory
    "منقول من الكتب - بلا توقيع مفتٍ - المصدر: ..." banner and matn-only mode,
    and the answer carries the "ليست فتوى مفتٍ" disclaimer
  - legacy signed pages display «موثّق» only after sign_off recorded sheikh id,
    timestamp and edition hash (signing is optional, never a gate)
  - no matching source -> "لا أعلم" + gap dossier (no composed fatwa)
  - every served hit is logged to dossier analytics and drives queue order
"""

import re
import sys

sys.path.insert(0, "src")

GOOD_FIELDS = {
    "work": "مختصر خليل",
    "edition": "دار الفكر",
    "volume": 1,
    "page": 42,
    "provenance": "shamela-export-v2 sha256:abc123",
    "license": "CC-BY-4.0",
}


def _prepare(tmp_path, monkeypatch):
    from rafiq.core import analytics
    from rafiq.rag import verify_corpus
    from rafiq.rag.madhhab_stores import load_seed_data, sync_candidates

    monkeypatch.setattr(verify_corpus, "VERIFICATIONS_PATH", tmp_path / "verifications.jsonl")
    monkeypatch.setattr(analytics, "HITS_PATH", tmp_path / "unsigned_hits.jsonl")
    load_seed_data()
    sync_candidates()


def _login(client, username="review_sheikh", role="sheikh"):
    from rafiq.api import auth, main

    auth.AUTH_DB.unlink(missing_ok=True)
    auth.init_db()
    auth.create_user(username, "review-pass-12345", role)
    main._login_limiter.reset()
    r = client.post(
        "/auth/login",
        data={"username": username, "password": "review-pass-12345"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    return r


def _csrf_from_page(html: str) -> str:
    m = re.search(r'<meta name="csrf" content="([^"]+)"', html)
    assert m, "csrf meta tag missing"
    return m.group(1)


def test_review_js_wires_existing_dom_ids_and_csp_shape():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    tpl = (root / "src/rafiq/api/templates/review.html").read_text(encoding="utf-8")
    js = (root / "src/rafiq/api/static/review.js").read_text(encoding="utf-8")

    template_ids = set(re.findall(r'id="([^"]+)"', tpl))
    js_ids = set(re.findall(r'el\("([^"]+)"\)', js))
    missing = js_ids - template_ids
    assert not missing, f"review.js references DOM ids missing from the template: {missing}"

    for dom_id in ("bar", "text", "source-meta", "reject-confirm", "reject-cancel"):
        assert dom_id in template_ids

    # CSP allows no inline script: the only script tag must be the external file
    assert '<script src="/static/review.js" defer>' in tpl
    assert "<script>" not in tpl
    assert 'name="csrf"' in tpl

    assert "/review/queue.json" in js
    assert "X-CSRF-Token" in js
    assert "KeyA" in js and "KeyR" in js and "KeyE" in js
    assert "KeyJ" in js and "KeyK" in js


def test_source_links_verified_patterns():
    from rafiq.rag.source_links import (
        openiti_file_url,
        page_hint,
        scan_links,
        shamela_book_url,
        source_citation,
    )

    khalil = (
        "OpenITI:0775AH/0767KhalilIbnIshaq.MukhtasarKhalil.Shamela0011355-ara1 "
        "sha256:abc PageV01P066 (page hint)"
    )
    assert page_hint(khalil) == 66
    assert openiti_file_url(khalil) == (
        "https://github.com/OpenITI/0775AH/blob/master/data/0767KhalilIbnIshaq/"
        "0767KhalilIbnIshaq.MukhtasarKhalil/0767KhalilIbnIshaq.MukhtasarKhalil."
        "Shamela0011355-ara1"
    )
    assert shamela_book_url(khalil) == "https://shamela.ws/book/11355"

    nawawi = "OpenITI:0676Nawawi.IdahFiManasikHajj.Shamela0096232-ara1 PageV01P045"
    assert openiti_file_url(nawawi) == (
        "https://github.com/OpenITI/0700AH/blob/master/data/0676Nawawi/"
        "0676Nawawi.IdahFiManasikHajj/0676Nawawi.IdahFiManasikHajj."
        "Shamela0096232-ara1"
    )
    assert shamela_book_url(nawawi) == "https://shamela.ws/book/96232"
    assert len(scan_links(nawawi)) == 2

    # unknown provenance: no invented links
    assert openiti_file_url("seed_maliki_arafat_1") is None
    assert shamela_book_url("seed_maliki_arafat_1") is None

    cit = source_citation("مختصر خليل", "خليل بن إسحاق", "دار الحديث", None, None, khalil)
    assert "مختصر خليل" in cit and "خليل بن إسحاق" in cit
    assert "دار الحديث" in cit and "ص66" in cit


def test_ask_unsigned_served_only_as_matn_with_mandatory_banner(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.core.messages import BANNERS

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)
    r = client.post("/ask", json={"query": "ما هي مواقيت الإحرام؟", "madhhab": "hanafi"})
    assert r.status_code == 200
    data = r.json()

    assert data["citations"], "dev/pilot must return the retrieved excerpts verbatim"
    finding = data["citations"][0]["findings"][0]
    assert finding["verified"] is False
    assert finding["label"] == "منقول من الكتب"
    assert finding["display_mode"] == "matn"
    assert finding["copy_as_fatwa_allowed"] is False
    assert finding["source_label"]

    # the mandatory banner is on top and names the source
    assert data["banners"][0].startswith("منقول من الكتب - بلا توقيع مفتٍ - المصدر: ")
    assert data["unsigned_notices"], "per-source notices must be returned"
    notice = data["unsigned_notices"][0]
    assert notice["severity"] == "danger"
    assert notice["copy_as_fatwa_allowed"] is False
    assert "المصدر:" in notice["text"]
    assert BANNERS["matn_only"] in data["banners"]
    assert BANNERS["unsigned_citations"] in data["banners"]
    assert BANNERS["pending_review"] in data["banners"]


def test_ask_signed_page_labelled_only_after_signoff(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.rag.madhhab_stores import search_passages
    from rafiq.rag.verify_corpus import sign_off

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)

    hits = search_passages("hanafi", "مواقيت الإحرام", limit=5)
    assert hits
    target = hits[0]
    sign_off("hanafi", target.id, "sheikh_test", {**GOOD_FIELDS, "page": 42})

    data = client.post("/ask", json={"query": "ما هي مواقيت الإحرام؟", "madhhab": "hanafi"}).json()
    matches = [f for c in data["citations"] for f in c["findings"] if f["source_id"] == target.id]
    assert matches, "signed page must be returned"
    assert matches[0]["verified"] is True
    assert matches[0]["label"] == "موثّق"
    assert matches[0]["display_mode"] == "signed"
    # unsigned siblings are still labelled distinctly (not موثّق)
    unsigned = [f for c in data["citations"] for f in c["findings"] if not f["verified"]]
    assert all(f["label"] == "منقول من الكتب" for f in unsigned)


def test_ask_no_source_returns_kickoff_phrase_and_gap_dossier(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.core.dossier import DOSSIER_DIR, load_dossier

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)
    data = client.post(
        "/ask", json={"query": "zzz موضوع غير موجود تماما xyzabc123", "madhhab": "maliki"}
    ).json()

    assert "لا أعلم" in data["message"]
    assert data["citations"] == []
    assert data["dossier"] is not None
    assert data["dossier"]["kind"] == "gap"

    d = load_dossier(data["dossier"]["id"])
    try:
        assert d is not None
        assert d.kind == "gap"
        assert d.status == "PENDING"  # never a fatwa
        assert d.per_madhhab == {}
    finally:
        (DOSSIER_DIR / f"{d.id}.json").unlink(missing_ok=True)


def test_analytics_log_unsigned_hits_and_order_queue(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.core import analytics

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)
    data = client.post("/ask", json={"query": "ما هي مواقيت الإحرام؟", "madhhab": "hanafi"}).json()
    hit_ids = {
        f["source_id"] for c in data["citations"] for f in c["findings"] if not f["verified"]
    }
    assert hit_ids

    hits = analytics.load_unsigned_hits()
    assert hits, "every unsigned hit must be logged"
    assert hits[-1]["query"] == "ما هي مواقيت الإحرام؟"
    assert {h["passage_id"] for h in hits[-1]["hits"]} == hit_ids

    queue = analytics.prioritized_pending()
    assert queue, "queue must contain real unsigned pages"
    assert queue[0]["passage"]["id"] in hit_ids
    assert queue[0]["direct_hits"] >= 1
    assert all(not (q["passage"]["provenance"] or "").startswith("seed") for q in queue), (
        "seed placeholders can never be signed and stay out of the queue"
    )

    prog = analytics.review_progress()
    assert prog["total"] >= prog["pending"] + prog["signed"]
    assert prog["pending"] >= sum(1 for q in queue), "queue view may be capped below the true total"
    assert prog["est_seconds"] > 0
    assert prog["seconds_per_page"] >= 1


def test_retrieval_relevance_and_matched_excerpts(tmp_path, monkeypatch):
    from rafiq.agents.faqih import faqih_agent
    from rafiq.rag.arabic import normalize_for_search
    from rafiq.rag.madhhab_stores import search_passages

    _prepare(tmp_path, monkeypatch)

    talaq = search_passages("hanbali", "ما حكم الطلاق في الحيض؟", limit=3)
    assert talaq, "talaq+menstruation question must retrieve"
    assert talaq[0].id.startswith(("cumda_talaq", "cumda_nikah")) or (
        "طلاق" in talaq[0].topic_tags
    ), talaq[0].id

    zakat = search_passages("shafii", "كم نصاب زكاة الذهب؟", limit=3)
    assert zakat, "zakat nisab question must retrieve"
    assert zakat[0].id.startswith(("muzani_zakat", "minhaj_zakat")), zakat[0].id
    zk = normalize_for_search(zakat[0].text)
    assert "نصاب" in zk or "ذهب" in zk

    out = faqih_agent("ما حكم الجمع بين الصلاتين في السفر؟", madhhab="maliki")
    assert out.status == "ok"
    assert any(f.source_id.startswith("khalil_salat") for f in out.findings)
    from rafiq.rag.madhhab_stores import get_passage

    top = out.findings[0]
    assert len(top.excerpt) <= 440, "excerpt must be windowed for reading"
    full = get_passage("maliki", top.source_id).text
    assert top.excerpt.replace("…", "").strip() in full, "excerpt must be a verbatim slice"


def test_public_ask_page_renders_book_based_disclosure(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text
    assert "/static/ask.js" in r.text
    assert "<script>" not in r.text, "CSP allows no inline script"
    assert "ليست فتوى مفتٍ" in r.text, "page must say the answer is not a mufti's fatwa"
    assert 'id="khulasa"' in r.text, "plain-language summary container must exist"
    assert "Content-Security-Policy" in r.headers

    js = client.get("/static/ask.js").text
    assert "/ask" in js
    assert "textContent" in js
    assert "renderKhulasa" in js
    assert "اعرض النصوص الحرفية كدليل" in js, "verbatim evidence must be collapsible"
    assert "innerHTML" not in js, "render must be textContent-only (no HTML injection)"


def test_shareability_meta_manifest_sitemap_robots(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)

    page = client.get("/").text
    assert 'property="og:title"' in page
    assert 'property="og:description"' in page
    assert 'name="twitter:card"' in page
    assert 'rel="manifest" href="/manifest.webmanifest"' in page
    assert 'name="theme-color"' in page
    assert 'name="description"' in page

    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200
    manifest = m.json()
    assert manifest["start_url"] == "/" and manifest["dir"] == "rtl"
    assert any(i["src"] == "/static/icon.svg" for i in manifest["icons"])

    icon = client.get("/static/icon.svg")
    assert icon.status_code == 200 and "<svg" in icon.text

    s = client.get("/sitemap.xml")
    assert s.status_code == 200
    assert "<urlset" in s.text and "http://testserver/" in s.text

    rb = client.get("/robots.txt")
    assert rb.status_code == 200
    assert "Sitemap: http://testserver/sitemap.xml" in rb.text
    assert "Disallow: /review" in rb.text

    gv = client.get("/googled98c9aca9979774d.html")
    assert gv.status_code == 200
    assert "google-site-verification" in gv.text

    js = client.get("/static/ask.js").text
    assert "wa.me" in js and "t.me/share" in js and "twitter.com/intent" in js
    assert "innerHTML" not in js

    # plain-language summary layer: extractive, templated, top 2-3 pages only
    ask = client.post("/ask", json={"query": "ما حكم صلاة الجماعة", "madhhab": "maliki"})
    assert ask.status_code == 200
    d = ask.json()
    khulasa = d.get("khulasa") or ""
    assert khulasa.startswith("بناءً على ما نقل من الكتب المذكورة"), khulasa
    assert khulasa.endswith("وليست فتوى معتمدة، وللفتوى المعتمدة راجع أهل العلم."), khulasa
    assert d.get("hukm_mubasat") in {
        "سنة",
        "سنة مؤكدة",
        "مستحب",
        "مباح",
        "مكروه",
        "حرام",
        "واجب",
        "غير واضح",
    }, d.get("hukm_mubasat")
    findings = [f for c in d["citations"] for f in c["findings"]]
    assert 0 < len(findings) <= 3, "only the best pages may be served"
    assert "الجماع" in khulasa, "summary must carry the asked subject verbatim"


def test_khulasa_is_extractive_and_detects_hukm():
    from rafiq.core.khulasa import END, START, UNKNOWN, build_khulasa

    citations = [
        {
            "extra": {"madhhab": "maliki"},
            "findings": [
                {
                    "excerpt": "الجماعة بفرض غير جمعة سنة1 ولا تتفاضل وإنما يحصل فضلها بركعة",
                    "work": "مختصر خليل",
                    "madhhab": "maliki",
                    "source_id": "khalil_salat_p040",
                }
            ],
        }
    ]
    kh = build_khulasa(citations, "ما حكم صلاة الجماعة")
    assert kh["hukm"] == "سنة", kh
    assert kh["text"].startswith(START) and kh["text"].endswith(END)
    assert "الجماعة" in kh["text"] and "سنة1" not in kh["text"]
    assert kh["source_id"] == "khalil_salat_p040"

    # negated permission is detected as haram; no keyword -> stays vague
    neg = [
        {
            "extra": {"madhhab": "maliki"},
            "findings": [
                {
                    "excerpt": "لا تجوز إمامة المميز في الفرض",
                    "work": "مختصر خليل",
                    "madhhab": "maliki",
                    "source_id": "x1",
                }
            ],
        }
    ]
    assert build_khulasa(neg, "ما حكم إمامة المميز")["hukm"] == "حرام"
    vague = [
        {
            "extra": {"madhhab": "maliki"},
            "findings": [
                {"excerpt": "باب في الطهارة", "work": "x", "madhhab": "maliki", "source_id": "x2"}
            ],
        }
    ]
    kv = build_khulasa(vague, "ما حكم صلاة الجماعة")
    assert kv["hukm"] == UNKNOWN
    assert "النص المنقول غير كافٍ لتحديد حكم واضح" in kv["text"]
    assert kv["text"].startswith(START) and kv["text"].endswith(END)


def test_signoff_stores_sheikh_timestamp_edition_hash_and_reviewed_text(tmp_path, monkeypatch):
    from rafiq.rag.madhhab_stores import (
        get_passage,
        list_passages,
        load_seed_data,
        sync_candidates,
    )
    from rafiq.rag.verify_corpus import (
        apply_verifications,
        edition_sha256,
        latest_verification,
        sign_off,
        text_sha256,
        verify_check,
    )

    _prepare(tmp_path, monkeypatch)
    p = list_passages("maliki", verified=False)[0]
    reviewed = p.text + "\n(تصحيح تحريري في لوحة المراجعة)"
    updated = sign_off(
        "maliki", p.id, "sheikh_review", GOOD_FIELDS, note="قوبل على المطبوع", text=reviewed
    )
    assert updated.verified is True
    assert updated.verified_by == "sheikh_review"
    assert updated.verified_at

    rec = latest_verification(p.id, "maliki")
    assert rec["edition_sha256"] == edition_sha256(rec)
    assert rec["text_sha256"] == text_sha256(reviewed)
    assert rec["reviewed_text"] == reviewed
    assert verify_check()["ok"] is True

    # store rebuild: load seeds + candidates again, then apply_verifications
    # restores the signed reviewed text, hash-bound
    load_seed_data()
    sync_candidates()
    applied = apply_verifications()
    assert applied >= 1
    p2 = get_passage("maliki", p.id)
    assert p2.verified is True
    assert p2.text == reviewed
    assert verify_check()["ok"] is True


def test_reject_and_fix_edition_never_sign(tmp_path, monkeypatch):
    import pytest

    from rafiq.core import analytics
    from rafiq.rag.madhhab_stores import list_passages
    from rafiq.rag.verify_corpus import (
        edit_edition,
        latest_record,
        reject,
        rejected_passages,
    )

    _prepare(tmp_path, monkeypatch)
    p = list_passages("maliki", verified=False)[0]

    edited = edit_edition(
        "maliki",
        p.id,
        "sheikh_fix",
        {**GOOD_FIELDS, "edition": "دار الفكر، ط2", "page": 77},
        text=p.text + " (تصحيح)",
    )
    assert edited.verified is False
    assert edited.edition == "دار الفكر، ط2"
    assert edited.page is None, "page stays null until sign-off (no unverified page numbers)"
    rec = latest_record(p.id, "maliki")
    assert rec["action"] == "edit_edition"
    assert rec["page"] == 77  # proposed value kept in the append-only record
    assert rec["text_sha256"]

    q = list_passages("maliki", verified=False)[1]
    reject("maliki", q.id, "sheikh_fix", "النص لا يطابق الطبعة المطبوعة")
    assert q.verified is False
    assert (q.madhhab, q.id) in rejected_passages()
    ids = {item["passage"]["id"] for item in analytics.prioritized_pending()}
    assert q.id not in ids, "rejected passages leave the review queue"

    with pytest.raises(ValueError):
        reject("maliki", q.id, "sheikh_fix", "")
    with pytest.raises(ValueError):
        edit_edition("maliki", q.id, "", GOOD_FIELDS)


def test_review_ui_auth_csrf_and_keyboard_contract(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)

    r = client.get("/review", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    assert client.get("/review/queue.json").status_code == 403

    _login(client)
    page = client.get("/review")
    assert page.status_code == 200
    assert 'dir="rtl"' in page.text
    assert "/static/review.js" in page.text
    assert _csrf_from_page(page.text)
    for key in ("[A]", "[R]", "[E]", "[J]", "[K]"):
        assert key in page.text, f"keyboard hint {key} missing"
    assert "غير موثّق" in page.text
    assert "Content-Security-Policy" in page.headers

    queue = client.get("/review/queue.json").json()
    assert queue["items"], "queue must expose unsigned real pages"
    assert all(not (i["provenance"] or "").startswith("seed") for i in queue["items"])
    assert all(i["scan_links"] for i in queue["items"] if i["provenance"].startswith("OpenITI:"))
    assert queue["queue_size"] <= 300, "queue payload must stay capped for responsiveness"
    assert queue["progress"]["pending"] >= queue["queue_size"]

    item = queue["items"][0]
    r = client.post(
        f"/review/{item['madhhab']}/{item['id']}/approve",
        data={
            "work": item["work"],
            "edition": item["edition"],
            "volume": "1",
            "page": str(item["page_hint"] or 1),
            "provenance": item["provenance"],
            "license": item["license"],
            "text": item["text"],
        },
    )
    assert r.status_code == 403, "approve without csrf must be refused"
    from rafiq.rag.madhhab_stores import get_passage

    assert get_passage(item["madhhab"], item["id"]).verified is False


def test_review_approve_reject_fix_flow(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rafiq.api.main import app
    from rafiq.rag.madhhab_stores import get_passage
    from rafiq.rag.verify_corpus import latest_record

    _prepare(tmp_path, monkeypatch)
    client = TestClient(app)
    _login(client)
    page = client.get("/review")
    csrf = _csrf_from_page(page.text)

    queue = client.get("/review/queue.json").json()
    item = queue["items"][0]
    fields = {
        "csrf": csrf,
        "work": item["work"],
        "edition": item["edition"],
        "volume": "1",
        "page": str(item["page_hint"] or 1),
        "provenance": item["provenance"],
        "license": item["license"],
        "text": item["text"],
        "note": "قوبل على المطبوع",
    }

    r = client.post(f"/review/{item['madhhab']}/{item['id']}/approve", data=fields)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["verified"] is True
    assert body["label"] == "موثّق"
    assert body["verified_by"] == "review_sheikh"
    assert body["verified_at"]
    assert body["edition_sha256"]
    assert get_passage(item["madhhab"], item["id"]).verified is True

    queue2 = client.get("/review/queue.json").json()
    assert all(i["id"] != item["id"] for i in queue2["items"]), "approved item left the queue"
    assert queue2["progress"]["signed"] == queue["progress"]["signed"] + 1
    assert queue2["progress"]["pending"] == queue["progress"]["pending"] - 1

    item2 = queue2["items"][0]
    r = client.post(
        f"/review/{item2['madhhab']}/{item2['id']}/reject",
        data={"csrf": csrf, "reason": "النص لا يطابق المطبوع"},
    )
    assert r.status_code == 200
    assert r.json()["verified"] is False
    assert get_passage(item2["madhhab"], item2["id"]).verified is False
    assert latest_record(item2["id"], item2["madhhab"])["action"] == "reject"

    item3 = next(i for i in queue2["items"] if i["id"] != item2["id"])
    r = client.post(
        f"/review/{item3['madhhab']}/{item3['id']}/fix-edition",
        data={
            "csrf": csrf,
            "work": item3["work"],
            "edition": "طبعة مصححة ط2",
            "volume": "1",
            "page": "9",
            "provenance": item3["provenance"],
            "license": item3["license"],
            "text": item3["text"] + " (تصحيح)",
            "note": "صححت رقم الطبعة",
        },
    )
    assert r.status_code == 200
    assert r.json()["verified"] is False
    fixed = get_passage(item3["madhhab"], item3["id"])
    assert fixed.verified is False
    assert fixed.edition == "طبعة مصححة ط2"

    queue3 = client.get("/review/queue.json").json()
    assert all(i["id"] != item2["id"] for i in queue3["items"])
    assert any(i["id"] == item3["id"] for i in queue3["items"]), "fixed but unsigned stays in queue"
