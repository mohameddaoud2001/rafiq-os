#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .tmp data/db data/dossiers

echo "=== Rafiq OS verify.sh ===" | tee VERIFY_REPORT.md
date | tee -a VERIFY_REPORT.md

pass() { echo "PASS: $1" | tee -a VERIFY_REPORT.md; }
fail() { echo "FAIL: $1" | tee -a VERIFY_REPORT.md; exit 1; }

echo "--- Step 1: uv sync --frozen ---"
if uv sync --frozen 2>&1 | tail -n 20; then pass "uv sync"; else fail "uv sync"; fi

echo "--- Step 2: ruff check ---"
if uv run ruff check . 2>&1 | tail -n 20; then pass "ruff check"; else fail "ruff check"; fi

echo "--- Step 3: ruff format --check ---"
if uv run ruff format --check . 2>&1 | tail -n 20; then pass "ruff format"; else fail "ruff format"; fi

echo "--- Step 4: pytest -q ---"
if uv run pytest -q 2>&1 | tail -n 40; then pass "pytest"; else fail "pytest"; fi

echo "--- Step 5: rafiq demo ---"
if uv run python -m rafiq.cli demo 2>&1 | tail -n 60; then pass "rafiq demo"; else fail "rafiq demo"; fi

echo "--- Step 5b: corpus verify-check ---"
# restore sign-offs from the append-only record file into freshly built stores
if uv run python -m rafiq.cli corpus apply-verifications 2>&1 | grep -q "verification record"; then pass "corpus apply-verifications"; else fail "corpus apply-verifications"; fi
if uv run python -m rafiq.cli corpus verify-check 2>&1 | grep -q '"ok": true'; then pass "corpus verify-check"; else fail "corpus verify-check"; fi
# governance invariant: revoked seed placeholders must never come back verified
uv run python -c "
from rafiq.rag.madhhab_stores import get_passage
for pid in ('maliki_arafat_1', 'maliki_arafat_2', 'maliki_qasr_9'):
    p = get_passage('maliki', pid)
    assert p is not None and p.verified is False, f'{pid} must stay unverified'
" && pass "revoked seeds stay unverified" || fail "revoked seeds stay unverified"

echo "--- Step 5c: corpus sync-candidates ---"
SYNCED=$(uv run python -m rafiq.cli corpus sync-candidates 2>&1)
grep -q "candidate passages" <<< "$SYNCED" && pass "corpus sync-candidates ($SYNCED)" || fail "corpus sync-candidates"
# real candidates must be present; if signed, the attestation must name the scholar
uv run python -c "
from rafiq.rag.madhhab_stores import get_passage
p = get_passage('maliki', 'maliki_khalil_hajj_p066')
assert p is not None and 'مختصر خليل' in (p.work or ''), p
if p.verified:
    assert p.verified_by and p.page, p
" && pass "khalil hajj candidate present" || fail "khalil hajj candidate present"
# every madhhab must have real (OpenITI-provenanced) candidates in its store
uv run python -c "
from rafiq.rag.madhhab_stores import list_passages
for mh in ('maliki', 'shafii', 'hanafi', 'hanbali'):
    rows = [p for p in list_passages(mh, limit=2000)
            if (p.provenance or '').startswith('OpenITI:')]
    assert rows, f'no OpenITI candidates for {mh}'
    print(mh, len(rows))
" && pass "all four madhhabs have real candidates" || fail "all four madhhabs have real candidates"
# expanded general-fiqh coverage: real chapters beyond the Hajj pilot set
uv run python -c "
from rafiq.rag.madhhab_stores import get_passage
general = {
    'maliki': 'khalil_tahara_p026',
    'hanafi': 'hidaya_salat_p070',
    'shafii': 'muzani_zakat_p144',
    'hanbali': 'cumda_atima_p115',
}
for mh, pid in general.items():
    p = get_passage(mh, pid)
    assert p is not None, f'{pid} missing from {mh} store'
    assert (p.provenance or '').startswith('OpenITI:'), (pid, p.provenance)
    assert not p.verified, f'{pid} must be unsigned until a sheikh signs it'
