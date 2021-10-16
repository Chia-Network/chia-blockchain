import { createApi } from '@reduxjs/toolkit/query/react';
import { FullNode } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';

import type Block from '../@types/Block';
import type BlockRecord from '../@types/BlockRecord';
import type BlockHeader from '../@types/BlockHeader';
import type BlockchainState from '../@types/BlockchainState';
import type BlockchainConnection from '../@types/BlockchainConnection';

export const fullNodeApi = createApi({
  reducerPath: 'fullNodeApi',
  baseQuery: chiaLazyBaseQuery({
    service: FullNode,
  }),
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
      async onCacheEntryAdded(
        arg,
        { updateCachedData, cacheDataLoaded, cacheEntryRemoved },
      ) {
        /*
        console.log('lalala', arg, rest, rest2, this, build);

        fullNodeApi.util.
        try {
          await cacheDataLoaded;

          updateCachedData((draft) => {
            Object.assign(draft, {
              added: 1,
            });
          });
        } finally {
          await cacheEntryRemoved;
          ws.close();
        }
        */
      },
      // transformResponse: (response: PostResponse) => response.data.post,
    }),
    getConnections: build.query<BlockchainConnection[]>({
      query: () => ({
        command: 'getConnections',
      }),
      // transformResponse: (response: PostResponse) => response.data.post,
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
