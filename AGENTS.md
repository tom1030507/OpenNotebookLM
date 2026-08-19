# Repository Guidelines

## Project Structure & Module Organization

`backend/app/` is the FastAPI application: HTTP routes in `routers/`, business
logic in `services/`, source importers in `adapters/`, SQLAlchemy models and
column types in `db/`, shared helpers in `utils/`. Keep routers thin — they
validate, delegate to a service, and shape the response.

`backend/scripts/` holds operational scripts, run as `python -m scripts.<name>`
from `/app`. `backend/tests/` has API and lifecycle tests, `backend/tests/unit/`
focused ones, and `backend/tests/eval/` the retrieval evaluation dataset.

`frontend/` is a Next.js app: routes in `app/`, reusable UI in `components/`,
hooks in `hooks/`, Zustand stores in `store/`, API client and session handling in
`lib/`.

Deployment lives in `deploy/` and the root `docker-compose.yml`.

Two traps in the layout:

- The **root-level `app/`** (`app/adapters/sqlite_vec.py`, `app/services/monitoring.py`,
  `app/routers/monitoring.py`) is orphaned. Nothing imports it, and
  `sqlite_vec.py` does not use sqlite-vec despite the name. Do not extend it;
  the live code is under `backend/app/`.
- **`docs/` is gitignored.** Anything you want tracked belongs in `README.md` or
  in a module docstring, not in `docs/`.

## Build, Test, and Development Commands

- `docker compose up -d --build` runs the stack: backend on `:8000`, frontend on
  `:3000`. Optional services via `--profile with-ollama` or `--profile with-cache`.
- `cd backend && pip install -r requirements.txt` then
  `python -m uvicorn app.main:app --reload` runs the API outside Docker.
- `cd frontend && npm ci && npm run dev` starts Next.js. `npm run build` for a
  production build, `npm run lint` for ESLint.
- `docker exec <backend-container> sh -lc "cd /app && python -m pytest tests -q"`
  runs the backend suite.
- `cd frontend && npm test` runs vitest.

**The backend suite needs the ML dependencies importable.** `app.services.embeddings`
imports `sentence_transformers` and `torch` at module scope, so a bare virtualenv
cannot even collect the tests — in practice the container is the place to run
them. `backend/tests/unit/test_config.py` additionally walks up to the repo root
for the `.env.example` files, so run it with the repo root available, not just
`backend/` mounted.

## Coding Style & Naming Conventions

Four-space indentation and PEP 8 for Python: `snake_case` functions and modules,
`PascalCase` classes, `UPPER_SNAKE_CASE` constants. Every public function gets a
docstring with `Args:` and `Returns:`.

Comment the *why*, not the *what*, and say what would go wrong otherwise — the
codebase leans on this, e.g. `meta_json` must be reassigned rather than mutated
because SQLAlchemy cannot see an in-place change to a JSON column, and that is
recorded where it matters. Do not leave a comment that only restates the code.

TypeScript follows the existing two-space, semicolon, single-quote style. React
components are `PascalCase.tsx`; hooks and stores read as `useMediaQuery`,
`useStore`.

Timestamps: new datetimes come from `app.utils.time.utc_now`, never
`datetime.now()` or `datetime.utcnow()`, and stored datetime columns use
`UTCDateTime` so everything the API emits carries a UTC designator. Where
ordering matters, prefer a Python-side default over `func.now()` — SQLite's
`CURRENT_TIMESTAMP` has second resolution, and tied timestamps make `order_by`
arbitrary.

## Testing Guidelines

Pytest for the backend. Name files `test_*.py`, functions `test_<behavior>`. Add
unit tests for service logic and API tests for route or persistence changes.
`backend/pytest.ini` registers the markers; `backend/tests/conftest.py` provides
the auth fixtures (`authenticated_client`, `authorize`, `auth_headers`,
`seed_user`) — use them rather than rolling your own token.

Every data-bearing route sits behind `get_current_user`, so a new route is
authenticated by default and a test that forgets a token gets `401`.

Note that some route tests replace `sys.modules["app.services.rag"]` with a stub
so importing the query router does not load the embedding model. That replacement
outlives the module that made it, so a test needing the real `app.services.rag`
must ask for it explicitly.

Retrieval changes should be measured, not asserted:
`python -m scripts.reindex --dry-run` and
`LLM_MODE=none python -m scripts.eval_retrieval --tag <name> --out <dir>` report
Recall@k, MRR and the shape of the index. Run artifacts belong under `output/`,
which is gitignored.

Frontend changes: run `npm test` and `npm run lint`, and describe the manual UI
checks you did.

## Working in Parallel

Several agents share this checkout, and the backend container bind-mounts
`backend/` — whatever branch is checked out is what runs. Work in a git worktree
under `.worktrees/<name>` rather than switching the primary tree, and never
`git stash` a tree you did not dirty.

## Commit & Pull Request Guidelines

Conventional Commit prefixes (`feat:`, `fix:`, `docs:`, `test:`), imperative
subjects, one concern per commit. A commit message should say what was wrong,
why the fix is shaped the way it is, and how the change was verified — not just
what changed.

Pull requests explain the change, list the validation commands actually run,
call out configuration or migration effects, and link relevant issues. Include
screenshots for visible UI changes. Deleting the remote branch is part of
merging, not a follow-up.

Never commit API keys, local databases, uploads, or model files. Copy
`.env.example` to `.env` for local configuration; a key present in `.env` but
absent from `backend/app/config.py` fails start-up and every test collection.
