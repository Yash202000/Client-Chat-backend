#!/bin/bash

# AgentConnect Backend Service Installation Script
# This script automates the installation of the systemd service

set -e  # Exit on error

echo "=================================="
echo "AgentConnect Backend Service Setup"
echo "=================================="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
   echo "ERROR: Please do not run this script as root or with sudo"
   echo "The script will prompt for sudo password when needed"
   exit 1
fi

# Check Docker installation
echo "[1/7] Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed. Please install Docker first."
    exit 1
fi
echo "✓ Docker found"

# Check Docker Compose
echo "[2/7] Checking Docker Compose..."
if ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose is not available. Please install Docker Compose."
    exit 1
fi
echo "✓ Docker Compose found"

# Check Docker permissions
echo "[3/7] Checking Docker permissions..."
if ! docker ps &> /dev/null; then
    echo "WARNING: Cannot run Docker without sudo"
    echo "Adding user to docker group..."
    sudo usermod -aG docker $USER
    echo "✓ Added to docker group. You may need to log out and back in for this to take effect."
    echo "  After logging back in, run this script again."
    exit 0
fi
echo "✓ Docker permissions OK"

# Check if .env file exists
echo "[4/7] Checking .env file..."
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found in current directory"
    echo "Please create .env file first"
    exit 1
fi
echo "✓ .env file found"

# Check if virtual environment exists
echo "[5/7] Checking virtual environment..."
if [ ! -f "venv/bin/uvicorn" ]; then
    echo "ERROR: Virtual environment not found or incomplete"
    echo "Please ensure venv exists with uvicorn installed"
    exit 1
fi
echo "✓ Virtual environment OK"

# Create log files
echo "[6/7] Creating log files..."
sudo touch /var/log/agentconnect-backend.log
sudo touch /var/log/agentconnect-backend-error.log
sudo chown $USER:$USER /var/log/agentconnect-backend.log
sudo chown $USER:$USER /var/log/agentconnect-backend-error.log
echo "✓ Log files created"

# Install service
echo "[7/7] Installing systemd service..."
sudo cp agentconnect-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable agentconnect-backend.service
echo "✓ Service installed and enabled"

echo ""
echo "=================================="
echo "Installation Complete!"
echo "=================================="
echo ""
echo "The service has been installed but not started yet."
echo ""
echo "Next steps:"
echo "1. Test Docker Compose services:"
echo "   docker compose up -d"
echo "   docker compose ps"
echo ""
echo "2. Start the backend service:"
echo "   sudo systemctl start agentconnect-backend.service"
echo ""
echo "3. Check service status:"
echo "   sudo systemctl status agentconnect-backend.service"
echo ""
echo "4. View logs:"
echo "   tail -f /var/log/agentconnect-backend.log"
echo ""
echo "For more information, see SERVICE-SETUP.md"
