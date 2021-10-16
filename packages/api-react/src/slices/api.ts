import { createSlice, PayloadAction } from '@reduxjs/toolkit';

type Config = {
  url: string;
  cert: string;
  key: string;
  webSocket: any;
};

const initialState = {} as { 
  config?: Config;
};

const apiSlice = createSlice({
  name: 'api',
  initialState,
  reducers: {
    initializeConfig: (state, action: PayloadAction<Config>) => {
      state.config = action.payload;
    },
  },
});

export const { initializeConfig } = apiSlice.actions;

export const selectApiConfig = (state: any) => state.api.config;

export default apiSlice.reducer;
