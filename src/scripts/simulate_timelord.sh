. .venv/bin/activate

# Starts a timelord, and a full node

_kill_servers() {
  ps -e | grep python | awk '{print $1}' | xargs -L1  kill
  ps -e | grep "vdf_server" | awk '{print $1}' | xargs -L1  kill
}

_kill_servers

python -m src.server.start_timelord &
P1=$!
python -m src.server.start_full_node "127.0.0.1" 8002 -t -u 8222 &
P2=$!

_term() {
  echo "Caught SIGTERM signal, killing all servers."
  kill -TERM "$P1" 2>/dev/null
  kill -TERM "$P2" 2>/dev/null
  _kill_servers
}

trap _term SIGTERM
trap _term SIGINT
trap _term INT
wait $P1 $P2
