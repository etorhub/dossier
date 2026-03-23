#!/usr/bin/env bash
# Live / one-shot terminal dashboard for the embedding queue (cluster job window).
# Requires: docker compose stack with worker; host python3 to parse JSON.
# Usage: ./scripts/embed-status.sh          # once
#        ./scripts/embed-status.sh --watch  # refresh every 1.5s (Ctrl+C to stop)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

WATCH=0
if [[ "${1:-}" == "--watch" || "${1:-}" == "-w" ]]; then
  WATCH=1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "embed-status.sh: python3 is required on the host to parse status JSON." >&2
  exit 1
fi

fetch_json() {
  docker compose exec -T worker python -m app.worker_cli embedding-status --compact
}

# shellcheck disable=SC2016
parse_summary_line() {
  python3 -c '
import json, sys

def fmt_ts(s):
    if not s:
        return "—"
    return s.replace("T", " ").replace("+00:00", " UTC")

d = json.load(sys.stdin)
lj = d.get("last_cluster_job")
if not lj:
    print("No finished cluster job in recent history yet.")
    raise SystemExit(0)
st = lj.get("status") or "?"
tr = lj.get("trigger") or "?"
parts = [st, tr]
res = lj.get("result") or {}
if res.get("articles_embedded") is not None:
    parts.append("embedded %s" % res["articles_embedded"])
if res.get("articles_clustered") is not None:
    parts.append("clustered %s" % res["articles_clustered"])
if res.get("stories_created") is not None:
    parts.append("stories %s" % res["stories_created"])
dur = lj.get("duration_ms")
if dur is not None:
    s = max(0, int(dur) // 1000)
    if s < 60:
        parts.append("in %ds" % s)
    elif s < 3600:
        parts.append("in %dm %ds" % (s // 60, s % 60))
    else:
        h, s = divmod(s, 3600)
        parts.append("in %dh %dm" % (h, s // 60))
fin = fmt_ts(lj.get("finished_at"))
print("%s · finished %s" % (" · ".join(parts), fin))
'
}

# Emit export lines with shlex-quoted values (safe eval for ISO timestamps).
emit_exports() {
  python3 -c '
import json, sys, shlex
d = json.load(sys.stdin)
keys = [
    "pending_embed_in_window",
    "embedded_in_window",
    "articles_in_window",
    "pending_embed_total",
    "cluster_window_hours",
    "embed_batch_size",
]
for k in keys:
    v = d.get(k)
    s = "" if v is None else str(v)
    print("export %s=%s" % (k, shlex.quote(s)))
pct = d.get("pct_embedded_in_window")
ps = "" if pct is None else str(pct)
print("export pct_embedded_in_window=%s" % shlex.quote(ps))
print("export cluster_job_running=%s" % shlex.quote("1" if d.get("cluster_job_running") else "0"))
ra = d.get("running_job_started_at") or ""
print("export running_job_started_at=%s" % shlex.quote(ra))
'
}

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  CYAN=$'\033[36m'
  GRN=$'\033[32m'
  YEL=$'\033[33m'
  RED=$'\033[31m'
  MAG=$'\033[35m'
  NC=$'\033[0m'
else
  BOLD="" DIM="" CYAN="" GRN="" YEL="" RED="" MAG="" NC=""
fi

SPINNER=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
frame=0

progress_bar() {
  local pct_raw=$1
  local width=${2:-26}
  local i filled empty j
  if [[ -z "$pct_raw" ]]; then
    printf "%s" "${DIM}│${NC}"
    for ((i = 0; i < width; i++)); do printf "·"; done
    printf "%s\n" "${DIM}│${NC} ${DIM}n/a${NC}"
    return
  fi
  # shellcheck disable=SC2076
  if [[ ! "$pct_raw" =~ ^[0-9]*\.?[0-9]+$ ]]; then
    printf "%s\n" "${DIM}(invalid pct)${NC}"
    return
  fi
  filled=$(python3 -c "w=int('$width'); p=float('$pct_raw'); print(int(round(w*min(100,max(0,p))/100.0)))")
  empty=$((width - filled))
  printf "%s" "${CYAN}▌${NC}${GRN}"
  for ((j = 0; j < filled; j++)); do printf "█"; done
  printf "%s" "${DIM}"
  for ((j = 0; j < empty; j++)); do printf "░"; done
  printf "%s" "${NC}${CYAN}▐${NC} ${BOLD}%s%%${NC}\n" "$pct_raw"
}

render_dashboard() {
  local json=$1
  local summary spin_ch started

  summary=$(echo "$json" | parse_summary_line)
  # shellcheck disable=SC1090
  eval "$(echo "$json" | emit_exports)"

  spin_ch="${SPINNER[$((frame % ${#SPINNER[@]}))]}"
  ((frame += 1)) || true

  local batch_note="∞ (no limit)"
  if [[ -n "${embed_batch_size:-}" && "${embed_batch_size:-0}" =~ ^[0-9]+$ && "${embed_batch_size:-0}" -gt 0 ]]; then
    batch_note="${embed_batch_size} per run"
  fi

  local win_note
  if [[ "${cluster_window_hours:-0}" == "0" ]]; then
    win_note="all time (no window)"
  else
    win_note="last ${cluster_window_hours}h"
  fi

  echo "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo "${BOLD}${CYAN}║${NC}  ${BOLD}Embeddings${NC} ${DIM}·${NC} cluster / embed queue  ${DIM}(${win_note})${NC}"
  echo "${BOLD}${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo "${CYAN}║${NC}  ${DIM}Pending (window)${NC}   ${BOLD}${pending_embed_in_window:-0}${NC}"
  echo "${CYAN}║${NC}  ${DIM}Embedded (window)${NC}  ${GRN}${embedded_in_window:-0}${NC}  ${DIM}/${NC} ${articles_in_window:-0} ${DIM}articles in window${NC}"
  echo "${CYAN}║${NC}  ${DIM}Pending (total DB)${NC} ${YEL}${pending_embed_total:-0}${NC}  ${DIM}without a valid vector${NC}"
  echo "${CYAN}║${NC}  ${DIM}Batch cap${NC}          ${MAG}${batch_note}${NC}"
  echo "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo "${CYAN}║${NC}  ${DIM}Coverage${NC}"
  echo -n "${CYAN}║${NC}    "
  progress_bar "${pct_embedded_in_window:-}" 28

  echo "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
  if [[ "${cluster_job_running:-0}" == "1" ]]; then
    started="${running_job_started_at:-?}"
    echo "${CYAN}║${NC}  ${YEL}${spin_ch}${NC}  ${BOLD}cluster job running${NC} ${DIM}(started ${started})${NC}"
  else
    echo "${CYAN}║${NC}  ${DIM}○${NC}  Idle ${DIM}(no unfinished cluster_articles job in job_runs)${NC}"
  fi
  echo "${CYAN}║${NC}  ${DIM}Last finished:${NC} ${summary}"
  echo "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo "${DIM}Tip:${NC} run cluster once with ${BOLD}docker compose exec worker python -m app.worker_cli cluster-articles${NC}"
  if [[ "$WATCH" -eq 1 ]]; then
    echo "${DIM}Watching… Ctrl+C to stop${NC}"
  else
    echo "${DIM}Live:${NC} ${BOLD}./scripts/embed-status.sh --watch${NC}"
  fi
}

run_once() {
  local json
  if ! json=$(fetch_json); then
    echo "${RED}Could not read embedding-status (is docker compose up? worker running?)${NC}" >&2
    return 1
  fi
  if [[ "$WATCH" -eq 1 ]]; then
    clear 2>/dev/null || true
  fi
  render_dashboard "$json"
}

if [[ "$WATCH" -eq 1 ]]; then
  while true; do
    run_once || true
    sleep 1.5
  done
else
  run_once
fi
