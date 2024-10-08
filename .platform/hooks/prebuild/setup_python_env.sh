#!/bin/bash
# Set up Python virtual environment
if [ ! -d "/var/app/staging/venv" ]; then
  python3 -m venv /var/app/staging/venv
fi
