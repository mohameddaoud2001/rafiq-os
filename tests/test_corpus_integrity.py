import pathlib
import sys
import tempfile

sys.path.insert(0, "src")

GOOD_FIELDS = {
    "work": "مختصر خليل",
    "edition": "دار الفكر",
    "volume": 1,
    "page": 42,
    "provenance": "shamela-export-v2 sha256:abc123",
    "license": "CC-BY-4.0",
}


def _fresh_corpus():
    from rafiq.rag import verify_corpus
    from rafiq.rag.madhhab_stores import load_seed_data

    verify_corpus.VERIFICATIONS_PATH = pathlib.Path(tempfile.mkdtemp()) / "verifications.jsonl"
    load_seed_data()


def test_off_topic_incidental_word_match_rejected():
    from rafiq.rag.madhhab_stores import search_passages, sync_candidates
    from rafiq.rag.verify_corpus import sign_off

    _fresh_corpus()
    sync_candidates()
    sign_off("maliki", "maliki_khalil_hajj_p066", "sheikh_test", {**GOOD_FIELDS, "page": 66})
    sign_off("maliki", "maliki_khalil_hajj_p073", "sheikh_test", {**GOOD_FIELDS, "page": 73})

    # p073's text mentions "حكم" and "صلاة" incidentally but carries no صلاة topic tag
    assert search_passages("maliki", "ما حكم صلاة الجماعة", verified_only=True) == []
    # a topic-tag core (عرفة) still reaches the signed pages
    hits = search_passages("maliki", "ما حكم الوقوف بعرفة", verified_only=True)
    assert any(h.id == "maliki_khalil_hajj_p066" for h in hits)


def test_relaxed_fallback_matches_arabic_variants():
    from rafiq.rag.madhhab_stores import search_passages

    _fresh_corpus()
    hits = search_passages("maliki", "ما حكم الوقوف بعرفة")
    assert hits, "relaxed core matching must find عرفة passages"
    assert any(h.id.startswith("maliki_arafat") for h in hits)


def test_question_punctuation_never_blocks_retrieval():
    from rafiq.rag.arabic import normalize_for_search
    from rafiq.rag.madhhab_stores import _query_cores, search_passages

    _fresh_corpus()
    # «؟» must never glue onto a core (الإحرام؟ -> احرام؟)
    normalized = normalize_for_search("ما هي سنن الإحرام؟")
    assert "؟" not in normalized
    assert "احرام" in _query_cores(normalized)

    # a question mark may not change the result set at all
    with_q = search_passages("maliki", "ما حكم الوقوف بعرفة؟")
    without_q = search_passages("maliki", "ما حكم الوقوف بعرفة")
    assert with_q
    assert [h.id for h in with_q] == [h.id for h in without_q]


def test_nonsense_query_stays_empty_everywhere():
    from rafiq.rag.madhhab_stores import MADHHABS, search_passages

    _fresh_corpus()
    for mh in MADHHABS:
        assert search_passages(mh, "موضوع غير موجود تماما xyzabc123") == []


def test_relaxed_fallback_respects_verified_only():
    from rafiq.rag.madhhab_stores import search_passages
    from rafiq.rag.verify_corpus import sign_off

    _fresh_corpus()
    assert search_passages("maliki", "ما حكم الوقوف بعرفة", verified_only=True) == []
    sign_off("maliki", "maliki_arafat_1", "sheikh_test", GOOD_FIELDS)
    hits = search_passages("maliki", "ما حكم الوقوف بعرفة", verified_only=True)
    assert [h.id for h in hits] == ["maliki_arafat_1"]


def test_revoke_flow():
    from rafiq.rag.madhhab_stores import get_passage, search_passages
    from rafiq.rag.verify_corpus import (
        latest_record,
        latest_verification,
        revoke,
        sign_off,
        verify_check,
    )

    _fresh_corpus()
    sign_off("maliki", "maliki_arafat_1", "sheikh_test", GOOD_FIELDS)
    assert get_passage("maliki", "maliki_arafat_1").verified is True

    revoke("maliki", "maliki_arafat_1", "operator", "نص توضيحي لا أصل مطبوع له")
    p = get_passage("maliki", "maliki_arafat_1")
    assert p.verified is False
    assert p.verified_by is None and p.verified_at is None
    assert p.page is None and p.volume is None
    assert latest_verification("maliki_arafat_1", "maliki") is None
    assert latest_record("maliki_arafat_1", "maliki")["action"] == "revoke"
    assert verify_check() == {"ok": True, "checked": 0, "mismatches": []}
    assert search_passages("maliki", "ما حكم الوقوف بعرفة", verified_only=True) == []

    p2 = sign_off("maliki", "maliki_arafat_1", "sheikh_test2", GOOD_FIELDS)
    assert p2.verified is True
    assert latest_verification("maliki_arafat_1", "maliki")["verified_by"] == "sheikh_test2"


def test_revoke_validation():
    import pytest

    from rafiq.rag.verify_corpus import revoke

    _fresh_corpus()
    with pytest.raises(ValueError):
        revoke("maliki", "maliki_arafat_1", "", "سبب")
    with pytest.raises(ValueError):
        revoke("maliki", "maliki_arafat_1", "operator", "")
    with pytest.raises(ValueError):
        revoke("maliki", "no_such_passage", "operator", "سبب")


def test_verify_check_flags_revoked_but_verified():
    from rafiq.rag.madhhab_stores import insert_passage
    from rafiq.rag.verify_corpus import revoke, sign_off, verify_check

    _fresh_corpus()
    signed = sign_off("maliki", "maliki_arafat_1", "sheikh_test", GOOD_FIELDS)
    revoke("maliki", "maliki_arafat_1", "operator", "سبب الإلغاء")
    insert_passage("maliki", signed.model_copy(update={"verified": True}))

    check = verify_check()
    assert check["ok"] is False
    assert any("revoked but still verified" in m["reason"] for m in check["mismatches"])


def test_apply_verifications_after_store_rebuild():
    from rafiq.rag.madhhab_stores import get_passage, load_seed_data
    from rafiq.rag.verify_corpus import apply_verifications, revoke, sign_off, verify_check

    _fresh_corpus()
    sign_off("maliki", "maliki_arafat_1", "sheikh_test", GOOD_FIELDS)
    sign_off("maliki", "maliki_arafat_2", "sheikh_test", GOOD_FIELDS)
    revoke("maliki", "maliki_arafat_2", "operator", "سبب الإلغاء")

    load_seed_data()
    assert get_passage("maliki", "maliki_arafat_1").verified is False

    applied = apply_verifications()
    assert applied == 1
    p = get_passage("maliki", "maliki_arafat_1")
    assert p.verified is True
    assert p.verified_by == "sheikh_test"
    assert p.page == 42
    assert get_passage("maliki", "maliki_arafat_2").verified is False
    check = verify_check()
    assert check["ok"] is True
    assert check["checked"] == 1


def test_sign_off_writes_audit_entry():
    import json

    from rafiq.core import audit
    from rafiq.rag.verify_corpus import sign_off

    _fresh_corpus()
    before = audit.AUDIT_PATH.stat().st_size if audit.AUDIT_PATH.exists() else 0
    sign_off("maliki", "maliki_arafat_1", "sheikh_test", GOOD_FIELDS)
    with open(audit.AUDIT_PATH, "rb") as f:
        f.seek(before)
        new_lines = [json.loads(x) for x in f.read().decode().splitlines() if x.strip()]
    assert new_lines[-1]["event"] == "corpus_signoff"
    assert new_lines[-1]["actor"] == "sheikh_test"
