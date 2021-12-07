import { Farmer } from '@chia/api';
import type { Plot, FarmerConnection, RewardTargets, SignagePoint, Pool, FarmingInfo } from '@chia/api';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import api, { baseQuery } from '../api';

export const apiWithTag = api.enhanceEndpoints({addTagTypes: ['Harvesters', 'RewardTargets', 'FarmerConnections', 'SignagePoints', 'PoolLoginLink', 'Pools', 'PayoutInstructions']})

export const farmerApi = apiWithTag.injectEndpoints({
  endpoints: (build) => ({
    ping: build.query<boolean, {
    }>({
      query: () => ({
        command: 'ping',
        service: Farmer,
      }),
      transformResponse: (response: any) => response?.success,
    }),

    getHarvesters: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getHarvesters',
        service: Farmer,
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
        service: Farmer,
        endpoint: () => farmerApi.endpoints.getHarvesters,
      }]),
    }),

    getRewardTargets: build.query<undefined, { 
      searchForPrivateKey: boolean; 
    }>({
      query: ({ searchForPrivateKey }) => ({
        command: 'getRewardTargets',
        service: Farmer,
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
        service: Farmer,
        args: [farmerTarget, poolTarget],
      }),
      invalidatesTags: ['RewardTargets'],
    }),

    getConnections: build.query<FarmerConnection[], undefined>({
      query: () => ({
        command: 'getConnections',
        service: Farmer,
      }),
      transformResponse: (response: any) => response?.connections,
      providesTags: (connections) => connections
        ? [
          ...connections.map(({ nodeId }) => ({ type: 'FarmerConnections', id: nodeId } as const)),
          { type: 'FarmerConnections', id: 'LIST' },
        ] 
        : [{ type: 'FarmerConnections', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onConnections',
        service: Farmer,
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
        service: Farmer,
        args: [host, port],
      }),
      invalidatesTags: [{ type: 'FarmerConnections', id: 'LIST' }],
    }),
    closeConnection: build.mutation<FarmerConnection, { 
      nodeId: string;
    }>({
      query: ({ nodeId }) => ({
        command: 'closeConnection',
        service: Farmer,
        args: [nodeId],
      }),
      invalidatesTags: (_result, _error, { nodeId }) => [{ type: 'FarmerConnections', id: 'LIST' }, { type: 'FarmerConnections', id: nodeId }],
    }),

    getPoolLoginLink: build.query<string, { 
      launcherId: string;
    }>({
      query: ({ launcherId }) => ({
        command: 'getPoolLoginLink',
        service: Farmer,
        args: [launcherId],
      }),
      transformResponse: (response: any) => response?.loginLink,
      providesTags: (launcherId) => [{ type: 'PoolLoginLink', id: launcherId }],
      // TODO invalidate when join pool/change pool
    }),

    getSignagePoints: build.query<SignagePoint[], undefined>({
      query: () => ({
        command: 'getSignagePoints',
        service: Farmer,
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
        service: Farmer,
        onUpdate: (draft, data) => {
          draft.unshift(data);
        },
      }]),
    }),

    getPoolState: build.query<Pool[], undefined>({
      query: () => ({
        command: 'getPoolState',
        service: Farmer,
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
        service: Farmer,
        args: [launcherId, payoutInstructions],
      }),
      invalidatesTags: (_result, _error, { launcherId }) => [{ type: 'PayoutInstructions', id: launcherId }],
    }),

    getFarmingInfo: build.query<FarmingInfo[], {
    }>({
      query: () => ({
        command: 'getFarmingInfo',
        service: Farmer,
      }),
      // transformResponse: (response: any) => response,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onFarmingInfoChanged',
        service: Farmer,
        endpoint: () => farmerApi.endpoints.getFarmingInfo,
      }]),
    }),
  }),
});

// TODO add new farming info query and event for last_attepmtp_proofs

export const { 
  usePingQuery,
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
  useGetFarmingInfoQuery,
} = farmerApi;
