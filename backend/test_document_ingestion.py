"""Test document ingestion API."""
import requests
import time
import os
from pathlib import Path

BASE_URL = "http://localhost:8000/api"

def create_sample_pdf():
    """Create a sample PDF file for testing."""
    # For testing, we'll create a simple text file with .pdf extension
    # In production, this would be a real PDF
    sample_file = Path("sample_test.pdf")
    sample_file.write_text("This is a sample PDF content for testing.")
    return sample_file

def test_document_ingestion():
    """Test document ingestion operations."""
    
    print("=" * 60)
    print("Testing Document Ingestion API")
    print("=" * 60)
    
    # First, create a project
    print("\n1. Creating a test project...")
    project_data = {
        "name": "Document Test Project",
        "description": "Testing document uploads"
    }
    response = requests.post(f"{BASE_URL}/projects", json=project_data)
    if response.status_code != 200:
        print(f"✗ Failed to create project: {response.status_code}")
        print(response.text)
        return
    
    project = response.json()
    project_id = project["id"]
    print(f"✓ Project created: {project_id}")
    
    # Test URL ingestion
    print("\n2. Testing URL document ingestion...")
    url_data = {
        "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "title": "Wikipedia: Artificial Intelligence"
    }
    response = requests.post(
        f"{BASE_URL}/projects/{project_id}/upload-url",
        json=url_data
    )
    
    if response.status_code == 200:
        url_doc = response.json()
        url_doc_id = url_doc["doc_id"]
        print(f"✓ URL document created: {url_doc_id}")
        print(f"  Status: {url_doc['status']}")
        print(f"  Message: {url_doc['message']}")
        
        # Check status
        time.sleep(2)  # Wait a bit for processing
        status_response = requests.get(f"{BASE_URL}/docs/{url_doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            print(f"  Processing status: {status['status']}")
            if status['progress'] is not None:
                print(f"  Progress: {status['progress']*100:.0f}%")
    else:
        print(f"✗ URL ingestion failed: {response.status_code}")
        print(response.text)
    
    # Test YouTube ingestion
    print("\n3. Testing YouTube document ingestion...")
    youtube_data = {
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Test YouTube Video"
    }
    response = requests.post(
        f"{BASE_URL}/projects/{project_id}/upload-youtube",
        json=youtube_data
    )
    
    if response.status_code == 200:
        yt_doc = response.json()
        yt_doc_id = yt_doc["doc_id"]
        print(f"✓ YouTube document created: {yt_doc_id}")
        print(f"  Status: {yt_doc['status']}")
        print(f"  Message: {yt_doc['message']}")
    else:
        print(f"✗ YouTube ingestion failed: {response.status_code}")
        print(response.text)
    
    # Test PDF upload (if we have a sample PDF)
    print("\n4. Testing PDF upload...")
    sample_pdf = create_sample_pdf()
    
    try:
        with open(sample_pdf, "rb") as f:
            files = {"file": (sample_pdf.name, f, "application/pdf")}
            data = {"title": "Sample PDF Document"}
            
            response = requests.post(
                f"{BASE_URL}/projects/{project_id}/upload",
                files=files,
                data=data
            )
            
            if response.status_code == 200:
                pdf_doc = response.json()
                pdf_doc_id = pdf_doc["doc_id"]
                print(f"✓ PDF document uploaded: {pdf_doc_id}")
                print(f"  Status: {pdf_doc['status']}")
                print(f"  Message: {pdf_doc['message']}")
                
                # Wait and check status
                time.sleep(3)
                status_response = requests.get(f"{BASE_URL}/docs/{pdf_doc_id}/status")
                if status_response.status_code == 200:
                    status = status_response.json()
                    print(f"  Processing status: {status['status']}")
                    
                # Get full document details
                doc_response = requests.get(f"{BASE_URL}/docs/{pdf_doc_id}")
                if doc_response.status_code == 200:
                    doc = doc_response.json()
                    print(f"  Document title: {doc['title']}")
                    print(f"  Source type: {doc['source_type']}")
            else:
                print(f"✗ PDF upload failed: {response.status_code}")
                print(response.text)
    finally:
        # Clean up sample file
        if sample_pdf.exists():
            sample_pdf.unlink()
    
    # List project documents
    print("\n5. Listing project documents...")
    response = requests.get(f"{BASE_URL}/projects/{project_id}/documents")
    if response.status_code == 200:
        documents = response.json()
        print(f"✓ Found {len(documents)} documents in project:")
        for doc in documents:
            print(f"  - {doc['title']} ({doc['source_type']}) - Status: {doc['status']}")
    else:
        print(f"✗ Failed to list documents: {response.status_code}")
    
    # Test document deletion
    if 'pdf_doc_id' in locals():
        print(f"\n6. Deleting document {pdf_doc_id}...")
        response = requests.delete(f"{BASE_URL}/docs/{pdf_doc_id}")
        if response.status_code == 200:
            print(f"✓ Document deleted successfully")
        else:
            print(f"✗ Failed to delete document: {response.status_code}")
    
    # Clean up - delete project
    print(f"\n7. Cleaning up - deleting project...")
    response = requests.delete(f"{BASE_URL}/projects/{project_id}")
    if response.status_code == 200:
        print(f"✓ Project deleted")
    
    print("\n" + "=" * 60)
    print("✅ Document Ingestion API tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    print("Document Ingestion API Testing")
    print("Make sure the server is running: python -m uvicorn app.main:app --reload")
    print("-" * 60)
    
    try:
        # Test health first
        response = requests.get("http://localhost:8000/healthz")
        if response.status_code == 200:
            print("✓ Server is running")
            
            # Run document ingestion tests
            test_document_ingestion()
        else:
            print("✗ Server health check failed")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Could not connect to the server.")
        print("Make sure the server is running on http://localhost:8000")
    except Exception as e:
        print(f"\n❌ Error: {e}")
