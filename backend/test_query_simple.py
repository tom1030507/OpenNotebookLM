#!/usr/bin/env python3
"""Simple test for query endpoint."""
import requests
import json

base_url = "http://localhost:8000/api"

print("Testing Query Endpoint")
print("=" * 40)

# Check if server is running
try:
    response = requests.get("http://localhost:8000/")
    print(f"✓ Server is running: {response.json()['name']}")
except:
    print("✗ Server is not running!")
    exit(1)

# Check available endpoints
response = requests.get("http://localhost:8000/openapi.json")
if response.status_code == 200:
    spec = response.json()
    query_endpoints = [path for path in spec.get("paths", {}) if "query" in path]
    print(f"\nQuery endpoints found: {len(query_endpoints)}")
    for endpoint in query_endpoints:
        print(f"  - {endpoint}")

# Test the query endpoint directly
print("\nTesting POST /api/query:")
test_query = {
    "query": "What is artificial intelligence?",
    "top_k": 2,
    "temperature": 0.5,
    "max_tokens": 100
}

response = requests.post(f"{base_url}/query", json=test_query)
print(f"Status Code: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    print("✓ Query successful!")
    print(f"  Answer: {result.get('answer', 'No answer')[:100]}...")
elif response.status_code == 404:
    print("✗ Endpoint not found - server may need restart")
    print("\nTo restart the server:")
    print("1. Stop the current server (Ctrl+C)")
    print("2. Run: python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
else:
    print(f"✗ Error: {response.text[:200]}")

print("\nNote: If the query endpoint is not found, the server needs to be restarted to load the new routes.")
