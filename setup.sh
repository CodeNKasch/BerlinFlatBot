#!/bin/bash
# BerlinFlatBot Setup Script
# Automates the setup process for both development and production

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check if running on Raspberry Pi
is_raspberry_pi() {
    if [ -f /proc/device-tree/model ]; then
        grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null
        return $?
    fi
    return 1
}

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
fi

print_header "BerlinFlatBot Setup Script"
echo ""
print_info "Detected OS: $OS"
if is_raspberry_pi; then
    print_info "Running on Raspberry Pi"
    IS_RPI=true
else
    IS_RPI=false
fi
echo ""

# Step 1: Check Python version
print_header "Step 1: Checking Python Installation"
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed!"
    echo ""
    if [ "$OS" = "linux" ]; then
        echo "Install Python 3 with:"
        echo "  sudo apt update && sudo apt install python3 python3-pip python3-venv"
    elif [ "$OS" = "macos" ]; then
        echo "Install Python 3 with:"
        echo "  brew install python3"
    fi
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
print_success "Python 3 is installed: $PYTHON_VERSION"

# Check if venv module is available
if ! python3 -m venv --help &> /dev/null; then
    print_error "Python venv module is not available!"
    if [ "$OS" = "linux" ]; then
        echo "Install it with: sudo apt install python3-venv"
    fi
    exit 1
fi
print_success "Python venv module is available"
echo ""

# Step 2: Create virtual environment
print_header "Step 2: Setting Up Virtual Environment"
if [ -d "venv" ]; then
    print_warning "Virtual environment already exists"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Removing old virtual environment..."
        rm -rf venv
        print_success "Old virtual environment removed"
    else
        print_info "Using existing virtual environment"
    fi
fi

if [ ! -d "venv" ]; then
    print_info "Creating virtual environment..."
    python3 -m venv venv
    print_success "Virtual environment created"
fi
echo ""

# Step 3: Install dependencies
print_header "Step 3: Installing Dependencies"
print_info "Activating virtual environment..."
source venv/bin/activate

print_info "Upgrading pip..."
pip install --upgrade pip > /dev/null 2>&1
print_success "pip upgraded"

print_info "Installing dependencies from requirements.txt..."
pip install -r requirements.txt
print_success "All dependencies installed"
echo ""

# Step 4: Check config.json
print_header "Step 4: Checking Configuration"
if [ ! -f "config.json" ]; then
    print_warning "config.json not found!"
    echo ""
    echo "You need to create config.json with your Telegram bot credentials."
    echo ""
    read -p "Would you like to create it now? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo ""
        echo "Please enter the following information:"
        echo ""

        read -p "Telegram Bot Token: " BOT_TOKEN
        read -p "Chat ID (where to send notifications): " CHAT_ID
        read -p "Private Chat ID (for error notifications): " PRIVATE_CHAT_ID
        read -p "Monitor Interval in seconds (default: 60): " MONITOR_INTERVAL
        MONITOR_INTERVAL=${MONITOR_INTERVAL:-60}

        cat > config.json << EOF
{
  "BOT_TOKEN": "$BOT_TOKEN",
  "CHAT_ID": "$CHAT_ID",
  "PRIVATE_CHAT_ID": "$PRIVATE_CHAT_ID",
  "MONITOR_INTERVAL": $MONITOR_INTERVAL
}
EOF
        print_success "config.json created"
    else
        print_warning "Skipping config.json creation"
        echo "You'll need to create it manually before running the bot."
    fi
else
    print_success "config.json exists"
    # Validate config.json
    if python3 -c "import json; json.load(open('config.json'))" 2>/dev/null; then
        print_success "config.json is valid JSON"
    else
        print_error "config.json is not valid JSON!"
        exit 1
    fi
fi
echo ""

# Step 5: Test imports
print_header "Step 5: Testing Installation"
print_info "Testing Python imports..."
if python3 -c "
import sys
sys.path.insert(0, '.')
from scrapers import InBerlinWohnenScraper, DegewoScraper, load_seen_flats
from bot import Config
" 2>/dev/null; then
    print_success "All imports successful"
