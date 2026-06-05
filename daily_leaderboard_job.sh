#!/bin/bash
# Daily leaderboard automation: pipeline + face sync + git push.
# Run manually from project root or via cron on EC2.
#
# Requires: .env with HUB_API_KEY, DAILY_ACTIVITY_API_KEY, EXTERNAL_API_SECRET
# Assumes: SSH-based git auth, state_fixed.json present for Playwright download
#
# Cron example (7:30 AM IST on UTC server): 30 2 * * * /path/to/daily_leaderboard_job.sh

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

# Preflight checks
if [[ ! -f .env ]]; then
  log "ERROR: .env missing"
  exit 1
fi
if [[ ! -f src/pipeline.py ]]; then
  log "ERROR: src/pipeline.py missing"
  exit 1
fi
if [[ ! -f download_faces.py ]]; then
  log "ERROR: download_faces.py missing"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

# Activate virtual environment and install dependencies
"$PYTHON_BIN" -m venv venv
source venv/bin/activate
playwright install chromium
pip install -r requirements.txt

log "START daily leaderboard job (last 7 days)"

log "Step 1: pipeline"
"$PYTHON_BIN" src/pipeline.py 2>&1 | tee -a "$LOG_FILE"

log "Step 2: download_faces"
"$PYTHON_BIN" download_faces.py 2>&1 | tee -a "$LOG_FILE"

log "Step 3: git commit/push"
git add data/ output/ logs/
if git diff --staged --quiet; then
  log "No file changes — skip commit"
else
  git commit -m "chore(leaderboard): generate daily leaderboard data (last 7 days)"
  if ! git push; then
    log "ERROR: git push failed"
    exit 1
  fi
fi

log "DONE"