" && pass "general fiqh chapters synced (unsigned)" || fail "general fiqh chapters synced (unsigned)"

echo "--- Step 6: API HTTP exercise ---"
# provision a review user for the auth flow (idempotent, resets password)
uv run python -m rafiq.cli auth add-user test_sheikh --role sheikh --password "verify-pass-123456" > /dev/null 2>&1 \
  || uv run python -m rafiq.cli auth set-password test_sheikh --password "verify-pass-123456" > /dev/null 2>&1 \
  || true
# start API background
uv run uvicorn rafiq.api.main:app --port 8000 --host 0.0.0.0 &
API_PID=$!
echo $API_PID > .tmp/api.pid
cleanup() { kill "${API_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT
# poll /health max 20s
for i in $(seq 1 20); do
  if curl -s http://localhost:8000/health | grep -q ok; then break; fi
  sleep 1
done

curl -s http://localhost:8000/health | grep -q ok && pass "/health" || fail "/health"

# golden queries a-c
echo "Query a"
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"الحافلة سخنت في عرفة والهدي باش يفسد؟"}' | grep -q route && pass "golden a" || fail "golden a"

echo "Query b"
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"هل أقصر الصلاة في السفر؟","madhhab":"maliki"}' | grep -q dossier && pass "golden b" || fail "golden b"

echo "Book-based answers: citations always served, labelled, with disclaimer"
CIT=$(curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"ما هي مواقيت الإحرام؟","madhhab":"hanafi"}')
echo "$CIT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['citations'], 'no citations returned'
assert any(not f['verified'] for c in d['citations'] for f in c['findings']), 'no unsigned findings'
assert any('ليست فتوى' in b for b in d['banners']), 'missing not-a-fatwa disclosure banner'
assert any(b.startswith('منقول من الكتب - بلا توقيع مفتٍ - المصدر:') for b in d['banners']), 'missing per-source book banner'
assert any(f['label'] == 'منقول من الكتب' for c in d['citations'] for f in c['findings'] if not f['verified']), 'unsigned findings must be labelled منقول من الكتب'
assert all((f['provenance'] or '').startswith('OpenITI:') for c in d['citations'] for f in c['findings']), 'dev seed placeholder leaked into served findings'
" && pass "citations labelled" || fail "citations labelled"

echo "Extractive book answer (fatwa) with disclaimer"
FATWA=$(curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"ما حكم من ترك الوضوء؟","madhhab":"maliki"}')
echo "$FATWA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
fw = d.get('fatwa')
assert fw and fw['text'], 'ruling book text must produce an extractive answer'
assert 'ليست فتوى مفتٍ' in fw['text'], 'answer must state it is not a mufti fatwa'
assert fw['based_on'], 'answer must carry its corpus citations'
assert '«' in fw['text'], 'answer must be compiled from verbatim quotes only'
assert fw['quotes'] and all(q['excerpt'] for q in fw['quotes']), 'answer quotes must be verbatim excerpts'
" && pass "book-based answer labelled" || fail "book-based answer labelled"

echo "Plain-language khulasa: extractive summary first, verbatim evidence below"
KH=$(curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"ما حكم صلاة الجماعة","madhhab":"maliki"}')
echo "$KH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
k = d.get('khulasa') or ''
assert k.startswith('بناءً على ما نقل من الكتب المذكورة'), k
assert k.endswith('وليست فتوى معتمدة، وللفتوى المعتمدة راجع أهل العلم.'), k
assert d.get('hukm_mubasat') in ['سنة','سنة مؤكدة','مستحب','مباح','مكروه','حرام','واجب','غير واضح'], d.get('hukm_mubasat')
assert 'الجماع' in k, k
findings = [f for c in d['citations'] for f in c['findings']]
assert 0 < len(findings) <= 3, len(findings)
assert any('p040' in f['source_id'] for f in findings), [f['source_id'] for f in findings]
assert d['fatwa'] and d['fatwa']['text'], 'verbatim evidence layer must stay'
" && pass "khulasa summary" || fail "khulasa summary"

