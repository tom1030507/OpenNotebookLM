# OpenNotebookLM

An open-source alternative to Google's NotebookLM with document understanding, RAG retrieval, and citation capabilities.

## Features

- 📄 **Multi-source Import**: PDF, URL, YouTube transcripts
- 🔍 **RAG-powered Q&A**: Retrieval-Augmented Generation with citation tracking
- 💾 **Local-first**: Prioritize local models to control costs
- 🚀 **Easy Deployment**: Docker Compose one-click setup
- 📊 **Export Options**: Markdown with citations, webhook integrations

## Quick Start

### Prerequisites

- Python 3.10+
- Docker & Docker Compose (optional)
- Node.js 18+ (for frontend)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/OpenNotebookLM.git
cd OpenNotebookLM
```

2. Copy environment variables:
```bash
cp deploy/.env.example deploy/.env
```

3. Edit `.env` file with your configuration

### Running with Docker

```bash
cd deploy
docker-compose up
```

The API will be available at `http://localhost:8000`

### Running Locally

#### Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

#### Frontend (coming soon)

```bash
cd frontend
npm install
npm run dev
```

## API Documentation

Once running, visit:
- API Docs: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/healthz`

## Project Structure

```
OpenNotebookLM/
├── backend/
│   ├── app/
│   │   ├── routers/      # API endpoints
│   │   ├── core/         # Core processing logic
│   │   ├── adapters/     # External service adapters
│   │   ├── db/           # Database models
│   │   └── utils/        # Utilities
│   └── tests/
├── frontend/             # Next.js frontend (coming soon)
├── deploy/              # Docker and deployment configs
├── docs/                # Documentation
└── data/                # Local data storage
```

## Configuration

Key environment variables:

- `LLM_MODE`: `local`, `cloud`, or `auto`
- `EMB_BACKEND`: `sqlitevec` or `faiss`
- `OPENAI_API_KEY`: For cloud LLM (optional)
- `MAX_FILE_SIZE_MB`: Maximum upload size
- `REDIS_URL`: Redis connection URL (optional, for caching)

See `deploy/.env.example` for all options.

## Development

### Running Tests

```bash
cd backend
pytest
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License

MIT License - see LICENSE file for details

## Roadmap

### ✅ Completed
- [x] Project Management API (CRUD operations)
- [x] Document Ingestion System
- [x] PDF text extraction (PyMuPDF, pdfminer)
- [x] URL content extraction (BeautifulSoup, readability)
- [x] YouTube transcript extraction (youtube-transcript-api)
- [x] Asynchronous document processing
- [x] Database models with SQLAlchemy
- [x] Document chunking system (recursive text splitter)
- [x] Embedding generation with sentence-transformers
- [x] Vector similarity search
- [x] RAG query pipeline with citations
- [x] Conversation management (with history tracking)
- [x] Advanced reranking (vector + keyword + length)
- [x] LLM integration (OpenAI API + local Ollama)
- [x] High-performance caching layer (Redis + in-memory fallback)
- [x] Cache integration for queries, embeddings, and chunks

### 🚧 In Progress
- [x] Export functionality (Markdown, JSON, Text)
- [ ] Frontend UI (React/Next.js)

### 📋 Planned
- [ ] Multi-user support with authentication
- [ ] Cloud deployment guides (AWS, GCP, Azure)
- [ ] Webhook integrations
- [ ] Advanced analytics dashboard
- [ ] Batch processing for large documents

## Support

For issues and questions, please use GitHub Issues.
