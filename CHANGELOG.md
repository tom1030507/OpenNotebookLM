# Changelog

All notable changes to OpenNotebookLM are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-25

OpenNotebookLM's first public release provides a self-hosted workspace for
grounding AI conversations and generated outputs in the user's own sources.

### Added

- Import pipelines for PDFs, text and Markdown files, web pages, and YouTube
  transcripts, including local Whisper transcription when captions are absent.
- Persistent hybrid retrieval that combines sqlite-vec dense candidates with
  FTS5/BM25 keyword candidates and supports CJK search terms.
- Multi-turn project conversations with document and section citations.
- Studio generation for Markdown reports, audio summaries, mind maps, and
  narrated slideshows.
- Export conversations as Markdown, JSON, or plain text; export whole projects
  as Markdown or JSON; and download project summaries as Markdown.
- Provider support for Claude, OpenAI-compatible APIs, Ollama, llama.cpp, and
  vLLM.
- Docker Compose and local development workflows for Windows, macOS, and Linux.

### Security

- Bearer authentication and ownership checks on every data-bearing route.
- Per-account project, document, conversation, export, and cache isolation.
- Bounded uploads, URL fetching, query budgets, and background ingestion work.

### Reliability

- Durable ingestion jobs with startup recovery and concurrency-safe SQLite
  transactions.
- Persistent retrieval indexes with lifecycle repair and re-index tooling.
- Deterministic backend, frontend, browser end-to-end, and production-like RAG
  CI workflows.

[Unreleased]: https://github.com/tom1030507/OpenNotebookLM/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tom1030507/OpenNotebookLM/releases/tag/v0.1.0
