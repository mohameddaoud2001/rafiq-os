import hashlib
import hmac
import json
import pathlib
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from rafiq.agents.contracts import contracts_agent, extract_text_from_pdf
from rafiq.api import auth
from rafiq.api.security import (
    DASHBOARD_CSP,
    SECURITY_HEADERS,
    RateLimiter,
    client_ip,
)
from rafiq.config import settings
from rafiq.core import analytics
from rafiq.core.audit import append_audit, verify_chain
from rafiq.core.dossier import DECISIONS, DOSSIER_DIR, add_decision
from rafiq.core.guardrails import check_all_input
from rafiq.core.messages import BANNERS, DISPLAY_MODES, ERRORS, LABELS, MADHHAB_NAMES
from rafiq.core.supervisor import get_supervisor
from rafiq.core.verifier import verify_agent_output
from rafiq.rag.source_links import page_hint, source_citation
from rafiq.rag.source_links import scan_url as resolve_scan_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production()
    auth.init_db()
    from rafiq.rag.madhhab_stores import ensure_corpus_loaded
    from rafiq.rag.verify_corpus import apply_verifications

    ensure_corpus_loaded()
    apply_verifications()
    yield


app = FastAPI(title="Rafiq OS - الرفيق المسند", version="0.1.0", lifespan=lifespan)

if settings.trusted_hosts():
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts())

templates_path = pathlib.Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

static_path = pathlib.Path(__file__).parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

_ask_limiter = RateLimiter(settings.RAFIQ_RATE_LIMIT_PER_MINUTE)
_login_limiter = RateLimiter(settings.RAFIQ_LOGIN_RATE_LIMIT_PER_MINUTE)


def current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        user = auth.resolve_session(token)
        if user:
            return user
    # DEV-ONLY header auth, never honored in prod
    if settings.RAFIQ_DEV_AUTH and not settings.is_prod():
        role = request.headers.get("x-role")
        reviewer = request.headers.get("x-reviewer")
        if role and reviewer:
            return {"username": reviewer, "role": role, "dev": True}
    return None


def check_csrf(request: Request, user: dict, form_csrf: Optional[str]) -> bool:
    if user.get("dev"):
        return True
    supplied = form_csrf or request.headers.get(auth.CSRF_HEADER) or ""
    expected = user.get("csrf") or ""
    return bool(expected) and hmac.compare_digest(supplied, expected)


def require_reviewer(request: Request) -> Optional[dict]:
    user = current_user(request)
    if not user or user["role"] not in auth.REVIEW_ROLES:
        return None
    return user


def annotate_finding(f: dict) -> dict:
    """Attach the mandatory display metadata to a faqih finding.

    Unsigned pages may only be shown as verbatim matn (never as a fatwa, never
    labelled موثّق); موثّق is only ever set from the stored verified flag, which
    only sign_off() can flip.
    """
    f["scan_url"] = f.get("scan_url") or resolve_scan_url(provenance=f.get("provenance"))
    f["page_hint"] = page_hint(f.get("provenance"))
    f["source_label"] = source_citation(
        work=f.get("work"),
        author=f.get("author"),
        edition=f.get("edition"),
        volume=f.get("volume"),
        page=f.get("page"),
        provenance=f.get("provenance"),
    )
    f["label"] = LABELS["verified"] if f.get("verified") else LABELS["unsigned"]
    f["display_mode"] = DISPLAY_MODES["signed"] if f.get("verified") else DISPLAY_MODES["matn"]
    f["copy_as_fatwa_allowed"] = bool(f.get("verified"))
    return f


def unsigned_notice(f: dict) -> dict:
    """Mandatory per-source banner for an unsigned finding (red/amber, on top)."""
    return {
        "severity": "danger",
        "madhhab": f.get("madhhab"),
        "passage_id": f.get("source_id"),
        "text": BANNERS["unsigned_pilot"].format(source=f.get("source_label") or "المصدر غير محدد"),
        "source": {
            "work": f.get("work"),
            "author": f.get("author"),
            "edition": f.get("edition"),
            "page": f.get("page"),
            "scan_url": f.get("scan_url"),
        },
        "display_mode": DISPLAY_MODES["matn"],
        "copy_as_fatwa_allowed": False,
    }


