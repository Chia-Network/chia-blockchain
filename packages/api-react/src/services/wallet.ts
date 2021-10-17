import { createApi } from '@reduxjs/toolkit/query/react';
import { Wallet, CAT } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import type Transaction from '../@types/Transaction';

const baseQuery = chiaLazyBaseQuery({
  service: Wallet,
});

export const walletApi = createApi({
  reducerPath: 'walletApi',
  baseQuery,
  tagTypes: ['Keys', 'Wallets', 'WalletBalance', 'Address', 'Transactions'],
  endpoints: (build) => ({
    getWallets: build.query<Wallet[], undefined>({
      query: () => ({
        command: 'getWallets',
      }),
      transformResponse: (response: any) => response?.wallets,
      providesTags(result) {
        return result ? [
          ...result.map(({ id }) => ({ type: 'Wallets', id } as const)),
          { type: 'Wallets', id: 'LIST' },
        ] :  [{ type: 'Wallets', id: 'LIST' }];
      },
    }),

    getTransaction: build.query<any, { 
      transactionId: string;
    }>({
      query: ({ transactionId }) => ({
        command: 'getTransaction',
        args: [transactionId],
      }),
    }),

    getPwStatus: build.query<any, { 
      walletId: number;
    }>({
      query: ({ walletId }) => ({
        command: 'getPwStatus',
        args: [walletId],
      }),
    }),

    pwAbsorbRewards: build.mutation<any, { 
      walletId: number;
      fee: string;
    }>({
      query: ({ walletId, fee }) => ({
        command: 'pwAbsorbRewards',
        args: [walletId, fee],
      }),
      invalidatesTags: [{ type: 'Transactions', id: 'LIST' }],
    }),

    pwJoinPool: build.mutation<any, { 
      walletId: number;
      poolUrl: string;
      relativeLockHeight: number;
      targetPuzzlehash?: string;
    }>({
      query: ({ walletId, poolUrl, relativeLockHeight, targetPuzzlehash  }) => ({
        command: 'pwJoinPool',
        args: [
          walletId,
          poolUrl,
          relativeLockHeight,
          targetPuzzlehash,
        ],
      }),
    }),

    pwSelfPool: build.mutation<any, { 
      walletId: number;
    }>({
      query: ({ walletId }) => ({
        command: 'pwSelfPool',
        args: [walletId],
      }),
    }),

    createNewWallet: build.mutation<any, { 
      walletType: 'pool_wallet' | 'rl_wallet' | 'did_wallet' | 'cc_wallet';
      options?: Object;
    }>({
      query: ({ walletType, options }) => ({
        command: 'createNewWallet',
        args: [walletType, options],
      }),
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }],
    }),

    deleteUnconfirmedTransactions: build.mutation<any, { 
      walletId: number;
    }>({
      query: ({ walletId }) => ({
        command: 'deleteUnconfirmedTransactions',
        args: [walletId],
      }),
    }),
  
    getWalletBalance: build.query<{
      confirmedWalletBalance: number;
      maxSendAmount: number;
      pendingChange: number;
      pendingCoinRemovalCount: number;
      spendableBalance: number;
      unconfirmedWalletBalance: number;
      unspentCoinCount: number;
      walletId: number;
      pendingBalance: number;
      pendingTotalBalance: number;
    }, { 
      walletId: number;
    }>({
      query: ({ walletId }) => ({
        command: 'getWalletBalance',
        args: [walletId],
      }),
      transformResponse: (response) => {
        const { 
          walletBalance,
          walletBalance: {
            confirmedWalletBalance,
            unconfirmedWalletBalance,
          },
        } = response;

        const pendingBalance = unconfirmedWalletBalance - confirmedWalletBalance;
        const pendingTotalBalance = confirmedWalletBalance + pendingBalance;

        return {
          ...walletBalance,
          pendingBalance,
          pendingTotalBalance,
        };
      },
    }),

    getFarmedAmount: build.query<any, undefined>({
      query: () => ({
        command: 'getFarmedAmount',
      }),
    }),
  
    sendTransaction: build.mutation<any, { 
      walletId: number;
      amount: string;
      fee: string; 
      address: string;
    }>({
      query: ({ walletId, amount, fee, address }) => ({
        command: 'sendTransaction',
        args: [
          walletId,
          amount,
          fee,
          address,
        ],
      }),
      invalidatesTags: [{ type: 'Transactions', id: 'LIST' }],
    }),

    generateMnemonic: build.mutation<string[], undefined>({
      query: () => ({
        command: 'generateMnemonic',
      }),
      transformResponse: (response: any) => response?.mnemonic,
    }),

    getPublicKeys: build.query<number[], undefined>({
      query: () => ({
        command: 'getPublicKeys',
      }),
      transformResponse: (response: any) => response?.publicKeyFingerprints,
      providesTags: (keys) => keys
        ? [
          ...keys.map((key) => ({ type: 'Keys', id: key } as const)),
          { type: 'Keys', id: 'LIST' },
        ] 
        :  [{ type: 'Keys', id: 'LIST' }],
    }),

    addKey: build.mutation<any, {
      mnemonic: string[];
      type: 'new_wallet' | 'skip' | 'restore_backup';
      filePath?: string;
    }>({
      query: ({ mnemonic, type, filePath }) => ({
        command: 'addKey',
        args: [mnemonic, type, filePath],
      }),
      invalidatesTags: [{ type: 'Keys', id: 'LIST' }],
    }),
  
    deleteKey: build.mutation<any, {
      fingerprint: number;
    }>({
      query: ({ fingerprint }) => ({
        command: 'deleteKey',
        args: [fingerprint],
      }),
      invalidatesTags: (_result, _error, { fingerprint }) => [{ type: 'Keys', id: fingerprint }],
    }),

    checkDeleteKey: build.mutation<{
      fingerprint: number;
      success: boolean;
      usedForFarmerRewards: boolean;
      usedForPoolRewards: boolean;
      walletBalance: boolean;
    }, {
      fingerprint: string;
    }>({
      query: ({ fingerprint }) => ({
        command: 'checkDeleteKey',
        args: [fingerprint],
      }),
    }),

    deleteAllKeys: build.mutation<any, undefined>({
      query: () => ({
        command: 'deleteAllKeys',
      }),
      invalidatesTags: [{ type: 'Keys', id: 'LIST' }],
    }),

    logIn: build.mutation<any, {
      fingerprint: string;
      type?: 'normal' | 'skip' | 'restore_backup';
      host?: string;
      filePath?: string;
    }>({
      query: ({
        fingerprint,
        type,
        filePath,
        host,
      }) => ({
        command: 'logIn',
        args: [fingerprint, type, filePath, host],
      }),
    }),

    logInAndSkipImport: build.mutation<any, {
      fingerprint: string;
      host?: string;
    }>({
      query: ({
        fingerprint,
        host,
      }) => ({
        command: 'logInAndSkipImport',
        args: [fingerprint, host],
      }),
    }),

    logInAndImportBackup: build.mutation<any, {
      fingerprint: string;
      filePath: string;
      host?: string;
    }>({
      query: ({
        fingerprint,
        filePath,
        host,
      }) => ({
        command: 'logInAndImportBackup',
        args: [fingerprint, filePath, host],
      }),
    }),

    getBackupInfo: build.query<any, {
      filePath: string;
      options: { fingerprint: string } | { words: string };
    }>({
      query: ({
        filePath,
        options,
      }) => ({
        command: 'getBackupInfo',
        args: [filePath, options],
      }),
    }),

    getBackupInfoByFingerprint: build.query<any, {
      filePath: string;
      fingerprint: string;
    }>({
      query: ({
        filePath,
        fingerprint,
      }) => ({
        command: 'getBackupInfoByFingerprint',
        args: [filePath, fingerprint],
      }),
    }),

    getBackupInfoByWords: build.query<any, {
      filePath: string;
      words: string;
    }>({
      query: ({
        filePath,
        words,
      }) => ({
        command: 'getBackupInfoByWords',
        args: [filePath, words],
      }),
    }),

    getPrivateKey: build.query<{
      farmerPk: string;
      fingerprint: number;
      pk: string;
      poolPk: string;
      seed?: string;
      sk: string;
    }, {
      fingerprint: string;
    }>({
      query: ({
        fingerprint,
      }) => ({
        command: 'getPrivateKey',
        args: [fingerprint],
      }),
      transformResponse: (response: any) => response?.privateKey,
    }),

    getTransactions: build.query<Transaction[], {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'getTransactions',
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.transactions,
      providesTags(result) {
        return result ? [
          ...result.map(({ name }) => ({ type: 'Transactions', id: name } as const)),
          { type: 'Transactions', id: 'LIST' },
        ] :  [{ type: 'Transactions', id: 'LIST' }];
      },
    }),

    getCurrentAddress: build.query<string, {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'getNextAddress',
        args: [walletId, false],
      }),
      transformResponse: (response: any) => response?.address,
      providesTags: (result, _error, { walletId }) => result 
        ? [{ type: 'Address', id: walletId }]
        : [],
    }),

    getNextAddress: build.mutation<string, {
      walletId: number;
      newAddress: boolean;
    }>({
      query: ({
        walletId,
        newAddress,
      }) => ({
        command: 'getNextAddress',
        args: [walletId, newAddress],
      }),
      transformResponse: (response: any) => response?.address,
      invalidatesTags: (result, _error, { walletId }) => result
        ? [{ type: 'Address', id: walletId }]
        : [],
    }),

    farmBlock: build.mutation<any, {
      address: string;
    }>({
      query: ({
        address,
      }) => ({
        command: 'farmBlock',
        args: [address],
      }),
    }),

    getHeightInfo: build.query<any, undefined>({
      query: () => ({
        command: 'getHeightInfo',
      }),
    }),

    getNetworkInfo: build.query<any, undefined>({
      query: () => ({
        command: 'getNetworkInfo',
      }),
    }),

    getSyncStatus: build.query<any, undefined>({
      query: () => ({
        command: 'getSyncStatus',
      }),
      async onCacheEntryAdded(_args, api) {
        const { cacheDataLoaded, cacheEntryRemoved, dispatch } = api;
        let unsubscribe;
        try {
          await cacheDataLoaded;

          const response = await baseQuery({
            command: 'onSyncChanged',
            args: [() => {
              dispatch(walletApi.endpoints.getSyncStatus.initiate(undefined, { 
                subscribe: false,
                forceRefetch: true,
              }));
            }],
          }, api, {});

          unsubscribe = response.data;
        } finally {
          await cacheEntryRemoved;
          if (unsubscribe) {
            unsubscribe();
          }
        }
      },
    }),

    getConnections: build.query<any, undefined>({
      query: () => ({
        command: 'getConnections',
      }),
    }),

    createBackup: build.mutation<any, {
      filePath: string;
    }>({
      query: ({
        filePath,
      }) => ({
        command: 'createBackup',
        args: [filePath],
      }),
    }),

    // CAT
    createNewCATWallet: build.mutation<any, {
      amount: string;
      fee: string;
      host?: string;
    }>({
      query: ({
        amount,
        fee,
        host
      }) => ({
        command: 'createNewWallet',
        service: CAT,
        args: [amount, fee, host],
      }),
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }, { type: 'Transactions', id: 'LIST' }],
    }),

    createCATWalletForExisting: build.mutation<any, {
      tail: string;
      fee: string;
      host?: string;
    }>({
      query: ({
        tail,
        fee,
        host
      }) => ({
        command: 'createWalletForExisting',
        service: CAT,
        args: [tail, fee, host],
      }),
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }, { type: 'Transactions', id: 'LIST' }],
    }),
  
    getCATTail: build.query<string, {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'getTail',
        service: CAT,
        args: [walletId],
      }),
    }),
  
    getCATName: build.query<string, {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'cc_get_name',
        service: CAT,
        args: [walletId],
      }),
    }),
  
    setCATName: build.mutation<any, {
      walletId: number;
      name: string;
    }>({
      query: ({
        walletId,
        name,
      }) => ({
        command: 'cc_set_name',
        service: CAT,
        args: [walletId, name],
      }),
    }),
  
    spendCAT: build.mutation<any, {
      walletId: number;
      address: string;
      amount: string;
      fee: string;
      memos?: string[];
    }>({
      query: ({
        walletId,
        address,
        amount,
        fee,
        memos,
      }) => ({
        command: 'cc_set_name',
        service: CAT,
        args: [walletId, address, amount, fee, memos],
      }),
      invalidatesTags: [{ type: 'Transactions', id: 'LIST' }],
    }),

    addCATToken: build.mutation<any, {
      tail: string;
      name: string;
      fee: string;
      host?: string;
    }>({
      async queryFn({ tail, name, fee, host }, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          const response = await fetchWithBQ({
            command: 'createWalletForExisting',
            service: CAT,
            args: [tail, fee, host],
          });
    
          console.log('createWalletForExisting response', response);
          
          const walletId = response?.walletId;
          if (!walletId) {
            throw new Error('Wallet id is not defined');
          }

          await fetchWithBQ({
            command: 'cc_set_name',
            service: CAT,
            args: [walletId, name],
          });

          return {
            data: walletId,
          };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }, { type: 'Transactions', id: 'LIST' }],
    }),
  }),
});

export const {
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
  useGetCurrentAddressQuery,
  useGetNextAddressMutation,
  useFarmBlockMutation,
  useGetHeightInfoQuery,
  useGetNetworkInfoQuery,
  useGetSyncStatusQuery,
  useGetConnectionsQuery,
  useCreateBackupMutation,

  // CAT
  useCreateNewCATWalletMutation,
  useCreateCATWalletForExistingMutation,
  useGetCATTailQuery,
  useGetCATNameQuery,
  useSetCATNameMutation,
  useSpendCATMutation,
  useAddCATTokenMutation,
} = walletApi;
