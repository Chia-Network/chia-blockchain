import { Daemon, optionsForPlotter, defaultsForPlotter } from '@chia/api';
import type { KeyringStatus, ServiceName } from '@chia/api';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import api, { baseQuery } from '../api';

const apiWithTag = api.enhanceEndpoints({addTagTypes: ['KeyringStatus', 'ServiceRunning']})

export const daemonApi = apiWithTag.injectEndpoints({
  endpoints: (build) => ({
    daemonPing: build.query<boolean, {
    }>({
      query: () => ({
        command: 'ping',
        service: Daemon,
      }),
      transformResponse: (response: any) => response?.success,
    }),

    getKeyringStatus: build.query<KeyringStatus, {
    }>({
      query: () => ({
        command: 'keyringStatus',
        service: Daemon,
      }),
      transformResponse: (response: any) => {
        const { status, ...rest } = response;

        return {
          ...rest,
        };
      },
      providesTags: ['KeyringStatus'],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onKeyringStatusChanged',
        service: Daemon,
        onUpdate: (draft, data) => {
          // empty base array
          draft.splice(0);

          const { status, ...rest } = data;

          // assign new items
          Object.assign(draft, rest);
        },
      }]),
    }),
    
    startService: build.mutation<boolean, {
      service: ServiceName;
      testing?: boolean,
    }>({
      query: ({ service, testing }) => ({
        command: 'startService',
        service: Daemon,
        args: [service, testing],
      }),
    }),

    stopService: build.mutation<boolean, {
      service: ServiceName;
    }>({
      query: ({ service }) => ({
        command: 'stopService',
        service: Daemon,
        args: [service],
      }),
    }),

    isServiceRunning: build.query<KeyringStatus, {
      service: ServiceName;
    }>({
      query: ({ service }) => ({
        command: 'isRunning',
        service: Daemon,
        args: [service],
      }),
      transformResponse: (response: any) => response?.isRunning,
      providesTags: (_result, _err, { service }) => [{ type: 'ServiceRunning', id: service }],
    }),
  
    setKeyringPassphrase: build.mutation<boolean, {
      currentPassphrase?: string, 
      newPassphrase?: string;
      passphraseHint?: string, 
      savePassphrase?: boolean,
    }>({
      query: ({ currentPassphrase, newPassphrase, passphraseHint, savePassphrase }) => ({
        command: 'setKeyringPassphrase',
        service: Daemon,
        args: [currentPassphrase, newPassphrase, passphraseHint, savePassphrase],
      }),
      invalidatesTags: () => ['KeyringStatus'],
      transformResponse: (response: any) => response?.success,
    }), 

    removeKeyringPassphrase: build.mutation<boolean, {
      currentPassphrase: string;
    }>({
      query: ({ currentPassphrase }) => ({
        command: 'removeKeyringPassphrase',
        service: Daemon,
        args: [currentPassphrase],
      }),
      invalidatesTags: () => ['KeyringStatus'],
      transformResponse: (response: any) => response?.success,
    }),

    migrateKeyring: build.mutation<boolean, {
      passphrase: string,
      passphraseHint: string,
      savePassphrase: boolean,
      cleanupLegacyKeyring: boolean,
    }>({
      query: ({ passphrase, passphraseHint, savePassphrase, cleanupLegacyKeyring }) => ({
        command: 'migrateKeyring',
        service: Daemon,
        args: [passphrase, passphraseHint, savePassphrase, cleanupLegacyKeyring],
      }),
      invalidatesTags: () => ['KeyringStatus'],
      transformResponse: (response: any) => response?.success,
    }),

    unlockKeyring: build.mutation<boolean, {
      key: string,
    }>({
      query: ({ key }) => ({
        command: 'unlockKeyring',
        service: Daemon,
        args: [key],
      }),
      invalidatesTags: () => ['KeyringStatus'],
      transformResponse: (response: any) => response?.success,
    }),

    getPlotters: build.query<Object, undefined>({
      query: () => ({
        command: 'getPlotters',
        service: Daemon,
      }),
      transformResponse: (response: any) => {
        const { plotters } = response;
        const plotterNames = Object.keys(plotters) as PlotterName[];
        const availablePlotters: PlotterMap<PlotterName, Plotter> = {};

        plotterNames.forEach((plotterName) => {
          const { 
            displayName = plotterName,
            version,
            installed,
            canInstall,
            bladebitMemoryWarning,
          } = plotters[plotterName];

          availablePlotters[plotterName] = {
            displayName,
            version,
            options: optionsForPlotter(plotterName),
            defaults: defaultsForPlotter(plotterName),
            installInfo: {
              installed,
              canInstall,
              bladebitMemoryWarning,
            },
          };
        });
        
        return availablePlotters;
      },
      // providesTags: (_result, _err, { service }) => [{ type: 'ServiceRunning', id: service }],
    }),

    stopPlotting: build.mutation<boolean, {
      id: string;
    }>({
      query: ({ id }) => ({
        command: 'stopPlotting',
        service: Daemon,
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
        service: Daemon,
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
  useDaemonPingQuery,
  useGetKeyringStatusQuery,
  useStartServiceMutation,
  useStopServiceMutation,
  useIsServiceRunningQuery,
  useSetKeyringPassphraseMutation,
  useRemoveKeyringPassphraseMutation,
  useMigrateKeyringMutation,
  useUnlockKeyringMutation,

  useGetPlottersQuery,
  useStopPlottingMutation,
  useStartPlottingMutation,
} = daemonApi;