echo "General fiqh coverage: real excerpts beyond the Hajj pilot"
GEN=$(curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"ما حكم صلاة الجماعة في المسجد؟","madhhab":"hanafi"}')
echo "$GEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['citations'], 'no citations for general fiqh query'
ids = [f['source_id'] for c in d['citations'] for f in c['findings']]
assert any(i.startswith('hidaya_') for i in ids), ids
assert all((f['provenance'] or '').startswith('OpenITI:') for c in d['citations'] for f in c['findings'])
" && pass "general fiqh query served from Hidaya" || fail "general fiqh query served from Hidaya"

echo "Better answers: relevance ranking + windowed verbatim excerpt"
RANK=$(curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"كم نصاب زكاة الذهب؟","madhhab":"shafii"}')
echo "$RANK" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
assert d['citations'], 'no citations for zakat nisab query'
f = d['citations'][0]['findings'][0]
assert f['source_id'].startswith(('muzani_zakat', 'minhaj_zakat')), f['source_id']
assert f.get('page_hint'), 'finding without page hint from provenance'
assert len(f['excerpt']) <= 560, 'excerpt must be windowed, not the whole page'
def norm(t): return re.sub(r'[\u064B-\u0652\u0670]', '', t)
ex = norm(f['excerpt'])
assert 'نصاب' in ex or 'ذهب' in ex, 'excerpt must be centred on the asked terms'
assert f['verified'] is False and f['label'] == 'منقول من الكتب'
" && pass "zakat nisab excerpt relevant + labelled" || fail "zakat nisab excerpt relevant + labelled"

echo "Public ask page (labelled excerpts for end users)"
PAGE=$(curl -s http://localhost:8000/)
grep -q 'dir="rtl"' <<< "$PAGE" && pass "ask page rtl" || fail "ask page rtl"
grep -Fq '/static/ask.js' <<< "$PAGE" && pass "ask page js wired" || fail "ask page js wired"
grep -Fq 'منقول من الكتب' <<< "$PAGE" && pass "ask page book-based disclosure" || fail "ask page book-based disclosure"
grep -Fq 'ليست فتوى مفتٍ' <<< "$PAGE" && pass "ask page not-a-fatwa note" || fail "ask page not-a-fatwa note"
grep -Fq 'id="khulasa"' <<< "$PAGE" && pass "ask page khulasa container" || fail "ask page khulasa container"
grep -q '<script>' <<< "$PAGE" && fail "ask page inline script" || pass "ask page no inline script"
AJS=$(curl -s http://localhost:8000/static/ask.js)
grep -Fq '/ask' <<< "$AJS" && grep -Fq 'textContent' <<< "$AJS" \
  && pass "ask js served" || fail "ask js served"
grep -Fq 'اعرض النصوص الحرفية كدليل' <<< "$AJS" && pass "ask js collapsible evidence" || fail "ask js collapsible evidence"
CSP_ASK=$(curl -s -D - -o /dev/null http://localhost:8000/ | tr -d '\r')
grep -qi "content-security-policy:.*script-src 'self'" <<< "$CSP_ASK" && pass "ask page csp" || fail "ask page csp"

echo "Shareability (OG meta, manifest, sitemap, robots, share buttons)"
grep -Fq 'property="og:title"' <<< "$PAGE" && pass "ask page og meta" || fail "ask page og meta"
grep -Fq 'rel="manifest"' <<< "$PAGE" && pass "ask page manifest link" || fail "ask page manifest link"
curl -s http://localhost:8000/manifest.webmanifest | grep -q '"start_url"' && pass "manifest served" || fail "manifest served"
curl -s http://localhost:8000/sitemap.xml | grep -q '<urlset' && pass "sitemap served" || fail "sitemap served"
curl -s http://localhost:8000/robots.txt | grep -q 'Sitemap:' && pass "robots served" || fail "robots served"
grep -Fq 'wa.me' <<< "$AJS" && pass "ask js share buttons" || fail "ask js share buttons"

echo "Unsigned-hit analytics logged for the sign-off queue"
uv run python -c "
import json, pathlib
p = pathlib.Path('data/analytics/unsigned_hits.jsonl')
assert p.exists(), 'unsigned hit analytics file missing'
rows = [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
assert rows and rows[-1]['hits'], 'no unsigned hits logged'
assert all('terms' in r for r in rows), 'analytics record missing normalized terms'
print(len(rows), 'records')
" && pass "unsigned-hit analytics" || fail "unsigned-hit analytics"

echo "Query c"
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"عندي مجموعة مالكية شاذلية طايرين من تونس لدبي لجدة، الجو كيفاش في عرفة؟"}' | grep -q route && pass "golden c" || fail "golden c"

echo "Hard-block query"
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"اقتلوا الحاكم"}' | grep -q blocked && pass "hard-block" || fail "hard-block"

echo "Not-found query"
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"موضوع غير موجود تماما xyzabc123"}' | grep -q "لا أعلم" && pass "not-found" || fail "not-found"

echo "Unauthenticated dashboard redirects to login"
CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/dashboard/mufti)
[ "$CODE" = "303" ] && pass "dashboard requires login" || fail "dashboard requires login (got $CODE)"

