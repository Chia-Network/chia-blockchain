import { createApi } from '@reduxjs/toolkit/query/react';
import { Daemon } from '@chia/api';
import type { KeyringStatus, ServiceName } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';

const baseQuery = chiaLazyBaseQuery({
  service: Daemon,
});

export const daemonApi = createApi({
  reducerPath: 'daemonApi',
  baseQuery,
  tagTypes: ['KeyringStatus', 'ServiceRunning'],
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

    isServiceRunning: build.query<KeyringStatus, {
      service: ServiceName;
    }>({
      query: ({ service }) => ({
        command: 'isRunning',
        args: [service],
      }),
      transformResponse: (response: any) => response?.isRunning,
      providesTags: (_result, _err, { service }) => [{ type: 'ServiceRunning', id: service }],
    }),
  
    setKeyringPassphrase: build.mutation<boolean, {
      currentPassphrase?: string, 
      newPassphrase?: string;
      passphraseHint?: string, 
      savePassphrase?: boolean,
    }>({
      query: ({ currentPassphrase, newPassphrase, passphraseHint, savePassphrase }) => ({
        command: 'setKeyringPassphrase',
        args: [currentPassphrase, newPassphrase, passphraseHint, savePassphrase],
      }),
      invalidatesTags: () => ['KeyringStatus'],
      transformResponse: (response: any) => response?.success,
    }), 

    removeKeyringPassphrase: build.mutation<boolean, {
      currentPassphrase: string;
    }>({
      query: ({ currentPassphrase }) => ({
        command: 'removeKeyringPassphrase',
        args: [currentPassphrase],
      }),
      invalidatesTags: () => ['KeyringStatus'],
      transformResponse: (response: any) => response?.success,
    }),
  }),
});

export const { 
  useGetKeyringStatusQuery,
  useIsServiceRunningQuery,
  useSetKeyringPassphraseMutation,
  useRemoveKeyringPassphraseMutation,
} = daemonApi;
