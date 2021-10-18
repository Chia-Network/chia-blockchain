import { configureStore, ConfigureStoreOptions } from '@reduxjs/toolkit';
import { TypedUseSelectorHook, useDispatch, useSelector } from 'react-redux';
import { clientApi } from './services/client';
import { fullNodeApi } from './services/fullNode';
import { walletApi } from './services/wallet';
import apiReducer from './slices/api';

export function createStore(options?: ConfigureStoreOptions['preloadedState']) {
  return configureStore({
    reducer: {
      [clientApi.reducerPath]: clientApi.reducer,
      [fullNodeApi.reducerPath]: fullNodeApi.reducer,
      [walletApi.reducerPath]: walletApi.reducer,
      api: apiReducer,
    },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        serializableCheck: false,
      }).concat(
        clientApi.middleware,
        fullNodeApi.middleware,
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
