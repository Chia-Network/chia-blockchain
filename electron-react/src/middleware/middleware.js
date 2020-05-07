import * as actions from '../modules/websocket';
import { format_message, incomingMessage } from '../modules/message';
import { handle_message} from './middleware_api'

const socketMiddleware = () => {
  let socket = null;
  let connected = false

  const onOpen = store => (event) => {
    store.dispatch(actions.wsConnected(event.target.url));
    var action = format_message("start_server", "{wallet_id: 1}")
    store.dispatch(action);
    console.log("Start Server")
  };

  const onClose = store => () => {
    store.dispatch(actions.wsDisconnected());
  };

  const onMessage = store => (event) => {
    const payload = JSON.parse(event.data);
    handle_message(store, payload)
  };

  return store => next => (action) => {
    switch (action.type) {
      case 'WS_CONNECT':
        if (socket !== null) {
          socket.close();
        }

        // connect to the remote host
        socket = new WebSocket(action.host);

        // websocket handlers
        socket.onmessage = onMessage(store);
        socket.onclose = onClose(store);
        socket.onopen = onOpen(store);
        connected = true
        break;
      case 'WS_DISCONNECT':
        if (socket !== null) {
          socket.close();
        }
        socket = null;
        break;
      case 'OUTGOING_MESSAGE':
        if (connected) {
          console.log("socket" + socket)
          console.log("Action command" + action.command + " data" + action.data)
          socket.send(JSON.stringify({ command: action.command, data: action.data }));
        } else {
          console.log("Socket not connected")
        }
        break;
      default:
        return next(action);
    }
  };
};

export default socketMiddleware();
