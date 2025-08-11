#!/usr/bin/env python3
"""
Build script for OpenNotebookLM Backend
Creates a standalone executable using PyInstaller
"""

import sys
import os
import shutil
from pathlib import Path
import subprocess

def clean_build():
    """Clean previous build artifacts."""
    print("Cleaning previous builds...")
    dirs_to_remove = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_remove:
        dir_path = Path(dir_name)
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"  Removed {dir_name}/")
    
    # Remove spec files
    for spec_file in Path('.').glob('*.spec'):
        spec_file.unlink()
        print(f"  Removed {spec_file}")

def install_pyinstaller():
    """Install PyInstaller if not installed."""
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} is installed")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

def create_spec_file():
    """Create a new spec file."""
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['run_server.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('.env.example', '.'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'sqlalchemy.sql.default_comparator',
        'app.main',
        'app.config',
        'app.db.database',
        'app.db.models',
        'app.routers.projects',
        'app.routers.ingest',
        'app.routers.query',
        'app.routers.export',
        'app.routers.health',
        'app.services.projects',
        'app.services.documents',
        'app.services.chunking',
        'app.services.embeddings',
        'app.services.rag',
        'app.services.llm',
        'app.services.export',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'notebook', 'jupyter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OpenNotebookLM-Backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''
    
    spec_file = Path('OpenNotebookLM.spec')
    spec_file.write_text(spec_content)
    print(f"Created {spec_file}")
    return spec_file

def build_executable(spec_file):
    """Build the executable using PyInstaller."""
    print("\nBuilding executable...")
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_file)]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ Build successful!")
        exe_path = Path('dist') / 'OpenNotebookLM-Backend.exe'
        if exe_path.exists():
            print(f"✓ Executable created: {exe_path}")
            print(f"  Size: {exe_path.stat().st_size / 1024 / 1024:.2f} MB")
        return True
    else:
        print("✗ Build failed!")
        print("Error output:")
        print(result.stderr)
        return False

def create_distribution():
    """Create a distribution package."""
    print("\nCreating distribution package...")
    
    dist_dir = Path('dist')
    if not dist_dir.exists():
        return
    
    # Copy necessary files
    files_to_copy = [
        '.env.example',
        'requirements.txt',
        'README.md',
    ]
    
    for file_name in files_to_copy:
        src = Path(file_name) if Path(file_name).exists() else Path('..') / file_name
        if src.exists():
            dst = dist_dir / file_name
            shutil.copy2(src, dst)
            print(f"  Copied {file_name}")
    
    # Create empty directories
    for dir_name in ['data', 'models', 'uploads']:
        (dist_dir / dir_name).mkdir(exist_ok=True)
        print(f"  Created {dir_name}/")
    
    print("\n✓ Distribution package ready in dist/")

def main():
    """Main build process."""
    print("=" * 60)
    print("OpenNotebookLM Backend Build Script")
    print("=" * 60)
    
    # Change to backend directory
    backend_dir = Path(__file__).parent
    os.chdir(backend_dir)
    
    # Step 1: Clean
    clean_build()
    
    # Step 2: Install PyInstaller
    install_pyinstaller()
    
    # Step 3: Create spec file
    spec_file = create_spec_file()
    
    # Step 4: Build
    if build_executable(spec_file):
        # Step 5: Create distribution
        create_distribution()
        
        print("\n" + "=" * 60)
        print("Build Complete!")
        print("Run the executable from: dist/OpenNotebookLM-Backend.exe")
        print("=" * 60)
    else:
        print("\nBuild failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nBuild cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nBuild error: {e}")
        sys.exit(1)
