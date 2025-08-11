"""Test embedding generation functionality."""
import requests
import time
import json
from pathlib import Path

BASE_URL = "http://localhost:8000/api"


def test_embeddings():
    """Test embedding generation after document processing."""
    
    print("=" * 60)
    print("Testing Embedding Generation")
    print("=" * 60)
    
    # 1. Create a project
    print("\n1. Creating test project...")
    project_data = {
        "name": "Embedding Test Project",
        "description": "Testing embedding generation"
    }
    response = requests.post(f"{BASE_URL}/projects", json=project_data)
    if response.status_code != 200:
        print(f"✗ Failed to create project: {response.status_code}")
        return
    
    project = response.json()
    project_id = project["id"]
    print(f"✓ Project created: {project_id}")
    
    # 2. Upload a small test document
    print("\n2. Uploading test document...")
    url_data = {
        "url": "https://www.python.org/about/",
        "title": "Python About Page"
    }
    response = requests.post(
        f"{BASE_URL}/projects/{project_id}/upload-url",
        json=url_data
    )
    
    if response.status_code != 200:
        print(f"✗ URL upload failed: {response.status_code}")
        return
    
    url_doc = response.json()
    doc_id = url_doc["doc_id"]
    print(f"✓ Document uploaded: {doc_id}")
    
    # 3. Wait for processing
    print("\n3. Waiting for processing (text extraction, chunking, embedding)...")
    max_attempts = 60  # Increased for embedding generation
    for i in range(max_attempts):
        time.sleep(3)
        
        # Check document status
        response = requests.get(f"{BASE_URL}/docs/{doc_id}/status")
        if response.status_code == 200:
            status = response.json()
            print(f"   Status: {status['status']}", end="")
            
            if status['status'] == 'ready':
                print(" ✓")
                break
            elif status['status'] == 'error':
                print(f"\n✗ Processing failed: {status.get('error_message')}")
                return
            else:
                print(f" (attempt {i+1}/{max_attempts})", end="\r")
    else:
        print("\n✗ Processing timeout")
        return
    
    # 4. Check database for embeddings
    print("\n4. Checking embeddings in database...")
    
    # Connect to database to check embeddings
    import sqlite3
    conn = sqlite3.connect('data/opennotebook.db')
    cursor = conn.cursor()
    
    # Count chunks for document
    cursor.execute("""
        SELECT COUNT(*) FROM chunks WHERE document_id = ?
    """, (doc_id,))
    chunk_count = cursor.fetchone()[0]
    print(f"   Document has {chunk_count} chunks")
    
    # Count embeddings for document
    cursor.execute("""
        SELECT COUNT(*) 
        FROM embeddings e
        JOIN chunks c ON e.chunk_id = c.id
        WHERE c.document_id = ?
    """, (doc_id,))
    embedding_count = cursor.fetchone()[0]
    print(f"   Document has {embedding_count} embeddings")
    
    if embedding_count > 0:
        print(f"✓ Embeddings generated successfully!")
        
        # Get embedding dimension
        cursor.execute("""
            SELECT LENGTH(vector) 
            FROM embeddings e
            JOIN chunks c ON e.chunk_id = c.id
            WHERE c.document_id = ?
            LIMIT 1
        """, (doc_id,))
        vector_size = cursor.fetchone()[0]
        print(f"   Vector storage size: {vector_size} bytes")
        
        # Get model name
        cursor.execute("""
            SELECT model_name 
            FROM embeddings e
            JOIN chunks c ON e.chunk_id = c.id
            WHERE c.document_id = ?
            LIMIT 1
        """, (doc_id,))
        model_name = cursor.fetchone()[0]
        print(f"   Model used: {model_name}")
    else:
        print("✗ No embeddings found")
    
    conn.close()
    
    # 5. Test similarity search (if we have an API endpoint)
    print("\n5. Testing similarity search...")
    # Note: This would require implementing a search API endpoint
    print("   (Search API endpoint not yet implemented)")
    
    # Clean up
    print("\n6. Cleaning up...")
    response = requests.delete(f"{BASE_URL}/projects/{project_id}")
    if response.status_code == 200:
        print("✓ Project deleted")
    
    print("\n" + "=" * 60)
    print("✅ Embedding tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    print("Embedding Generation Test")
    print("Make sure the server is running: python -m uvicorn app.main:app --reload")
    print("-" * 60)
    
    try:
        # Test health first
        response = requests.get("http://localhost:8000/healthz")
        if response.status_code == 200:
            print("✓ Server is running")
            print("\nNote: First run will download the embedding model (~90MB)")
            print("This may take a few minutes...\n")
            
            # Run embedding tests
            test_embeddings()
        else:
            print("✗ Server health check failed")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Could not connect to the server.")
        print("Make sure the server is running on http://localhost:8000")
    except Exception as e:
        print(f"\n❌ Error: {e}")
