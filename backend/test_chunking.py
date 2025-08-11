"""Test document chunking functionality."""
import requests
import time
import json
from pathlib import Path

BASE_URL = "http://localhost:8000/api"


def test_chunking():
    """Test document chunking after ingestion."""
    
    print("=" * 60)
    print("Testing Document Chunking")
    print("=" * 60)
    
    # 1. Create a project
    print("\n1. Creating test project...")
    project_data = {
        "name": "Chunking Test Project",
        "description": "Testing document chunking"
    }
    response = requests.post(f"{BASE_URL}/projects", json=project_data)
    if response.status_code != 200:
        print(f"✗ Failed to create project: {response.status_code}")
        return
    
    project = response.json()
    project_id = project["id"]
    print(f"✓ Project created: {project_id}")
    
    # 2. Upload a URL document for testing
    print("\n2. Uploading URL document...")
    url_data = {
        "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "title": "AI Wikipedia Article"
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
    
    # 3. Wait for processing and chunking
    print("\n3. Waiting for processing and chunking...")
    max_attempts = 30
    for i in range(max_attempts):
        time.sleep(2)
        
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
    
    # 4. Check if chunks were created
    print("\n4. Checking chunks in database...")
    
    # We need to add an API endpoint to get chunks
    # For now, let's check indirectly through document details
    response = requests.get(f"{BASE_URL}/docs/{doc_id}")
    if response.status_code == 200:
        doc = response.json()
        chunk_count = doc.get("chunk_count", 0)
        
        if chunk_count > 0:
            print(f"✓ Document has {chunk_count} chunks")
        else:
            print("✗ No chunks found")
    
    # 5. Test with PDF
    print("\n5. Testing PDF chunking...")
    pdf_path = Path("real_test.pdf")
    if pdf_path.exists():
        with open(pdf_path, "rb") as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            data = {"title": "Test PDF for Chunking"}
            
            response = requests.post(
                f"{BASE_URL}/projects/{project_id}/upload",
                files=files,
                data=data
            )
            
            if response.status_code == 200:
                pdf_doc = response.json()
                pdf_doc_id = pdf_doc["doc_id"]
                print(f"✓ PDF uploaded: {pdf_doc_id}")
                
                # Wait for processing
                time.sleep(5)
                
                response = requests.get(f"{BASE_URL}/docs/{pdf_doc_id}")
                if response.status_code == 200:
                    doc = response.json()
                    chunk_count = doc.get("chunk_count", 0)
                    print(f"   PDF has {chunk_count} chunks")
    
    # 6. Test with YouTube
    print("\n6. Testing YouTube chunking...")
    youtube_data = {
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Test Video for Chunking"
    }
    response = requests.post(
        f"{BASE_URL}/projects/{project_id}/upload-youtube",
        json=youtube_data
    )
    
    if response.status_code == 200:
        yt_doc = response.json()
        yt_doc_id = yt_doc["doc_id"]
        print(f"✓ YouTube video uploaded: {yt_doc_id}")
        
        # Wait for processing
        time.sleep(5)
        
        response = requests.get(f"{BASE_URL}/docs/{yt_doc_id}")
        if response.status_code == 200:
            doc = response.json()
            chunk_count = doc.get("chunk_count", 0)
            print(f"   YouTube video has {chunk_count} chunks")
    
    # Clean up
    print("\n7. Cleaning up...")
    response = requests.delete(f"{BASE_URL}/projects/{project_id}")
    if response.status_code == 200:
        print("✓ Project deleted")
    
    print("\n" + "=" * 60)
    print("✅ Chunking tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    print("Document Chunking Test")
    print("Make sure the server is running: python -m uvicorn app.main:app --reload")
    print("-" * 60)
    
    try:
        # Test health first
        response = requests.get("http://localhost:8000/healthz")
        if response.status_code == 200:
            print("✓ Server is running")
            
            # Run chunking tests
            test_chunking()
        else:
            print("✗ Server health check failed")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Could not connect to the server.")
        print("Make sure the server is running on http://localhost:8000")
    except Exception as e:
        print(f"\n❌ Error: {e}")
