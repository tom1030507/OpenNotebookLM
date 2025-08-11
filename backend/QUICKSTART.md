# Quick Start Guide

## Installation

### 1. Create Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

For minimal testing:
```bash
pip install -r requirements-minimal.txt
pip install requests  # For manual testing
```

For full installation:
```bash
pip install -r requirements.txt
```

### 3. Setup Environment

```bash
# Copy environment template
copy ..\deploy\.env.example .env

# Or on Linux/Mac
cp ../deploy/.env.example .env
```

## Running the Server

```bash
# Start the development server
python -m uvicorn app.main:app --reload

# The server will be available at:
# - API: http://localhost:8000
# - Docs: http://localhost:8000/docs
# - Health: http://localhost:8000/healthz
```

## Testing

### 1. Basic System Test
```bash
python test_basic.py
```

### 2. Manual API Testing
```bash
# In another terminal (keep server running)
python test_api_manual.py
```

### 3. Unit Tests
```bash
pytest tests/test_projects.py -v
```

## API Examples

### Create a Project
```bash
curl -X POST "http://localhost:8000/api/projects" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"My Project\", \"description\": \"Test project\"}"
```

### List Projects
```bash
curl "http://localhost:8000/api/projects"
```

### Get Specific Project
```bash
curl "http://localhost:8000/api/projects/{project_id}"
```

### Update Project
```bash
curl -X PUT "http://localhost:8000/api/projects/{project_id}" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"Updated Name\"}"
```

### Delete Project
```bash
curl -X DELETE "http://localhost:8000/api/projects/{project_id}"
```

## Interactive API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

You can test all endpoints directly from the browser!

## Troubleshooting

### Port Already in Use
```bash
# Change port
python -m uvicorn app.main:app --port 8001 --reload
```

### Database Issues
```bash
# Delete database and restart
del data\opennotebook.db  # Windows
rm data/opennotebook.db    # Linux/Mac
```

### Module Import Errors
Make sure you're in the virtual environment and have installed dependencies:
```bash
# Check if in venv
where python  # Windows
which python  # Linux/Mac

# Reinstall dependencies
pip install -r requirements-minimal.txt
```

## Next Steps

1. Test the Project Management API
2. Implement Document Upload functionality
3. Add PDF processing
4. Implement RAG query system

See the main README for full documentation.
