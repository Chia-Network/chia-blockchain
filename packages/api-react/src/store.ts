import { configureStore, ConfigureStoreOptions } from '@reduxjs/toolkit';
import { TypedUseSelectorHook, useDispatch, useSelector } from 'react-redux';
import { clientApi } from './services/client';
import { daemonApi } from './services/daemon';
import { farmerApi } from './services/farmer';
import { fullNodeApi } from './services/fullNode';
import { harvesterApi } from './services/harvester';
import { plotterApi } from './services/plotter';
import { walletApi } from './services/wallet';
import apiReducer from './slices/api';

export function createStore(options?: ConfigureStoreOptions['preloadedState']) {
  return configureStore({
    reducer: {
      [clientApi.reducerPath]: clientApi.reducer,
      [daemonApi.reducerPath]: daemonApi.reducer,
      [farmerApi.reducerPath]: farmerApi.reducer,
      [fullNodeApi.reducerPath]: fullNodeApi.reducer,
      [harvesterApi.reducerPath]: harvesterApi.reducer,
      [plotterApi.reducerPath]: plotterApi.reducer,
      [walletApi.reducerPath]: walletApi.reducer,
      api: apiReducer,
    },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        serializableCheck: false,
      }).concat(
        clientApi.middleware,
        daemonApi.middleware,
        farmerApi.middleware,
        fullNodeApi.middleware,
        harvesterApi.middleware,
        plotterApi.middleware,
        walletApi.middleware,
      ),
    ...options,
  });
}

export const store = createStore();

export type AppDispatch = typeof store.dispatch;
export const useAppDispatch = () => useDispatch<AppDispatch>();
export type RootState = ReturnType<typeof store.getState>;
export const useTypedSelector: TypedUseSelectorHook<RootState> = useSelector;
