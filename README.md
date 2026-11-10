# ContinuityOS

ContinuityOS helps project teams preserve authorized project knowledge and
prepare evidence-backed, role-scoped handovers. Important claims are intended
to remain traceable to their source evidence; human review is required before
sharing.

## Current implementation

- Email/password accounts, signed HTTP-only sessions, project membership, and
  project-scoped owner, reviewer, member, and incoming-lead roles.
- Authorized TXT, Markdown, CSV, PDF, and DOCX uploads, extracted line-addressed
  spans, SHA-256 source digests, and source access audit events.
- Source reconstruction works without external services using the deterministic
  rule-based fallback. When OpenRouter is configured, it proposes categorized
  candidates from role-visible, not-yet-reconstructed source lines.
- Provider candidates are saved only when their verbatim quote and line number
  match an accessible source span. Proposed claims still require human review.
- Claim ledger, exact normalized-quote validation, source/evidence access
  filtering, and keyword retrieval with ACL predicates before search.
- Claim accept/edit/reject/unresolved review actions, recorded edit history,
  explicit conflicts and reviewer resolutions, missing-evidence questions, and
  a deterministic, explicitly draft-only readiness score.
- Immutable approved handover snapshots, recipient-clearance rendering with
  content-free redaction counts, incoming-lead acknowledgements, and an audit
  log.
- A clearly synthetic AURORA fixture with citations, a deliberate technical
  conflict, a restricted test source, and a missing-evidence item.
- Responsive vanilla HTML, CSS, and JavaScript interface served by FastAPI.
- Three locally switchable workspace themes: clean light, dark operations, and
  editorial/document-first. The selection is stored in the browser only.

The synthetic AURORA corpus is intentionally smaller than the proposed 12
documents / 47 commits / one chat export. Do not treat those target corpus
counts or the proposal's extraction/performance targets as achieved.

### Known limitations

- OpenRouter extraction is optional. Its categories map into the existing claim
  ledger (for example, technical debt to risk and handover notes to tasks);
  it does not create a separate claims system.
- Citation validation confirms quote containment and claim text presence. It
  does not establish semantic entailment, independent provenance, or
  corroboration. OpenRouter candidates are not proof that the cited text
  semantically supports a claim. Corroboration is therefore not awarded.
- Search is ACL-filtered keyword search, not BM25/vector hybrid retrieval.
- PDF spans use extracted line numbers rather than preserving page coordinates.
- OpenRouter extraction is optional and sends only the current user's
  role-visible source-line text to OpenRouter when reconstruction is run.
  Source IDs and filenames are not sent. Each run is limited to 60,000
  characters. Only exact, single-line quotes are saved; model-reported conflict
  flags are suggestions for human review, not persisted conflict resolutions.
  Provider errors are explicit and do not silently fall back.
- GitHub/Drive connectors, background jobs, exports/share links, and
  acknowledgment notifications are not configured.
- GitHub Actions and deployment configuration are not included.
- The app is a functional development MVP, not a production-ready identity or
  compliance system. There is no email verification, password recovery,
  rate-limiting, or independent external security assessment.

## Run locally

Requires Python 3.12 or 3.13.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

The default database is a local SQLite file. To use PostgreSQL, set
`DATABASE_URL` in `.env` to a PostgreSQL connection URL and start that database
before applying migrations. Set `SECRET_KEY` to a private, random value of at
least 32 characters and keep the same key across server workers. The provided
placeholder is for local setup only; replace it in `.env` before running the
app. When deploying behind HTTPS, set `SESSION_COOKIE_SECURE=true`; do not
commit `.env` or real secrets.

To enable AI-assisted claim extraction, add `OPENROUTER_API_KEY` to `.env` and
optionally set `OPENROUTER_MODEL` (defaults to `openai/gpt-4o-mini`). Restart
the server after changing `.env`. The key stays on the server. Running
**Reconstruct visible sources** sends the current user's authorized,
not-yet-reconstructed source-line text to OpenRouter. Review provider privacy
and retention terms before sending sensitive project text. Remove or blank the
key to use deterministic reconstruction without external AI calls.

Visit `http://127.0.0.1:8000` for the application and
`http://127.0.0.1:8000/docs` for the interactive API documentation.
After signing in, use the **Theme** selector in the top bar to switch among
Clean light, Dark operations, and Editorial themes.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The integration tests use an isolated in-memory SQLite database. The health
check uses the configured local database; apply Alembic migrations before
starting the server.

### Browser end-to-end test

Requires Node.js 18 or later. Install the JavaScript test runner and its
Chromium browser once:

```powershell
npm.cmd install
npx.cmd playwright install chromium
```

Run the browser workflow:

```powershell
npm.cmd run test:e2e
```

The browser test starts a temporary FastAPI server with a separately migrated
SQLite database, creates owner and incoming-lead accounts, uploads project and
restricted sources, reconstructs and reviews cited claims, resolves a
conflict, approves a handover, checks recipient redaction, and records the
incoming lead's acknowledgement. It does not use or modify the configured
development database.

## Architecture

- `backend/app/routes/` contains endpoint groups for account, project,
  ingestion, reconstruction, review, and handover workflows.
- `backend/app/security.py` validates signed sessions, project memberships,
  role requirements, and role-based sensitivity clearance.
- `backend/app/services.py` contains citation checks and shared
  authorization-aware claim queries.
- `backend/app/openrouter.py` contains the optional structured OpenRouter
  client and candidate validation; the API key remains server-side.
- `backend/app/static/` contains the responsive browser interface.
- `backend/migrations/` contains versioned Alembic schema changes.
- `tests/` contains parser, model, API integration/security, and browser
  end-to-end tests.

The detailed product source of truth is the supplied
`CONTINUITYOS_AGENT_INSTRUCTIONS.md`. It is not currently present in this
workspace; retain and copy that document to the repository root before
relying on links to it from the project documentation.
