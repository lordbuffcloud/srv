#!/bin/bash

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv and install requirements if needed
echo "Activating virtual environment..."
source venv/bin/activate

# Check if requirements are installed
if ! python -c "import click" &> /dev/null; then
    echo "Installing requirements..."
    pip install -r requirements.txt
fi

# Run srv.py in interactive mode
echo "Starting SRV in interactive mode..."
python srv.py interactive 