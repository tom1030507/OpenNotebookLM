# OpenNotebookLM

<div align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="License">
  <img src="https://img.shields.io/badge/docker-ready-blue.svg" alt="Docker">
</div>

<br>

> An open-source alternative to Google's NotebookLM - Transform your documents into an intelligent knowledge base with advanced RAG capabilities.

## 🌟 Key Features

### 📚 Document Intelligence
- **Multi-format Support**: Import PDFs, web pages, and YouTube transcripts
- **Smart Chunking**: Context-aware document splitting with metadata preservation
- **Vector Search**: High-performance semantic search using embeddings

### 🤖 AI-Powered Q&A
- **RAG Pipeline**: Retrieval-Augmented Generation with source citations
- **Conversation Memory**: Context-aware multi-turn conversations
- **Hybrid Models**: Support for both local (Ollama) and cloud (OpenAI) LLMs

### ⚡ Performance & Scalability
- **Caching Layer**: Redis/in-memory caching for <1ms response times
- **Batch Processing**: Efficient handling of large document sets
- **Async Operations**: Non-blocking document processing

### 🔐 Enterprise Ready
- **Authentication**: JWT-based auth with role-based access control
- **Multi-user Support**: Isolated projects and conversations per user
- **Export Options**: JSON, Markdown, and plain text exports

### 🎨 Modern UI
- **React/Next.js Frontend**: Responsive and intuitive interface
- **Real-time Updates**: WebSocket support for live updates
- **Dark Mode**: Built-in theme switching

## 🚀 Quick Start

### Prerequisites

| Component | Version | Required |
|-----------|---------|----------|
| Python | 3.10+ | ✅ |
| Node.js | 18+ | ✅ |
| Docker | 20.10+ | Optional |
| Redis | 6.0+ | Optional |

### 🐳 Docker Installation (Recommended)

```bash
# Clone repository
git clone https://github.com/yourusername/OpenNotebookLM.git
cd OpenNotebookLM

# Configure environment
cp deploy/.env.example deploy/.env
# Edit .env with your settings

# Start services
cd deploy
docker-compose up -d

# Check status
docker-compose ps
```

Access points:
- 🌐 Frontend: http://localhost:3000
- 🔧 Backend API: http://localhost:8000
- 📚 API Docs: http://localhost:8000/docs

### 💻 Local Development

#### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start development server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
# or yarn install

# Start development server
npm run dev
# or yarn dev
```

#### Database Setup

```bash
# SQLite (default)
# Database will be created automatically at ./data/opennotebook.db

# PostgreSQL (optional)
# Set DATABASE_URL in .env:
# DATABASE_URL=postgresql://user:password@localhost/opennotebook
```

## 📖 Documentation

### API Documentation
- **Interactive API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/healthz

### Guides
- [Quick Start Guide](./docs/quickstart.md)
- [Cache Implementation](./docs/cache-implementation.md)
- [API Reference](./docs/api-reference.md)
- [Deployment Guide](./docs/deployment.md)

## 🏗️ Architecture

```
OpenNotebookLM/
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── api/            # API route handlers
│   │   ├── services/       # Business logic layer
│   │   │   ├── cache.py    # Caching service
│   │   │   ├── rag.py      # RAG pipeline
│   │   │   ├── embeddings.py # Embedding generation
│   │   │   └── llm.py      # LLM integration
│   │   ├── adapters/       # External integrations
│   │   │   ├── pdf.py      # PDF processing
│   │   │   ├── url.py      # Web scraping
│   │   │   └── youtube.py  # YouTube transcripts
│   │   ├── db/             # Database layer
│   │   │   ├── models.py   # SQLAlchemy models
│   │   │   └── database.py # Database connection
│   │   └── routers/        # API endpoints
│   └── tests/              # Test suites
│       ├── unit/           # Unit tests
│       ├── integration/    # Integration tests
│       └── e2e/            # End-to-end tests
├── frontend/               # Next.js frontend
│   ├── components/         # React components
│   ├── pages/             # Next.js pages
│   ├── stores/            # Zustand state management
│   └── utils/             # Utility functions
├── deploy/                # Deployment configurations
│   ├── docker-compose.yml # Docker orchestration
│   └── kubernetes/        # K8s manifests
└── docs/                  # Documentation
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default | Options |
|----------|-------------|---------|----------|
| **LLM Configuration** ||||
| `LLM_MODE` | LLM provider mode | `auto` | `local`, `cloud`, `auto` |
| `LLM_MODEL` | Model name | `llama2` | Any Ollama/OpenAI model |
| `OPENAI_API_KEY` | OpenAI API key | - | Required for cloud mode |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` | - |
| **Embedding Configuration** ||||
| `EMB_MODEL_NAME` | Embedding model | `BAAI/bge-small-en-v1.5` | Any sentence-transformer |
| `EMB_DIMENSION` | Embedding dimension | `384` | Model-specific |
| `EMB_BACKEND` | Vector store backend | `sqlitevec` | `sqlitevec`, `faiss` |
| **Cache Configuration** ||||
| `REDIS_URL` | Redis connection URL | - | `redis://localhost:6379` |
| `CACHE_TTL` | Default cache TTL | `3600` | Seconds |
| **Database Configuration** ||||
| `DATABASE_URL` | Database connection | `sqlite:///./data/opennotebook.db` | Any SQLAlchemy URL |
| **Security Configuration** ||||
| `JWT_SECRET_KEY` | JWT signing key | Random | Strong secret key |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` | - |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiry | `30` | Minutes |
| **Application Settings** ||||
| `MAX_FILE_SIZE_MB` | Max upload size | `50` | MB |
| `CHUNK_SIZE` | Document chunk size | `1000` | Characters |
| `CHUNK_OVERLAP` | Chunk overlap | `200` | Characters |

For a complete list, see [`deploy/.env.example`](./deploy/.env.example)

## 🧪 Testing

### Running Tests

```bash
# Run all tests
cd backend
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test suite
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/

# Run with verbose output
pytest -v
```

### Test Coverage

| Component | Coverage | Status |
|-----------|----------|--------|
| Cache Service | 95% | ✅ |
| RAG Pipeline | 88% | ✅ |
| Auth System | 92% | ✅ |
| Document Processing | 85% | ✅ |
