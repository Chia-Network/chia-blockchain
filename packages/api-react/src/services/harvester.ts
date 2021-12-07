import { createApi } from '@reduxjs/toolkit/query/react';
import { Harvester } from '@chia/api';
import type { Plot } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';

const baseQuery = chiaLazyBaseQuery({
  service: Harvester,
});

export const harvesterApi = createApi({
  reducerPath: 'harvesterApi',
  baseQuery,
  tagTypes: ['Plots', 'PlotDirectories'],
  endpoints: (build) => ({
    ping: build.query<boolean, {
    }>({
      query: () => ({
        command: 'ping',
      }),
      transformResponse: (response: any) => response?.success,
    }),

    getPlots: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getPlots',
      }),
      transformResponse: (response: any) => { 
        console.log('get plots respojnse', response);
        return response?.plots;
      },
      providesTags: (plots) => plots
        ? [
          ...plots.map(({ filename }) => ({ type: 'Plots', id: filename } as const)),
          { type: 'Plots', id: 'LIST' },
        ] 
        :  [{ type: 'Plots', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onRefreshPlots',
        endpoint: () => harvesterApi.endpoints.getPlots,
      }]),
    }),
    refreshPlots: build.mutation<undefined, { 
    }>({
      query: () => ({
        command: 'refreshPlots',
      }),
    }),
    deletePlot: build.mutation<boolean, { 
      filename: string;
    }>({
      query: ({ filename }) => ({
        command: 'deletePlot',
        args: [filename],
      }),
      transformResponse(response) {
        console.log('restponse deletePlot', response);
        return response?.success;
      },
      invalidatesTags: (_result, _error, { filename }) => [
        { type: 'Plots', id: 'LIST' }, 
        { type: 'Plots', id: filename },
        { type: 'Harvesters', id: 'LIST' },
      ],
    }),

    getPlotDirectories: build.query<string[], undefined>({
      query: () => ({
        command: 'getPlotDirectories',
      }),
      transformResponse: (response: any) => response?.directories,
      providesTags: (directories) => directories
        ? [
          ...directories.map((directory) => ({ type: 'PlotDirectories', id: directory } as const)),
          { type: 'PlotDirectories', id: 'LIST' },
        ] 
        :  [{ type: 'PlotDirectories', id: 'LIST' }],
    }),
    addPlotDirectory: build.mutation<Object, {
      dirname: string;
    }>({
      query: ({ dirname }) => ({
        command: 'addPlotDirectory',
        args: [dirname],
      }),
      invalidatesTags: (_result, _error, { dirname }) => [
        { type: 'PlotDirectories', id: 'LIST'}, 
        { type: 'PlotDirectories', id: dirname },
      ],
    }),
    removePlotDirectory: build.mutation<Object, {
      dirname: string;
    }>({
      query: ({ dirname }) => ({
        command: 'removePlotDirectory',
        args: [dirname],
      }),
      invalidatesTags: (_result, _error, { dirname }) => [{ type: 'PlotDirectories', id: 'LIST'}, { type: 'PlotDirectories', id: dirname }],
    }), 
  }),
});

export const { 
  usePingQuery,
  useGetPlotsQuery,
  useRefreshPlotsMutation,
  useDeletePlotMutation,
  useGetPlotDirectoriesQuery,
  useAddPlotDirectoryMutation,
  useRemovePlotDirectoryMutation,
} = harvesterApi;
