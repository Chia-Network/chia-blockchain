import { Farmer } from '@chia/api';
import type { Plot, FarmerConnection, RewardTargets, SignagePoint, Pool, FarmingInfo } from '@chia/api';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import api, { baseQuery } from '../api';

const MAX_SIGNAGE_POINTS = 500;
export const apiWithTag = api.enhanceEndpoints({addTagTypes: ['Harvesters', 'RewardTargets', 'FarmerConnections', 'SignagePoints', 'PoolLoginLink', 'Pools', 'PayoutInstructions', 'HarvesterPlots', 'HarvesterPlotsInvalid', 'HarvestersSummary', 'HarvesterPlotsKeysMissing', 'HarvesterPlotsDuplicates']})

export const farmerApi = apiWithTag.injectEndpoints({
  endpoints: (build) => ({
    farmerPing: build.query<boolean, {
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
        command: 'onHarvesterChanged',
        service: Farmer,
        endpoint: () => farmerApi.endpoints.getHarvesters,
      }]),
    }),

    getHarvestersSummary: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getHarvestersSummary',
        service: Farmer,
      }),
      transformResponse: (response: any) => response?.harvesters,
      providesTags: (harvesters) => harvesters
        ? [
          ...harvesters.map(({ id }) => ({ type: 'HarvestersSummary', id } as const)),
          { type: 'HarvestersSummary', id: 'LIST' },
        ]
        :  [{ type: 'HarvestersSummary', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onHarvesterUpdated',
        service: Farmer,
        onUpdate(draft, data) {
          const { connection: { nodeId } } = data;

          const index = draft.findIndex((harvester) => harvester.connection.nodeId === nodeId);
          if (index !== -1) {
            draft[index] = data;
          } else {
            draft.push(data);
          }
        }
      }, {
        command: 'onHarvesterRemoved',
        service: Farmer,
        onUpdate(draft, data) {
          const { nodeId } = data;

          const index = draft.findIndex((harvester) => harvester.connection.nodeId === nodeId);
          if (index !== -1) {
            draft.splice(index, 1);
          }
        }
      }]),
    }),

    getHarvesterPlotsValid: build.query<Plot[], {
      nodeId: string;
      page?: number;
      pageSize?: number;
    }>({
      query: ({ nodeId, page, pageSize }) => ({
        command: 'getHarvesterPlotsValid',
        service: Farmer,
        args: [nodeId, page, pageSize],
      }),
      transformResponse: (response: any) => response?.plots,
      providesTags: (plots) => plots
        ? [
          ...plots.map(({ plotId }) => ({ type: 'HarvesterPlots', plotId } as const)),
          { type: 'HarvesterPlots', id: 'LIST' },
        ]
        :  [{ type: 'HarvesterPlots', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onHarvesterUpdated',
        service: Farmer,
        endpoint: () => farmerApi.endpoints.getHarvesterPlotsValid,
        skip: (_draft, data, args) => args.nodeId !== data?.connection?.nodeId,
      }]),
    }),

    getHarvesterPlotsInvalid: build.query<Plot[], {
      nodeId: string;
      page?: number;
      pageSize?: number;
    }>({
      query: ({ nodeId, page, pageSize }) => ({
        command: 'getHarvesterPlotsInvalid',
        service: Farmer,
        args: [nodeId, page, pageSize],
      }),
      transformResponse: (response: any) => response?.plots,
      providesTags: (plots) => plots
        ? [
          ...plots.map((filename) => ({ type: 'HarvesterPlotsInvalid', filename } as const)),
          { type: 'HarvesterPlotsInvalid', id: 'LIST' },
        ]
        :  [{ type: 'HarvesterPlotsInvalid', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onHarvesterUpdated',
        service: Farmer,
        endpoint: () => farmerApi.endpoints.getHarvesterPlotsInvalid,
        skip: (_draft, data, args) => args.nodeId !== data?.connection?.nodeId,
      }]),
    }),

    getHarvesterPlotsKeysMissing: build.query<Plot[], {
      nodeId: string;
      page?: number;
      pageSize?: number;
    }>({
      query: ({ nodeId, page, pageSize }) => ({
        command: 'getHarvesterPlotsKeysMissing',
        service: Farmer,
        args: [nodeId, page, pageSize],
      }),
      transformResponse: (response: any) => response?.plots,
      providesTags: (plots) => plots
        ? [
          ...plots.map((filename) => ({ type: 'HarvesterPlotsKeysMissing', filename } as const)),
          { type: 'HarvesterPlotsKeysMissing', id: 'LIST' },
        ]
        :  [{ type: 'HarvesterPlotsKeysMissing', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onHarvesterUpdated',
        service: Farmer,
        endpoint: () => farmerApi.endpoints.getHarvesterPlotsKeysMissing,
        skip: (_draft, data, args) => args.nodeId !== data?.connection?.nodeId,
      }]),
    }),

    getHarvesterPlotsDuplicates: build.query<Plot[], {
      nodeId: string;
      page?: number;
      pageSize?: number;
    }>({
      query: ({ nodeId, page, pageSize }) => ({
        command: 'getHarvesterPlotsDuplicates',
        service: Farmer,
        args: [nodeId, page, pageSize],
      }),
      transformResponse: (response: any) => response?.plots,
      providesTags: (plots) => plots
        ? [
          ...plots.map((filename) => ({ type: 'HarvesterPlotsDuplicates', filename } as const)),
          { type: 'HarvesterPlotsDuplicates', id: 'LIST' },
        ]
        :  [{ type: 'HarvesterPlotsDuplicates', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onHarvesterUpdated',
        service: Farmer,
        endpoint: () => farmerApi.endpoints.getHarvesterPlotsDuplicates,
        skip: (_draft, data, args) => args.nodeId !== data?.connection?.nodeId,
      }]),
    }),

    getRewardTargets: build.query<undefined, {
      searchForPrivateKey?: boolean;
    }>({
      query: ({ searchForPrivateKey } = {}) => ({
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

    getFarmerConnections: build.query<FarmerConnection[], undefined>({
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
    openFarmerConnection: build.mutation<FarmerConnection, {
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
    closeFarmerConnection: build.mutation<FarmerConnection, {
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
          if (draft.length > MAX_SIGNAGE_POINTS) {
            draft.splice(MAX_SIGNAGE_POINTS, draft.length - MAX_SIGNAGE_POINTS);
          }
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
  useFarmerPingQuery,
  useGetHarvestersQuery,
  useGetHarvestersSummaryQuery,
  useGetHarvesterPlotsValidQuery,
  useGetHarvesterPlotsDuplicatesQuery,
  useGetHarvesterPlotsInvalidQuery,
  useGetHarvesterPlotsKeysMissingQuery,
  useGetRewardTargetsQuery,
  useSetRewardTargetsMutation,
  useGetFarmerConnectionsQuery,
  useOpenFarmerConnectionMutation,
  useCloseFarmerConnectionMutation,
  useGetPoolLoginLinkQuery,
  useGetSignagePointsQuery,
  useGetPoolStateQuery,
  useSetPayoutInstructionsMutation,
  useGetFarmingInfoQuery,
} = farmerApi;
