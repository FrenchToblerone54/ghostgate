#!/bin/bash
set -e

echo "Building GhostGate binary in Docker..."

cd "$(dirname "$0")/.."

echo "Building Docker image..."
BUILD_ARGS=""
if [ -n "${HTTP_PROXY:-}" ]; then
  BUILD_ARGS="$BUILD_ARGS --build-arg HTTP_PROXY=$HTTP_PROXY"
fi
if [ -n "${HTTPS_PROXY:-}" ]; then
  BUILD_ARGS="$BUILD_ARGS --build-arg HTTPS_PROXY=$HTTPS_PROXY"
fi
docker build $BUILD_ARGS -t ghostgate-builder -f build/Dockerfile .

echo "Building binary..."
docker run --rm -v "$(pwd):/build" ghostgate-builder bash -c "
cd /build
rm -rf build/ghostgate build/ghostgate.pkg
python3.13 -m PyInstaller --onefile --name ghostgate --add-data 'frontend:frontend' --collect-all rich main.py
cd dist
sha256sum ghostgate > ghostgate.sha256
"

echo "Build complete!"
echo "Binary available in dist/"
ls -lh dist/