def unsigned_hit_rows(findings: list, fallback_madhhab: str) -> list:
    return [
        {"madhhab": f.get("madhhab") or fallback_madhhab, "passage_id": f["source_id"]}
        for f in findings
        if f.get("source_id")
    ]


def build_book_answer(citations: list) -> Optional[dict]:
    """Extractive answer for ruling questions: fixed disclaimer + verbatim quotes.

    Owner decision 2026-10-18: the answer is a book-based composition - the
    only text the system contributes is the fixed disclaimer; every quoted
    sentence is verbatim corpus text with its source. The system never writes
    new fiqh wording, so there is nothing to sign.
    """
    quotes = []
    for cit in citations:
        mh = MADHHAB_NAMES.get((cit.get("extra") or {}).get("madhhab", ""), "")
        for f in (cit.get("findings") or [])[:2]:
            heading = " - ".join(x for x in (mh, f.get("work")) if x)
            quotes.append(
                {
                    "heading": heading or None,
                    "excerpt": f.get("excerpt") or "",
                    "source_label": f.get("source_label"),
                    "source_id": f.get("source_id"),
                }
            )
    if not quotes:
        return None
    quotes = quotes[:3]
    lines = [BANNERS["book_based_answer"], ""]
    for q in quotes:
        lines.append(f"[{q['heading']}]" if q["heading"] else "[نقل]")
        lines.append("«" + q["excerpt"] + "»")
        if q["source_label"]:
            lines.append("(" + q["source_label"] + ")")
        lines.append("")
    return {
        "text": "\n".join(lines).strip(),
        "quotes": quotes,
        "based_on": [q["source_id"] for q in quotes if q["source_id"]],
        "disclaimer": BANNERS["book_based_answer"],
    }


