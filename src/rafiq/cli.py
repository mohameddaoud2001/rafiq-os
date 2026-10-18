"""CLI"""

import argparse
import getpass
import json
import pathlib
import sys

from rafiq.config import settings
from rafiq.rag.ingest import check_corpus_file, ingest_file


def cmd_demo(args):
    if settings.is_prod():
        print("demo uses auto-approve and is dev-only; set RAFIQ_ENV=dev")
        sys.exit(1)
    print("=== Rafiq OS Demo - 3 golden scenarios ===")
    from rafiq.core.graph import run_query

    scenarios = [
        ("الحافلة سخنت في عرفة والهدي باش يفسد؟", {"madhhab": "maliki"}),
        (
            "هل أقصر الصلاة في السفر؟ وما الذكر المناسب؟",
            {"madhhab": "maliki", "tariqa": "shadhiliyya"},
        ),
        (
            "عندي مجموعة مالكية شاذلية طايرين من تونس لدبي لجدة، "
            "الجو كيفاش في عرفة؟ وش عندهم أذكار اليوم؟",
            {"madhhab": "maliki", "tariqa": "shadhiliyya"},
        ),
    ]
    for q, opts in scenarios:
        print(f"\n--- Query: {q}")
        try:
            result = run_query(
                q,
                madhhab=opts.get("madhhab"),
                tariqa=opts.get("tariqa"),
                location="عرفة",
                auto_approve=True,
            )
            rp = result.get("route_plan")
            agents_shown = rp.get("agents") if isinstance(rp, dict) else rp
            print(f"Agents: {agents_shown}")
            print(f"Dossier: {result.get('dossier_id')} Status: {result.get('dossier_status')}")
            outs = result.get("agent_outputs", [])
            print(f"Outputs: {len(outs)} agents_activated: {len(outs)}/6")
        except Exception as e:
            print(f"Error: {e}")

    print("\n--- Additional checks: hard-block, not-found, contract ---")
    from rafiq.core.guardrails import check_all_input

    blocked, warnings, flags = check_all_input("اقتلوا الحاكم")
    print(f"Hard block test (اقتلوا الحاكم): blocked={blocked} flags={flags}")

    from rafiq.rag.retriever import MadhhabRetriever

    r = MadhhabRetriever()
    res = r.search("موضوع غير موجود تماما", madhhab="maliki", limit=2)
    if not res:
        print("Not-found test: correctly returns لا أعلم phrase")

    print("\nDemo done.")


def cmd_ingest(args):
    path = pathlib.Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    try:
        count = ingest_file(path)
        print(f"Ingested {count} passages from {path}")
    except Exception as e:
        print(f"Ingest failed: {e}")
        sys.exit(1)


def cmd_audit_verify(args):
    from rafiq.core.audit import verify_chain

    result = verify_chain()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        sys.exit(1)


def cmd_auth(args):
    from rafiq.api import auth

    if args.auth_cmd == "add-user":
        password = args.password or getpass.getpass("password: ")
        auth.create_user(args.username, password, args.role)
        print(f"created user {args.username} role={args.role}")
    elif args.auth_cmd == "set-password":
        password = args.password or getpass.getpass("password: ")
        auth.set_password(args.username, password)
        print(f"password updated for {args.username}")
    elif args.auth_cmd == "list-users":
        for u in auth.list_users():
            state = "disabled" if u["disabled"] else "active"
            print(f"{u['username']}\t{u['role']}\t{state}")
    else:
        print("usage: rafiq auth add-user|set-password|list-users")


def cmd_corpus(args):
    if args.corpus_cmd == "check":
        report = check_corpus_file(pathlib.Path(args.file))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            sys.exit(1)
    elif args.corpus_cmd == "verify-check":
        from rafiq.rag.verify_corpus import verify_check

        report = verify_check()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            sys.exit(1)
    elif args.corpus_cmd == "sync-candidates":
        from rafiq.rag.madhhab_stores import sync_candidates

        added = sync_candidates()
        print(f"added {added} candidate passages (existing passages and sign-offs untouched)")
    elif args.corpus_cmd == "review-sheet":
        from rafiq.rag.review_sheet import build_review_sheet

        out = build_review_sheet(madhhab=args.madhhab, out_path=pathlib.Path(args.out))
        print(f"review sheet written: {out}")
    elif args.corpus_cmd == "revoke":
        from rafiq.rag.verify_corpus import revoke

        p = revoke(args.madhhab, args.passage_id, args.by, args.reason)
        print(
            json.dumps(
                {
                    "passage_id": p.id,
                    "madhhab": p.madhhab,
                    "verified": p.verified,
                    "revoked_by": args.by,
                },
                ensure_ascii=False,
            )
        )
    elif args.corpus_cmd == "apply-verifications":
        from rafiq.rag.verify_corpus import apply_verifications

        applied = apply_verifications()
        print(f"re-applied {applied} verification record(s) to stores")
    else:
        print(
            "usage: rafiq corpus check <file.jsonl> | rafiq corpus verify-check"
            " | rafiq corpus sync-candidates | rafiq corpus review-sheet"
            " | rafiq corpus revoke <madhhab> <passage_id> --by X --reason Y"
            " | rafiq corpus apply-verifications"
        )


