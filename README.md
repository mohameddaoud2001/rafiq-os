---
title: Al-Rafiq Al-Musnid
emoji: 📖
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
---

# الرَّفِيق المُسْنِد - Rafiq OS

## ما هو هذا المشروع؟
منصة مساعدة للحج - PoC تنفيذي ببيانات محاكاة ونصوص توضيحية.

### ما هو محاكى / غير محقق
- جميع النصوص الفقهية في `data/corpus/*/seed.jsonl` ملخصات توضيحية `verified:false` بدون أرقام صفحات، مع لافتة `تنبيه: هذا النص توضيحي / غير محقق`
- الطقس/الأسطول/الشاحنات/الآبار `data_source: sim`
- التواريخ الهجرية حسابية قد تختلف يوما عن الرؤية
- شهادة الأمين إثبات تقني HMAC وليست شهادة حلال/شرعية
- "الحديث غير موجود في القاعدة" لا يعني صحته
- تنبيهات العقود اشتباه لمراجعة الهيئة الشرعية

لا توجد ادعاءات تكلفة أو توفير وقت غير مقاسة.

## التشغيل السريع

```bash
uv sync
uv run pytest -q
uv run python -m rafiq.cli demo
uv run python -m rafiq.cli serve --port 8000
curl http://localhost:8000/health
# ask page for end users (labelled excerpts, never a fatwa): http://localhost:8000/
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"query":"الحافلة سخنت في عرفة والهدي باش يفسد؟"}'
```

## Pilot auth (real, replaces DEV-ONLY headers)

```bash
# provision the first reviewer (no default accounts are ever created)
uv run python -m rafiq.cli auth add-user <username> --role sheikh
uv run python -m rafiq.cli auth list-users
# then log in at http://localhost:8000/login and review dossiers at /dashboard/mufti
```

- Passwords: scrypt hashes. Sessions: opaque tokens stored hashed, HttpOnly + SameSite=Lax cookie (Secure in prod).
- CSRF: per-session token, required on all review decisions.
- Roles: `user`, `sheikh`, `admin`; only `sheikh`/`admin` may decide dossiers. Reviewer identity is taken from the session, never from form input.
- Quorum: `RAFIQ_QUORUM` (default 1) distinct approving reviewers required; below quorum status is `AWAITING_QUORUM`.
- Rate limits: `/auth/login` 5/min/IP, `/ask` `RAFIQ_RATE_LIMIT_PER_MINUTE` (default 60), in-memory (single worker).
- `RAFIQ_DEV_AUTH=1` re-enables X-Role/X-Reviewer header auth for local automation - dev env only, refused in prod.

## Production checklist

```bash
export RAFIQ_ENV=prod
export RAFIQ_AMIN_SECRET=$(head -c 32 /dev/urandom | base64)   # 32+ chars, required
export RAFIQ_TRUSTED_HOSTS=rafiq.example.com                    # required
export RAFIQ_TLS_CERT=/etc/ssl/rafiq/fullchain.pem              # optional, enables TLS
export RAFIQ_TLS_KEY=/etc/ssl/rafiq/privkey.pem
uv run python -m rafiq.cli serve --host 0.0.0.0 --port 8443
```

Startup fails fast on unsafe prod config (default/short secret, dev header auth, missing trusted hosts).
Secure cookies + HSTS + CSP + X-Frame-Options are enforced automatically.

## Corpus provenance gate

`verified:true` passages require `work, edition, volume, page, provenance, license, verified_by, verified_at` or ingestion is rejected.

```bash
uv run python -m rafiq.cli corpus check data/corpus/maliki/seed.jsonl
```

## Book-based answers (owner decision 2026-10-18) + optional sign-off

