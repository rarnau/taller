#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

pip install -r "$CLAUDE_PROJECT_DIR/requirements.txt" --quiet
echo 'export PYTHONPATH="$CLAUDE_PROJECT_DIR"' >> "$CLAUDE_ENV_FILE"
