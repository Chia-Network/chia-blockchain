import { createApi } from '@reduxjs/toolkit/query/react';
import { Plotter } from '@chia/api';
import type { Plot } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';

const baseQuery = chiaLazyBaseQuery({
  service: Plotter,
});

export const plotterApi = createApi({
  reducerPath: 'plotterApi',
  baseQuery,
  tagTypes: ['PlotQueue'],
  endpoints: (build) => ({
    getPlotQueue: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getQueue',
      }),
      // transformResponse: (response: any) => response,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onQueueChanged',
        endpoint: () => plotterApi.endpoints.getPlotQueue,
      }]),
    }),

    stopPlotting: build.mutation<boolean, {
      id: string;
    }>({
      query: ({ id }) => ({
        command: 'stopPlotting',
        args: [id],
      }),
      transformResponse: (response: any) => response?.success,
      // providesTags: (_result, _err, { service }) => [{ type: 'ServiceRunning', id: service }],
    }),

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
  }),
});

export const { 
  useGetPlotQueueQuery,
  useStopPlottingMutation,
  useStartPlottingMutation,
} = plotterApi;
