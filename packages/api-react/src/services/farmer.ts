import { createApi } from '@reduxjs/toolkit/query/react';
import { Farmer } from '@chia/api';
import type { Plot, FarmerConnection, RewardTargets, SignagePoint, Pool } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';

const baseQuery = chiaLazyBaseQuery({
  service: Farmer,
});

export const farmerApi = createApi({
  reducerPath: 'farmerApi',
  baseQuery,
  tagTypes: ['Harvesters', 'RewardTargets', 'FarmerConnections', 'SignagePoints', 'PoolLoginLinks', 'Pools', 'PayoutInstructions'],
  endpoints: (build) => ({
    getHarvesters: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getHarvesters',
      }),
      transformResponse: (response: any) => response?.harvesters,
      providesTags: (harvesters) => harvesters
        ? [
          ...harvesters.map(({ id }) => ({ type: 'Harvesters', id } as const)),
          { type: 'Harvesters', id: 'LIST' },
        ] 
        :  [{ type: 'Harvesters', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onRefreshPlots',
        endpoint: () => farmerApi.endpoints.getHarvesters,
      }]),
    }),

    getRewardTargets: build.query<undefined, { 
      searchForPrivateKey: boolean; 
    }>({
      query: ({ searchForPrivateKey }) => ({
        command: 'getRewardTargets',
        args: [searchForPrivateKey],
      }),
      // transformResponse: (response: any) => response,
      providesTags: ['RewardTargets']
    }),

    setRewardTargets: build.mutation<RewardTargets, { 
      farmerTarget: string;
      poolTarget: string;
    }>({
      query: ({ farmerTarget, poolTarget }) => ({
        command: 'setRewardTargets',
        args: [farmerTarget, poolTarget],
      }),
      invalidatesTags: ['RewardTargets'],
    }),

    getConnections: build.query<FarmerConnection[], undefined>({
      query: () => ({
        command: 'getConnections',
      }),
      transformResponse: (response: any) => response?.connections,
      providesTags: (connections) => connections
        ? [
          ...connections.map(({ nodeId }) => ({ type: 'FarmerConnections', id: nodeId } as const)),
          { type: 'FarmerConnections', id: 'LIST' },
        ] 
        :  [{ type: 'FarmerConnections', id: 'LIST' }],
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
    openConnection: build.mutation<FarmerConnection, { 
      host: string;
      port: number;
    }>({
      query: ({ host, port }) => ({
        command: 'openConnection',
        args: [host, port],
      }),
      invalidatesTags: [{ type: 'FarmerConnections', id: 'LIST' }],
    }),
    closeConnection: build.mutation<FarmerConnection, { 
      nodeId: number;
    }>({
      query: ({ nodeId }) => ({
        command: 'closeConnection',
        args: [nodeId],
      }),
      invalidatesTags: (_result, _error, { nodeId }) => [{ type: 'FarmerConnections', id: 'LIST' }, { type: 'FarmerConnections', id: nodeId }],
    }),

    getPoolLoginLink: build.query<string, { 
      launcherId: string;
    }>({
      query: ({ launcherId }) => ({
        command: 'getPoolLoginLink',
        args: [launcherId],
      }),
      transformResponse: (response: any) => response?.loginLink,
      providesTags: (launcherId) => [{ type: 'PoolLoginLinks', id: launcherId }],
      // TODO invalidate when join pool/change pool
    }),

    getSignagePoints: build.query<SignagePoint[], undefined>({
      query: () => ({
        command: 'getSignagePoints',
      }),
      transformResponse: (response: any) => response?.signagePoints,
      providesTags: (signagePoints) => signagePoints
        ? [
          ...signagePoints.map(({ signagePoint }) => ({ type: 'SignagePoints', id: signagePoint?.challengeHash } as const)),
          { type: 'SignagePoints', id: 'LIST' },
        ] 
        :  [{ type: 'SignagePoints', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onNewSignagePoint',
        onUpdate: (draft, data) => {
          const { signagePoint } = data;

          console.log('onNewSignagePoint', data, draft);
          draft.unshift(signagePoint);
        },
      }]),
    }),

    getPoolState: build.query<Pool[], undefined>({
      query: () => ({
        command: 'getPoolState',
      }),
      transformResponse: (response: any) => response?.poolState,
      providesTags: (poolsList) => poolsList
        ? [
          ...poolsList.map(({ p2SingletonPuzzleHash }) => ({ type: 'Pools', id: p2SingletonPuzzleHash } as const)),
          { type: 'Pools', id: 'LIST' },
        ] 
        :  [{ type: 'Pools', id: 'LIST' }],
    }),

    setPayoutInstructions: build.mutation<undefined, { 
      launcherId: string;
      payoutInstructions: string;
    }>({
      query: ({ launcherId, payoutInstructions }) => ({
        command: 'setPayoutInstructions',
        args: [launcherId, payoutInstructions],
      }),
      invalidatesTags: (_result, _error, { launcherId }) => [{ type: 'PayoutInstructions', id: launcherId }],
    }),
  }),
});

// TODO add new farming info query and event for last_attepmtp_proofs

export const { 
  useGetHarvestersQuery,
  useGetRewardTargetsQuery,
  useSetRewardTargetsMutation,
  useGetConnectionsQuery,
  useOpenConnectionMutation,
  useCloseConnectionMutation,
  useGetPoolLoginLinkQuery,
  useGetSignagePointsQuery,
  useGetPoolStateQuery,
  useSetPayoutInstructionsMutation,
} = farmerApi;
