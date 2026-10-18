STATUS: IN_PROGRESS
# Progress

## Milestones
- [x] M0 skeleton, rule files, Makefile, verify.sh skeleton; ruff and pytest green
- [x] M1 config, schemas, Arabic normalization, audit chain
- [x] M2 RAG stores, seed data, ingest, threshold, verifier
- [x] M3 live providers, three MCP servers, toolbus
- [x] M4 six agents
- [x] M5 guardrails and supervisor + golden routing tests
- [x] M6 LangGraph core: dossier, interrupt/resume, quorum, seal, SQLite checkpoint
- [x] M7 API, dashboard, CLI
- [x] M8 Docker, compose, devcontainer, README, full verify.sh, VERIFY_REPORT.md
- [x] M9 pilot hardening: real auth (scrypt+sessions+CSRF+roles), rate limits, prod fail-fast,
      TLS-ready serve, security headers, quorum enforcement, auto-approve labelled + prod-blocked,
      corpus license/provenance gate, repo-wide ruff green
- [x] M10 corpus safety: prod fail-safe (unverified passages never cited; `RAFIQ_REQUIRE_VERIFIED`),
      scholar sign-off workflow (/dashboard/corpus, append-only data/verifications.jsonl, text-hash
      bound), tamper detection (`rafiq corpus verify-check`), tests
- [x] M11 real-text candidates: OpenITI mARkdown converter (scripts/openiti_to_candidates.py),
      Mukhtasar Khalil Hajj chapter (pages 66-76, Shamela 0011355, دار الحديث 1426هـ) imported as
      reviewable candidates, additive `corpus sync-candidates` (never clobbers sign-offs),
      startup auto-sync, Arabic sheikh guide (docs/sheikh-review-guide-ar.md), tests
- [x] M13 all-madhhab real-text candidates: converter gains --end-with section boundary,
      single-# باب/فصل subheading tags, dots-only page filler skip; five new OpenITI
      print-edition sources imported as review candidates - الهداية (hanafi 52p),
      منهاج الطالبين + مختصر المزني + الإيضاح في مناسك الحج والعمرة (shafii 12+13+402p),
      عمدة الفقه (hanbali 8p); every madhhab now has real candidates awaiting sign-off,
      verify.sh asserts it; editions/URIs/sha256 recorded per file
- [x] M12 retrieval + sign-off integrity: relaxed retrieval fallback (strict FTS AND, then
      topic-tag-anchored core matching with Arabic stopwords/particle stripping; verified filter
      always applied) so real Arabic queries reach signed pages and off-topic questions return
      "لا أعلم" instead of incidental word matches; append-only revocation
      (`rafiq corpus revoke`, verify-check flags revoked-but-verified); `corpus apply-verifications`
      restores sign-offs into rebuilt stores at startup (hash-bound, revoked never restored);
      sign_off/revoke write audit entries; tests never touch real data/verifications.jsonl;
      revoked 3 false seed attestations (no printable source) keeping 11 real Khalil sign-offs

- [x] M14 pilot disclosure (owner decision): /ask ruling/mixed responses return verbatim
      `citations` with per-passage verified flags + mandatory "not signed / not a fatwa"
      banner while the dossier stays PENDING; dev on by default, prod only via explicit
      RAFIQ_PILOT_UNVERIFIED=1 (loud startup warning), RAFIQ_REQUIRE_VERIFIED=1 always wins;
      tests + verify.sh assert the labelled disclosure

- [x] M15 pilot usefulness + batch sign-off: verified source-link resolver (OpenITI file +
      Shamela page, unknown provenance gets no invented link); /ask findings now carry
      label (موثّق/غير موثّق), display_mode (signed/matn), copy_as_fatwa_allowed, source
      citation + scan_url, with a per-source «غير موثّق - يحتاج مراجعة شيخ - المصدر: ...»
      banner on top and matn-only copy; zero-result queries file a gap dossier with the
      exact "لا أعلم" phrase; unsigned hits logged to data/analytics/unsigned_hits.jsonl
      and drive a prioritized /review queue; keyboard batch sign-off UI (/review, J/K/A/R/E)
      stores sheikh id, timestamp, edition_sha256 and reviewed_text; append-only reject /
      edit_edition never sign; verify.sh exercises the review auth/CSRF/queue contract
      without writing any attestation

