. ./activate

_restart_harvester_servers() {
  PROCS=`ps -e | grep -E 'chia_harvester' | awk '!/grep/' | awk '{print $1}'`
  if [ -n "$PROCS" ]; 
  then
    echo "Shutting down harvesters"
    echo "$PROCS" | xargs -L1 kill
    echo "Restarting harvesters"
    _run_bg_cmd python -m src.server.start_harvester
  else
    echo "No running harvesters found"
  fi
}

BG_PIDS=""
_run_bg_cmd() {
  "$@" &
  BG_PIDS="$BG_PIDS $!"
}

_restart_harvester_servers

_term() {
  echo "Caught TERM or INT signal, killing all servers."
  for PID in $BG_PIDS; do
    kill -TERM "$PID"
  done
  _kill_servers
}

trap _term TERM
trap _term INT
