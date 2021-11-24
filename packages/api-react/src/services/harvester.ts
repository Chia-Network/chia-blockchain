import { createApi } from '@reduxjs/toolkit/query/react';
import { Harvester } from '@chia/api';
import type { Plot, BlockchainConnection } from '@chia/api';
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
    getPlots: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getPlots',
      }),
      transformResponse: (response: any) => response?.plots,
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
    deletePlot: build.mutation<BlockchainConnection, { 
      filename: string;
    }>({
      query: ({ filename }) => ({
        command: 'deletePlot',
        args: [filename],
      }),
      invalidatesTags: (_result, _error, { filename }) => [{ type: 'Plots', id: 'LIST' }, { type: 'Plots', id: filename }],
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
      invalidatesTags: (_result, _error, { dirname }) => [{ type: 'PlotDirectories', id: 'LIST'}, { type: 'PlotDirectories', id: dirname }],
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
  useGetPlotsQuery,
  useRefreshPlotsMutation,
  useDeletePlotMutation,
  useGetPlotDirectoriesQuery,
  useAddPlotDirectoryMutation,
  useRemovePlotDirectoryMutation,
} = harvesterApi;
