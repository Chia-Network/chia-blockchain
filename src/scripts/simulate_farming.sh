. .venv/bin/activate

# Starts a harvester, farmer, and full node.

_kill_servers() {
  ps -e | grep python | awk '{print $1}' | xargs -L1  kill
}

_kill_servers

python -m src.server.start_harvester &
P1=$!
python -m src.server.start_farmer &
P2=$!
python -m src.server.start_full_node "127.0.0.1" 8444 -f -t -u 8222 &
P3=$!

_term() {
  echo "Caught SIGTERM signal, killing all servers."
  kill -TERM "$P1" 2>/dev/null
  kill -TERM "$P2" 2>/dev/null
  kill -TERM "$P3" 2>/dev/null
  _kill_servers
}

trap _term SIGTERM
trap _term SIGINT
trap _term INT
wait $P1 $P2 $P3
