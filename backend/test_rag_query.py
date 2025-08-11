#!/usr/bin/env python3
"""Test script for RAG query system."""
import requests
import json
import time
import sys


def test_rag_query():
    """Test the RAG query endpoint."""
    base_url = "http://localhost:8000/api"
    
    print("Testing RAG Query System")
    print("=" * 50)
    
    # Step 1: Create a test project
    print("\n1. Creating test project...")
    project_data = {
        "name": "RAG Test Project",
        "description": "Project for testing RAG queries"
    }
    response = requests.post(f"{base_url}/projects", json=project_data)
    if response.status_code != 200:
        print(f"Failed to create project: {response.text}")
        return
    project = response.json()
    project_id = project["id"]
    print(f"✓ Created project: {project_id}")
    
    # Step 2: Add a test document
    print("\n2. Adding test document...")
    doc_data = {
        "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "title": "AI Wikipedia Article"
    }
    response = requests.post(f"{base_url}/projects/{project_id}/upload-url", json=doc_data)
    if response.status_code != 200:
        print(f"Failed to add document: {response.text}")
        return
    document = response.json()
    doc_id = document["doc_id"]
    print(f"✓ Added document: {doc_id}")
    
    # Step 3: Wait for processing
    print("\n3. Waiting for document processing...")
    max_wait = 60  # Maximum 60 seconds
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        response = requests.get(f"{base_url}/docs/{doc_id}")
        if response.status_code == 200:
            doc_status = response.json()
            if doc_status["status"] == "ready":
                print(f"✓ Document processed successfully")
                print(f"  - Chunks: {doc_status.get('chunk_count', 0)}")
                # Count embeddings from chunks
                break
            elif doc_status["status"] == "error":
                print(f"✗ Document processing failed: {doc_status.get('error_message')}")
                return
        time.sleep(2)
    else:
        print("✗ Timeout waiting for document processing")
        return
    
    # Step 4: Test simple query
    print("\n4. Testing simple query...")
    query_data = {
        "query": "What is artificial intelligence?",
        "project_id": project_id,
        "top_k": 3,
        "temperature": 0.5,
        "max_tokens": 256
    }
    
    response = requests.post(f"{base_url}/query", json=query_data)
    if response.status_code != 200:
        print(f"✗ Query failed: {response.text}")
        return
    
    result = response.json()
    print(f"✓ Query successful!")
    print(f"  - Answer length: {len(result['answer'])} chars")
    print(f"  - Sources found: {len(result.get('sources', []))}")
    print(f"  - Chunks used: {result.get('chunks_used', 0)}")
    print(f"  - Model: {result.get('model_used', 'N/A')}")
    
    if result.get('conversation_id'):
        print(f"  - Conversation ID: {result['conversation_id']}")
    
    print(f"\nAnswer preview (first 200 chars):")
    print(f"  {result['answer'][:200]}...")
    
    if result.get('sources'):
        print(f"\nSources:")
        for i, source in enumerate(result['sources'][:3], 1):
            print(f"  {i}. {source.get('document_title', 'Unknown')} - Chunk {source.get('chunk_index', '?')}")
    
    # Step 5: Test conversation-based query
    if result.get('conversation_id'):
        print("\n5. Testing follow-up query in conversation...")
        conversation_id = result['conversation_id']
        
        follow_up = {
            "query": "Can you explain more about machine learning?",
            "conversation_id": conversation_id,
            "top_k": 3,
            "temperature": 0.5,
            "max_tokens": 256
        }
        
        response = requests.post(f"{base_url}/query", json=follow_up)
        if response.status_code == 200:
            follow_result = response.json()
            print(f"✓ Follow-up query successful!")
            print(f"  - Answer length: {len(follow_result['answer'])} chars")
            print(f"  - Conversation maintained: {follow_result.get('conversation_id') == conversation_id}")
            
            # Get conversation history
            response = requests.get(f"{base_url}/conversations/{conversation_id}")
            if response.status_code == 200:
                conv_data = response.json()
                print(f"  - Total messages: {len(conv_data.get('messages', []))}")
        else:
            print(f"✗ Follow-up query failed: {response.text}")
    
    # Step 6: Test without project (general query)
    print("\n6. Testing general query (no project)...")
    general_query = {
        "query": "What is machine learning?",
        "top_k": 2,
        "temperature": 0.7,
        "max_tokens": 128
    }
    
    response = requests.post(f"{base_url}/query", json=general_query)
    if response.status_code == 200:
        general_result = response.json()
        print(f"✓ General query successful!")
        print(f"  - Answer length: {len(general_result['answer'])} chars")
        print(f"  - Sources from all projects: {len(general_result.get('sources', []))}")
    else:
        print(f"✗ General query failed: {response.text}")
    
    # Step 7: List conversations
    print("\n7. Listing project conversations...")
    response = requests.get(f"{base_url}/projects/{project_id}/conversations")
    if response.status_code == 200:
        conversations = response.json()
        print(f"✓ Found {len(conversations)} conversation(s)")
        for conv in conversations:
            print(f"  - {conv['title'][:50]}... ({conv['message_count']} messages)")
    else:
        print(f"✗ Failed to list conversations: {response.text}")
    
    print("\n" + "=" * 50)
    print("RAG Query System Test Complete!")


if __name__ == "__main__":
    try:
        test_rag_query()
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to server. Make sure the backend is running on http://localhost:8000")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
