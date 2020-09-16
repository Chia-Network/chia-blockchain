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
const parseArgs = require('minimist');

const Root = ({ store }) => {
  return (
    <Provider store={store}>
      <WebSocketConnection host={getDaemonHost()}>
        <Router>
          <Route path="/" component={App} />
        </Router>
      </WebSocketConnection>
    </Provider>
  )
};

ReactDOM.render(<Root store={store} />, document.getElementById("root"));

window.onload = () => {
  var title = "Chia Blockchain"
  if (!config.isLocalHost()) {
    title += " - [" + config.getDaemonHost() + "]";
  }
  window.document.title = title;

  if (isElectron()) {
    window.ipcRenderer.on("exit-daemon", (event, ...args) => {
      store.dispatch(exit_and_close(event));
    });
  }
};

function getDaemonHost() {
  if (isElectron()) {
    // leave this here - it breaks loading if declared at the module level
    const remote = window.require('electron').remote;

    // see if the Main process got the selfHostName on the command line  
    // so the Render process can set the correct HTML document title
    const argv = parseArgs(remote.process.argv.slice(1));
    if (argv.selfHostName) {
      config.setSelfHostName(argv.selfHostName);
    }
  }
  else {
    // if the host name was passed on the url, update the config    
    var query = url.parse(window.document.URL, true).query;
    if (query && query.selfHostName) {
      config.setSelfHostName(query.selfHostName);
    }
  }

  return config.getDaemonHost();
}
