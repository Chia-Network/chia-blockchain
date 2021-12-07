import * as client from './client';
import * as daemon from './daemon';
import * as farmer from './farmer';
import * as fullNode from './fullNode';
import * as harvester from './harvester';
import * as plotter from './plotter';
import * as wallet from './wallet';

export const {
  clientApi,

  useCloseMutation,
  useGetStateQuery,
  useStartServiceMutation: useClientStartServiceMutation,
} = client;

// daemon hooks
export const {
  daemonApi,

  usePingQuery: useDaemonPingQuery,
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
} = daemon;

// farmer hooks
export const {
  farmerApi,

  usePingQuery: useFarmerPingQuery,
  useGetHarvestersQuery,
  useGetRewardTargetsQuery,
  useSetRewardTargetsMutation,
  useGetConnectionsQuery: useGetFarmerConnectionsQuery,
  useOpenConnectionMutation: useOpenFarmerConnectionMutation,
  useCloseConnectionMutation: useCloseFarmerConnectionMutation,
  useGetPoolLoginLinkQuery,
  useGetSignagePointsQuery,
  useGetPoolStateQuery,
  useSetPayoutInstructionsMutation,
  useGetFarmingInfoQuery,
} = farmer;

// full node hooks
export const {
  fullNodeApi,

  usePingQuery: useFullNodePingQuery,
  useGetBlockRecordsQuery,
  useGetUnfinishedBlockHeadersQuery,
  useGetBlockchainStateQuery,
  useGetConnectionsQuery: useGetFullNodeConnectionsQuery,
  useOpenConnectionMutation: useOpenFullNodeConnectionMutation,
  useCloseConnectionMutation: useCloseFullNodeConnectionMutation,
  useGetBlockQuery,
  useGetBlockRecordQuery,
} = fullNode;

// wallet hooks
export const {
  walletApi,

  usePingQuery: useWalletPingQuery,
  useGetLoggedInFingerprintQuery,
  useGetWalletsQuery,
  useGetTransactionQuery,
  useGetPwStatusQuery,
  usePwAbsorbRewardsMutation,
  usePwJoinPoolMutation,
  usePwSelfPoolMutation,
  useCreateNewWalletMutation,
  useDeleteUnconfirmedTransactionsMutation,
  useGetWalletBalanceQuery,
  useGetFarmedAmountQuery,
  useSendTransactionMutation,
  useGenerateMnemonicMutation,
  useGetPublicKeysQuery,
  useAddKeyMutation,
  useDeleteKeyMutation,
  useCheckDeleteKeyMutation,
  useDeleteAllKeysMutation,
  useLogInMutation,
  useLogInAndSkipImportMutation,
  useLogInAndImportBackupMutation,
  useGetBackupInfoQuery,
  useGetBackupInfoByFingerprintQuery,
  useGetBackupInfoByWordsQuery,
  useGetPrivateKeyQuery,
  useGetTransactionsQuery,
  useGetTransactionsCountQuery,
  useGetCurrentAddressQuery,
  useGetNextAddressMutation,
  useFarmBlockMutation,
  useGetHeightInfoQuery,
  useGetNetworkInfoQuery,
  useGetSyncStatusQuery,
  useGetConnectionsQuery: useGetWalletConnectionsQuery,
  useOpenConnectionMutation: useOpenWalletConnectionMutation,
  useCloseConnectionMutation: useCloseWalletConnectionMutation,
  useCreateBackupMutation,
  useGetAllOffersQuery,
  useCreateOfferForIdsMutation,
  useCancelOfferMutation,
  useCheckOfferValidityMutation,
  useTakeOfferMutation,
  useGetOfferSummaryMutation,
  useGetOfferDataMutation,
  useGetOfferRecordMutation,

  // Pool
  useCreateNewPoolWalletMutation,

  // CAT wallet hooks
  useCreateNewCATWalletMutation,
  useCreateCATWalletForExistingMutation,
  useGetCATAssetIdQuery,
  useGetCatListQuery,
  useGetCATNameQuery,
  useSetCATNameMutation,
  useSpendCATMutation,
  useAddCATTokenMutation,

  // NFTs
  useGetPlotNFTsQuery,
} = wallet;

// harvester hooks
export const {
  harvesterApi,

  usePingQuery: useHarvesterPingQuery,
  useGetPlotsQuery,
  useRefreshPlotsMutation,
  useDeletePlotMutation,
  useGetPlotDirectoriesQuery,
  useAddPlotDirectoryMutation,
  useRemovePlotDirectoryMutation,
} = harvester;

// plotter hooks
export const {
  plotterApi,

  useGetPlotQueueQuery,
  // useStopPlottingMutation,
  // useStartPlottingMutation,
} = plotter;