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
| Studio: mind map of a project's sources and their topics | ✅ **topics are named by the LLM when one is configured**, otherwise taken from document structure |
| Studio: video summary | ✅ **a narrated slideshow played in the browser**, not a video file; narration written by the LLM when one is configured |
| Per-user isolation: your projects, documents and conversations are yours alone | ✅ |

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

### Whose data is whose

Projects and documents carry an owner, and every route that reads or writes them
checks it. Conversations follow their project; retrieval is confined to the
caller's own documents even when no project is selected, so a question cannot
reach another account's chunks.

A resource that belongs to someone else answers `404`, exactly like one that does
not exist. That is deliberate: `403` would confirm the id is real, which turns id
enumeration into a way of discovering what other accounts have.

**Rows created before ownership existed have no owner, and the API treats them as
belonging to nobody rather than to everybody.** They stay in the database and
stop appearing in the UI until they are claimed:

```bash
docker exec <backend-container> sh -lc   "cd /app && python -m scripts.assign_owner --username <account> --dry-run"
```

Drop `--dry-run` to write. Only null owners are touched, so it is safe to re-run
and can never move a row between accounts. The `user_id` columns themselves are
added to an existing database on start-up by `db.database.ensure_added_columns`,
since `create_all` only ever creates missing *tables*.

Not scoped per account: `/api/cache/stats`, `/api/cache/health` and
`/api/cache/clear` act on one shared process-wide cache. They need a token but
not an owner, and clearing it affects everyone.

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

### OpenAI, or any provider that speaks its API

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6            # default
OPENAI_BASE_URL=                # empty for OpenAI itself
```

`OPENAI_BASE_URL` redirects this path at any service implementing the same
chat-completions API, which is most of them. Give it the provider's `/v1`
endpoint and an `OPENAI_MODEL` that provider actually serves:

| Provider | `OPENAI_BASE_URL` |
|----------|-------------------|
| Groq | `https://api.groq.com/openai/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| xAI | `https://api.x.ai/v1` |
| Mistral | `https://api.mistral.ai/v1` |

Model ids differ per provider and change often — list them rather than
guessing, e.g. `curl -s $OPENAI_BASE_URL/models -H "Authorization: Bearer $KEY"`.

#### Reasoning models return their thinking as the answer

Groq's reasoning models (`qwen/qwen3.6-27b`, MiniMax M2.7) put their entire chain
of thought in `message.content`, wrapped in `<think>` tags — so it arrives as the
answer and the UI renders it. `OPENAI_REASONING_FORMAT=hidden` suppresses it
(`parsed` moves it to a separate field, `raw` is the provider default).

Measured on one retrieval question at the 512-token budget `services/rag.py`
sends:

| `OPENAI_MODEL` | `<think>` in the answer | output tokens used |
|----------------|-------------------------|--------------------|
| `qwen/qwen3.6-27b` | yes | 373 / 512 |
| `qwen/qwen3.6-27b` + `hidden` | no | 332 / 512 |
| `llama-3.3-70b-versatile` | no | 25 / 512 |

`hidden` cleans the output but the reasoning is still generated, still billed,
and still counted against `max_tokens` — and because it comes first, hitting the
ceiling truncates the answer rather than the thinking. That is what
`OPENAI_MIN_MAX_TOKENS` (default 2048) exists to prevent: at the 512
`services/rag.py` sends, turns that reasoned for the whole budget came back cut
mid-sentence, or empty. Raise it further if answers still arrive truncated — a
five-turn conversation measured here peaked at 1915 output tokens. A
non-reasoning model is the cheaper way to a clean answer.

`OPENAI_REASONING_FORMAT` itself is a Groq extension — it is sent only when set,
because OpenAI and the others reject parameters they do not recognise.

`openai/gpt-oss-*` models are unaffected: they return reasoning in a separate
field already.

This path sends `max_tokens`. It has not been exercised against a live key here,
and newer OpenAI models have been migrating that parameter to
`max_completion_tokens` — if a request is rejected for the parameter name, that
is the thing to change in `OpenAICompatibleProvider.generate`.

Note the `openai` SDK also reads an `OPENAI_BASE_URL` from the process
environment on its own, so an exported value takes effect even when this setting
is unset. Set it explicitly if you mean to reach OpenAI.

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

