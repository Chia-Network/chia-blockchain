import React from "react";
import ReactDOM from "react-dom";
import { BrowserRouter as Router, Route } from "react-router-dom";
import { Provider } from "react-redux";
import App from "./App";
import "./assets/css/App.css";
import store from "./modules/store";
import WebSocketConnection from "./hocs/WebsocketConnection";
import { exit_and_close } from "./modules/message";
import isElectron from "is-electron";

const url = require("url");
const config = require("./util/config");
const parseArgs = require("minimist");

const Root = ({ store }) => {
  return (
    <Provider store={store}>
      <WebSocketConnection>
        <Router>
          <Route path="/" component={App} />
        </Router>
      </WebSocketConnection>
    </Provider>
  );
};

ReactDOM.render(<Root store={store} />, document.getElementById("root"));
