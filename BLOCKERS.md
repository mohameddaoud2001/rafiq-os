# BLOCKERS.md

## Open before real Muslim users (pilot hardening + corpus safety + real text done; scholars are the gate)

- Scholarly validity (the gate): the review queue now holds real print-edition text for all
  four madhhabs (~498 passages: Khalil/Hidaya/Minhaj/Muzani/Idah/Cumdat), but only the 11
  Khalil pages are signed off (sheikh_omar). Muftis per madhhab must review at
  /dashboard/corpus (guide: docs/sheikh-review-guide-ar.md). Since the 2026-10-17 pilot
  disclosure, users do see the verbatim excerpts (each flagged `verified: false` + the
  «ليست فتوى» banner) alongside the pending dossier; strict prod fail-safe ("لا أعلم")
  applies unless the owner sets RAFIQ_PILOT_UNVERIFIED=1, and RAFIQ_REQUIRE_VERIFIED=1
  always wins. The signed `verified: true` label still requires real sign-off - this is
  the trust model, not a bug.
- OpenITI license resolved: CC BY-NC-SA 4.0 (non-commercial). Pilot OK with attribution;
  commercial deployment needs a differently licensed edition - decision for the project owner.
- Real Quran.com/Tanzil text fetch needs network - sim placeholder used.
- Infrastructure: still SQLite (FTS5 + checkpoints + auth); migrate to Postgres/pgvector per
  DECISIONS before multi-instance deployment.
- Rate limiting is per-process in-memory; needs shared store with multiple workers.
- No external IdP/2FA yet - pilot accounts are CLI-provisioned local users.
- No monitoring/backups/alerting configured.

## Closed by retrieval + sign-off integrity (M12)

- Real Arabic queries now reach signed passages: strict FTS5 AND first, then a topic-tag-anchored
  core fallback (Arabic stopwords + particle stripping; text matches only rank). verified_only
  applies to all strategies; off-topic questions return "لا أعلم" instead of incidental matches.
- Revocation is append-only (`rafiq corpus revoke`); verify-check flags revoked-but-verified stores.
- `corpus apply-verifications` (CLI + API startup) restores sign-offs into rebuilt stores from the
  append-only record file (hash-bound; revoked never restored).
- sign_off/revoke write audit chain entries; tests can no longer wipe real data/verifications.jsonl.
- 3 false seed attestations revoked; 11 real Khalil Hajj pages (66-76) attested by sheikh_omar and
  cited under RAFIQ_REQUIRE_VERIFIED=1.

## Closed by real-text candidates (M11)

- OpenITI mARkdown -> candidate converter (scripts/openiti_to_candidates.py) with tests.
- Mukhtasar Khalil Hajj chapter (Shamela 0011355, دار الحديث، تحقيق أحمد جاد) imported as
  11 page-level candidates; page hints kept in provenance, page field null until sign-off.
- `rafiq corpus sync-candidates` additive loading; API startup auto-syncs; sign-offs never clobbered.

## Closed by corpus safety (M10)

- Prod (or RAFIQ_REQUIRE_VERIFIED=1) never cites unverified passages: faqih returns "لا أعلم".
- Scholar sign-off workflow: /dashboard/corpus (sheikh/admin + CSRF), append-only
  data/verifications.jsonl binding scholar identity to sha256 of reviewed text + source fields.
- Tamper detection: `rafiq corpus verify-check` flags verified passages whose text/fields
  changed after sign-off (also run in verify.sh).

## Closed by pilot hardening (M9)

- DEV-ONLY header auth replaced by real sessions + CSRF + roles (headers only via RAFIQ_DEV_AUTH in dev).
- Default HMAC secret now refused in prod; TLS-ready serve command; security headers enforced.