The default is `intfloat/multilingual-e5-base` (768 dimensions). The previous
default, `bge-small-en-v1.5`, was English-only.

The e5 family is trained with asymmetric prefixes — indexed text as
`passage: …`, a search string as `query: …`. `services/embeddings.py` applies
them automatically for models whose name contains `e5`, and adds nothing for
models that must not have them. If you switch to a non-e5 model, no change is
needed.

**Memory is the binding constraint, not download size.** Measured in this
project's container, with the app's own imports already loaded (0.61 GB):

| Model | Peak RSS | Dimensions | Download |
|---|---|---|---|
| `intfloat/multilingual-e5-base` | 2.69 GB | 768 | ~1.1 GB |
| `BAAI/bge-m3` | 4.85 GB | 1024 | ~4.6 GB |

bge-m3 is the stronger multilingual model and needs no prefixes, but on an 8 GB
host it OOM-killed a full re-index. Use it only where the memory headroom is
real.

sentence-transformers caches models under `$HOME/.cache/torch`. Docker Compose
redirects that to the mounted `./models` volume so recreating the container does
not re-download; outside Docker, set `SENTENCE_TRANSFORMERS_HOME` somewhere
persistent.

Stored vectors are only comparable to vectors produced by the same model.
**Changing `EMB_MODEL_NAME` invalidates every embedding already in the
database** — retrieval will fail on a dimension mismatch until documents are
re-indexed. To switch models:

1. Stop the backend.
2. Set the new `EMB_MODEL_NAME` in `.env`.
3. Restart, then rebuild the index in place:
   ```bash
   docker exec <backend-container> sh -lc "cd /app && python -m scripts.reindex"
   ```

`scripts/reindex.py` re-extracts, re-chunks and re-embeds every document already
in the database, keeping document ids — so projects, conversations and citations
survive, which deleting the embeddings and re-uploading by hand does not. Back up
`backend/data/opennotebook.db` first and use `--dry-run` to see what it would
touch; `--source-type` and `--ids` narrow it. A source it cannot re-read — a URL
that now 404s, a PDF whose upload is gone — is marked `error` and keeps its old
chunks, so it stops being retrievable until it is re-added.

The same script is how a change to extraction or chunking reaches documents that
are already indexed. Stored chunks were produced by the old code and do not
improve on their own.

## Retrieval

Retrieval is hybrid: a dense vector search and a BM25 keyword search run over the
same scope, and their two ranked lists are fused. Both halves are needed.

The dense half alone is weak here in a way that is easy to miss. Measured on this
project's evaluation corpus, `multilingual-e5-base` returns cosine similarities
between roughly 0.67 and 0.71 for relevant and irrelevant chunks alike — a spread
of about 0.01 between rank 1 and rank 10. Any similarity threshold inside that
band is arbitrary, which is why `RETRIEVAL_MIN_SCORE` defaults to 0 and why an
exact term match carries so much weight.

The BM25 half supplies that. Its tokenizer emits Latin words and **CJK character
bigrams**, so Chinese text is searchable; splitting on whitespace, as the previous
re-ranker did, yields one token for an entire Chinese sentence and scores zero.

Fusion ranks by the *best* reciprocal rank either retriever gave a chunk, with the
sum as the tie-break. Plain summed RRF credits a chunk simply for appearing in
both lists, and with a weak dense list that buries a keyword hit: two questions
whose answer BM25 ranked first fell out of the top ten entirely that way.

Chunking follows the document's own structure. Extraction emits headings as
`## Heading`, the chunker keeps a heading stack so no chunk straddles a section,
and the section path is stored on the chunk, prepended to the text that gets
embedded, and shown in the citation.

### Measuring retrieval quality

`backend/scripts/eval_retrieval.py` scores retrieval against a fixed corpus of
six Wikipedia pages (three English, three Traditional Chinese) and 30 questions,
12 of them cross-lingual. It builds its own database and never touches
`data/opennotebook.db`:

```bash
docker exec <backend-container> sh -lc   "cd /app && LLM_MODE=none python -m scripts.eval_retrieval --tag mychange --out /tmp/rag-eval"
```

