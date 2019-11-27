. .venv/bin/activate
. scripts/common.sh

# Starts an introducer

_run_bg_cmd python -m src.server.start_introducer

wait
