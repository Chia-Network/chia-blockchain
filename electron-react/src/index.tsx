import React from "react";
import ReactDOM from "react-dom";
import { BrowserRouter as Router, Route } from "react-router-dom";
import { Provider } from "react-redux";
import App from "./components/App";
import "./assets/css/App.css";
import store from "./modules/store";
import WebSocketConnection from "./hocs/WebsocketConnection";
import { daemon_rpc_ws } from "./util/config";
import { exit_and_close } from "./modules/message";
import isElectron from "is-electron";

const Root = ({ store }) => (
  <Provider store={store}>
    <WebSocketConnection host={daemon_rpc_ws}>
      <Router>
        <Route path="/" component={App} />
      </Router>
    </WebSocketConnection>
  </Provider>
);

ReactDOM.render(<Root store={store} />, document.getElementById("root"));

window.onload = () => {
  if (isElectron()) {
    window.ipcRenderer.on("exit-daemon", (event, ...args) => {
      store.dispatch(exit_and_close(event));
    });
  }
};
