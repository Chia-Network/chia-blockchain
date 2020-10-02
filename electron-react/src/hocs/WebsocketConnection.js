import { useDispatch, useSelector } from "react-redux";
import { wsConnect, wsConnecting } from "../modules/websocket";

const WebSocketConnection = props => {
  const dispatch = useDispatch();
  const connected = useSelector(state => state.websocket.connected);
  const connecting = useSelector(state => state.websocket.connecting);
  const host = useSelector(state => state.daemon_state.daemon_host);

  var timeout = null;

  function connect(host) {
    timeout = setTimeout(() => {
      dispatch(wsConnect(host));
    }, 300);
  }

  if (!timeout && !connected && !connecting) {
    dispatch(wsConnecting());
    connect(host);
  }

  return props.children;
};

export default WebSocketConnection;
