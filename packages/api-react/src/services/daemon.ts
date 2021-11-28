import { createApi } from '@reduxjs/toolkit/query/react';
import { Daemon } from '@chia/api';
import type { KeyringStatus } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';

const baseQuery = chiaLazyBaseQuery({
  service: Daemon,
});

export const daemonApi = createApi({
  reducerPath: 'daemonApi',
  baseQuery,
  tagTypes: ['KeyringStatus'],
  endpoints: (build) => ({
    getKeyringStatus: build.query<KeyringStatus, {
    }>({
      query: () => ({
        command: 'keyringStatus',
      }),
      transformResponse: (response: any) => {
        const { status, ...rest } = response;

        return {
          ...rest,
        };
      },
      providesTags: ['KeyringStatus'],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onKeyringStatusChanged',
        onUpdate: (draft, data) => {
          // empty base array
          draft.splice(0);

          console.log('onKeyringStatusChanged get', data);
          const { status, ...rest } = data;

          // assign new items
          Object.assign(draft, rest);
        },
      }]),
    }),
  
    setKeyringPassphrase: build.mutation<Object, {
      newPassphrase: string;
    }>({
      query: ({ newPassphrase }) => ({
        command: 'setKeyringPassphrase',
        args: [newPassphrase],
      }),
      invalidatesTags: () => ['KeyringStatus'],
    }), 
  }),
});

export const { 
  useGetKeyringStatusQuery,
  useSetKeyringPassphraseMutation,
} = daemonApi;
