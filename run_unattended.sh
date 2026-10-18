#!/usr/bin/env bash
# Keeps opencode working until the project passes its own verify gate.
cd "$(dirname "$0")" || exit 1
mkdir -p .tmp
MAX=10
for i in $(seq 1 "$MAX"); do
  echo "=== round $i/$MAX  $(date +%T) ==="
  CONT="--continue"
  if head -n1 PROGRESS.md 2>/dev/null | grep -q '^STATUS: DONE'; then
    if bash scripts/verify.sh > .tmp/verify.log 2>&1; then echo "VERIFIED"; exit 0; fi
    sed -i '1s/.*/STATUS: IN_PROGRESS/' PROGRESS.md
    PROMPT="You wrote STATUS: DONE but scripts/verify.sh fails. Fix the root causes, re-run it, and only then set STATUS: DONE again. Last output: $(tail -n 40 .tmp/verify.log)"
  elif [ ! -f PROGRESS.md ] && [ "$i" -eq 1 ]; then
    CONT=""
    PROMPT="$(cat KICKOFF.md)"
  else
    PROMPT="Continue autonomously: read AGENTS.md and PROGRESS.md, resume the first unfinished milestone, never ask questions, and finish by making scripts/verify.sh pass."
  fi
  opencode run --auto $CONT "$PROMPT"
done
echo "Stopped after $MAX rounds. Read PROGRESS.md and BLOCKERS.md."
exit 1
