import reduxThunk from "redux-thunk";
import { createStore, applyMiddleware, compose } from "redux";
import rootReducer from "./reducers";
import wsMiddleware from "../middleware/middleware";
import isElectron from "is-electron";
import dev_config from "../dev_config";

const middleware = [reduxThunk, wsMiddleware];

const store =
  // when using electron wo redux or wo electron (ie in the browser) don't pass extensions to the composer
  (isElectron() && !dev_config.redux_tool) || !isElectron()
    ? createStore(rootReducer, compose(applyMiddleware(...middleware)))
    : createStore(
      rootReducer,
      compose(
        applyMiddleware(...middleware),
        window.__REDUX_DEVTOOLS_EXTENSION__ &&
        window.__REDUX_DEVTOOLS_EXTENSION__()
      )
    );

export default store;
