# OpenNotebookLM

<div align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="License">
  <img src="https://img.shields.io/badge/docker-ready-blue.svg" alt="Docker">
</div>

<br>

> A self-hosted alternative to Google's NotebookLM: import your documents, ask
> questions about them, and get answers with citations back to the source.

Everything runs on your machine. Documents, embeddings, and conversations live
in a local SQLite database; the only thing that leaves your machine is the
prompt sent to whichever LLM provider you configure — and you can point that at
a local model too.

## What works today

| Capability | Status |
|---|---|
| Import PDFs, web pages, YouTube transcripts | ✅ |
| Chunking, embedding, semantic retrieval with citations | ✅ |
| Multi-turn conversations, persisted per project | ✅ |
| Generated answers from Claude, OpenAI, or a local model | ✅ **once you configure a provider** — see [Configuring the LLM](#configuring-the-llm) |
| Register / sign in; the API refuses every request without a bearer token | ✅ |
| Export a conversation, a project, or a project summary | ✅ |
| Studio: audio summary (browser speech), Markdown report | ✅ |
| Studio: video summary, mind map | ❌ not implemented — marked as unavailable in the UI |
| Per-user isolation of projects | ❌ accounts exist, but every signed-in user sees every project |

**Without an LLM provider configured, question answering still returns a
response — but an extractive one**: the first few sentences of the best-matching
chunks, prefixed "Based on the provided documents". The API labels those
responses `model_used: "fallback"`. That is the single most important thing to
know before evaluating answer quality.

## Quick start

### Prerequisites

| Component | Version | Required |
|-----------|---------|----------|
| Docker | 20.10+ | ✅ for the Docker path |
| Python | 3.10+ | ✅ for local development |
| Node.js | 18+ | ✅ for local development |

### Docker

```bash
git clone https://github.com/tom1030507/OpenNotebookLM.git
cd OpenNotebookLM

cp .env.example .env        # then edit it — see Configuration below
docker compose up -d --build
docker compose ps
```

- Frontend: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/healthz

The root `docker-compose.yml` also defines optional `ollama` and `redis`
services; start them with `--profile with-ollama` / `--profile with-cache`.

### Local development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

```bash
# Frontend (in a second terminal)
cd frontend
npm ci
npm run dev
```

The database is created automatically at `backend/data/opennotebook.db` on
first run. The first request also downloads the embedding model (see below), so
expect a slow cold start.

### Signing in

**Register** on `/login` creates an account through `POST /api/auth/register`;
passwords are hashed with bcrypt. Signing in exchanges those credentials for a
bearer token at `POST /api/auth/token`. There is no way in that skips the
backend — a session it never issued is refused by every API route.

The API is the boundary. Every route below except the health checks and the two
credential endpoints is mounted behind `get_current_user`, so a request with no
`Authorization` header, or with a token the backend cannot validate, gets `401`
either way — the two are deliberately indistinguishable. The frontend attaches
the token to every request it makes, and on a `401` it discards the local
session and returns to `/login` rather than leaving you on a workspace where
each panel fails on its own.

Sign-in also mirrors the token into an `auth_token` cookie, because the Next.js
middleware that guards `/` runs on the server and cannot read `localStorage`.
That middleware only checks the cookie is *present*: it is a navigation
convenience so you land on `/login` instead of an empty workspace, and it is not
what protects your data. The API is.

Signed-in users all see the same projects — see the last row of
[What works today](#what-works-today).

## Configuring the LLM

Question answering is only as good as the model behind it. Set **one** of these
in `.env`; `LLM_MODE=auto` (the default) picks the first one configured, in the
order Claude → OpenAI → local server.

### Claude (default when a key is present)

```bash
CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-opus-5      # default
CLAUDE_EFFORT=low               # low | medium | high | xhigh | max
```

Two details worth knowing:

- **Sampling parameters are not sent.** Current Claude models reject
  `temperature`, so the `temperature` argument in a query request is ignored on
  this path. Control depth with `CLAUDE_EFFORT` instead. Answering from
  retrieved chunks is not reasoning-heavy, which is why the default is `low`.
- **Thinking is on by default and shares the output budget with the answer.**
  A request's `max_tokens` is therefore raised to at least
  `CLAUDE_MIN_MAX_TOKENS` (2048) so the reply isn't truncated by the thinking.

### OpenAI

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6            # default
```

This path is written against the chat-completions API and sends `max_tokens`.
It has not been exercised against a live key here, and newer OpenAI models have
been migrating that parameter to `max_completion_tokens` — if a request is
rejected for the parameter name, that is the thing to change in
`OpenAICompatibleProvider.generate`.

### A local model (Ollama, llama.cpp, vLLM)

Any server that speaks the OpenAI chat-completions API works:

```bash
LLM_MODE=local
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2           # must match a model you have pulled
```

```bash
ollama serve
ollama pull llama3.2
```

### Checking which provider is actually in use

`GET /healthz` reports the configured provider and model:

```json
{ "config": { "llm_mode": "auto", "llm_provider": "claude", "llm_model": "claude-opus-5" } }
```

That says *configured*, not *reachable* — no network call is made from a health
check. To tell whether an answer was generated or extracted, read `model_used`
on the `/api/query` response: anything other than `"fallback"` is a real
generated answer. A provider that fails at call time logs the underlying error
at `ERROR` level and falls back for that request.

## Embeddings

Retrieval quality depends on the embedding model, configured by
`EMB_MODEL_NAME`. The dimension is read from the model at load time, so
`EMB_DIMENSION` self-corrects and does not need to match.

The default is `BAAI/bge-m3`: multilingual (the previous default,
`bge-small-en-v1.5`, was English-only) and usable without query/passage
prefixes. Budget for the first run — sentence-transformers fetches the whole
model repository, about **4.6 GB** for bge-m3, and caches it under
`$HOME/.cache/torch`. Docker Compose redirects that cache to the mounted
`./models` volume so recreating the container doesn't re-download it; if you run
the backend outside Docker, set `SENTENCE_TRANSFORMERS_HOME` somewhere
persistent.

`intfloat/multilingual-e5-base` (768 dimensions, roughly a quarter of the
download) also loads against this dependency set and is a reasonable lighter
choice — but the e5 family expects `query: ` and `passage: ` prefixes on its
inputs, and `services/embeddings.py` does not add them. Without that change it
works but retrieves worse, silently, which is why it is not the default.

Stored vectors are only comparable to vectors produced by the same model.
**Changing `EMB_MODEL_NAME` invalidates every embedding already in the
database** — retrieval will fail on a dimension mismatch until documents are
re-indexed. To switch models:

1. Stop the backend.
2. Set the new `EMB_MODEL_NAME` in `.env`.
3. Delete the existing embeddings (they are regenerated on re-ingest):
   ```bash
   sqlite3 backend/data/opennotebook.db "DELETE FROM embeddings;"
   ```
4. Restart, then re-upload the affected documents.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz`, `/ready` | Liveness and readiness |
| `POST` | `/api/auth/register`, `/api/auth/token` | Create an account, exchange credentials for a token |
| `GET` | `/api/auth/me` | The account behind a bearer token |
| `GET`/`POST` | `/api/projects` | List and create projects |
| `GET`/`PUT`/`DELETE` | `/api/projects/{id}` | Read, rename, delete a project |
| `GET` | `/api/projects/{id}/documents` | Documents in a project |
| `POST` | `/api/projects/{id}/upload` | Upload a file (PDF, txt, md) |
| `POST` | `/api/projects/{id}/upload-url` | Import a web page |
| `POST` | `/api/projects/{id}/upload-youtube` | Import a YouTube transcript |
| `GET` | `/api/docs/{id}`, `/api/docs/{id}/status` | Document detail and ingest status |
| `GET` | `/api/docs/{id}/file` | The stored file, served inline (PDF preview) |
| `POST` | `/api/query` | Ask a question; returns `answer`, `sources`, `chunks_used`, `model_used` |
| `GET`/`POST` | `/api/projects/{id}/conversations` | List and create conversations |
| `GET`/`PUT`/`DELETE` | `/api/conversations/{id}` | Read, rename, delete a conversation |
| `GET` | `/api/export/conversation/{id}` | Export one conversation (markdown, json, txt) |
| `GET` | `/api/export/project/{id}` | Export a project (markdown, json) |
| `GET` | `/api/export/project/{id}/summary` | Project summary — powers Studio's report and audio |
| `GET`/`DELETE` | `/api/cache/*` | Cache stats, health, clear, invalidate, warm up |

Every path except `/healthz`, `/ready` and the two `/api/auth` credential
endpoints requires `Authorization: Bearer <token>` and answers `401` without
one. `/api/docs/{id}/file` is no exception, which is why the preview pane
fetches a file through the API client and renders the bytes, rather than
pointing an `<iframe>` at the route.

Interactive docs at `/docs`, ReDoc at `/redoc`.

Every datetime the API returns carries a UTC designator (`+00:00`), so clients
in any timezone render timestamps correctly.

## Project layout

```
OpenNotebookLM/
├── backend/
│   ├── app/
│   │   ├── routers/          # auth, projects, ingest, query, export, files, health
│   │   ├── services/         # rag, embeddings, llm, chunking, documents,
│   │   │                     # export, projects, auth, cache, document_files
│   │   ├── adapters/         # pdf, url, youtube
│   │   ├── db/               # SQLAlchemy models, session, UTCDateTime column type
│   │   ├── utils/            # logging, time
│   │   ├── api/cache.py      # cache management endpoints
│   │   ├── config.py         # settings (env-driven)
│   │   └── main.py           # app factory and router registration
│   └── tests/                # pytest; tests/unit/ holds the focused ones
├── frontend/                 # Next.js App Router
│   ├── app/                  # routes: / and /login
│   ├── components/           # workspace UI (layout/, chat/, dialogs)
│   ├── hooks/                # useMediaQuery, useDialogFocus, useDocumentStatusWatch
│   ├── lib/                  # api client, theme, session, speech, datetime
│   ├── store/                # Zustand store
│   └── middleware.ts         # session gate for /
├── deploy/                   # Dockerfile.api, docker-compose.yml, .env.example
└── docker-compose.yml        # backend, frontend, optional ollama and redis
```

## Configuration

Environment variables, with the defaults from `backend/app/config.py`:

| Variable | Description | Default |
|----------|-------------|---------|
| **LLM** | | |
| `LLM_MODE` | Provider selection: `auto`, `claude`, `openai`, `local`, `none` | `auto` |
| `CLAUDE_API_KEY` | Anthropic API key | – |
| `CLAUDE_MODEL` | Claude model id | `claude-opus-5` |
| `CLAUDE_EFFORT` | Reasoning depth: `low`…`max` | `low` |
| `CLAUDE_MIN_MAX_TOKENS` | Floor for a request's output budget | `2048` |
| `OPENAI_API_KEY` | OpenAI API key | – |
| `OPENAI_MODEL` | OpenAI model id | `gpt-5.6` |
| `OLLAMA_BASE_URL` | Local OpenAI-compatible endpoint | `http://localhost:11434/v1` |
| `OLLAMA_MODEL` | Local model name | `llama3.2` |
| **Embedding** | | |
| `EMB_MODEL_NAME` | sentence-transformers model | `BAAI/bge-m3` |
| `EMB_DIMENSION` | Vector dimension (auto-corrected from the model) | `1024` |
| `EMB_BACKEND` | Vector store backend | `sqlitevec` |
| **Retrieval & chunking** | | |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Chunking window | `512` / `50` |
| `RETRIEVAL_TOP_K` | Chunks retrieved per question | `5` |
| `RERANK_ENABLED` | Re-rank retrieved chunks | `true` |
| **Database** | | |
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./data/opennotebook.db` |
| **Auth** | | |
| `JWT_SECRET_KEY` | Token signing key — **required** unless `APP_ENV=development` | – |
| `JWT_ALGORITHM` | Signing algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime | `720` |
| **Uploads** | | |
| `MAX_FILE_SIZE_MB` | Upload limit | `50` |
| `ALLOWED_FILE_TYPES` | Accepted extensions | `pdf,txt,md` |

Without `JWT_SECRET_KEY`, a development server signs tokens with a key
generated per process — sessions do not survive a restart. Any non-development
deployment refuses to start without it.

See [`.env.example`](./.env.example) and
[`deploy/.env.example`](./deploy/.env.example).

## Testing

```bash
# Backend — from the repo root, against a running container
docker exec <backend-container> sh -lc "cd /app && python -m pytest tests -q"

# or locally, if the ML dependencies are installed
cd backend && pytest -q

# Frontend
cd frontend && npm test          # vitest
cd frontend && npm run lint
```

Both suites are green on `master`. Note that the backend suite needs the ML
dependencies (`sentence-transformers` and its transformers pin) importable — a
bare virtualenv without them cannot collect the tests.

## Known limitations

Stated plainly, because several of these look like features until you hit them:

- **The API is not behind authentication.** Accounts and the login flow work,
  but every `/api/*` endpoint accepts unauthenticated requests, and projects
  have no owner — anyone signed in sees everything.
- **Caching is in-memory.** `app/services/cache.py` will use Redis if a client
  and a `redis_url` setting are present; neither ships, so the cache is
  per-process and resets on restart.
- **YouTube import depends on YouTube.** The pinned
  `youtube-transcript-api==0.6.1` scrapes the watch page, and YouTube rate-limits
  it — imports can fail with an XML parse error on a blocked response even
  though the code is correct.
- **Studio's video summary and mind map are not implemented.** They are visible
  but disabled, and generating either needs backend work.
- **No WebSockets.** Ingest progress is polled, not pushed.

## License

MIT.
