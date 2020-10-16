import reduxThunk from "redux-thunk";
import { createStore, applyMiddleware, compose } from "redux";
import rootReducer from "./reducers";
import wsMiddleware from "../middleware/middleware";
import isElectron from "is-electron";
import dev_config from "../dev_config";

const middleware = [reduxThunk, wsMiddleware];

const store =
  isElectron() && !dev_config.redux_tool
    ? createStore(rootReducer, compose(applyMiddleware(...middleware)))
    : createStore(
        rootReducer,
        compose(
          applyMiddleware(...middleware),  /* preloadedState, */
          window.__REDUX_DEVTOOLS_EXTENSION_COMPOSE__ && window.__REDUX_DEVTOOLS_EXTENSION_COMPOSE__()
        )
      );

export default store;
