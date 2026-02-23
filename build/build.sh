#!/bin/bash
set -e

echo "Building GhostGate binary..."

cd "$(dirname "$0")/.."

python3.13 -m PyInstaller --onefile --name ghostgate --add-data "frontend:frontend" main.py

echo "Generating checksum..."
cd dist
sha256sum ghostgate > ghostgate.sha256
cd ..

echo "Build complete!"
echo "Binary available in dist/"
ls -lh dist/