Ground truth is answer-bearing *text*, not chunk ids, so the same question set
stays comparable across changes to the chunker. Reports land in the `--out`
directory as `metrics.json` and `report.md`.

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
| `GET` | `/api/projects/{id}/mindmap` | Mind map of a project; returns `root`, `node_count`, `model_used` |
| `GET` | `/api/projects/{id}/video-summary` | Scene script for Studio's video summary; returns `scenes`, `estimated_seconds`, `model_used` |
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
| `OPENAI_BASE_URL` | Redirect the OpenAI path at a compatible provider | – (OpenAI) |
| `OPENAI_REASONING_FORMAT` | Groq only: `parsed`, `raw`, `hidden` | – |
| `OPENAI_MIN_MAX_TOKENS` | Floor for a request's output budget | `2048` |
| `OLLAMA_BASE_URL` | Local OpenAI-compatible endpoint | `http://localhost:11434/v1` |
| `OLLAMA_MODEL` | Local model name | `llama3.2` |
| **Embedding** | | |
| `EMB_MODEL_NAME` | sentence-transformers model | `intfloat/multilingual-e5-base` |
| `EMB_DIMENSION` | Vector dimension (auto-corrected from the model) | `768` |
| `EMB_BACKEND` | Vector store backend | `sqlitevec` |
| **Retrieval & chunking** | | |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Chunking window, in characters | `512` / `50` |
| `RETRIEVAL_TOP_K` | Chunks retrieved per question | `5` |
| `RETRIEVAL_CANDIDATE_K` | Candidates each retriever offers before fusion | `30` |
| `RETRIEVAL_MIN_SCORE` | Minimum cosine similarity for a dense candidate | `0.0` |
| `HYBRID_ENABLED` | Fuse dense and BM25 retrieval | `true` |
| `HYBRID_RRF_K` | Rank-damping constant for the fusion | `60` |
| `DEDUPE_JACCARD` | Token overlap at which two candidates are one passage | `0.9` |
| `CONTEXT_CHAR_BUDGET` | Ceiling on retrieved context in a prompt | `12000` |
| `RERANK_ENABLED` | Legacy heuristic re-ranker, used when `HYBRID_ENABLED=false` | `true` |
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

- **There is no sharing.** Ownership is all-or-nothing: a project belongs to one
  account, and there is no way to grant another account access to it.
- **Caching is in-memory.** `app/services/cache.py` will use Redis if a client
  and a `redis_url` setting are present; neither ships, so the cache is
  per-process and resets on restart.
- **YouTube import depends on YouTube.** The pinned
  `youtube-transcript-api==0.6.1` scrapes the watch page, and YouTube rate-limits
  it — imports can fail with an XML parse error on a blocked response even
  though the code is correct.
- **Studio's video summary is not a video file.** The backend returns a scene
  script and the browser plays it as a narrated slideshow, reading the narration
  out with the Web Speech API — the same split the audio summary uses. There is
  nothing to download but the script, as Markdown. Rendering an MP4 would mean
  adding a drawing library, a speech engine and ffmpeg to the image; recording
  the slideshow in the browser is no substitute, because Web Speech output cannot
  be captured into a `MediaStream` and the file would come out silent.
- **A video summary's narration is only as good as its inputs.** With no LLM
  configured each source scene is extracted instead — heading structure first,
  then the document's opening sentences, then word frequency — and `model_used`
  says so, in the response and in the player.
- **A mind map's topics are only as good as its inputs.** With no LLM
  configured they come from the documents' own heading structure, and for a
  PDF with no headings from word frequency — useful, but a keyword list rather
  than a reading of the text. `model_used` on the response says which
  happened, and the dialog repeats it, so an extracted map is never presented
  as a generated one.
- **No WebSockets.** Ingest progress is polled, not pushed.
- **Cross-lingual retrieval is only partly there.** A question in one language
  finds passages in the other when they share a proper noun, because BM25 matches
  it. When the vocabulary does not overlap at all — an English question whose
  answer exists only in Chinese prose — `multilingual-e5-base` does not reliably
  bridge the gap. `BAAI/bge-m3` is the stronger multilingual model and would
  likely close it, but needs roughly 4.85 GB of RSS against this one's 2.69 GB.
- **Retrieval scans the whole scope on every question.** Both halves are linear
  in the number of chunks in the project; `sqlite-vec` and `faiss-cpu` are
  installed but not wired up, so `EMB_BACKEND` has no effect.

## License

MIT.
