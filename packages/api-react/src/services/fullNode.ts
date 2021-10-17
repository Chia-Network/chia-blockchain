import { createApi } from '@reduxjs/toolkit/query/react';
import { FullNode } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';

import type Block from '../@types/Block';
import type BlockRecord from '../@types/BlockRecord';
import type BlockHeader from '../@types/BlockHeader';
import type BlockchainState from '../@types/BlockchainState';
import type BlockchainConnection from '../@types/BlockchainConnection';

const baseQuery = chiaLazyBaseQuery({
  service: FullNode,
});

export const fullNodeApi = createApi({
  reducerPath: 'fullNodeApi',
  baseQuery,
  tagTypes: ['BlockchainState'],
  endpoints: (build) => ({
    getBlockRecords: build.query<BlockRecord[], { 
      end: number; 
      count?: number;
    }>({
      query: ({ end, count }) => ({
        command: 'getBlockRecords',
        args: [end, count],
      }),
      // transformResponse: (response: PostResponse) => response.data.post,
    }),
    getUnfinishedBlockHeaders: build.query<BlockHeader[], undefined>({
      query: () => ({
        command: 'getUnfinishedBlockHeaders',
      }),
      // transformResponse: (response: PostResponse) => response.data.post,
    }),
    getBlockchainState: build.query<BlockchainState, undefined>({
      query: () => ({
        command: 'getBlockchainState',
      }),
      providesTags: ['BlockchainState'],
      async onCacheEntryAdded(_arg, api) {
        const { updateCachedData, cacheDataLoaded, cacheEntryRemoved } = api;
        let unsubscribe;
        try {
          await cacheDataLoaded;

          const response = await baseQuery({
            command: 'onBlockchainState',
            args: [(data: any) => {
              updateCachedData((draft) => {
                Object.assign(draft, {
                  ...data.blockchainState,
                });
              });
            }],
          }, api, {});

          unsubscribe = response.data;
        } finally {
          await cacheEntryRemoved;
          if (unsubscribe) {
            unsubscribe();
          }
        }
      },
      transformResponse: (response: any) => response?.blockchainState,
    }),
    getConnections: build.query<BlockchainConnection[], undefined>({
      query: () => ({
        command: 'getConnections',
      }),
      transformResponse: (response: any) => response?.connections,
      async onCacheEntryAdded(_arg, api) {
        const { updateCachedData, cacheDataLoaded, cacheEntryRemoved } = api;
        let unsubscribe;
        try {
          await cacheDataLoaded;

          const response = await baseQuery({
            command: 'onConnections',
            args: [(data: any) => {
              updateCachedData((draft) => {
                Object.assign(draft, data.connections);
              });
            }],
          }, api, {});

          unsubscribe = response.data;
        } finally {
          await cacheEntryRemoved;
          if (unsubscribe) {
            unsubscribe();
          }
        }
      },
    }),
    getBlock: build.query<Block, { 
      headerHash: string;
    }>({
      query: ({ headerHash }) => ({
        command: 'getBlock',
        args: [headerHash],
      }),
      // transformResponse: (response: PostResponse) => response.data.post,
    }),
    getBlockRecord: build.query<BlockRecord, { 
      headerHash: string;
    }>({
      query: ({ headerHash }) => ({
        command: 'getBlockRecord',
        args: [headerHash],
      }),
      // transformResponse: (response: PostResponse) => response.data.post,
    }),
    openConnection: build.mutation<BlockchainConnection, { 
      host: string;
      port: number;
    }>({
      query: ({ host, port }) => ({
        command: 'openConnection',
        args: [host, port],
      }),
      invalidatesTags: ['FullNodeConnection'],
    }),
    closeConnection: build.mutation<BlockchainConnection, { 
      nodeId: number;
    }>({
      query: ({ nodeId }) => ({
        command: 'closeConnection',
        args: [nodeId],
      }),
      invalidatesTags: ['FullNodeConnection'],
    }),
  }),
});

export const { 
  useGetBlockRecordsQuery,
  useGetUnfinishedBlockHeadersQuery,
  useGetBlockchainStateQuery,
  useGetConnectionsQuery,
  useGetBlockQuery,
  useGetBlockRecordQuery,
  useOpenConnectionMutation,
  useCloseConnectionMutation,
} = fullNodeApi;
