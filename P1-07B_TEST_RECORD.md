# P1-07B Backend checkpoint and deployment candidate

- Rollback commit: `7f21ba4c2416661a74535c525a414ed34732a632`.
- Full local backend regression: 124 total, 118 PASS, 0 FAIL, 6 SKIP.
- Tests executed with `DATABASE_URL` and `MARKSIX_SYNC_TEST_DSN` absent from the child environment. Skips: disposable local PostgreSQL tests and missing external original probe.
- Full Flutter: 1111 PASS, 183 existing FAIL, 5 SKIP; exact failure-name comparison found zero new failures. Focused production-config Flutter: 207 PASS, 0 FAIL.
- Backend changes limited to the MarkSix smart-selection GET handler, pure B3 strategy module, related tests, and API/evidence documentation.
- Existing MarkSix immutable analysis snapshot and source revision are reused. No schema changes, migration, new dependencies, changes to V7/A7 formula, other lottery, Energy/VIP policy, production database, or scheduler.
- Existing workflow and enabled repository variable/secret remain unchanged. Render deployment is manual; no Render configuration changes made.
- Local raw backend log: `P1-07B-backend.log` (ignored generated log). SHA-256: `c9b617c28579e4aa2ae1ee1034f2c879b3aced4be5d6ea2e63b497b2bc59e629`.
