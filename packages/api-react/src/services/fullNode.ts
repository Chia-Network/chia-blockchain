import { FullNode } from '@chia/api';
import type { Block, BlockRecord, BlockHeader, BlockchainState, FullNodeConnection } from '@chia/api';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import api, { baseQuery } from '../api';

const apiWithTag = api.enhanceEndpoints({addTagTypes: ['BlockchainState', 'FeeEstimate', 'FullNodeConnections']})

export const fullNodeApi = apiWithTag.injectEndpoints({
  endpoints: (build) => ({
    fullNodePing: build.query<boolean, {
    }>({
      query: () => ({
        command: 'ping',
        service: FullNode,
      }),
      transformResponse: (response: any) => response?.success,
    }),

    getBlockRecords: build.query<BlockRecord[], {
      start?: number;
      end?: number;
    }>({
      query: ({ start, end }) => ({
        command: 'getBlockRecords',
        service: FullNode,
        args: [start, end],
      }),
      transformResponse: (response: any) => response?.blockRecords,
    }),
    getUnfinishedBlockHeaders: build.query<BlockHeader[], undefined>({
      query: () => ({
        command: 'getUnfinishedBlockHeaders',
        service: FullNode,
      }),
      transformResponse: (response: any) => response?.headers,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onBlockchainState',
        service: FullNode,
        endpoint: () => fullNodeApi.endpoints.getUnfinishedBlockHeaders,
      }]),
    }),
    getBlockchainState: build.query<BlockchainState, undefined>({
      query: () => ({
        command: 'getBlockchainState',
        service: FullNode,
      }),
      providesTags: ['BlockchainState'],
      transformResponse: (response: any) => response?.blockchainState,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onBlockchainState',
        service: FullNode,
        onUpdate: (draft, data) => Object.assign(draft, {
          ...data.blockchainState,
        }),
      }]),
    }),
    getFullNodeConnections: build.query<FullNodeConnection[], undefined>({
      query: () => ({
        command: 'getConnections',
        service: FullNode,
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
        service: FullNode,
        onUpdate: (draft, data) => {
          // empty base array
          draft.splice(0);

          // assign new items
          Object.assign(draft, data.connections);
        },
      }]),
    }),
    openFullNodeConnection: build.mutation<FullNodeConnection, {
      host: string;
      port: number;
    }>({
      query: ({ host, port }) => ({
        command: 'openConnection',
        service: FullNode,
        args: [host, port],
      }),
      invalidatesTags: [{ type: 'FullNodeConnections', id: 'LIST' }],
    }),
    closeFullNodeConnection: build.mutation<FullNodeConnection, {
      nodeId: string;
    }>({
      query: ({ nodeId }) => ({
        command: 'closeConnection',
        service: FullNode,
        args: [nodeId],
      }),
      invalidatesTags: (_result, _error, { nodeId }) => [{ type: 'FullNodeConnections', id: 'LIST' }, { type: 'FullNodeConnections', id: nodeId }],
    }),
    getBlock: build.query<Block, {
      headerHash: string;
    }>({
      query: ({ headerHash }) => ({
        command: 'getBlock',
        service: FullNode,
        args: [headerHash],
      }),
      transformResponse: (response: any) => response?.block,
    }),
    getBlockRecord: build.query<BlockRecord, {
      headerHash: string;
    }>({
      query: ({ headerHash }) => ({
        command: 'getBlockRecord',
        service: FullNode,
        args: [headerHash],
      }),
      transformResponse: (response: any) => response?.blockRecord,
    }),
    getFeeEstimate: build.query<string, {
      targetTimes: number[];
      cost: number;
    }>({
      query: ({
        targetTimes,
        cost,
      }) => ({
        command: 'getFeeEstimate',
        service: FullNode,
        args: [targetTimes, cost],
      }),
      providesTags: [{ type: 'FeeEstimate' }],
    }),
  }),
});

export const {
  useFullNodePingQuery,
  useGetBlockRecordsQuery,
  useGetUnfinishedBlockHeadersQuery,
  useGetBlockchainStateQuery,
  useGetFullNodeConnectionsQuery,
  useOpenFullNodeConnectionMutation,
  useCloseFullNodeConnectionMutation,
  useGetBlockQuery,
  useGetBlockRecordQuery,
  useGetFeeEstimateQuery,
} = fullNodeApi;
