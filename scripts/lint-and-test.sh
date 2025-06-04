#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

echo "Running Ruff linter..."
ruff check .

echo "Running Black formatter check..."
black --check .

echo "Running MyPy type checker..."
mypy .

echo "Running Pytest tests..."
# Ensure that PYTHONPATH is set correctly if your tests are not found
export PYTHONPATH=${PYTHONPATH}:.
pytest -q

# Optional: run coverage
# echo "Running tests with coverage..."
# coverage run -m pytest
# coverage report -m
# coverage html # for html report

echo "All checks and tests passed!" 