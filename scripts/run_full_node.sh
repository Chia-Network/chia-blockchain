. .venv/bin/activate
. scripts/common.sh

# Starts the DB
_run_bg_cmd mongod --dbpath ./db/

# Starts a full node
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8444 -id 1 -u 8222

wait
