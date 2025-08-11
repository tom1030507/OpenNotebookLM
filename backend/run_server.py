#!/usr/bin/env python3
"""
Entry point for running OpenNotebookLM Backend Server
This script is used for PyInstaller packaging
"""

import sys
import os
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Set environment variables if .env exists
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

def main():
    """Main entry point."""
    import uvicorn
    from app.main import app
    from app.config import get_settings
    
    settings = get_settings()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                     OpenNotebookLM Backend                   ║
║                         Version 0.1.0                        ║
╚══════════════════════════════════════════════════════════════╝

Starting server...
- Host: 0.0.0.0
- Port: {settings.app_port}
- Environment: {settings.app_env}
- Debug: {settings.debug}

API Documentation: http://localhost:{settings.app_port}/docs
Health Check: http://localhost:{settings.app_port}/healthz

Press CTRL+C to stop the server
""")
    
    # Run the server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.app_port,
        reload=False,  # Disable reload for packaged app
        log_level=settings.log_level.lower(),
        access_log=True
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nServer stopped by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        print("\nPress Enter to exit...")
        input()
        sys.exit(1)
