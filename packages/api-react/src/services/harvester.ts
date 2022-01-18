import { Harvester } from '@chia/api';
import type { Plot } from '@chia/api';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import api, { baseQuery } from '../api';
import { apiWithTag } from './farmer';

const apiWithTag2 = apiWithTag.enhanceEndpoints({addTagTypes: ['Plots', 'PlotDirectories']})

export const harvesterApi = apiWithTag2.injectEndpoints({
  endpoints: (build) => ({
    harvesterPing: build.query<boolean, {
    }>({
      query: () => ({
        command: 'ping',
        service: Harvester,
      }),
      transformResponse: (response: any) => response?.success,
    }),

    getPlots: build.query<Plot[], {
    }>({
      query: () => ({
        command: 'getPlots',
        service: Harvester,
      }),
      transformResponse: (response: any) => { 
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
        service: Harvester,
        endpoint: () => harvesterApi.endpoints.getPlots,
      }]),
    }),
    refreshPlots: build.mutation<undefined, { 
    }>({
      query: () => ({
        command: 'refreshPlots',
        service: Harvester,
      }),
      invalidatesTags: [{ type: 'Harvesters', id: 'LIST' }],
    }),

    deletePlot: build.mutation<boolean, { 
      filename: string;
    }>({
      /*
      query: ({ filename }) => ({
        command: 'deletePlot',
        service: Harvester,
        args: [filename],
      }),
      */
      async queryFn({ filename }, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          console.log('DELETE PLOT', filename);
          const { data, error } = await fetchWithBQ({
            command: 'deletePlot',
            service: Harvester,
            args: [filename],
          });

          console.log('DELETE PLOT response', error, data);

          if (error) {
            throw error;
          }

          const refreshResponse = await fetchWithBQ({
            command: 'refreshPlots',
            service: Harvester,
          });

          console.log('refresh response', refreshResponse);

          if (refreshResponse.error) {
            throw error;
          } 

          return {
            data,
          };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
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
        service: Harvester,
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
        service: Harvester,
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
        service: Harvester,
        args: [dirname],
      }),
      invalidatesTags: (_result, _error, { dirname }) => [{ type: 'PlotDirectories', id: 'LIST'}, { type: 'PlotDirectories', id: dirname }],
    }), 
  }),
});

export const { 
  useHarvesterPingQuery,
  useGetPlotsQuery,
  useRefreshPlotsMutation,
  useDeletePlotMutation,
  useGetPlotDirectoriesQuery,
  useAddPlotDirectoryMutation,
  useRemovePlotDirectoryMutation,
} = harvesterApi;