- **No sign-off is required or checked to serve text.** Real book text is served in every environment (dev and prod alike), always labelled «منقول من الكتب - بلا توقيع مفتٍ - المصدر: ...» and preceded by the mandatory banner: «تنبيه: الجواب مبني على نقل حرفي من كتب معتمدة مذكورة معه - ليست فتوى مفتٍ معتمد ولا حكماً ملزماً، وللفتوى راجع أهل العلم». The flags `RAFIQ_REQUIRE_VERIFIED` / `RAFIQ_PILOT_UNVERIFIED` are kept inert for backward compatibility.
- **Extractive book answer (`fatwa` field):** ruling/mixed `/ask` responses include a `fatwa` object (`text`, `quotes`, `based_on`, `disclaimer`). The only text the system contributes is the fixed disclaimer `book_based_answer`; every quoted sentence is a verbatim corpus excerpt with its work/madhhab attribution. The system never composes fiqh wording, so there is nothing to sign. The dossier is still filed PENDING as an archive record.
- **Plain-language summary (`khulasa` + `hukm_mubasat`, 2026-10-18):** ruling/mixed answers start with a one-sentence summary built ONLY from a fixed template + a contiguous verbatim clause of the top-scored citation + a hukm label (سنة/سنة مؤكدة/مستحب/مباح/مكروه/حرام/واجب/غير واضح) detected inside that same span - no LLM, no generated fiqh wording; conflicting or keyword-less spans report «غير واضح» and «النص المنقول غير كافٍ لتحديد حكم واضح». Findings are trimmed to the density-peak 2-3 pages, the verbatim evidence collapses under «اعرض النصوص الحرفية كدليل», and every existing banner/label stays. The `fatwa` object is kept for compatibility.
- **Labels (2026-10-18):** every citation carries `label` (`موثّق` only for the 11 legacy signed Khalil pages / `منقول من الكتب` for everything else), `display_mode` (`signed` / `matn`), `copy_as_fatwa_allowed`, a source citation and a verified `scan_url`. Only real OpenITI book text is ever served - the fabricated dev seed summaries («ملخص توضيحي غير محقق») are filtered out of every answer.
- **Public ask page (2026-10-18):** `GET /` is a simple RTL page (no inline JS, textContent-only rendering) where any user can ask; it shows the book-based answer first, the mandatory banners, the per-source «منقول من الكتب - بلا توقيع مفتٍ» label, the page hint and the scan link in front of every excerpt, and the footer states plainly that these are quotations from books, not a signed fatwa.
- **Answer quality (2026-10-18):** retrieval re-ranks strict FTS AND matches together with tag-anchored candidates using one IDF-weighted scorer (rare cores like نصاب/خلع outweigh generic ones; curated tag-core matches weigh most), and excerpts returned to users are verbatim windows of ~400 chars centred on the asked terms, with «…» marking every cut - never the whole page, never edited text.
- **Optional sign-off tooling:** sheikhs/admins may still review passages at `/dashboard/corpus` (single) or `/review` (keyboard batch: `J/K` next/prev, `A` sign, `R` reject, `E` fix edition) against the licensed source. Each sign-off is appended to `data/verifications.jsonl` binding the scholar identity, timestamp and the sha256 of the exact reviewed text plus an `edition_sha256`; `reject` / `edit_edition` never sign. Signing now only flips the `موثّق` label - it is never a serving gate.
- **Tamper check:** if any verified text or source field changes after sign-off, it is flagged:

```bash
uv run python -m rafiq.cli corpus verify-check
```

Only real scholars can fill this in - the system provides the mechanism, not the verification.

## Real-text corpus (all four madhhabs)

`data/corpus/<madhhab>/candidates/*.jsonl` (plus `data/corpus/easy/candidates/`
for the beginner matn layer) hold real text from real digitized print editions,
one passage per print page, awaiting scholar sign-off at
`/review` (maliki is cited for the signed pages; the others await review):

