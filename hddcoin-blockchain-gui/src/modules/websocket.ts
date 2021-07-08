export const wsConnect = (host: string) => ({ type: 'WS_CONNECT', host });
export const wsConnecting = (host: string) => ({ type: 'WS_CONNECTING', host });
export const wsConnected = (host: string) => ({ type: 'WS_CONNECTED', host });
export const wsDisconnect = (host: string) => ({ type: 'WS_DISCONNECT', host });
export const wsDisconnected = (host: string) => ({
  type: 'WS_DISCONNECTED',
  host,
});

type WebsocketState = {
  connected: boolean;
  connecting: boolean;
  host?: string;
};

const initialState: WebsocketState = {
  connected: false,
  connecting: false,
};

export default function websocketReducer(
  state = { ...initialState },
  action: any,
): WebsocketState {
  switch (action.type) {
    case 'WS_CONNECTED':
      return {
        ...state,
        host: action.host,
        connected: true,
        connecting: false,
      };
    case 'WS_DISCONNECTED':
      return {
        ...state,
        host: action.host,
        connected: false,
        connecting: false,
      };
    case 'WS_CONNECTING':
      return {
        ...state,
        host: action.host,
        connecting: true,
      };
    default:
      return state;
  }
}
