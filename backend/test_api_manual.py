"""Manual API testing script using requests."""
import requests
import json
import time

# Base URL
BASE_URL = "http://localhost:8000/api"

def test_project_crud():
    """Test project CRUD operations manually."""
    
    print("=" * 60)
    print("Testing Project Management API")
    print("=" * 60)
    
    # 1. Create a project
    print("\n1. Creating a new project...")
    create_data = {
        "name": "My Research Project",
        "description": "A collection of papers and notes for my research"
    }
    response = requests.post(f"{BASE_URL}/projects", json=create_data)
    if response.status_code == 200:
        project = response.json()
        project_id = project["id"]
        print(f"✓ Project created with ID: {project_id}")
        print(f"  Name: {project['name']}")
        print(f"  Description: {project['description']}")
    else:
        print(f"✗ Failed to create project: {response.status_code}")
        print(response.text)
        return
    
    # 2. Get the project
    print(f"\n2. Getting project {project_id}...")
    response = requests.get(f"{BASE_URL}/projects/{project_id}")
    if response.status_code == 200:
        project = response.json()
        print(f"✓ Project retrieved:")
        print(f"  Name: {project['name']}")
        print(f"  Created: {project['created_at']}")
    else:
        print(f"✗ Failed to get project: {response.status_code}")
    
    # 3. List all projects
    print("\n3. Listing all projects...")
    response = requests.get(f"{BASE_URL}/projects")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Found {data['total']} projects:")
        for p in data['projects']:
            print(f"  - {p['name']} (ID: {p['id']})")
    else:
        print(f"✗ Failed to list projects: {response.status_code}")
    
    # 4. Update the project
    print(f"\n4. Updating project {project_id}...")
    update_data = {
        "name": "Updated Research Project",
        "description": "Updated description with more details"
    }
    response = requests.put(f"{BASE_URL}/projects/{project_id}", json=update_data)
    if response.status_code == 200:
        project = response.json()
        print(f"✓ Project updated:")
        print(f"  New name: {project['name']}")
        print(f"  New description: {project['description']}")
    else:
        print(f"✗ Failed to update project: {response.status_code}")
    
    # 5. Create another project for testing
    print("\n5. Creating another project...")
    create_data2 = {
        "name": "Secondary Project",
        "description": "Another test project"
    }
    response = requests.post(f"{BASE_URL}/projects", json=create_data2)
    if response.status_code == 200:
        project2 = response.json()
        project2_id = project2["id"]
        print(f"✓ Second project created with ID: {project2_id}")
    else:
        print(f"✗ Failed to create second project: {response.status_code}")
    
    # 6. Search projects
    print("\n6. Searching for projects containing 'Research'...")
    response = requests.get(f"{BASE_URL}/projects?search=Research")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Found {len(data['projects'])} matching projects:")
        for p in data['projects']:
            print(f"  - {p['name']}")
    else:
        print(f"✗ Failed to search projects: {response.status_code}")
    
    # 7. Test pagination
    print("\n7. Testing pagination (page 1, 2 items per page)...")
    response = requests.get(f"{BASE_URL}/projects?page=1&per_page=2")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Page {data['page']} of projects:")
        print(f"  Total: {data['total']}, Showing: {len(data['projects'])}")
        for p in data['projects']:
            print(f"  - {p['name']}")
    else:
        print(f"✗ Failed to paginate: {response.status_code}")
    
    # 8. Delete a project
    print(f"\n8. Deleting project {project2_id}...")
    response = requests.delete(f"{BASE_URL}/projects/{project2_id}")
    if response.status_code == 200:
        print(f"✓ Project deleted successfully")
    else:
        print(f"✗ Failed to delete project: {response.status_code}")
    
    # 9. Verify deletion
    print(f"\n9. Verifying project {project2_id} is deleted...")
    response = requests.get(f"{BASE_URL}/projects/{project2_id}")
    if response.status_code == 404:
        print(f"✓ Project not found (as expected)")
    else:
        print(f"✗ Project still exists: {response.status_code}")
    
    print("\n" + "=" * 60)
    print("✅ All manual tests completed!")
    print("=" * 60)


def test_health_check():
    """Test health check endpoint."""
    print("\nTesting Health Check...")
    response = requests.get("http://localhost:8000/healthz")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Health check passed: {data['ok']}")
        print(f"  Version: {data['version']}")
        print(f"  Environment: {data['environment']}")
    else:
        print(f"✗ Health check failed: {response.status_code}")


if __name__ == "__main__":
    print("Manual API Testing Script")
    print("Make sure the server is running: python -m uvicorn app.main:app --reload")
    print("-" * 60)
    
    try:
        # Test health first
        test_health_check()
        
        # Test project CRUD
        test_project_crud()
        
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Could not connect to the server.")
        print("Make sure the server is running on http://localhost:8000")
        print("\nTo start the server:")
        print("  cd backend")
        print("  python -m uvicorn app.main:app --reload")
    except Exception as e:
        print(f"\n❌ Error: {e}")