@app.middleware("http")
async def pilot_guard(request: Request, call_next):
    path = request.url.path
    if path == "/auth/login" and not _login_limiter.allow(client_ip(request)):
        return JSONResponse(
            status_code=429, content={"detail": "too many login attempts, try again later"}
        )
    if path == "/ask" and not _ask_limiter.allow(client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if settings.cookie_secure() or request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    if path == "/" or path.startswith(("/dashboard", "/login", "/review")):
        response.headers.setdefault("Content-Security-Policy", DASHBOARD_CSP)
    return response


@app.get("/health")
def health():
    return {"status": "ok", "live_mode": settings.RAFIQ_LIVE, "router": settings.RAFIQ_ROUTER}


@app.get("/", response_class=HTMLResponse)
async def ask_page(request: Request):
    """Public ask page: a book-based answer (verbatim excerpts + fixed disclaimer)
    with every quote attributed to its printed source. It is not a fatwa and no
    sign-off is required to serve it."""
    return templates.TemplateResponse(request, "ask.html", {})


def _public_base(request: Request) -> str:
    """Public base URL for sitemap/robots: explicit setting wins (behind TLS proxies)."""
    return (settings.RAFIQ_PUBLIC_URL or str(request.base_url)).rstrip("/")


@app.get("/manifest.webmanifest")
async def manifest_webmanifest():
    return JSONResponse(
        {
            "name": "الرفيق المسند - جواب من الكتب",
            "short_name": "الرفيق المسند",
            "description": (
                "جواب مبني على نقل حرفي من كتب معتمدة مذكورة، مع مواضعها من الطبعات - ليس فتوى مفتٍ"
            ),
            "lang": "ar",
            "dir": "rtl",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#faf8f4",
            "theme_color": "#1b5e20",
            "icons": [
                {
                    "src": "/static/icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                }
            ],
        },
        media_type="application/manifest+json",
    )


@app.get("/sitemap.xml")
async def sitemap_xml(request: Request):
    base = _public_base(request)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{base}/</loc></url>\n"
        "</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


@app.get("/robots.txt")
async def robots_txt(request: Request):
    base = _public_base(request)
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /review\n"
        "Disallow: /dashboard\n"
        "Disallow: /login\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = current_user(request)
    if user and user["role"] in auth.REVIEW_ROLES:
        return RedirectResponse("/dashboard/mufti", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/auth/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = auth.authenticate(username, password)
    if not user:
        ip_digest = hashlib.sha256(client_ip(request).encode("utf-8")).hexdigest()
        append_audit("login_failed", username or "unknown", {"ip_digest": ip_digest})
        return templates.TemplateResponse(
            request, "login.html", {"error": "بيانات الدخول غير صحيحة"}, status_code=401
        )
    token, _csrf = auth.create_session(user["username"], ttl_hours=settings.RAFIQ_SESSION_TTL_HOURS)
    append_audit("login_ok", user["username"], {"role": user["role"]})
    response = RedirectResponse("/dashboard/mufti", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure(),
        max_age=int(settings.RAFIQ_SESSION_TTL_HOURS * 3600),
        path="/",
    )
    return response


@app.post("/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.revoke_session(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


@app.post("/ask")
async def ask(payload: dict):
    query = payload.get("query", "")
    madhhab = payload.get("madhhab", "maliki")
    tariqa = payload.get("tariqa")
    location = payload.get("location", "عرفة")

    blocked, warnings, flags = check_all_input(query)
    if blocked:
        append_audit("ask_blocked", "api", {"flags": flags})
        return JSONResponse(
            status_code=200,
            content={
                "blocked": True,
                "reason": warnings[0] if warnings else "blocked",
                "flags": flags,
                "banners": [BANNERS["unverified"]],
            },
        )

    # Supervisor
    sup_fn = get_supervisor(settings.RAFIQ_ROUTER)
    plan = sup_fn(query, madhhab, tariqa, location)

    # Dispatch agents (simplified sync version for API)
    from rafiq.core.graph import dispatch_agents

    outputs = dispatch_agents(plan, query, madhhab, tariqa, location, settings.RAFIQ_LIVE)

    # Verify
    verified = [verify_agent_output(o) for o in outputs]

    is_ruling = plan.intent in ["ruling", "mixed"]

    annotated = []
    for out in verified:
        o = out.model_dump()
        for f in o["findings"]:
            if o["agent"] == "faqih":
                annotate_finding(f)
        annotated.append(o)

    informational = [o for o in annotated if o["informational_only"] or not is_ruling]
    citations = [o for o in annotated if o["agent"] == "faqih" and o["findings"]]
    source_findings = [f for o in annotated if o["agent"] == "faqih" for f in o["findings"]]
    unsigned_findings = [f for f in source_findings if not f["verified"]]
    notices = [unsigned_notice(f) for f in unsigned_findings]

    # Every served quote is real book text, plainly labelled
    # "منقول من الكتب - بلا توقيع مفتٍ - المصدر: ..." with the mandatory
    # "ليست فتوى مفتٍ معتمد" banner (owner decision 2026-10-18: no sign-off
    # is required or checked; legacy verified:true records still show موثّق).
    banners = [n["text"] for n in notices]
    if notices:
        banners.append(BANNERS["matn_only"])
    if is_ruling:
        banners.append(BANNERS["pending_review"])
        banners.append(BANNERS["book_based_answer"])
    banners.append(BANNERS["unverified"])
    if notices:
        banners.append(BANNERS["unsigned_citations"])
    if settings.RAFIQ_LIVE == "sim" and not is_ruling:
        banners.append(BANNERS["sim_data"])

    if is_ruling:
        # Create dossier
        from rafiq.core.audit import get_last_hash
        from rafiq.core.dossier import create_dossier

        per_madhhab = {}
        waqi = {}
        hadith = {}
        for out in verified:
            if out.agent == "faqih":
                per_madhhab[out.extra.get("madhhab", madhhab)] = {
                    "findings": [f.model_dump() for f in out.findings]
                }
            if out.agent in ["logistics", "weather_health"]:
                waqi[out.agent] = out.extra
            if out.agent == "muhaddith":
                hadith = [f.model_dump() for f in out.findings]
        prev_hash = get_last_hash()
        d = create_dossier(
            query,
            per_madhhab,
            hadith,
            waqi,
            warnings,
            previous_audit_hash=prev_hash,
            kind="masala",
            unsigned_hits=[f["source_id"] for f in unsigned_findings],
        )
        dossier = {"id": d.id, "status": d.status, "masala": d.masala, "kind": d.kind}

        if unsigned_findings:
            # Dossier analytics: log every query that hit unsigned pages so the
            # /review queue is ordered by what people actually ask.
            analytics.record_unsigned_hit(
                query,
                madhhab,
                unsigned_hit_rows(unsigned_findings, madhhab),
                intent=plan.intent,
                dossier_id=d.id,
            )

        # For mixed, return informational now and dossier pending
        returned_info = informational if plan.intent == "mixed" else []
        response = {
            "route": plan.model_dump(),
            "informational": returned_info,
            "citations": citations,
            "unsigned_notices": notices,
            "dossier": dossier,
            "banners": banners,
            "fatwa": build_book_answer(citations),
        }
        if not citations and not returned_info:
            response["message"] = ERRORS["not_found"]
        return response

    # KICKOFF fail-safe: no signed or unsigned source found. Return the exact
    # KICKOFF phrase and log the knowledge gap to a dossier (no fatwa generated).
    total_findings = sum(len(o.findings) for o in verified)
    if total_findings == 0:
        from rafiq.core.audit import get_last_hash
        from rafiq.core.dossier import create_dossier

        d = create_dossier(
            query, {}, {}, {}, warnings, previous_audit_hash=get_last_hash(), kind="gap"
        )
        return {
            "route": plan.model_dump(),
            "informational": [],
            "citations": [],
            "unsigned_notices": [],
            "dossier": {"id": d.id, "status": d.status, "masala": d.masala, "kind": d.kind},
            "message": ERRORS["not_found"],
            "banners": banners,
            "fatwa": None,
        }

    if unsigned_findings:
        analytics.record_unsigned_hit(
            query,
            madhhab,
            unsigned_hit_rows(unsigned_findings, madhhab),
            intent=plan.intent,
        )

    return {
        "route": plan.model_dump(),
        "informational": informational,
        "citations": citations,
        "unsigned_notices": notices,
        "dossier": None,
        "banners": banners,
        "fatwa": None,
    }


@app.post("/contracts/scan")
async def contracts_scan(file: UploadFile = File(None), text: str = Form(None)):
    content = ""
    if file:
        data = await file.read()
        if file.filename.endswith(".pdf"):
            content = extract_text_from_pdf(data)
        else:
            content = data.decode("utf-8", errors="ignore")
    elif text:
        content = text
    else:
        raise HTTPException(status_code=400, detail="Provide file or text")

    out = contracts_agent(content)
    return out.model_dump()


@app.get("/dashboard/mufti", response_class=HTMLResponse)
async def mufti_dashboard(request: Request):
    user = current_user(request)
    if not user or user["role"] not in auth.REVIEW_ROLES:
        return RedirectResponse("/login", status_code=303)
    dossiers = []
    if DOSSIER_DIR.exists():
        for p in DOSSIER_DIR.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.loads(f.read())
                    dossiers.append(data)
            except Exception:
                pass
    return templates.TemplateResponse(
        request,
        "mufti.html",
        {"dossiers": dossiers, "user": user, "csrf": user.get("csrf", "")},
    )


@app.post("/dashboard/mufti/{dossier_id}/decision")
async def mufti_decision(
    dossier_id: str,
    request: Request,
    decision: str = Form(None),
    note: str = Form(None),
    csrf: str = Form(None),
):
    user = current_user(request)
    if not user or user["role"] not in auth.REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not check_csrf(request, user, csrf):
        raise HTTPException(status_code=403, detail="CSRF check failed")
    if decision not in DECISIONS:
        raise HTTPException(status_code=400, detail=f"decision must be one of {sorted(DECISIONS)}")

    try:
        d = add_decision(dossier_id, user["username"], decision, note or "")
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)
    append_audit(
        "dossier_decision", user["username"], {"dossier_id": dossier_id, "decision": decision}
    )

    # HTMX response
    if "hx-request" in request.headers:
        return HTMLResponse(f"<p>تم {decision} للملف {dossier_id} بواسطة {user['username']}</p>")
    return d.model_dump()


@app.get("/dashboard/corpus", response_class=HTMLResponse)
async def corpus_dashboard(request: Request, madhhab: str = "maliki"):
    user = current_user(request)
    if not user or user["role"] not in auth.REVIEW_ROLES:
        return RedirectResponse("/login", status_code=303)
    from rafiq.rag.madhhab_stores import MADHHABS, list_passages
    from rafiq.rag.verify_corpus import verify_check

    if madhhab not in MADHHABS:
        madhhab = "maliki"
    pending = list_passages(madhhab, verified=False, limit=100)
    verified_count = len(list_passages(madhhab, verified=True, limit=100000))
    check = verify_check()
    return templates.TemplateResponse(
        request,
        "corpus.html",
        {
            "user": user,
            "csrf": user.get("csrf", ""),
            "madhhab": madhhab,
            "madhhabs": MADHHABS,
            "pending": pending,
            "verified_count": verified_count,
            "check": check,
        },
    )


@app.post("/dashboard/corpus/{madhhab}/{passage_id}/verify")
async def corpus_verify(
    madhhab: str,
    passage_id: str,
    request: Request,
    work: str = Form(None),
    edition: str = Form(None),
    volume: str = Form(None),
    page: str = Form(None),
    provenance: str = Form(None),
    license: str = Form(None),
    note: str = Form(None),
    csrf: str = Form(None),
):
    from rafiq.rag.madhhab_stores import MADHHABS
    from rafiq.rag.verify_corpus import sign_off

    user = current_user(request)
    if not user or user["role"] not in auth.REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not check_csrf(request, user, csrf):
        raise HTTPException(status_code=403, detail="CSRF check failed")
    if madhhab not in MADHHABS:
        raise HTTPException(status_code=404, detail="Unknown madhhab")

    try:
        p = sign_off(
            madhhab,
            passage_id,
            user["username"],
            {
                "work": work,
                "edition": edition,
                "volume": volume,
                "page": page,
                "provenance": provenance,
                "license": license,
            },
            note or "",
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)

    if "hx-request" in request.headers:
        return HTMLResponse(f"<p>تم توثيق النص {passage_id} بواسطة {user['username']}</p>")
    return p.model_dump()


@app.get("/review", response_class=HTMLResponse)
async def review_page(request: Request):
    """Keyboard-driven batch sign-off UI for sheikhs (A/R/E, J/K)."""
    user = require_reviewer(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    response = templates.TemplateResponse(
        request, "review.html", {"user": user, "csrf": user.get("csrf", "")}
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/review/queue.json")
async def review_queue(request: Request):
    user = require_reviewer(request)
    if not user:
        raise HTTPException(status_code=403, detail="Forbidden")
    items = analytics.queue_with_links()
    response = JSONResponse(
        {
            "items": items,
            "queue_size": len(items),
            "progress": analytics.review_progress(),
            "user": user["username"],
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _review_form_fields(
    work: str = Form(None),
    edition: str = Form(None),
    volume: str = Form(None),
    page: str = Form(None),
    provenance: str = Form(None),
    license: str = Form(None),
) -> dict:
    return {
        "work": work,
        "edition": edition,
        "volume": volume,
        "page": page,
        "provenance": provenance,
        "license": license,
    }


def _reviewer_or_403(request: Request, csrf: Optional[str]) -> dict:
    user = require_reviewer(request)
    if not user:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not check_csrf(request, user, csrf):
        raise HTTPException(status_code=403, detail="CSRF check failed")
    return user


@app.post("/review/{madhhab}/{passage_id}/approve")
async def review_approve(
    madhhab: str,
    passage_id: str,
    request: Request,
    text: str = Form(None),
    note: str = Form(None),
    csrf: str = Form(None),
    work: str = Form(None),
    edition: str = Form(None),
    volume: str = Form(None),
    page: str = Form(None),
    provenance: str = Form(None),
    license: str = Form(None),
):
    """Approve = sign. Calls sign_off(): stores sheikh id, timestamp, edition hash."""
    from rafiq.rag.madhhab_stores import MADHHABS
    from rafiq.rag.verify_corpus import latest_verification, sign_off

    user = _reviewer_or_403(request, csrf)
    if madhhab not in MADHHABS:
        raise HTTPException(status_code=404, detail="Unknown madhhab")
    try:
        p = sign_off(
            madhhab,
            passage_id,
            user["username"],
            _review_form_fields(work, edition, volume, page, provenance, license),
            note or "",
            text=text,
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)
    rec = latest_verification(passage_id, madhhab) or {}
    return {
        "ok": True,
        "passage_id": passage_id,
        "madhhab": madhhab,
        "verified": p.verified,
        "label": LABELS["verified"],
        "verified_by": p.verified_by,
        "verified_at": p.verified_at,
        "edition_sha256": rec.get("edition_sha256"),
        "message": f"تم التوثيق ({LABELS['verified']}) بواسطة {user['username']}",
    }


@app.post("/review/{madhhab}/{passage_id}/reject")
async def review_reject(
    madhhab: str,
    passage_id: str,
    request: Request,
    reason: str = Form(None),
    csrf: str = Form(None),
):
    from rafiq.rag.madhhab_stores import MADHHABS
    from rafiq.rag.verify_corpus import reject

    user = _reviewer_or_403(request, csrf)
    if madhhab not in MADHHABS:
        raise HTTPException(status_code=404, detail="Unknown madhhab")
    try:
        reject(madhhab, passage_id, user["username"], reason or "")
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)
    return {
        "ok": True,
        "passage_id": passage_id,
        "madhhab": madhhab,
        "verified": False,
        "label": LABELS["unsigned"],
        "message": "سُجّل الرفض - النص باقٍ منقولاً من الكتب بلا توقيع",
    }


@app.post("/review/{madhhab}/{passage_id}/fix-edition")
async def review_fix_edition(
    madhhab: str,
    passage_id: str,
    request: Request,
    text: str = Form(None),
    note: str = Form(None),
    csrf: str = Form(None),
    work: str = Form(None),
    edition: str = Form(None),
    volume: str = Form(None),
    page: str = Form(None),
    provenance: str = Form(None),
    license: str = Form(None),
):
    """Fix edition/text without signing: verified stays false until approve."""
    from rafiq.rag.madhhab_stores import MADHHABS
    from rafiq.rag.verify_corpus import edit_edition

    user = _reviewer_or_403(request, csrf)
    if madhhab not in MADHHABS:
        raise HTTPException(status_code=404, detail="Unknown madhhab")
    try:
        p = edit_edition(
            madhhab,
            passage_id,
            user["username"],
            _review_form_fields(work, edition, volume, page, provenance, license),
            text=text,
            note=note or "",
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)
    return {
        "ok": True,
        "passage_id": passage_id,
        "madhhab": madhhab,
        "verified": p.verified,
        "label": LABELS["unsigned"],
        "message": "حُفظت التصحيحات - النص بلا توقيع حتى يوقّعه شيخ إن شاء (التوقيع اختياري)",
    }


@app.get("/audit/verify")
def audit_verify():
    result = verify_chain()
    return result


@app.get("/amin/certificate/{truck_id}")
def amin_certificate(truck_id: str):
    from rafiq.live.sim import get_truck_temps_sim

    trucks = get_truck_temps_sim()
    for t in trucks:
        if t["truck_id"] == truck_id:
            from rafiq.agents.logistics import generate_amin_certificate

            cert = generate_amin_certificate(truck_id, t["readings"], t["status"])
            return cert
    raise HTTPException(status_code=404, detail="Truck not found")


@app.post("/amin/verify")
def amin_verify(payload: dict):
    cert = payload.get("certificate")
    readings = payload.get("readings")
    if not cert or not readings:
        raise HTTPException(status_code=400, detail="certificate and readings required")
    from rafiq.agents.logistics import verify_amin_certificate

    ok = verify_amin_certificate(cert, readings)
    return {"ok": ok, "status": cert.get("status")}
