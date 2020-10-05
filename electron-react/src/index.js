import React from "react";
import ReactDOM from "react-dom";
import { BrowserRouter as Router, Route } from "react-router-dom";
import { Provider } from "react-redux";
import App from "./App";
import "./assets/css/App.css";
import store from "./modules/store";
import WebSocketConnection from "./hocs/WebsocketConnection";

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
