import * as client from './client';
import * as daemon from './daemon';
import * as farmer from './farmer';
import * as fullNode from './fullNode';
import * as harvester from './harvester';
import * as wallet from './wallet';

export const {
  clientApi,

  useCloseMutation,
  useGetStateQuery,
} = client;


// daemon hooks
export const {
  daemonApi,

  useGetKeyringStatusQuery,
  useIsServiceRunningQuery,
  useSetKeyringPassphraseMutation,
  useRemoveKeyringPassphraseMutation,
} = daemon;

// farmer hooks
export const {
  farmerApi,

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
} = farmer;

// full node hooks
export const {
  fullNodeApi,

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

  // CAT wallet hooks
  useCreateNewCATWalletMutation,
  useCreateCATWalletForExistingMutation,
  useGetCATAssetIdQuery,
  useGetCatListQuery,
  useGetCATNameQuery,
  useSetCATNameMutation,
  useSpendCATMutation,
  useAddCATTokenMutation,
} = wallet;

// harvester hooks
export const {
  harvesterApi,

  useGetPlotsQuery,
  useRefreshPlotsMutation,
  useDeletePlotMutation,
  useGetPlotDirectoriesQuery,
  useAddPlotDirectoryMutation,
  useRemovePlotDirectoryMutation,
} = harvester;
