ps -e | grep python | awk '{print $1}' | xargs -L1  kill
ps -e | grep "vdf_server" | awk '{print $1}' | xargs -L1  kill