- [x] M16 usefulness without waiting for sign-off (owner directive "make it
      useful for every Muslim"): fabricated dev seed summaries are filtered out
      of every served answer (only real OpenITI book text can ever be cited);
      corpus expanded from 498 to 1193 real pages by converting general fiqh
      chapters (طهارة، صلاة، زكاة، صيام، بيوع، نكاح، ...) from the same verified
      editions via scripts/gen_chapters.py (خليل 123، الهداية 235، المنهاج 115،
      المزني 129، العمدة 93 - all verified:false, page/volume null); sync_candidates
      batched (1193 rows ~2s) and the /review queue capped at 300 with the true
      pending total shown; docker-compose now defaults RAFIQ_PILOT_UNVERIFIED=1
      so a deployment serves labelled excerpts with the mandatory banner while
      RAFIQ_REQUIRE_VERIFIED=1 still forces strict "لا أعلم"; tests + verify.sh
      assert seeds never leak and general-fiqh queries are served from real books

- [x] M17 better answers + plain disclosure to the asker (owner request): one
      IDF-weighted scorer re-ranks strict FTS AND matches with tag-anchored
      candidates (rare cores نصاب/خلع outweigh صلاة/حكم; tag-core matches weigh
      most; coverage bonus), fixing questions like "الطلاق في الحيض" that used
      to surface a taharah page; excerpts shown to users are verbatim ~400-char
      windows centred on the asked terms with «…» cuts (never the whole page,
      never edited); a public RTL ask page at GET / (textContent-only, no
      inline JS, CSP) shows the banners, «غير موثّق - يحتاج مراجعة شيخ» badge,
      page hint and scan link on every excerpt so the asker always knows it is
      unsigned; tests + verify.sh assert ranking, windowing and the page

- [x] M18 no-signing book answers (owner directive "fix everything and remove
      any signing... say it is based on books and not mufti"): sign-off removed
      as a serving requirement - real book text is served in every environment
      under the mandatory «منقول من الكتب - بلا توقيع مفتٍ - المصدر: ...» banner
      and the "ليست فتوى مفتٍ معتمد" disclaimer; ruling /ask responses include
      an extractive `fatwa` object (fixed disclaimer + verbatim quotes with
      work/madhhab attribution + `based_on` source ids) - the system never
      writes fiqh wording, so there is nothing to sign; labels reworded
      (unsigned = «منقول من الكتب»; «موثّق» only for the 11 legacy signed Khalil
      pages); ask page shows the answer first with the not-a-fatwa footer;
      sign-off tooling/records kept intact but dormant (never a gate);
      RAFIQ_REQUIRE_VERIFIED / RAFIQ_PILOT_UNVERIFIED are inert;
      tests + verify.sh assert served citations, labels, fatwa disclaimer

- [x] M19 share it with Muslims worldwide (owner request): site-level Open
      Graph/Twitter meta + description + theme-color on the ask page;
      robots.txt (review/dashboard/login disallowed) and sitemap.xml with
      RAFIQ_PUBLIC_URL override for TLS proxies; PWA manifest
      (/manifest.webmanifest) + SVG icon so phones can add-to-home-screen;
      share buttons (WhatsApp/Telegram/X) with a short honest caption
      («منقول من الكتب - بلا توقيع مفتٍ، وليس فتوى») on every answer;
      docs/deploy.md runbook (VPS, compose, Caddy TLS, DNS, Search Console,
      backups, update/monitor, NC-license rules); tests + verify.sh assert
      meta/manifest/sitemap/robots/share wiring

Current step: M19 done - deploy runbook + shareability in place. Deploy target
(domain/VPS), Search Console submission and community seeding are owner actions
(see docs/deploy.md). Sign-off remains optional and dormant; «موثّق» marks only
the 11 legacy signed Khalil Hajj pages. Remaining for wider reach: more
books/chapters via gen_chapters.py, semantic retrieval, UI locales
(EN/UR/ID/TR), CC BY-NC-SA decision for commercial use.
Resume: bash scripts/verify.sh
