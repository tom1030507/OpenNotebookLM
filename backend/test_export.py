#!/usr/bin/env python3
"""Test script for export functionality."""
import requests
import json
import os
import sys

def test_export():
    """Test the export endpoints."""
    base_url = "http://localhost:8000/api"
    filename = None  # Initialize filename variable
    
    print("Testing Export Functionality")
    print("=" * 50)
    
    # First, get an existing conversation or project
    print("\n1. Getting existing projects...")
    response = requests.get(f"{base_url}/projects")
    if response.status_code != 200:
        print(f"Failed to get projects: {response.status_code}")
        print(f"Response: {response.text}")
        return
    
    try:
        data = response.json()
        # Extract projects from the response
        projects = data.get('projects', []) if isinstance(data, dict) else data
    except json.JSONDecodeError:
        print("Failed to parse projects response")
        return
    
    if not projects or len(projects) == 0:
        print("No projects found. Creating a test project...")
        # Create a test project
        project_data = {
            "name": "Export Test Project",
            "description": "Project for testing export functionality"
        }
        response = requests.post(f"{base_url}/projects", json=project_data)
        if response.status_code != 200:
            print(f"Failed to create project: {response.text}")
            return
        project = response.json()
        project_id = project["id"]
    else:
        project = projects[0]
        project_id = project["id"]
    
    print(f"✓ Using project: {project['name']} ({project_id})")
    
    # Get conversations for this project
    print("\n2. Getting conversations...")
    response = requests.get(f"{base_url}/projects/{project_id}/conversations")
    if response.status_code == 200:
        conversations = response.json()
        if conversations:
            conversation_id = conversations[0]["id"]
            print(f"✓ Found {len(conversations)} conversation(s)")
        else:
            conversation_id = None
            print("No conversations found")
    else:
        conversation_id = None
        print("Failed to get conversations")
    
    # Test 1: Export project summary
    print("\n3. Testing project summary export...")
    response = requests.get(f"{base_url}/export/project/{project_id}/summary")
    if response.status_code == 200:
        print("✓ Project summary exported successfully")
        print(f"  Content-Type: {response.headers.get('content-type')}")
        print(f"  Size: {len(response.content)} bytes")
        
        # Save the file
        filename = f"export_test_summary_{project_id}.md"
        with open(filename, 'wb') as f:
            f.write(response.content)
        print(f"  Saved to: {filename}")
    else:
        print(f"✗ Summary export failed: {response.status_code}")
    
    # Test 2: Export project as JSON
    print("\n4. Testing project JSON export...")
    response = requests.get(f"{base_url}/export/project/{project_id}?format=json")
    if response.status_code == 200:
        print("✓ Project exported as JSON successfully")
        print(f"  Size: {len(response.content)} bytes")
        
        # Parse and display some info
        try:
            data = json.loads(response.content)
            print(f"  Documents: {len(data.get('documents', []))}")
            print(f"  Conversations: {len(data.get('conversations', []))}")
        except:
            pass
    else:
        print(f"✗ JSON export failed: {response.status_code}")
    
    # Test 3: Export project as Markdown
    print("\n5. Testing project Markdown export...")
    response = requests.get(f"{base_url}/export/project/{project_id}?format=markdown")
    if response.status_code == 200:
        print("✓ Project exported as Markdown successfully")
        print(f"  Size: {len(response.content)} bytes")
    else:
        print(f"✗ Markdown export failed: {response.status_code}")
    
    # Test 4: Export conversation (if available)
    if conversation_id:
        print(f"\n6. Testing conversation export ({conversation_id})...")
        
        # Export as Markdown
        response = requests.get(f"{base_url}/export/conversation/{conversation_id}?format=markdown")
        if response.status_code == 200:
            print("✓ Conversation exported as Markdown")
            print(f"  Size: {len(response.content)} bytes")
        else:
            print(f"✗ Markdown export failed: {response.status_code}")
        
        # Export as JSON
        response = requests.get(f"{base_url}/export/conversation/{conversation_id}?format=json")
        if response.status_code == 200:
            print("✓ Conversation exported as JSON")
        else:
            print(f"✗ JSON export failed: {response.status_code}")
        
        # Export as Text
        response = requests.get(f"{base_url}/export/conversation/{conversation_id}?format=txt")
        if response.status_code == 200:
            print("✓ Conversation exported as Text")
        else:
            print(f"✗ Text export failed: {response.status_code}")
    
    print("\n" + "=" * 50)
    print("Export functionality test complete!")
    
    # Clean up test files
    if filename and os.path.exists(filename):
        print(f"\nNote: Test file '{filename}' was created. You can delete it if not needed.")


if __name__ == "__main__":
    try:
        test_export()
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to server. Make sure the backend is running on http://localhost:8000")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
