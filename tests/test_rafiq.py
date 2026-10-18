import pathlib
import sys

sys.path.insert(0, "src")


def test_arabic_normalization():
    from rafiq.rag.arabic import normalize_arabic

    assert normalize_arabic("أإآ") == "ااا"
    assert normalize_arabic("ى") == "ي"
    assert normalize_arabic("ة") == "ه"
    assert normalize_arabic("السَّلامُ") == "السلام"  # tashkeel stripped
    assert normalize_arabic("٠١٢") == "012"


def test_guardrails_hard_block():
    from rafiq.core.guardrails import check_all_input

    blocked, warnings, flags = check_all_input("اقتلوا الحاكم")
    assert blocked is True
    assert "HARD_BLOCK" in flags


def test_guardrails_adab_block():
    from rafiq.core.guardrails import check_all_input

    blocked, warnings, flags = check_all_input("الأشاعرة كفار")
    assert blocked is True


def test_guardrails_allowed_diff():
    from rafiq.core.guardrails import check_all_input

    blocked, warnings, flags = check_all_input("ما الفرق بين الأشعرية والماتريدية؟")
    assert blocked is False


def test_guardrails_talfiq():
    from rafiq.core.guardrails import check_talfiq

    is_t, msg = check_talfiq("اجمع لي أسهل الأقوال من المذاهب")
    assert is_t is True


def test_supervisor_golden():
    from rafiq.core.supervisor import supervisor_rules

    # a) bus overheated
    plan = supervisor_rules("الحافلة سخنت في عرفة والهدي باش يفسد؟")
    assert set(plan.agents) == {"logistics", "weather_health", "faqih"}

    # d) contract
    plan = supervisor_rules("scan this contract")
    assert "contracts" in plan.agents

    # e) hadith
    plan = supervisor_rules("is this hadith authentic?")
    assert "muhaddith" in plan.agents

    # b) qasr + dhikr
    plan = supervisor_rules(
        "هل أقصر الصلاة في السفر؟ وما الذكر المناسب؟", madhhab="maliki", tariqa="shadhiliyya"
    )
    assert "faqih" in plan.agents
    assert "murabbi" in plan.agents

    # c) group travel
    plan = supervisor_rules(
        "عندي مجموعة مالكية شاذلية طايرين من تونس لدبي لجدة، "
        "الجو كيفاش في عرفة؟ وش عندهم أذكار اليوم؟"
    )
    assert set(plan.agents) == {"weather_health", "murabbi"}


def test_rag_isolation_and_ingest():

    from rafiq.rag.ingest import validate_passage
    from rafiq.rag.madhhab_stores import load_seed_data, search_passages

    load_seed_data()

    # isolation: maliki search returns only maliki records (seed ids are prefixed)
    res_maliki = search_passages("maliki", "الوقوف بعرفة", limit=5)
    assert len(res_maliki) > 0
    for p in res_maliki:
        assert p.madhhab == "maliki"
        assert p.volume is None and p.page is None  # verified:false rule

    # ingest rejection: verified:true without volume/page should fail
    bad = {
        "id": "bad_1",
        "madhhab": "maliki",
        "text": "نص",
        "work": "كتاب",
        "edition": "ط1",
        "volume": 1,
        "page": None,
        "verified": True,
        "provenance": "test",
    }
    try:
        validate_passage(bad)
        assert False, "should have raised"
    except ValueError:
        pass

    # verified:false with volume non-null should fail
    bad2 = {
        "id": "bad_2",
        "madhhab": "maliki",
        "text": "نص",
        "verified": False,
        "volume": 1,
        "page": 1,
        "provenance": "seed",
    }
    try:
        validate_passage(bad2)
        assert False, "should have raised for verified:false with volume"
    except ValueError:
        pass


def test_muhaddith_isnad():
    from rafiq.agents.muhaddith import check_isnad

    chain = ["راوٍ تجريبي ١", "راوٍ تجريبي ٢"]
    res = check_isnad(chain)
    # these two overlap 150-180 and share city الكوفة
    assert res["checks"][0]["status"] == "connected_plausible"

    chain_break = ["راوٍ تجريبي ١", "راوٍ تجريبي ٣"]
    res2 = check_isnad(chain_break)
    assert res2["checks"][0]["status"] == "break_suspected"


def test_amin_certificate():
    from rafiq.agents.logistics import generate_amin_certificate, verify_amin_certificate

    readings = [
        {"ts": "2024-01-01T00:00:00Z", "temp_c": 2.0},
        {"ts": "2024-01-01T01:00:00Z", "temp_c": 3.0},
    ]
    cert = generate_amin_certificate("هدي-1", readings, "cold_chain_intact")
    assert "readings_digest" in cert
    assert "signature" in cert
    assert cert["disclaimer"]
    assert verify_amin_certificate(cert, readings) is True
    # tamper
    bad_readings = [{"ts": "2024-01-01T00:00:00Z", "temp_c": 10.0}]
    assert verify_amin_certificate(cert, bad_readings) is False


