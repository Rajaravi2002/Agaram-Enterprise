# Agaram Finance Stage 5 Test and Remediation Report

**Test date:** 2026-09-15

## Results

| Check | Result |
|---|---:|
| Existing and new regression tests | 18/18 passed |
| Python compilation | Passed |
| Module imports | 29/29 passed |
| Unauthenticated route smoke checks | 41 routes checked; no 5xx responses |
| Core workflow integration | Loan creation, payment, top-up, Excel export/import, login, and authenticated pages passed |
| Dependency audit | No known vulnerabilities found |

## Bugs fixed

1. **PostgreSQL-incompatible Excel upsert:** Excel import used SQLite-only `INSERT OR REPLACE`. It now uses portable `UPDATE`/`INSERT` logic and preserves an existing loan row instead of deleting and recreating it.
2. **Invalid Excel rows accepted:** Rows with missing customer names, missing/invalid dates, non-positive loan amounts, or non-positive tenure are now rejected and reported instead of creating invalid records.
3. **Unsafe restore behavior:** Restore now validates the JSON structure and table columns before any destructive operation, uses a transaction savepoint, and rejects unknown columns. A malformed backup therefore cannot partially replace the database.
4. **Outdated/vulnerable dependencies:** Flask, Werkzeug, psycopg, `python-dotenv`, pandas, and Click pins were updated to versions compatible with the tested environment and free of findings from `pip-audit`.

## Static scan notes

Bandit reported no high-severity issues. Remaining medium/low-confidence findings concern controlled internal table-name SQL in backup/migration utilities, broad exception handling, and non-cryptographic randomness used only by sample-data generation. These are not runtime failures in the tested application workflows.

Generated backup and report data from the uploaded archive was excluded from the corrected ZIP so the deliverable does not redistribute potentially sensitive operational data.
