_kill_servers() {
  PROCS=`ps -e | grep -E 'chia_|vdf_server' | awk '{print $1}'`
  if [ -n "$PROCS" ]; then
    echo "$PROCS" | xargs -L1 kill
  fi
}

_kill_servers

BG_PIDS=""
_run_bg_cmd() {
  "$@" &
  BG_PIDS="$BG_PIDS $!"
}


_term() {
  echo "Caught TERM or INT signal, killing all servers."
  for PID in $BG_PIDS; do
    kill -TERM "$PID"
  done
  _kill_servers
}

trap _term TERM
trap _term INT
