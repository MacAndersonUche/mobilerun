#!/bin/bash
# Cross-platform startup script for Mobilerun self-hosted backend

set -e

echo "🚀 Starting Mobilerun Self-Hosted Backend..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.11 or later."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}' | cut -d. -f1,2)
echo "✓ Python $PYTHON_VERSION detected"

# Check if backend directory exists
if [ ! -d "backend" ]; then
    echo "❌ backend directory not found. Run this script from the repository root."
    exit 1
fi

cd backend

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Install/update dependencies
echo "📦 Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found. Creating template..."
    cat > .env << 'EOF'
# Mobilerun Backend Configuration
ALLOW_UNAUTHENTICATED=true
JWT_SECRET=dev-secret-change-in-production

# LLM Provider API Keys (add at least one)
GOOGLE_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Backend URL (for QR codes)
BACKEND_URL=http://localhost:8000
EOF
    echo "📝 Created .env file. Please add your API keys before running."
fi

# Load environment variables
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check if at least one API key is set
if [ -z "$GOOGLE_API_KEY" ] && [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "⚠️  WARNING: No LLM API keys configured!"
    echo "   Please add at least one API key to backend/.env:"
    echo "   - GOOGLE_API_KEY for Gemini"
    echo "   - OPENAI_API_KEY for OpenAI"
    echo "   - ANTHROPIC_API_KEY for Claude"
    echo ""
fi

# Start the server
echo "🌐 Starting backend server on http://localhost:8000..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Mobilerun Control Center"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Backend:  http://localhost:8000"
echo "  Docs:     http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python main.py
