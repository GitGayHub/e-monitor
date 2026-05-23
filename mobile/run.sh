#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$SCRIPT_DIR/set_env.sh" ]; then
    source "$SCRIPT_DIR/set_env.sh"
else
    echo "ERROR: mobile/set_env.sh not found. Copy mobile/set_env.example.sh to mobile/set_env.sh and fill in tokens."
    exit 1
fi

cd "$REPO_DIR"

echo "=== [1/3] Pulling latest state from GitHub ==="
git add seen_ids.json config.json price_history.db 2>/dev/null || true
if ! git diff --cached --quiet; then
    git commit -m "Sync state before pull"
fi
git pull --rebase || { echo "git pull failed"; exit 1; }

echo
echo "=== [2/3] Starting bot (Ctrl+C to exit) ==="
echo
trap '' INT
python monitor.py || true
trap - INT

echo
echo "=== [3/3] Pushing state updates to GitHub ==="
git add seen_ids.json config.json price_history.db 2>/dev/null || true
if ! git diff --cached --quiet; then
    git commit -m "Sync state after manual run"
    git push
    echo "Done."
else
    echo "No state changes to push."
fi
