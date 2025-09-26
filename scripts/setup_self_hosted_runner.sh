#!/bin/bash

# GitHub Actions Self-Hosted Runner Setup Script
# This script helps set up a self-hosted GitHub Actions runner on your local machine

set -e

echo "🚀 Setting up GitHub Actions Self-Hosted Runner"
echo "================================================"

# Check if we're on macOS or Linux
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="osx"
    ARCH="x64"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
    if [[ $(uname -m) == "arm64" ]] || [[ $(uname -m) == "aarch64" ]]; then
        ARCH="arm64"
    else
        ARCH="x64"
    fi
else
    echo "❌ Unsupported platform: $OSTYPE"
    exit 1
fi

echo "🔍 Detected platform: $PLATFORM-$ARCH"

# Create runner directory
RUNNER_DIR="$HOME/github-actions-runner"
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

# Download the latest runner package
echo "📥 Downloading GitHub Actions Runner..."
RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')
RUNNER_FILE="actions-runner-${PLATFORM}-${ARCH}-${RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_FILE}"

curl -o "$RUNNER_FILE" -L "$DOWNLOAD_URL"
tar xzf "$RUNNER_FILE"
rm "$RUNNER_FILE"

echo "✅ Runner downloaded and extracted"
echo ""
echo "🔧 Next steps:"
echo "1. Go to your GitHub repository: https://github.com/YOUR_USERNAME/YOUR_REPO/settings/actions/runners"
echo "2. Click 'New self-hosted runner'"
echo "3. Copy the configuration command and run it in: $RUNNER_DIR"
echo "4. The command will look like:"
echo "   ./config.sh --url https://github.com/YOUR_USERNAME/YOUR_REPO --token YOUR_TOKEN"
echo ""
echo "5. After configuration, start the runner with:"
echo "   ./run.sh"
echo ""
echo "6. For running as a service (recommended for automation):"
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "   sudo ./svc.sh install"
    echo "   sudo ./svc.sh start"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "   sudo ./svc.sh install"
    echo "   sudo ./svc.sh start"
fi
echo ""
echo "📁 Runner installed in: $RUNNER_DIR"
echo "🎉 Setup complete! Follow the steps above to configure your runner."
