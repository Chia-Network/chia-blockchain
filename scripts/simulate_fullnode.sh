. .venv/bin/activate

_kill_servers() {
  ps -e | grep python | awk '{print $1}' | xargs -L1  kill
  ps -e | grep "vdf_server" | awk '{print $1}' | xargs -L1  kill
}

_kill_servers

python -m src.server.start_full_node "127.0.0.1" 8002 -id 1 -f &
P4=$!
python -m src.server.start_full_node "127.0.0.1" 8004 -id 2 -t -u 8222 &
P5=$!
python -m src.server.start_full_node "127.0.0.1" 8005 -id 3 &
P6=$!

_term() {
  echo "Caught SIGTERM signal, killing all servers."
  kill -TERM "$P4" 2>/dev/null
  kill -TERM "$P5" 2>/dev/null
  kill -TERM "$P6" 2>/dev/null
  _kill_servers
}

trap _term SIGTERM
trap _term SIGINT
trap _term INT
wait $P4 $P5 $P6
