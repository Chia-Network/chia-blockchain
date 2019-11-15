. .venv/bin/activate

# Starts a harvester, farmer, timelord, and 3 full nodes.

_kill_servers() {
  ps -e | grep python | awk '{print $1}' | xargs -L1  kill
  ps -e | grep "vdf_server" | awk '{print $1}' | xargs -L1  kill
}

_kill_servers

python -m src.server.start_harvester &
P1=$!
python -m src.server.start_timelord &
P2=$!
python -m src.server.start_farmer &
P3=$!
python -m src.server.start_introducer &
P4=$!
python -m src.server.start_full_node "127.0.0.1" 8002 -f &
P5=$!
python -m src.server.start_full_node "127.0.0.1" 8444 -t -u 8222 &
P6=$!
python -m src.server.start_full_node "127.0.0.1" 8005 &
P7=$!

_term() {
  echo "Caught SIGTERM signal, killing all servers."
  kill -TERM "$P1" 2>/dev/null
  kill -TERM "$P2" 2>/dev/null
  kill -TERM "$P3" 2>/dev/null
  kill -TERM "$P4" 2>/dev/null
  kill -TERM "$P5" 2>/dev/null
  kill -TERM "$P6" 2>/dev/null
  kill -TERM "$P7" 2>/dev/null
  _kill_servers
}

trap _term SIGTERM
trap _term SIGINT
trap _term INT
wait $P1 $P2 $P3 $P4 $P5 $P6 $P7
