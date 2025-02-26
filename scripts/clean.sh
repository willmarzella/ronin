#!/bin/bash

# Print start message
echo "Cleaning up Python cache files..."

# Find and remove all __pycache__ directories
find . -type d -name "__pycache__" -exec rm -r {} +

# Find and remove all .pyc files
find . -type f -name "*.pyc" -delete

# Find and remove all .pyo files
find . -type f -name "*.pyo" -delete

# Find and remove all .pyd files
find . -type f -name "*.pyd" -delete

# Print completion message with count of removed items
echo "Cleanup completed!"
