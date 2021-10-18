import { createApi } from '@reduxjs/toolkit/query/react';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';

const baseQuery = chiaLazyBaseQuery();

export const clientApi = createApi({
  reducerPath: 'fullNodeApi',
  baseQuery,
  tagTypes: ['BlockchainState'],
  endpoints: (build) => ({
    close: build.mutation<boolean, {
      force?: boolean;
    }>({
      query: ({ force }) => ({
        command: 'close',
        client: true,
        args: [force]
      }),
    }),
  }),
});

export const { 
  useCloseMutation,
} = clientApi;
