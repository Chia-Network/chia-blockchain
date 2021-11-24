import { createApi } from '@reduxjs/toolkit/query/react';
import { FullNode } from '@chia/api';
import type { Block, BlockRecord, BlockHeader, BlockchainState, FullNodeConnection } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';

const baseQuery = chiaLazyBaseQuery({
  service: FullNode,
});

export const fullNodeApi = createApi({
  reducerPath: 'fullNodeApi',
  baseQuery,
  tagTypes: ['BlockchainState', 'FullNodeConnections'],
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
      transformResponse: (response: any) => response?.blockchainState,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onBlockchainState',
        onUpdate: (draft, data) => Object.assign(draft, {
          ...data.blockchainState,
        }),
      }]),
    }),
    getConnections: build.query<FullNodeConnection[], undefined>({
      query: () => ({
        command: 'getConnections',
      }),
      transformResponse: (response: any) => response?.connections,
      providesTags: (connections) => connections
      ? [
        ...connections.map(({ nodeId }) => ({ type: 'FullNodeConnections', id: nodeId } as const)),
        { type: 'FullNodeConnections', id: 'LIST' },
      ] 
      :  [{ type: 'FullNodeConnections', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onConnections',
        onUpdate: (draft, data) => {
          // empty base array
          draft.splice(0);

          // assign new items
          Object.assign(draft, data.connections);
        },
      }]),
    }),
    openConnection: build.mutation<FullNodeConnection, { 
      host: string;
      port: number;
    }>({
      query: ({ host, port }) => ({
        command: 'openConnection',
        args: [host, port],
      }),
      invalidatesTags: [{ type: 'FullNodeConnections', id: 'LIST' }],
    }),
    closeConnection: build.mutation<FullNodeConnection, { 
      nodeId: number;
    }>({
      query: ({ nodeId }) => ({
        command: 'closeConnection',
        args: [nodeId],
      }),
      invalidatesTags: (_result, _error, { nodeId }) => [{ type: 'FullNodeConnections', id: 'LIST' }, { type: 'FullNodeConnections', id: nodeId }],
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
  }),
});

export const { 
  useGetBlockRecordsQuery,
  useGetUnfinishedBlockHeadersQuery,
  useGetBlockchainStateQuery,
  useGetConnectionsQuery,
  useOpenConnectionMutation,
  useCloseConnectionMutation,
  useGetBlockQuery,
  useGetBlockRecordQuery,
} = fullNodeApi;
