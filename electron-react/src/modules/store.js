import reduxThunk from 'redux-thunk';
import { createStore, applyMiddleware, compose } from 'redux';
import isElectron from 'is-electron';
import rootReducer from './rootReducer';
import wsMiddleware from '../middleware/middleware';
import dev_config from '../dev_config';
import { exit_and_close } from './message';

const middleware = [reduxThunk, wsMiddleware];

const store =
  isElectron() && !dev_config.redux_tool
    ? createStore(rootReducer, compose(applyMiddleware(...middleware)))
    : createStore(
        rootReducer,
        compose(
          applyMiddleware(...middleware),  /* preloadedState, */
          window.__REDUX_DEVTOOLS_EXTENSION_COMPOSE__ && window.__REDUX_DEVTOOLS_EXTENSION_COMPOSE__() || compose
        )
      );

window.onload = () => {
  if (isElectron()) {
    window.ipcRenderer.on('exit-daemon', (event) => {
      store.dispatch(exit_and_close(event));
    });
  }
};

export default store;