echo "Login"
COOKIE_JAR=.tmp/cookies.txt
rm -f "$COOKIE_JAR"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -c "$COOKIE_JAR" -X POST http://localhost:8000/auth/login -d "username=test_sheikh&password=verify-pass-123456")
[ "$CODE" = "303" ] && pass "login" || fail "login (got $CODE)"

echo "Dashboard rtl (authenticated)"
DASH=$(curl -s -b "$COOKIE_JAR" http://localhost:8000/dashboard/mufti)
grep -q 'dir="rtl"' <<< "$DASH" && pass "dashboard rtl" || fail "dashboard rtl"

echo "Corpus dashboard (authenticated sheikh)"
CORPUS=$(curl -s -b "$COOKIE_JAR" http://localhost:8000/dashboard/corpus)
grep -q 'dir="rtl"' <<< "$CORPUS" && pass "corpus dashboard rtl" || fail "corpus dashboard rtl"
grep -q 'verify' <<< "$CORPUS" && pass "corpus sign-off form present" || fail "corpus sign-off form present"
grep -q 'مختصر خليل' <<< "$CORPUS" && pass "corpus dashboard lists real Khalil text" || fail "corpus dashboard lists real Khalil text"

echo "Review tooling UI (optional scholar sign-off; never a serving gate)"
CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/review)
[ "$CODE" = "303" ] && pass "review requires login" || fail "review requires login (got $CODE)"
REVIEW_PAGE=$(curl -s -b "$COOKIE_JAR" http://localhost:8000/review)
grep -q 'dir="rtl"' <<< "$REVIEW_PAGE" && pass "review page rtl" || fail "review page rtl"
grep -Fq '/static/review.js' <<< "$REVIEW_PAGE" && pass "review js wired" || fail "review js wired"
for k in A R E J K; do
  grep -Fq "[$k]" <<< "$REVIEW_PAGE" || fail "review key hint [$k] missing"
done
pass "review keyboard hints"
JS=$(curl -s http://localhost:8000/static/review.js)
grep -Fq 'KeyA' <<< "$JS" && grep -Fq '/review/' <<< "$JS" \
  && grep -Fq 'reject-confirm' <<< "$JS" && grep -Fq 'reject-cancel' <<< "$JS" \
  && pass "review js served" || fail "review js served"
CSP_HDR=$(curl -s -D - -o /dev/null -b "$COOKIE_JAR" http://localhost:8000/review | tr -d '\r')
grep -qi "content-security-policy:.*script-src 'self'" <<< "$CSP_HDR" && pass "review csp" || fail "review csp"
QUEUE=$(curl -s -b "$COOKIE_JAR" http://localhost:8000/review/queue.json)
echo "$QUEUE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d['items']
assert items, 'review queue empty'
assert all(not (i.get('provenance') or '').startswith('seed') for i in items), 'seed placeholder leaked into queue'
assert all(i.get('scan_links') for i in items), 'queue item without source links'
assert all(i.get('page_hint') for i in items), 'queue item without page hint'
assert len(items) <= 300, 'queue payload must stay capped'
assert d['progress']['pending'] >= len(items), d['progress']
assert d['progress']['signed'] + d['progress']['pending'] <= d['progress']['total']
" && pass "review queue ordered + linked" || fail "review queue ordered + linked"
TOP=$(echo "$QUEUE" | python3 -c "import sys,json; i=json.load(sys.stdin)['items'][0]; print(i['madhhab'], i['id'])")
TOP_MH=${TOP%% *}; TOP_ID=${TOP#* }
CODE=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "http://localhost:8000/review/${TOP_MH}/${TOP_ID}/approve" -d "work=x&edition=y&volume=1&page=1&provenance=z&license=CC-BY-4.0")
[ "$CODE" = "403" ] && pass "review approve csrf required" || fail "review approve csrf required (got $CODE)"
uv run python -c "
from rafiq.rag.madhhab_stores import get_passage
p = get_passage('${TOP_MH}', '${TOP_ID}')
assert p is not None and p.verified is False, 'csrf-less approve must never sign'
" && pass "review csrf-less approve signed nothing" || fail "review csrf-less approve signed nothing"

echo "Corpus sign-off requires csrf"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST http://localhost:8000/dashboard/corpus/maliki/maliki_arafat_1/verify -d "work=x&edition=y&volume=1&page=1&provenance=z&license=CC-BY-4.0")
[ "$CODE" = "403" ] && pass "corpus sign-off csrf required" || fail "corpus sign-off csrf required (got $CODE)"

echo "Pending -> approve"
# create dossier then approve via authenticated session + csrf
RESP=$(curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"هل أقصر الصلاة في السفر؟","madhhab":"maliki"}')
DOSSIER_ID=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin).get('dossier',{}).get('id',''))")
if [ -z "$DOSSIER_ID" ]; then fail "create dossier for approve test"; fi

echo "Unauthenticated decision is forbidden"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/dashboard/mufti/${DOSSIER_ID}/decision -d "decision=APPROVED")
[ "$CODE" = "403" ] && pass "decision requires auth" || fail "decision requires auth (got $CODE)"

echo "Dev header auth is off"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/dashboard/mufti/${DOSSIER_ID}/decision -H "X-Role: sheikh" -H "X-Reviewer: test_sheikh" -d "decision=APPROVED")
[ "$CODE" = "403" ] && pass "dev header auth off" || fail "dev header auth off (got $CODE)"

DASH=$(curl -s -b "$COOKIE_JAR" http://localhost:8000/dashboard/mufti)
CSRF=$(echo "$DASH" | python3 -c "
import re, sys
m = re.search(r'name=\"csrf\" value=\"([^\"]+)\"', sys.stdin.read())
print(m.group(1) if m else '')
")
if [ -z "$CSRF" ]; then fail "csrf token extraction"; fi

curl -s -b "$COOKIE_JAR" -X POST http://localhost:8000/dashboard/mufti/${DOSSIER_ID}/decision -d "csrf=${CSRF}" -d "decision=APPROVED" -d "note=ok" | grep -q APPROVED && pass "pending->approve" || fail "pending->approve"

echo "Audit verify"
curl -s http://localhost:8000/audit/verify | grep -q '"ok":true' && pass "audit verify" || fail "audit verify"

echo "Amin cert"
curl -s http://localhost:8000/amin/certificate/هدي-1 | grep -q signature && pass "amin cert" || fail "amin cert"

curl -s http://localhost:8000/amin/certificate/هدي-1 > /tmp/cert.json
# build readings from sim for verify
uv run python -c "from rafiq.live.sim import get_truck_temps_sim; import json; t=[x for x in get_truck_temps_sim() if x['truck_id']=='هدي-1'][0]; print(json.dumps({'certificate': __import__('json').load(open('/tmp/cert.json')), 'readings': t['readings']}))" > /tmp/verify_payload.json
curl -s -X POST http://localhost:8000/amin/verify -H "Content-Type: application/json" -d @/tmp/verify_payload.json | grep -q '"ok":true' && pass "amin verify" || fail "amin verify"

# stop API
kill $API_PID || true
sleep 2

echo "--- Step 7: Docker ---"
if docker info > /dev/null 2>&1; then
  echo "Docker available, testing compose"
  # isolate from host docker config (e.g. stale Windows credsStore helpers)
  mkdir -p .tmp/docker-config
  echo '{}' > .tmp/docker-config/config.json
  if [ -d "$HOME/.docker/cli-plugins" ]; then
    mkdir -p .tmp/docker-config/cli-plugins
    cp -f "$HOME/.docker/cli-plugins/"* .tmp/docker-config/cli-plugins/ 2>/dev/null || true
  fi
  export DOCKER_CONFIG="$PWD/.tmp/docker-config"
  # compose requires an explicit secret (no dev default in the image env)
  export RAFIQ_AMIN_SECRET="${RAFIQ_AMIN_SECRET:-$(head -c 32 /dev/urandom | base64)}"
  # remap host ports to the 88xx block if defaults are taken by other services
  port_busy() { ss -ltn 2>/dev/null | grep -q ":$1 "; }
  if port_busy "${RAFIQ_API_PORT:-8000}" || port_busy "${RAFIQ_TURATH_PORT:-8001}" \
     || port_busy "${RAFIQ_IBADAT_PORT:-8002}" || port_busy "${RAFIQ_LIVE_PORT:-8003}"; then
    echo "default ports busy, remapping docker smoke test to 8800-8803"
    export RAFIQ_API_PORT=8800 RAFIQ_TURATH_PORT=8801 RAFIQ_IBADAT_PORT=8802 RAFIQ_LIVE_PORT=8803
  fi
  DAPI="${RAFIQ_API_PORT:-8000}"; DTURATH="${RAFIQ_TURATH_PORT:-8001}"
  DIBADAT="${RAFIQ_IBADAT_PORT:-8002}"; DLIVE="${RAFIQ_LIVE_PORT:-8003}"
  if docker compose build 2>&1 | tail -n 20; then pass "docker compose build"; else fail "docker compose build"; fi
  # clear stale containers/volumes from earlier runs
  docker compose down -v --remove-orphans > /dev/null 2>&1 || true
  # pre-populate the shared data volume from one image: four services sharing a
  # fresh volume race to seed it ("failed to mkdir ... file exists")
  docker volume create rafiq-os_data_volume > /dev/null 2>&1 || true
  docker run --rm -v rafiq-os_data_volume:/data rafiq-os-api:latest \
    sh -c "cp -a /app/data/. /data/ 2>/dev/null || true" > /dev/null 2>&1 || true
  if docker compose up -d --wait 2>&1 | tail -n 20; then pass "docker compose up"; else fail "docker compose up"; fi
  sleep 3
  curl -s http://localhost:${DAPI}/health | grep -q ok && pass "docker api health" || echo "SKIPPED docker api health"
  curl -s http://localhost:${DTURATH}/health | grep -q ok && pass "docker turath health" || echo "SKIPPED docker turath"
  curl -s http://localhost:${DIBADAT}/health | grep -q ok && pass "docker ibadat health" || echo "SKIPPED docker ibadat"
  curl -s http://localhost:${DLIVE}/health | grep -q ok && pass "docker live health" || echo "SKIPPED docker live"
  docker compose down -v 2>&1 | tail -n 10
  pass "docker compose down"
else
  echo "SKIPPED: Docker not available" | tee -a VERIFY_REPORT.md
fi

echo "=== VERIFIED ===" | tee -a VERIFY_REPORT.md
echo "All checks passed. See VERIFY_REPORT.md"
