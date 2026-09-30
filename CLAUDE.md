# Project: Smart Event Registration (Flask + SQLite)

## Working rules
- Surgical edits only. No full-file rewrites, no reformatting, no renaming unrelated code.
- One phase per session. One commit per checklist item, message format: `phaseN: <item>`.
- Work on branch `hardening`. Never touch `.env`, `students.db`, or `static/uploads/*` real data.
- Before changing behavior, write a failing pytest that demonstrates the bug. Then fix. Then run the full suite.
- Ask before any destructive schema change. Migrations must be additive (ALTER TABLE ADD COLUMN, new tables).
- If an audit finding doesn't match the actual code, say so instead of applying the fix.

## Phase 0: Baseline (no behavior changes)
- [ ] Create branch, add `requirements-dev.txt` (pytest), create `tests/` with a Flask test client fixture using a temp DB and temp storage dir.
- [ ] Write characterization tests for the current happy path (upload, register, success page).
- [ ] Check git history for committed secrets (`git log -p -- .env`). Report findings; do not fix.
- [ ] Add `.gitignore` entries: `.env`, `*.db`, `storage/`, backups.

## Phase 1: Stop the bleeding
- [ ] Delete `/test` route and the `name == 'test'` branch in `index()`. Test: both return 404 / normal validation.
- [ ] Delete the `print("USING:", ...)` line. `debug` comes from env var `FLASK_DEBUG`, default False.
- [ ] Create `storage/{tmp,profiles,payments,placards,tickets}` outside `static/`. Point `static_url_path` back to `/static` and keep only CSS/JS/images that are public.
- [ ] New table `uploads(token TEXT PK, kind, stored_name, created_at, ocr_trans_id)`. `/upload` saves under a random name (`uuid4().hex`), inserts a row, returns only the token.
- [ ] Remove `profile_path` / `payment_path` as trusted form input. Form submits tokens; the server resolves them via the `uploads` table. Reject unknown tokens. Test: submitting `.env`, `../app.py`, or an absolute path as a token fails.
- [ ] Upload validation: `MAX_CONTENT_LENGTH` 5 MB, extension whitelist (png/jpg/jpeg/webp), `Image.open().verify()`, reopen and re-encode to JPEG/PNG, set `Image.MAX_IMAGE_PIXELS` (e.g. 25M). Tests: SVG, HTML renamed to .png, 6 MB file, decompression bomb all rejected.
- [ ] Serve stored files only through routes that check authorization (see Phase 2 token). Test: `/uploads/payments/...` and `/placards/...` old URLs return 404.
- [ ] Success page: replace `/success/<roll_number>` with `/success/<public_token>` (uuid4 stored on the student row). Test: roll-number URL returns 404.

## Phase 2: Integrity and trust model
- [ ] Additive migration on `students`: `public_token`, `status` (PENDING/CONFIRMED/REJECTED), `ocr_trans_id`, `trans_id_source` (ocr/manual), `payment_phash`, `email_status`, `checked_in_at`, `ticket_secret`.
- [ ] Registration flow order: validate -> single transaction INSERT (rely on UNIQUE(roll_number), UNIQUE(trans_id); catch IntegrityError -> friendly message) -> generate placard/QR -> move files -> commit. On any failure, roll back and delete generated files. Test: two threads registering same roll number -> exactly one row, one set of files.
- [ ] Server decides trans_id: if OCR value stored in `uploads.ocr_trans_id`, ignore the submitted value. If OCR failed and user typed one, set `status=PENDING`, `trans_id_source=manual`. Tighten regex to `\b\d{12}\b` for UPI UTR (keep the old regex as a fallback flagged manual).
- [ ] Duplicate screenshot detection: compute perceptual hash (`imagehash`), flag near-duplicates as PENDING. Test with a resized copy of an existing screenshot.
- [ ] Signed QR: payload = `ticket_id.HMAC_SHA256(server_secret, ticket_id)[:16]` (hex or base32). Verify with `hmac.compare_digest`.
- [ ] `/admin/*` behind login (single admin password hash from env, session cookie, CSRF, rate limit). Pages: pending approvals (shows payment image, OCR vs typed ID), approve/reject, search.
- [ ] `/admin/checkin` accepts scanned QR payload, verifies signature, requires `status=CONFIRMED`, sets `checked_in_at` atomically (`UPDATE ... WHERE checked_in_at IS NULL`), returns already-used on second scan. Tests: forged QR, unconfirmed ticket, double scan.
- [ ] Email: `ThreadPoolExecutor(max_workers=3)`, SMTP `timeout=10`, update `email_status` (sent/failed) and add an admin "resend" button. Also send the abuse alert in the background.

## Phase 3: Production hardening
- [ ] `SQLite`: `PRAGMA journal_mode=WAL`, `busy_timeout`.
- [ ] Flask-Limiter with a persistent/shared backend on `/upload`, `/`, admin login. Remove custom `ABUSE_TRACKER` once replaced.
- [ ] `ProxyFix` with configurable proxy count from env. Document the deployment shape (Nginx/Cloudflare or none).
- [ ] Security headers: `X-Content-Type-Options: nosniff`, `Content-Security-Policy`, `Referrer-Policy`; served files get `Content-Disposition` and correct mimetype.
- [ ] `TESSERACT_CMD` from env, fallback `shutil.which('tesseract')`, clear startup error if missing.
- [ ] Run under Waitress (Windows) or Gunicorn (Linux). Add `run.md` with the exact command.
- [ ] `retrieve.py`: write backups outside the repo and web root, encrypt or at least restrict permissions; add a `--purge-after-days` retention option. It must not be importable by the web app.

## Definition of done
- All tests pass; `pytest -q` runs in under a minute.
- Manual attacker checklist (README section): path tampering, enumerating old URLs, oversized/SVG upload, forged QR, replayed QR, concurrent duplicate registration, `/test`, debug console.
- README updated: remove the claim that the read-only field secures the transaction ID; document the PENDING flow and the check-in flow.
