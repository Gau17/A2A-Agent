#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.
set -o pipefail # Exit immediately if a command in a pipeline fails.

# Determine the script's directory and the project root
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT="${SCRIPT_DIR}/.."

# Navigate to project root to ensure tools run in the correct context
cd "${PROJECT_ROOT}"
echo "Running all checks and tests from project root: $(pwd)"
echo # Blank line for readability

echo "::group::Running Ruff linter"
ruff check .
echo "::endgroup::"
echo # Blank line for readability

echo "::group::Running Black formatter check"
black --check .
echo "::endgroup::"
echo # Blank line for readability

echo "::group::Running MyPy type checker"
mypy . --non-interactive
echo "::endgroup::"
echo # Blank line for readability

echo "::group::Running Pytest tests"
# If tests are not found, you might need to adjust PYTHONPATH or pytest configuration.
# For example: export PYTHONPATH=${PYTHONPATH}:.
pytest
echo "::endgroup::"
echo # Blank line for readability

# Optional: run coverage
# echo "::group::Running tests with coverage"
# coverage run -m pytest
# coverage report -m
# coverage html # for html report
# echo "::endgroup::"
# echo # Blank line for readability

echo "All checks and tests passed!" 