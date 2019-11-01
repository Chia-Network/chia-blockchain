_kill_servers() {
  ps -e | grep python | grep "start_" | awk '{print $1}' | xargs -L1  kill -9
  ps -e | grep "fast_vdf/server" | awk '{print $1}' | xargs -L1  kill -9
}

_kill_servers

python -m src.server.start_plotter &
P1=$!
python -m src.server.start_timelord &
P2=$!
python -m src.server.start_farmer &
P3=$!
python -m src.server.start_full_node "127.0.0.1" 8002 -f &
P4=$!
python -m src.server.start_full_node "127.0.0.1" 8004 -t -u 8222 &
P5=$!
python -m src.server.start_full_node "127.0.0.1" 8005 &
P6=$!

_term() {
  echo "Caught SIGTERM signal, killing all servers."
  kill -TERM "$P1" 2>/dev/null
  kill -TERM "$P2" 2>/dev/null
  kill -TERM "$P3" 2>/dev/null
  kill -TERM "$P4" 2>/dev/null
  kill -TERM "$P5" 2>/dev/null
  kill -TERM "$P6" 2>/dev/null
  _kill_servers
}

trap _term SIGTERM
trap _term SIGINT
trap _term INT
wait $P1 $P2 $P3 $P4 $P5 $P6