def test_weather_health():
    from rafiq.agents.weather_health import heat_stress_level

    assert heat_stress_level(42.5, 48, 25, 10) == "extreme"
    assert heat_stress_level(30, 31, 50, 3) == "low"


def test_contracts():
    from rafiq.agents.contracts import contracts_agent

    text = "هذا العقد فيه فائدة 5% ربا صريح"
    out = contracts_agent(text)
    assert len(out.findings) > 0
    assert any("riba" in f.topic_tags for f in out.findings)


def test_audit_chain():
    import tempfile

    from rafiq.core import audit
    from rafiq.core.audit import append_audit, verify_chain

    audit.AUDIT_PATH = pathlib.Path(tempfile.mkdtemp()) / "audit.jsonl"
    append_audit("test_event", "tester", {"data": "test"})
    append_audit("test_event2", "tester", {"data": "test2"})
    res = verify_chain()
    assert res["ok"] is True
    # tamper
    with open(audit.AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write('{"bad": "line"}\n')
    res2 = verify_chain()
    assert res2["ok"] is False


def test_verifier():
    from rafiq.core.state import AgentOutput, Finding
    from rafiq.core.verifier import verify_agent_output

    out = AgentOutput(agent="faqih", status="ok", findings=[Finding(source_id="", excerpt="no id")])
    verified = verify_agent_output(out)
    assert len(verified.findings) == 0


def test_api_pending_approve():
    import re

    from fastapi.testclient import TestClient

    from rafiq.api import auth, main
    from rafiq.api.main import app
    from rafiq.rag.madhhab_stores import load_seed_data

    load_seed_data()
    main._login_limiter.reset()
    auth.AUTH_DB.unlink(missing_ok=True)
    auth.init_db()
    auth.create_user("test_sheikh", "test-pass-123456", "sheikh")
    client = TestClient(app)
    # health
    r = client.get("/health")
    assert r.status_code == 200

    # ask informational
    r = client.post("/ask", json={"query": "الجو كيفاش في عرفة؟"})
    assert r.status_code == 200
    data = r.json()
    assert "route" in data

    # ruling seeking -> dossier
    r = client.post("/ask", json={"query": "هل أقصر الصلاة في السفر؟", "madhhab": "maliki"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("dossier") is not None
    dossier_id = data["dossier"]["id"]

    # dashboard requires login: anonymous is redirected
    anon = TestClient(app)
    r = anon.get("/dashboard/mufti", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    # login
    r = client.post(
        "/auth/login",
        data={"username": "test_sheikh", "password": "test-pass-123456"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard/mufti"

    # dashboard returns 200 with dir rtl
    r = client.get("/dashboard/mufti")
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text
    m = re.search(r'name="csrf" value="([^"]+)"', r.text)
    assert m, "csrf token missing from dashboard"
    csrf = m.group(1)

    # approve anonymously should 403
    r = anon.post(f"/dashboard/mufti/{dossier_id}/decision", data={"decision": "APPROVED"})
    assert r.status_code == 403

    # dev header auth is disabled by default
    r = anon.post(
        f"/dashboard/mufti/{dossier_id}/decision",
        headers={"X-Role": "sheikh", "X-Reviewer": "test"},
        data={"decision": "APPROVED"},
    )
    assert r.status_code == 403

    # session without csrf should 403
    r = client.post(f"/dashboard/mufti/{dossier_id}/decision", data={"decision": "APPROVED"})
    assert r.status_code == 403

    # invalid decision value should 400
    r = client.post(
        f"/dashboard/mufti/{dossier_id}/decision", data={"csrf": csrf, "decision": "MAYBE"}
    )
    assert r.status_code == 400

    # approve with session + csrf
    r = client.post(
        f"/dashboard/mufti/{dossier_id}/decision",
        data={"csrf": csrf, "decision": "APPROVED", "note": "ok"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "APPROVED"
    # reviewer identity comes from the authenticated session, not the form
    assert body["decisions"][0]["reviewer"] == "test_sheikh"

    # audit verify
    r = client.get("/audit/verify")
    assert r.status_code == 200

    # amin cert
    r = client.get("/amin/certificate/هدي-1")
    assert r.status_code == 200
    cert = r.json()
    assert "signature" in cert

    # amin verify
    from rafiq.live.sim import get_truck_temps_sim

    trucks = get_truck_temps_sim()
    t = [x for x in trucks if x["truck_id"] == "هدي-1"][0]
    r = client.post("/amin/verify", json={"certificate": cert, "readings": t["readings"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_mcp_toolbus_discovery():
    from rafiq.mcp_servers.toolbus import call_tool, discover_tools

    tools = discover_tools()
    assert "search_passages" in tools
    assert "weather" in tools
    # call dummy tool
    res = call_tool("weather", location="عرفة")
    assert "temperature_c" in res or "data_source" in res