| Madhhab | Work | Edition | Pages |
|---|---|---|---|
| maliki | مختصر خليل (كتاب الحج) | دار الحديث، القاهرة، ط1 1426هـ/2005م | 11 (signed) |
| maliki | مختصر خليل (الطهارة، الصلاة، الزكاة، الصيام، النكاح، البيوع، ...) | دار الحديث، القاهرة، ط1 1426هـ/2005م | 123 |
| maliki | الشرح الكبير على مختصر خليل للدردير (الطهارة … الوقف والهبة) | دار الفكر، بيروت، 4 مجلدات، تح: محمد عليش | 1302 |
| maliki | متن العشماوية (طهارة، صلاة، جمعة، جنازة، صيام - طبقة المبتدئين) | شركة الشمرلي للنشر، مصر (بلا تاريخ) | 15 |
| maliki | متن الرسالة لابن أبي زيد القيرواني (طهارة، صلاة، جنازة، صيام، زكاة، حج - طبقة المبتدئين) | بيانات الطبعة غير مذكورة في الرقمنة | 62 |
| hanafi | الهداية في شرح بداية المبتدي (كتاب الحج) | دار إحياء التراث العربي، بيروت، ط1 1425هـ/2004م | 52 |
| hanafi | الهداية (الطهارات، الصلاة، الزكاة، الصوم، النكاح، البيوع، ...) | دار إحياء التراث العربي، بيروت، ط1 1425هـ/2004م | 235 |
| shafii | منهاج الطالبين (كتاب الحج) | دار الفكر، ط1 1425هـ/2005م | 12 |
| shafii | منهاج الطالبين (الطهارة، الصلاة، الجماعة، الزكاة، البيع، الطلاق، ...) | دار الفكر، ط1 1425هـ/2005م | 115 |
| shafii | مختصر المزني (كتاب الحج) | دار الفكر، بيروت، ط2 1403هـ/1983م | 13 |
| shafii | مختصر المزني (الطهارة، الصلاة، الزكاة، البيع، الطلاق، ...) | دار الفكر، بيروت، ط2 1403هـ/1983م | 129 |
| shafii | الإيضاح في مناسك الحج والعمرة | دار البشائر الإسلامية، ط2 1414هـ/1994م | 402 |
| hanbali | عمدة الفقه (كتاب الحج والعمرة) | المكتبة العصرية، 1425هـ/2004م | 8 |
| hanbali | عمدة الفقه (الطهارة، الصلاة، الزكاة، البيوع، الفرائض، الأطعمة، ...) | المكتبة العصرية، 1425هـ/2004م | 93 |

1193 real pages total; every general-chapter page is `verified:false` with
`page`/`volume` null until a sheikh signs it.

- Source: OpenITI RELEASE (Shamela digitizations), license **CC BY-NC-SA 4.0**
  (non-commercial) - commercial use needs a differently licensed edition.
- Page references live in the `provenance` string only; the `page` field stays
  null until a scholar confirms it at sign-off (no unverified page numbers).
- Load into the stores (additive; never clobbers sign-offs):

```bash
uv run python -m rafiq.cli corpus sync-candidates
```

Regenerate all general-chapter files from the OpenITI sources (URLs in the
script docstring):

```bash
uv run python scripts/gen_chapters.py
```

Convert another chapter/book from an OpenITI mARkdown file:

```bash
uv run python scripts/openiti_to_candidates.py --input <file> \
  --output data/corpus/<madhhab>/candidates/<name>.jsonl \
  --id-prefix <madhhab>_<work>_<chapter> --section "<### | chapter title>" \
  [--end-with "<next كتاب title>"] \
  --work "..." --author "..." --edition "..." --license "..." --provenance "OpenITI:<uri> sha256:<hash>"
```

`--end-with` stops the section at that exact following header (use when the
chapter contains باب/فصل sub-headers that would otherwise end it early).

Reviewing sheikhs: see `docs/sheikh-review-guide-ar.md` (Arabic).

## Architecture
```
guard_in -> supervisor (rules) -> Send fan-out to agents -> verifier -> guard_out -> dossier -> mufti_review (interrupt) -> END
Agents: faqih, muhaddith, murabbi, logistics, weather_health, contracts
MCP: turath 8001, ibadat 8002, live 8003 (FastMCP + toolbus)
RAG: 4 separate SQLite FTS5 indexes, Arabic normalization
Live: sim deterministic, real Open-Meteo/Aladhan keyless
API: FastAPI + Jinja2+HTMX RTL dashboard, /audit/verify, /amin/*
```

## Limits
| Aspect | Limit |
|---|---|
| Fiqh text | Only from retrieved records, templates, no LLM writes |
| Scripture | References only, verbatim from provider in real mode, placeholder in sim |
| Fatwa | System never issues - creates PENDING dossier for sheikh review |
| Data | sim by default, offline works with no keys |

## Docker
```bash
export RAFIQ_AMIN_SECRET=$(head -c 32 /dev/urandom | base64)   # compose refuses to start without it
docker compose build
docker compose up -d --wait
curl http://localhost:8000/health
curl http://localhost:8001/health
docker compose down -v
```

## Deploy & share (public site)

Production runbook (VPS + docker compose + Caddy TLS + DNS + Google Search
Console + backups + license rules): **docs/deploy.md**. Shareability is built
in: Open Graph/Twitter meta on `/`, `sitemap.xml`, `robots.txt`,
`manifest.webmanifest` + icon (add-to-home-screen), and share buttons
(WhatsApp/Telegram/X) on every answer. Set `RAFIQ_PUBLIC_URL` behind TLS
proxies so sitemap/robots emit the public domain.

## English Quickstart
See above. PoC executable with simulated live data and sample passages.
