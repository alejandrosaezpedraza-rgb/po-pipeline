#!/usr/bin/env bash
# Start the demo ERP (127.0.0.1:7811) and the PO pipeline app (127.0.0.1:7820), then open the page.
#
#   ./start.sh            start everything
#   ./start.sh --reset    wipe ERP orders, CRM, runs, customer folders and handled-mail list, then start
#   ./start.sh --no-open  don't open a browser
#
# Ctrl-C stops both servers.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

RESET=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --reset) RESET=1 ;;
    --no-open) OPEN=0 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$1"; exit 1; }

echo "PO pipeline · checking what's needed"

# 1. Python 3.9+ (standard library only at runtime)
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || die "Python 3.9 or newer is required (python3 or python on PATH)."
ok "Python: $("$PY" -c 'import sys; print(sys.version.split()[0])')"

port_busy() { "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1', $1)) == 0 else 1)"; }

APP_PORT=7820
ERP_PORT=7811
if port_busy $APP_PORT || port_busy $ERP_PORT; then
  die "Port $APP_PORT or $ERP_PORT is already in use. Is another copy running? Stop it first (Ctrl-C in its terminal)."
fi

# 2. Reset
if [ "$RESET" = 1 ]; then
  echo "Resetting to a clean state:"
  for d in state erp/data customers; do
    if [ -e "$d" ]; then rm -rf "$d"; ok "removed $d/"; fi
  done
fi
mkdir -p state/logs erp/data customers

# 3. Sample POs (committed; regenerated only if missing)
missing=0
for s in edi-printout corporate-form store-order change-form distributor-po; do
  [ -f "samples/$s.pdf" ] && [ -f "samples/truth/$s.json" ] || missing=1
done
if [ "$missing" = 1 ]; then
  if "$PY" samples/make_samples.py >/dev/null 2>&1; then ok "Sample POs generated"
  else warn "Sample POs missing and could not be generated (pip install reportlab, then: $PY samples/make_samples.py)"; fi
else
  ok "5 sample POs in samples/"
fi

# 4. Settings and extractor
if [ -f .env ]; then ok ".env found"; else warn "No .env, using defaults (copy .env.example to .env to change settings)"; fi
"$PY" - <<'EOF' || true
from app import config, extract
cfg = config.load()
b = extract.describe_backend(cfg)
mark = "\033[32m✓\033[0m" if b["ready"] else "\033[33m!\033[0m"
print(f"  {mark} Extractor: {b['label']}" + (f" · model {b['model']}" if b.get("model") else ""))
if b.get("hint"):
    print(f"      {b['hint']}")
print(f"  \033[32m✓\033[0m Send mode: {cfg['SEND_MODE']}" + ("" if cfg['SEND_MODE'] == 'dry' else f" · allowed: {cfg['SEND_ALLOWED'] or '(none)'}"))
mw = cfg["MAILBOX_WATCH"]
print(f"  \033[32m✓\033[0m Mailbox watcher: {mw}")
EOF

# 5. Start servers
PIDS=()
cleanup() {
  trap - EXIT INT TERM
  echo
  echo "Stopping..."
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait_up() {
  "$PY" - "$1" <<'EOF'
import sys, time, urllib.request
url = sys.argv[1]
for _ in range(60):
    try:
        urllib.request.urlopen(url, timeout=1).read()
        sys.exit(0)
    except Exception:
        time.sleep(0.25)
sys.exit(1)
EOF
}

"$PY" -u -m erp.server >state/logs/erp.log 2>&1 &
PIDS+=($!)
wait_up "http://127.0.0.1:$ERP_PORT/api/health" || { tail -20 state/logs/erp.log; die "Demo ERP did not start (log above)"; }
ok "Demo ERP   http://127.0.0.1:$ERP_PORT"

"$PY" -u -m app.server >state/logs/app.log 2>&1 &
PIDS+=($!)
wait_up "http://127.0.0.1:$APP_PORT/api/config" || { tail -20 state/logs/app.log; die "App did not start (log above)"; }
ok "PO intake  http://127.0.0.1:$APP_PORT"

URL="http://127.0.0.1:$APP_PORT/"
if [ "$OPEN" = 1 ]; then
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) cmd.exe //c start "" "$URL" >/dev/null 2>&1 || true ;;
    Darwin) open "$URL" ;;
    *) (xdg-open "$URL" >/dev/null 2>&1 || true) ;;
  esac
fi
echo "Running. Logs in state/logs/. Press Ctrl-C to stop."
wait
