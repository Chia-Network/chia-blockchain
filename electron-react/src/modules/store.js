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
          applyMiddleware(...middleware),
          window.__REDUX_DEVTOOLS_EXTENSION__ &&
            window.__REDUX_DEVTOOLS_EXTENSION__()
        )
      );

export default store;
