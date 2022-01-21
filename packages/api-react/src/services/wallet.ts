import { Wallet, CAT, Pool, Farmer, WalletType, OfferTradeRecord } from '@chia/api';
import type { Transaction, WalletConnections } from '@chia/api';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import normalizePoolState from '../utils/normalizePoolState';
import api, { baseQuery } from '../api';

const apiWithTag = api.enhanceEndpoints({addTagTypes: ['Keys', 'Wallets', 'WalletBalance', 'Address', 'Transactions', 'WalletConnections', 'LoggedInFingerprint', 'PoolWalletStatus', 'NFTs', 'OfferTradeRecord']})

export const walletApi = apiWithTag.injectEndpoints({
  endpoints: (build) => ({
    walletPing: build.query<boolean, {
    }>({
      query: () => ({
        command: 'ping',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.success,
    }),

    getLoggedInFingerprint: build.query<string | undefined, {
    }>({
      query: () => ({
        command: 'getLoggedInFingerprint',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.fingerprint,
      providesTags: [{ type: 'LoggedInFingerprint' }],
    }),

    getWallets: build.query<Wallet[], undefined>({
      /*
      query: () => ({
        command: 'getWallets',
      }),
      */
      async queryFn(_args, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          const { data, error } = await fetchWithBQ({
            command: 'getWallets',
            service: Wallet,
          });

          if (error) {
            throw error;
          }
          
          const wallets = data?.wallets;
          if (!wallets) {
            throw new Error('List of the wallets is not defined');
          }

          return {
            data: await Promise.all(wallets.map(async (wallet: Wallet) => {
              const { type } = wallet;
              const meta = {};
              if (type === WalletType.CAT) {
                // get CAT asset
                const { data: assetData, error: assetError } = await fetchWithBQ({
                  command: 'getAssetId',
                  service: CAT,
                  args: [wallet.id],
                });

                if (assetError) {
                  throw assetError;
                }

                meta.assetId = assetData.assetId;

                // get CAT name
                const { data: nameData, error: nameError } = await fetchWithBQ({
                  command: 'getName',
                  service: CAT,
                  args: [wallet.id],
                });

                if (nameError) {
                  throw nameError;
                }

                meta.name = nameData.name;
              }

              return {
                ...wallet,
                meta,
              };
            })),
          };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
      // transformResponse: (response: any) => response?.wallets,
      providesTags(result) {
        return result ? [
          ...result.map(({ id }) => ({ type: 'Wallets', id } as const)),
          { type: 'Wallets', id: 'LIST' },
        ] :  [{ type: 'Wallets', id: 'LIST' }];
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onWalletCreated',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getWallets,
      }]),
    }),

    getTransaction: build.query<Transaction, { 
      transactionId: string;
    }>({
      query: ({ transactionId }) => ({
        command: 'getTransaction',
        service: Wallet,
        args: [transactionId],
      }),
      transformResponse: (response: any) => response?.transaction,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onTransactionUpdate',
        service: Wallet,
        onUpdate: (draft, data, { transactionId }) => {
          const { additionalData: { transaction } } = data;

          console.log('on tx update', transaction.name, transactionId, transaction.name === transactionId, transaction);

          if (transaction.name === transactionId) {
            Object.assign(draft, transaction);
          }
        },
      }]),
    }),

    getPwStatus: build.query<any, { 
      walletId: number;
    }>({
      query: ({ walletId }) => ({
        command: 'getPwStatus',
        service: Wallet,
        args: [walletId],
      }),
      /*
      transformResponse: (response: any, _error, { walletId }) => ({
        ...response,
        walletId,
      }),
      */
      providesTags(result, _error, { walletId }) {
        return result 
          ? [{ type: 'PoolWalletStatus', id: walletId }] 
          : [];
      },
    }),

    pwAbsorbRewards: build.mutation<any, { 
      walletId: number;
      fee: string;
    }>({
      query: ({ walletId, fee }) => ({
        command: 'pwAbsorbRewards',
        service: Wallet,
        args: [walletId, fee],
      }),
      invalidatesTags: [
        { type: 'Transactions', id: 'LIST' }, 
        { type: 'NFTs', id: 'LIST' }, 
      ],
    }),

    pwJoinPool: build.mutation<any, { 
      walletId: number;
      poolUrl: string;
      relativeLockHeight: number;
      targetPuzzlehash?: string;
      fee?: string;
    }>({
      query: ({ walletId, poolUrl, relativeLockHeight, targetPuzzlehash, fee }) => ({
        command: 'pwJoinPool',
        service: Wallet,
        args: [
          walletId,
          poolUrl,
          relativeLockHeight,
          targetPuzzlehash,
          fee,
        ],
      }),
      invalidatesTags: [
        { type: 'Transactions', id: 'LIST' }, 
        { type: 'NFTs', id: 'LIST' }, 
      ],
    }),

    pwSelfPool: build.mutation<any, { 
      walletId: number;
      fee?: string;
    }>({
      query: ({ walletId, fee }) => ({
        command: 'pwSelfPool',
        service: Wallet,
        args: [walletId, fee],
      }),
      invalidatesTags: [
        { type: 'Transactions', id: 'LIST' }, 
        { type: 'NFTs', id: 'LIST' }, 
      ], 
    }),

    createNewWallet: build.mutation<any, { 
      walletType: 'pool_wallet' | 'rl_wallet' | 'did_wallet' | 'cat_wallet';
      options?: Object;
    }>({
      query: ({ walletType, options }) => ({
        command: 'createNewWallet',
        service: Wallet,
        args: [walletType, options],
      }),
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }],
    }),

    deleteUnconfirmedTransactions: build.mutation<any, { 
      walletId: number;
    }>({
      query: ({ walletId }) => ({
        command: 'deleteUnconfirmedTransactions',
        service: Wallet,
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
        service: Wallet,
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

        const pendingBalance = BigInt(unconfirmedWalletBalance) - BigInt(confirmedWalletBalance);
        const pendingTotalBalance = BigInt(confirmedWalletBalance) + BigInt(pendingBalance);

        return {
          ...walletBalance,
          pendingBalance,
          pendingTotalBalance,
        };
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onCoinAdded',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getWalletBalance,
      }, {
        command: 'onCoinRemoved',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getWalletBalance,
      }, {
        command: 'onPendingTransaction',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getWalletBalance,
      }]),
    }),

    getFarmedAmount: build.query<any, undefined>({
      query: () => ({
        command: 'getFarmedAmount',
        service: Wallet,
      }),
    }),
  
    sendTransaction: build.mutation<any, { 
      walletId: number;
      amount: string;
      fee: string; 
      address: string;
      waitForConfirmation?: boolean;
    }>({
      async queryFn(args, queryApi, _extraOptions, fetchWithBQ) {
        let subscribeResponse: {
          data: Function;
        } | undefined;

        function unsubscribe() {
          if (subscribeResponse) {
            subscribeResponse.data();
            subscribeResponse = undefined;
          }
        }

        try {
          const { walletId, amount, fee, address, waitForConfirmation } = args;
          
          return {
            data: await new Promise(async (resolve, reject) => {
              const updatedTransactions: Transaction[] = [];
              let transactionName: string;

              function processUpdates() {
                if (!transactionName) {
                  return;
                }

                const transaction = updatedTransactions.find(
                  (trx) => trx.name === transactionName && !!trx?.sentTo?.length,
                );

                if (transaction) {
                  resolve({
                    transaction,
                    transactionId: transaction.name,
                  });
                }
              }

              // bind all changes related to transactions
              if (waitForConfirmation) {
                // subscribing to tx_updates
                subscribeResponse = await baseQuery({
                  command: 'onTransactionUpdate',
                  service: Wallet,
                  args: [(data: any) => {
                    const { additionalData: { transaction } } = data;
  
                    updatedTransactions.push(transaction);
                    processUpdates();
                  }],
                }, queryApi, {});
              }

              // make transaction
              const { data: sendTransactionData, error, ...rest } = await fetchWithBQ({
                command: 'sendTransaction',
                service: Wallet,
                args: [walletId, amount, fee, address],
              });

              if (error) {
                reject(error);
                return;
              }

              if (!waitForConfirmation) {
                resolve(sendTransactionData);
                return;
              }

              const { transaction } = sendTransactionData;
              if (!transaction) {
                reject(new Error('Transaction is not present in response'));
                return;
              }

              transactionName = transaction.name;
              updatedTransactions.push(transaction);
              processUpdates();
            }),
          };
        } catch (error: any) {
          return {
            error,
          };
        } finally {
          unsubscribe();
        }
      },
      invalidatesTags: [{ type: 'Transactions', id: 'LIST' }],
    }),

    generateMnemonic: build.mutation<string[], undefined>({
      query: () => ({
        command: 'generateMnemonic',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.mnemonic,
    }),

    getPublicKeys: build.query<number[], undefined>({
      query: () => ({
        command: 'getPublicKeys',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.publicKeyFingerprints,
      providesTags: (keys) => keys
        ? [
          ...keys.map((key) => ({ type: 'Keys', id: key } as const)),
          { type: 'Keys', id: 'LIST' },
        ] 
        :  [{ type: 'Keys', id: 'LIST' }],
    }),

    addKey: build.mutation<number, {
      mnemonic: string[];
      type: 'new_wallet' | 'skip' | 'restore_backup';
      filePath?: string;
    }>({
      query: ({ mnemonic, type, filePath }) => ({
        command: 'addKey',
        service: Wallet,
        args: [mnemonic, type, filePath],
      }),
      transformResponse: (response: any) => response?.fingerprint,
      invalidatesTags: [{ type: 'Keys', id: 'LIST' }],
    }),
  
    deleteKey: build.mutation<any, {
      fingerprint: number;
    }>({
      query: ({ fingerprint }) => ({
        command: 'deleteKey',
        service: Wallet,
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
        service: Wallet,
        args: [fingerprint],
      }),
    }),

    deleteAllKeys: build.mutation<any, undefined>({
      query: () => ({
        command: 'deleteAllKeys',
        service: Wallet,
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
        service: Wallet,
        args: [fingerprint, type, filePath, host],
      }),
      invalidatesTags: [{ type: 'LoggedInFingerprint' }],
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
        service: Wallet,
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
        service: Wallet,
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
        service: Wallet,
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
        service: Wallet,
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
        service: Wallet,
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
        service: Wallet,
        args: [fingerprint],
      }),
      transformResponse: (response: any) => response?.privateKey,
    }),

    getTransactions: build.query<Transaction[], {
      walletId: number;
      start?: number;
      end?: number;
      sortKey?: 'CONFIRMED_AT_HEIGHT' | 'RELEVANCE';
      reverse?: boolean;
    }>({
      query: ({
        walletId,
        start,
        end,
        sortKey,
        reverse,
      }) => ({
        command: 'getTransactions',
        service: Wallet,
        args: [walletId, start, end, sortKey, reverse],
      }),
      transformResponse: (response: any) => response?.transactions,
      providesTags(result) {
        return result ? [
          ...result.map(({ name }) => ({ type: 'Transactions', id: name } as const)),
          { type: 'Transactions', id: 'LIST' },
        ] :  [{ type: 'Transactions', id: 'LIST' }];
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onCoinAdded',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getTransactions,
      }, {
        command: 'onCoinRemoved',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getTransactions,
      }, {
        command: 'onPendingTransaction',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getTransactions,
      }]),
    }),

    getTransactionsCount: build.query<number, {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'getTransactionsCount',
        service: Wallet,
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.count,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onCoinAdded',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getTransactionsCount,
      }, {
        command: 'onCoinRemoved',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getTransactionsCount,
      }, {
        command: 'onPendingTransaction',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getTransactionsCount,
      }]),
    }),

    getCurrentAddress: build.query<string, {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'getNextAddress',
        service: Wallet,
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
        service: Wallet,
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
        service: Wallet,
        args: [address],
      }),
    }),

    getHeightInfo: build.query<number, undefined>({
      query: () => ({
        command: 'getHeightInfo',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.height,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onSyncChanged',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getHeightInfo,
      }, {
        command: 'onNewBlock',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getHeightInfo,
      }]),
    }),

    getNetworkInfo: build.query<any, undefined>({
      query: () => ({
        command: 'getNetworkInfo',
        service: Wallet,
      }),
    }),

    getSyncStatus: build.query<any, undefined>({
      query: () => ({
        command: 'getSyncStatus',
        service: Wallet,
      }),
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onSyncChanged',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getSyncStatus,
      }]),
    }),

    getWalletConnections: build.query<WalletConnections[], undefined>({
      query: () => ({
        command: 'getConnections',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.connections,
      providesTags: (connections) => connections
      ? [
        ...connections.map(({ nodeId }) => ({ type: 'WalletConnections', id: nodeId } as const)),
        { type: 'WalletConnections', id: 'LIST' },
      ] 
      :  [{ type: 'WalletConnections', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onConnections',
        service: Wallet,
        onUpdate: (draft, data) => {
          // empty base array
          draft.splice(0);

          // assign new items
          Object.assign(draft, data.connections);
        },
      }]),
    }),
    openWalletConnection: build.mutation<WalletConnections, { 
      host: string;
      port: number;
    }>({
      query: ({ host, port }) => ({
        command: 'openConnection',
        service: Wallet,
        args: [host, port],
      }),
      invalidatesTags: [{ type: 'WalletConnections', id: 'LIST' }],
    }),
    closeWalletConnection: build.mutation<WalletConnections, { 
      nodeId: string;
    }>({
      query: ({ nodeId }) => ({
        command: 'closeConnection',
        service: Wallet,
        args: [nodeId],
      }),
      invalidatesTags: (_result, _error, { nodeId }) => [{ type: 'WalletConnections', id: 'LIST' }, { type: 'WalletConnections', id: nodeId }],
    }),
    createBackup: build.mutation<any, {
      filePath: string;
    }>({
      query: ({
        filePath,
      }) => ({
        command: 'createBackup',
        service: Wallet,
        args: [filePath],
      }),
    }),

    // Offers
    getAllOffers: build.query<OfferTradeRecord[], undefined>({
      query: () => ({
        command: 'getAllOffers',
        service: Wallet,
      }),
      transformResponse: (response: any) => {
        if (!response?.offers) {
          return response?.tradeRecords;
        }
        return response?.tradeRecords.map((tradeRecord: OfferTradeRecord, index: number) => ({
          ...tradeRecord, _offerData: response?.offers?.[index]
        }));
      },
      providesTags(result) {
        return result ? [
          ...result.map(({ tradeId }) => ({ type: 'OfferTradeRecord', id: tradeId } as const)),
          { type: 'OfferTradeRecord', id: 'LIST' },
        ] : [{ type: 'OfferTradeRecord', id: 'LIST' }];
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onCoinAdded',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getAllOffers,
      }, {
        command: 'onCoinRemoved',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getAllOffers,
      }, {
        command: 'onPendingTransaction',
        service: Wallet,
        endpoint: () => walletApi.endpoints.getAllOffers,
      }]),
    }),

    createOfferForIds: build.mutation<any, {
      walletIdsAndAmounts: { [key: string]: number };
      validateOnly?: boolean;
    }>({
      query: ({
        walletIdsAndAmounts,
        validateOnly,
      }) => ({
        command: 'createOfferForIds',
        service: Wallet,
        args: [walletIdsAndAmounts, validateOnly],
      }),
      invalidatesTags: [{ type: 'OfferTradeRecord', id: 'LIST' }],
    }),

    cancelOffer: build.mutation<any, {
      tradeId: string;
      secure: boolean;
      fee: number | string;
    }>({
      query: ({
        tradeId,
        secure,
        fee,
      }) => ({
        command: 'cancelOffer',
        service: Wallet,
        args: [tradeId, secure, fee],
      }),
      invalidatesTags: (result, error, { tradeId }) => [{ type: 'OfferTradeRecord', id: tradeId }],
    }),

    checkOfferValidity: build.mutation<any, string>({
      query: (offerData: string) => ({
        command: 'checkOfferValidity',
        service: Wallet,
        args: [offerData],
      }),
    }),

    takeOffer: build.mutation<any, {
      offer: string;
      fee: number | string;
    }>({
      query: ({
        offer,
        fee,
      }) => ({
        command: 'takeOffer',
        service: Wallet,
        args: [offer, fee],
      }),
      invalidatesTags: [{ type: 'OfferTradeRecord', id: 'LIST' }],
    }),

    getOfferSummary: build.mutation<any, string>({
      query: (offerData: string) => ({
        command: 'getOfferSummary',
        service: Wallet,
        args: [offerData],
      }),
    }),

    getOfferData: build.mutation<any, string>({
      query: (offerId: string) => ({
        command: 'getOfferData',
        service: Wallet,
        args: [offerId],
      }),
    }),

    getOfferRecord: build.mutation<any, OfferTradeRecord>({
      query: (offerId: string) => ({
        command: 'getOfferRecord',
        service: Wallet,
        args: [offerId],
      }),
    }),

    // Pool
    createNewPoolWallet: build.mutation<{
      transaction: Transaction;
      p2SingletonPuzzleHash: string;
    }, {
      initialTargetState: Object,
      fee?: string,
      host?: string;
    }>({
      query: ({
        initialTargetState,
        fee,
        host
      }) => ({
        command: 'createNewWallet',
        service: Pool,
        args: [initialTargetState, fee, host],
      }),
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }, { type: 'Transactions', id: 'LIST' }],
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
      assetId: string;
      fee: string;
      host?: string;
    }>({
      query: ({
        assetId,
        fee,
        host
      }) => ({
        command: 'createWalletForExisting',
        service: CAT,
        args: [assetId, fee, host],
      }),
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }, { type: 'Transactions', id: 'LIST' }],
    }),
  
    getCATAssetId: build.query<string, {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'getAssetId',
        service: CAT,
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.assetId,
    }),

    getCatList: build.query<{
      assetId: string;
      name: string;
      symbol: string;
    }[], undefined>({
      query: () => ({
        command: 'getCatList',
        service: CAT,
      }),
      transformResponse: (response: any) => response?.catList,
    }),
  
    getCATName: build.query<string, {
      walletId: number;
    }>({
      query: ({
        walletId,
      }) => ({
        command: 'getName',
        service: CAT,
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.name,
    }),
  
    setCATName: build.mutation<any, {
      walletId: number;
      name: string;
    }>({
      query: ({
        walletId,
        name,
      }) => ({
        command: 'setName',
        service: CAT,
        args: [walletId, name],
      }),
      invalidatesTags: [{ type: 'Wallets', id: 'LIST' }],
    }),
  
    spendCAT: build.mutation<any, {
      walletId: number;
      address: string;
      amount: string;
      fee: string;
      memos?: string[];
      waitForConfirmation?: boolean;
    }>({
      async queryFn(args, queryApi, _extraOptions, fetchWithBQ) {
        let subscribeResponse: {
          data: Function;
        } | undefined;

        function unsubscribe() {
          if (subscribeResponse) {
            // console.log('Unsubscribing from tx_updates');
            subscribeResponse.data();
            subscribeResponse = undefined;
          }
        }

        try {
          const { 
            walletId,
            address,
            amount,
            fee,
            memos, 
            waitForConfirmation,
           } = args;
          
          return {
            data: await new Promise(async (resolve, reject) => {
              const updatedTransactions: Transaction[] = [];
              let transactionName: string;

              function processUpdates() {
                if (!transactionName) {
                  console.log(`Transaction name is not defined`, updatedTransactions);
                  return;
                }

                const transaction = updatedTransactions.find(
                  (trx) => trx.name === transactionName && !!trx?.sentTo?.length,
                );

                if (transaction) {
                  // console.log('we found transaction with all data hurai');
                  resolve({
                    transaction,
                    transactionId: transaction.name,
                  });
                } else {
                  // console.log('we do not have transaction in the list with data', updatedTransactions);
                }
              }

              // bind all changes related to transactions
              if (waitForConfirmation) {
                // subscribing to tx_updates
                subscribeResponse = await baseQuery({
                  command: 'onTransactionUpdate',
                  service: Wallet,
                  args: [(data: any) => {
                    const { additionalData: { transaction } } = data;

                    // console.log('update received');
  
                    updatedTransactions.push(transaction);
                    processUpdates();
                  }],
                }, queryApi, {});
              }

              // make transaction
              // console.log('sending transaction');
              const { data: sendTransactionData, error, ...rest } = await fetchWithBQ({
                command: 'spend',
                service: CAT,
                args: [walletId, address, amount, fee, memos],
              });

              // console.log('response', sendTransactionData, error, rest);

              if (error) {
                reject(error);
                return;
              }

              if (!waitForConfirmation) {
                resolve(sendTransactionData);
                return;
              }

              const { transaction } = sendTransactionData;
              if (!transaction) {
                reject(new Error('Transaction is not present in response'));
              }

              transactionName = transaction.name;
              updatedTransactions.push(transaction);
              processUpdates();
            }),
          };
        } catch (error: any) {
          console.log('something went wrong', error);
          return {
            error,
          };
        } finally {
          console.log('unsubscribing')
          unsubscribe();
        }


        /*
        let subscribeResponse: {
          data: Function;
        } | undefined;

        function unsubscribe() {
          if (subscribeResponse) {
            subscribeResponse.data();
            subscribeResponse = undefined;
          }
        }

        try {
          const {
            walletId,
            address,
            amount,
            fee,
            memos, 
            waitForConfirmation,
          } = args;
          
          return {
            data: new Promise(async (resolve, reject) => {
              const updatedTransactions: Transaction[] = [];
              let transactionName: string;

              function processUpdates() {
                if (!transactionName) {
                  return;
                }

                const transaction = updatedTransactions.find(
                  (trx) => trx.name === transactionName && !!trx?.sentTo?.length,
                );

                if (transaction) {
                  resolve({
                    transaction,
                    transactionId: transaction.name,
                  });
                }
              }

              // bind all changes related to transactions
              if (waitForConfirmation) {
                subscribeResponse = await baseQuery({
                  command: 'onTransactionUpdate',
                  args: [(data: any) => {
                    const { additionalData: { transaction } } = data;
  
                    updatedTransactions.push(transaction);
                    processUpdates();
                  }],
                }, queryApi, {});
              }

              // make transaction
              const { data: sendTransactionData, error } = await fetchWithBQ({
                command: 'spend',
                service: CAT,
                args: [walletId, address, amount, fee, memos],
              });

              if (error) {
                reject(error);
                return;
              }

              if (!waitForConfirmation) {
                resolve(sendTransactionData);
                return;
              }

              const { transaction } = sendTransactionData;
              if (!transaction) {
                reject(new Error('Transaction is not present in response'));
              }

              transactionName = transaction.name;
              updatedTransactions.push(transaction);
              processUpdates();
            }),
          };
        } catch (error: any) {
          return {
            error,
          };
        } finally {
          unsubscribe();
        }
        */
      },
      invalidatesTags: [{ type: 'Transactions', id: 'LIST' }],
    }),

    addCATToken: build.mutation<any, {
      assetId: string;
      name: string;
      fee: string;
      host?: string;
    }>({
      async queryFn({ assetId, name, fee, host }, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          const { data, error } = await fetchWithBQ({
            command: 'createWalletForExisting',
            service: CAT,
            args: [assetId, fee, host],
          });

          if (error) {
            throw error;
          }
          
          const walletId = data?.walletId;
          if (!walletId) {
            throw new Error('Wallet id is not defined');
          }

          await fetchWithBQ({
            command: 'setName',
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

    // PlotNFTs
    getPlotNFTs: build.query<Object, undefined>({
      async queryFn(_args, { signal }, _extraOptions, fetchWithBQ) {
        try {
          const [wallets, poolStates] = await Promise.all<Wallet[], PoolState[]>([
            (async () => {
              const { data, error } = await fetchWithBQ({
                command: 'getWallets',
                service: Wallet,
              });
    
              if (error) {
                throw error;
              }
              
              const wallets = data?.wallets;
              if (!wallets) {
                throw new Error('List of the wallets is not defined');
              }

              return wallets;
            })(),
            (async () => {
              const { data, error } = await fetchWithBQ({
                command: 'getPoolState',
                service: Farmer,
              });
    
              if (error) {
                throw error;
              }
              
              const poolState = data?.poolState;
              if (!poolState) {
                throw new Error('Pool state is not defined');
              }

              return poolState;
            })(),
          ]);

          if (signal.aborted) {
            throw new Error('Query was aborted');
          }
    
          // filter pool wallets
          const poolWallets =
            wallets?.filter(
              (wallet) => wallet.type === WalletType.POOLING_WALLET,
            ) ?? [];
    
          const [poolWalletStates, walletBalances] = await Promise.all([
            await Promise.all<PoolWalletStatus>(poolWallets.map(async (wallet) => {
              const { data, error } = await fetchWithBQ({
                command: 'getPwStatus',
                service: Wallet,
                args: [wallet.id],
              });
    
              if (error) {
                throw error;
              }

              return {
                ...data?.state,
                walletId: wallet.id,
              };
            })),
            await Promise.all<WalletBalance>(poolWallets.map(async (wallet) => {
                const { data, error } = await fetchWithBQ({
                  command: 'getWalletBalance',
                  service: Wallet,
                  args: [wallet.id],
                });
      
                if (error) {
                  throw error;
                }

                return data?.walletBalance;
              })),
            ]);

          if (signal.aborted) {
            throw new Error('Query was aborted');
          }
    
          // combine poolState and poolWalletState
          const nfts: PlotNFT[] = [];
          const external: PlotNFTExternal[] = [];
    
          poolStates.forEach((poolStateItem) => {
            const poolWalletStatus = poolWalletStates.find(
              (item) => item.launcherId === poolStateItem.poolConfig.launcherId,
            );
            if (!poolWalletStatus) {
              external.push({
                poolState: normalizePoolState(poolStateItem),
              });
              return;
            }
    
            const walletBalance = walletBalances.find(
              (item) => item?.walletId === poolWalletStatus.walletId,
            );
    
            if (!walletBalance) {
              external.push({
                poolState: normalizePoolState(poolStateItem),
              });
              return;
            }
    
            nfts.push({
              poolState: normalizePoolState(poolStateItem),
              poolWalletStatus,
              walletBalance,
            });
          });

          return {
            data: {
              nfts,
              external,
            },
          };
        } catch (error) {
          return {
            error,
          };
        }
      },
      providesTags: [{ type: 'NFTs', id: 'LIST' }], 
    }),
  }),
});

export const {
  useWalletPingQuery,
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
  useGetWalletConnectionsQuery,
  useOpenWalletConnectionMutation,
  useCloseWalletConnectionMutation,
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

  // CAT
  useCreateNewCATWalletMutation,
  useCreateCATWalletForExistingMutation,
  useGetCATAssetIdQuery,
  useGetCatListQuery,
  useGetCATNameQuery,
  useSetCATNameMutation,
  useSpendCATMutation,
  useAddCATTokenMutation,

  // NFTS
  useGetPlotNFTsQuery,
} = walletApi;
