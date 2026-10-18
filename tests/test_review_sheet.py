import sys

sys.path.insert(0, "src")


def test_review_sheet_real_candidates_only(tmp_path):
    from rafiq.rag.madhhab_stores import load_seed_data, sync_candidates
    from rafiq.rag.review_sheet import build_review_sheet

    load_seed_data()
    sync_candidates()
    out = build_review_sheet("maliki", out_path=tmp_path / "sheet.html")
    content = out.read_text(encoding="utf-8")
    assert "maliki_khalil_hajj_p066" in content
    assert "مختصر خليل" in content
    assert "ص66" in content
    # seed summaries are not reviewable against any print - excluded
    assert "maliki_arafat_1" not in content
    assert "ملخص توضيحي" not in content
    assert 'dir="rtl"' in content