else
    print_error "Import test failed!"
    exit 1
fi

if [ -f "config.json" ]; then
    print_info "Testing configuration loading..."
    if python3 -c "
import sys
sys.path.insert(0, '.')
from bot import Config
config = Config()
print(f'Monitor interval: {config.monitor_interval}s')
" 2>/dev/null; then
        print_success "Configuration loads successfully"
    else
        print_error "Configuration loading failed!"
        exit 1
    fi
fi
echo ""

# Step 6: SystemD service setup (Linux only)
if [ "$OS" = "linux" ] && [ "$IS_RPI" = true ]; then
    print_header "Step 6: SystemD Service Setup (Optional)"
    echo ""
    echo "Would you like to set up the bot as a systemd service?"
    echo "This will make the bot start automatically on boot."
    echo ""
    read -p "Set up systemd service? (y/N): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        CURRENT_DIR=$(pwd)
        CURRENT_USER=$(whoami)
        VENV_PYTHON="$CURRENT_DIR/venv/bin/python3"
        BOT_SCRIPT="$CURRENT_DIR/bot.py"

        print_info "Creating systemd service file..."

        cat > telegram.service << EOF
[Unit]
Description=Berlin Flat Monitor Bot
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$VENV_PYTHON $BOT_SCRIPT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

        print_success "Service file created: telegram.service"
        echo ""
        print_info "To install the service, run these commands:"
        echo ""
        echo "  sudo cp telegram.service /etc/systemd/system/"
        echo "  sudo systemctl daemon-reload"
        echo "  sudo systemctl enable telegram.service"
        echo "  sudo systemctl start telegram.service"
        echo ""

        read -p "Install and start the service now? (y/N): " -n 1 -r
        echo

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Installing service..."
            sudo cp telegram.service /etc/systemd/system/
            sudo systemctl daemon-reload
            print_success "Service installed"

            print_info "Enabling service (start on boot)..."
            sudo systemctl enable telegram.service
            print_success "Service enabled"

            print_info "Starting service..."
            sudo systemctl start telegram.service
            print_success "Service started"

            echo ""
            print_info "Checking service status..."
            sleep 2
            sudo systemctl status telegram.service --no-pager -n 10
        fi
    fi
    echo ""
fi

# Step 7: SD Card Optimizations (Raspberry Pi only)
if [ "$IS_RPI" = true ]; then
    print_header "Step 7: SD Card Optimizations (Optional)"
    echo ""
    echo "The bot includes optimizations to reduce SD card wear:"
    echo "  • Cache stored in RAM (/dev/shm)"
    echo "  • Batched writes (every 10 flats)"
    echo "  • Logs to stdout (captured by journald)"
    echo ""
    echo "Additional optimizations are available in SD_CARD_OPTIMIZATION.md:"
    echo "  • Configure journald for RAM storage"
    echo "  • Disable swap"
    echo "  • Mount directories as tmpfs"
    echo ""
    print_info "See SD_CARD_OPTIMIZATION.md for details"
    echo ""
fi

# Final summary
print_header "Setup Complete!"
echo ""
print_success "BerlinFlatBot is ready to use!"
echo ""
echo "Next steps:"
echo ""

if [ ! -f "config.json" ]; then
    echo "  1. Create config.json with your Telegram bot credentials"
    echo "     See SETUP.md for details"
    echo ""
fi

echo "  • Run the bot in development mode:"
echo "      ./run.sh"
echo ""
echo "  • Run manually:"
echo "      source venv/bin/activate"
echo "      python3 bot.py"
echo ""

if [ "$IS_RPI" = true ]; then
    echo "  • View service logs (if installed as service):"
    echo "      journalctl -u telegram.service -f"
    echo ""
    echo "  • Apply SD card optimizations:"
    echo "      See SD_CARD_OPTIMIZATION.md"
    echo ""
fi

echo "  • Read documentation:"
echo "      SETUP.md - Setup and usage guide"
echo "      SD_CARD_OPTIMIZATION.md - Raspberry Pi optimizations"
echo "      REFACTORING.md - Code structure details"
echo ""

print_success "Happy flat hunting! 🏠"
echo ""