def cmd_serve(args):
    import uvicorn

    settings.validate_production()
    ssl_kwargs = {}
    if settings.RAFIQ_TLS_CERT and settings.RAFIQ_TLS_KEY:
        ssl_kwargs = {
            "ssl_certfile": settings.RAFIQ_TLS_CERT,
            "ssl_keyfile": settings.RAFIQ_TLS_KEY,
        }
    uvicorn.run(
        "rafiq.api.main:app", host=args.host, port=args.port, reload=args.reload, **ssl_kwargs
    )


def cmd_ask(args):
    from rafiq.core.graph import run_query

    query = args.query
    result = run_query(
        query,
        madhhab=args.madhhab,
        tariqa=args.tariqa,
        location=args.location,
        auto_approve=args.auto_approve,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Query: {query}")
        print(f"Dossier ID: {result.get('dossier_id')} Status: {result.get('dossier_status')}")
        for out in result.get("agent_outputs", []):
            print(
                f"- Agent {out.get('agent')}: {out.get('status')} "
                f"findings={len(out.get('findings', []))}"
            )
            for f in out.get("findings", [])[:2]:
                print(f"  * {f.get('source_id')}: {f.get('excerpt')[:100]}")


def main():
    parser = argparse.ArgumentParser(prog="rafiq")
    sub = parser.add_subparsers(dest="cmd")

    # demo
    sub.add_parser("demo")

    # ingest
    p_ing = sub.add_parser("ingest")
    p_ing.add_argument("file", help="jsonl file")

    # audit-verify
    sub.add_parser("audit-verify")

    # auth
    p_auth = sub.add_parser("auth")
    auth_sub = p_auth.add_subparsers(dest="auth_cmd")
    p_adduser = auth_sub.add_parser("add-user")
    p_adduser.add_argument("username")
    p_adduser.add_argument("--role", default="sheikh", choices=["user", "sheikh", "admin"])
    p_adduser.add_argument("--password", default=None, help="prompted if omitted")
    p_setpw = auth_sub.add_parser("set-password")
    p_setpw.add_argument("username")
    p_setpw.add_argument("--password", default=None, help="prompted if omitted")
    auth_sub.add_parser("list-users")

    # corpus
    p_corpus = sub.add_parser("corpus")
    corpus_sub = p_corpus.add_subparsers(dest="corpus_cmd")
    p_check = corpus_sub.add_parser("check")
    p_check.add_argument("file")
    corpus_sub.add_parser("verify-check")
    corpus_sub.add_parser("sync-candidates")
    p_sheet = corpus_sub.add_parser("review-sheet")
    p_sheet.add_argument("--madhhab", default="maliki")
    p_sheet.add_argument("--out", default="data/review_sheet_maliki.html")
    p_revoke = corpus_sub.add_parser("revoke")
    p_revoke.add_argument("madhhab")
    p_revoke.add_argument("passage_id")
    p_revoke.add_argument("--by", required=True)
    p_revoke.add_argument("--reason", required=True)
    corpus_sub.add_parser("apply-verifications")

    # serve
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")

    # ask (default if positional query)
    p_ask = sub.add_parser("ask")
    p_ask.add_argument("query", nargs="?", help="query text")
    p_ask.add_argument("--madhhab", default="maliki")
    p_ask.add_argument("--tariqa", default=None)
    p_ask.add_argument("--location", default="عرفة")
    p_ask.add_argument("--json", action="store_true")
    p_ask.add_argument("--auto-approve", action="store_true")

    # Direct query as first arg without subcommand: python -m rafiq.cli "query" --madhhab ...
    # We'll parse manually
    args, unknown = parser.parse_known_args()

    # If no subcommand but first arg looks like query (not starting with -), treat as ask
    if args.cmd is None:
        # re-parse with ask parser for direct query mode
        direct_parser = argparse.ArgumentParser()
        direct_parser.add_argument("query", nargs="?", help="query")
        direct_parser.add_argument("--madhhab", default="maliki")
        direct_parser.add_argument("--tariqa", default=None)
        direct_parser.add_argument("--location", default="عرفة")
        direct_parser.add_argument("--json", action="store_true")
        direct_parser.add_argument("--auto-approve", action="store_true")
        direct_args = direct_parser.parse_args()
        if direct_args.query:
            cmd_ask(direct_args)
            return
        # else run demo if no args
        if len(sys.argv) == 1:
            parser.print_help()
            return

    if args.cmd == "demo":
        cmd_demo(args)
    elif args.cmd == "ingest":
        cmd_ingest(args)
    elif args.cmd == "audit-verify":
        cmd_audit_verify(args)
    elif args.cmd == "auth":
        cmd_auth(args)
    elif args.cmd == "corpus":
        cmd_corpus(args)
    elif args.cmd == "serve":
        cmd_serve(args)
    elif args.cmd == "ask":
        # args.query may be None if using direct mode
        if not args.query:
            # try to get query from leftover
            if unknown:
                args.query = " ".join(unknown)
        if not args.query:
            print("Provide query")
            sys.exit(1)
        cmd_ask(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
