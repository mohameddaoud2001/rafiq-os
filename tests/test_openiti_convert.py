import json
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

FIXTURE = """######OpenITI#

#META#Header#End#

# PageV01P066
### | باب في أحكام كتاب الحج
### | مدخل
# ...
# نص الصفحة الأولى1 في الحج
~~وتكملة النص إلى ms042 PageV01P066
# ونص يلي ذلك
~~PageV01P067
# نص الصفحة الثالثة
### | فصل في فرع
# وفرع من الباب
### | باب في الذكاة
# نص الذكاة يجب ألا يظهر
"""


def test_parse_markdown_section_pages_and_cleanup():
    import openiti_to_candidates as conv

    pages = conv.parse_markdown_section(FIXTURE, "باب في أحكام كتاب الحج")
    assert [p["page"] for p in pages] == [66, 67]
    p66, p67 = pages
    assert "نص الصفحة الأولى" in p66["text"]
    assert "وتكملة النص" in p66["text"]
    assert "ms042" not in p66["text"]
    assert "..." not in p66["text"].replace("….", "")
    assert "نص يلي ذلك" in p67["text"]
    assert "نص الصفحة الثالثة" in p67["text"]
    assert "وفرع من الباب" in p67["text"]
    assert "نص الذكاة" not in p67["text"]
    assert "فصل في فرع" in p67["headings"]


FIXTURE_END_WITH = """######OpenITI#

### | كتاب الحج
# PageV01P010
# كتاب الحج
~~نص المسألة الأولى PageV01P010
# باب الإحرام
# نص الإحرام
~~وتكملته PageV01P011
### | كتاب النكاح
# نص لا يظهر
"""


def test_dots_only_lines_with_inline_marker_are_skipped():
    import openiti_to_candidates as conv

    text = """######OpenITI#
### | كتاب الحج
# نص الصفحة الأولى في أحكام هذا الباب PageV01P010
# . . . . . . . . . . . . . . . . . . . PageV01P011
# نص الصفحة الثالثة في ختام هذا الباب PageV01P012
"""
    pages = conv.parse_markdown_section(text, "كتاب الحج")
    assert [p["page"] for p in pages] == [10, 12]
    assert all("." not in p["text"].replace("….", "") for p in pages)


def test_end_with_boundary_and_single_hash_subheadings():
    import openiti_to_candidates as conv

    pages = conv.parse_markdown_section(FIXTURE_END_WITH, "كتاب الحج", end_with="كتاب النكاح")
    assert [p["page"] for p in pages] == [10, 11]
    p10, p11 = pages
    assert "نص المسألة الأولى" in p10["text"]
    assert "باب الإحرام" in p11["text"]
    assert "باب الإحرام" in p11["headings"]
    assert "نص لا يظهر" not in p11["text"]


def test_section_not_found_raises():
    import openiti_to_candidates as conv
    import pytest

    with pytest.raises(ValueError):
        conv.parse_markdown_section(FIXTURE, "باب غير موجود")


def test_to_candidates_shape():
    import openiti_to_candidates as conv

    pages = conv.parse_markdown_section(FIXTURE, "باب في أحكام كتاب الحج")
    rows = conv.to_candidates(
        pages,
        "maliki_test_hajj",
        "maliki",
        "مختصر خليل",
        "خليل",
        "طبعة",
        "CC BY-NC-SA 4.0",
        "OpenITI:test sha256:abc",
        ["هدي"],
    )
    assert len(rows) == 2
    r = rows[0]
    assert r["id"] == "maliki_test_hajj_p066"
    assert r["verified"] is False
    assert r["volume"] is None and r["page"] is None
    assert "PageV01P066" in r["provenance"]
    assert "confirm at sign-off" in r["provenance"]
    assert "maliki" in r["topic_tags"] and "الحج" in r["topic_tags"]
    assert "فصل في فرع" in rows[1]["topic_tags"]


def test_real_candidates_files_are_valid():
    from pathlib import Path

    from rafiq.rag.ingest import check_corpus_file

    path = Path("data/corpus/maliki/candidates/khalil_hajj.jsonl")
    assert path.exists(), "run scripts/openiti_to_candidates.py to generate candidates"
    report = check_corpus_file(path)
    assert report["ok"] is True
    assert report["unverified"] == report["total"] >= 10
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    assert all(r["license"].startswith("CC BY-NC-SA") for r in rows)


def test_every_madhhab_has_valid_real_candidates():
    from pathlib import Path

    from rafiq.rag.ingest import check_corpus_file

    for madhhab in ("maliki", "shafii", "hanafi", "hanbali"):
        files = sorted(Path(f"data/corpus/{madhhab}/candidates").glob("*.jsonl"))
        assert files, f"no real-text candidates for {madhhab}"
        for f in files:
            report = check_corpus_file(f)
            assert report["ok"] is True, (f, report["errors"][:3])
            assert report["unverified"] == report["total"] >= 5
            rows = [
                json.loads(line)
                for line in f.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert all(r["verified"] is False for r in rows)
            assert all(r["volume"] is None and r["page"] is None for r in rows)
            assert all(r["provenance"].startswith("OpenITI:") for r in rows)
            assert all(r["license"].startswith("CC BY-NC-SA") for r in rows)


def test_sync_candidates_additive_and_non_clobbering():
    import pathlib
    import tempfile

    from rafiq.rag import verify_corpus
    from rafiq.rag.madhhab_stores import get_passage, load_seed_data, sync_candidates
    from rafiq.rag.verify_corpus import sign_off, verify_check

    verify_corpus.VERIFICATIONS_PATH = pathlib.Path(tempfile.mkdtemp()) / "verifications.jsonl"
    load_seed_data()
    added = sync_candidates()
    assert added >= 10

    pid = "maliki_khalil_hajj_p066"
    p = get_passage("maliki", pid)
    assert p is not None and p.verified is False

    try:
        sign_off(
            "maliki",
            pid,
            "sh_test",
            {
                "work": "مختصر خليل",
                "edition": "دار الحديث، القاهرة",
                "volume": 1,
                "page": 66,
                "provenance": "OpenITI sha256:abc",
                "license": "CC BY-NC-SA 4.0",
            },
        )
        # second sync must not clobber the verified row nor the sign-off
        sync_candidates()
        p2 = get_passage("maliki", pid)
        assert p2.verified is True
        assert p2.verified_by == "sh_test"
        assert p2.page == 66
        assert verify_check()["ok"] is True
    finally:
        load_seed_data()
