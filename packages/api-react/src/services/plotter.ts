import { Plotter } from '@chia/api';
import type { Plot } from '@chia/api';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import api, { baseQuery } from '../api';

const apiWithTag = api.enhanceEndpoints({addTagTypes: ['PlotQueue']})

export const plotterApi = apiWithTag.injectEndpoints({
  endpoints: (build) => ({
    getPlotQueue: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getQueue',
        service: Plotter,
      }),
      // transformResponse: (response: any) => response,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onQueueChanged',
        service: Plotter,
        endpoint: () => plotterApi.endpoints.getPlotQueue,
      }]),
    }),
/*
    stopPlotting: build.mutation<boolean, {
      id: string;
    }>({
      query: ({ id }) => ({
        command: 'stopPlotting',
        service: Plotter,
        args: [id],
      }),
      transformResponse: (response: any) => response?.success,
      // providesTags: (_result, _err, { service }) => [{ type: 'ServiceRunning', id: service }],
    }),
    */
/*
    startPlotting: build.mutation<boolean, PlotAdd>({
      query: ({ 
        bladebitDisableNUMA,
        bladebitWarmStart,
        c,
        delay,
        disableBitfieldPlotting,
        excludeFinalDir,
        farmerPublicKey,
        finalLocation,
        fingerprint,
        madmaxNumBucketsPhase3,
        madmaxTempToggle,
        madmaxThreadMultiplier,
        maxRam,
        numBuckets,
        numThreads,
        overrideK,
        parallel,
        plotCount,
        plotSize,
        plotterName,
        poolPublicKey,
        queue,
        workspaceLocation,
        workspaceLocation2,
       }) => ({
        command: 'startPlotting',
        service: Plotter,
        args: [
          plotterName,
          plotSize,
          plotCount,
          workspaceLocation,
          workspaceLocation2 || workspaceLocation,
          finalLocation,
          maxRam,
          numBuckets,
          numThreads,
          queue,
          fingerprint,
          parallel,
          delay,
          disableBitfieldPlotting,
          excludeFinalDir,
          overrideK,
          farmerPublicKey,
          poolPublicKey,
          c,
          bladebitDisableNUMA,
          bladebitWarmStart,
          madmaxNumBucketsPhase3,
          madmaxTempToggle,
          madmaxThreadMultiplier,
        ],
      }),
      transformResponse: (response: any) => response?.success,
      // providesTags: (_result, _err, { service }) => [{ type: 'ServiceRunning', id: service }],
    }),
    */
  }),
});

export const { 
  useGetPlotQueueQuery,
  // useStopPlottingMutation,
  // useStartPlottingMutation,
} = plotterApi;
