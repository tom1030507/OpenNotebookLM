"""Basic test to verify the application can start."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that basic imports work."""
    try:
        from app.config import get_settings
        from app.db.database import init_db
        from app.db.models import Base
        print("✓ All imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False

def test_config():
    """Test configuration loading."""
    try:
        from app.config import get_settings
        settings = get_settings()
        print(f"✓ Config loaded: {settings.app_name}")
        return True
    except Exception as e:
        print(f"✗ Config error: {e}")
        return False

def test_database():
    """Test database initialization."""
    try:
        from app.db.database import init_db
        init_db()
        print("✓ Database initialized")
        return True
    except Exception as e:
        print(f"✗ Database error: {e}")
        return False

if __name__ == "__main__":
    print("Running basic tests...\n")
    
    tests = [
        test_imports,
        test_config,
        test_database,
    ]
    
    results = []
    for test in tests:
        results.append(test())
        print()
    
    if all(results):
        print("✅ All basic tests passed!")
    else:
        print("❌ Some tests failed")
        sys.exit(1)
