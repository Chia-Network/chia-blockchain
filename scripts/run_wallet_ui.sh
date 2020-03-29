. ./activate

# Starts a wallet UI
chia-websocket-server &
npm run --prefix ./electron-ui start

wait
