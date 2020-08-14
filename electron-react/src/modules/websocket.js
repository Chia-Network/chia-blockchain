export const wsConnect = host => ({ type: "WS_CONNECT", host });
export const wsConnecting = host => ({ type: "WS_CONNECTING", host });
export const wsConnected = host => ({ type: "WS_CONNECTED", host });
export const wsDisconnect = host => ({ type: "WS_DISCONNECT", host });
export const wsDisconnected = host => ({ type: "WS_DISCONNECTED", host });

const websocketInitialState = {
  connected: false,
  connecting: false
};

export const websocketReducer = (
  state = { ...websocketInitialState },
  action
) => {
  switch (action.type) {
    case "WS_CONNECTED":
      // console.log("connected now!");
      return {
        ...state,
        host: action.host,
        connected: true,
        connecting: false
      };
    case "WS_DISCONNECTED":
      return {
        ...state,
        host: action.host,
        connected: false,
        connecting: false
      };
    case "WS_CONNECTING":
      return { ...state, host: action.host, connecting: true };

    default:
      return state;
  }
};
