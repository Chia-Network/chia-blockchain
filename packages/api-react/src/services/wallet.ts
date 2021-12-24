import { createApi } from '@reduxjs/toolkit/query/react';
import { CAT, OfferTradeRecord, Wallet, WalletType } from '@chia/api';
import chiaLazyBaseQuery from '../chiaLazyBaseQuery';
import type Transaction from '../@types/Transaction';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';

const baseQuery = chiaLazyBaseQuery({
  service: Wallet,
});

export const walletApi = createApi({
  reducerPath: 'walletApi',
  baseQuery,
  tagTypes: ['Keys', 'Wallets', 'WalletBalance', 'Address', 'Transactions', 'OfferTradeRecord'],
  endpoints: (build) => ({
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
                // get CAT tail
                const { data: tailData, tailError } = await fetchWithBQ({
                  command: 'getTail',
                  service: CAT,
                  args: [wallet.id],
                });

                if (tailError) {
                  throw tailError;
                }

                meta.tail = tailData.colour;

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
        endpoint: () => walletApi.endpoints.getWallets,
      }]),
    }),

    getTransaction: build.query<Transaction, { 
      transactionId: string;
    }>({
      query: ({ transactionId }) => ({
        command: 'getTransaction',
        args: [transactionId],
      }),
      transformResponse: (response: any) => {
        console.log('TODO transformResponse getTransaction return transaction object', response);
        return response.transaction;
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onTransactionUpdate',
        onUpdate: (draft, data) => {
          const { additionalData: { transaction } } = data;

          Object.assign(draft, transaction);
        },
      }]),
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
      walletType: 'pool_wallet' | 'rl_wallet' | 'did_wallet' | 'cat_wallet';
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
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onCoinAdded',
        endpoint: () => walletApi.endpoints.getWalletBalance,
      }, {
        command: 'onCoinRemoved',
        endpoint: () => walletApi.endpoints.getWalletBalance,
      }, {
        command: 'onPendingTransaction',
        endpoint: () => walletApi.endpoints.getWalletBalance,
      }]),
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

    addKey: build.mutation<number, {
      mnemonic: string[];
      type: 'new_wallet' | 'skip' | 'restore_backup';
      filePath?: string;
    }>({
      query: ({ mnemonic, type, filePath }) => ({
        command: 'addKey',
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
        endpoint: () => walletApi.endpoints.getTransactions,
      }, {
        command: 'onCoinRemoved',
        endpoint: () => walletApi.endpoints.getTransactions,
      }, {
        command: 'onPendingTransaction',
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
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.count,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onCoinAdded',
        endpoint: () => walletApi.endpoints.getTransactionsCount,
      }, {
        command: 'onCoinRemoved',
        endpoint: () => walletApi.endpoints.getTransactionsCount,
      }, {
        command: 'onPendingTransaction',
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

    getHeightInfo: build.query<number, undefined>({
      query: () => ({
        command: 'getHeightInfo',
      }),
      transformResponse: (response: any) => response?.height,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onSyncChanged',
        endpoint: () => walletApi.endpoints.getHeightInfo,
      }, {
        command: 'onNewBlock',
        endpoint: () => walletApi.endpoints.getHeightInfo,
      }]),
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
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [{
        command: 'onSyncChanged',
        endpoint: () => walletApi.endpoints.getSyncStatus,
      }]),
    }),

    getConnections: build.query<any, undefined>({
      query: () => ({
        command: 'getConnections',
      }),
      transformResponse: (response: any) => response?.connections,
      async onCacheEntryAdded(_arg, api) {
        const { updateCachedData, cacheDataLoaded, cacheEntryRemoved } = api;
        let unsubscribe;
        try {
          await cacheDataLoaded;

          const response = await baseQuery({
            command: 'onConnections',
            args: [(data: any) => {
              updateCachedData((draft) => {
                // empty base array
                draft.splice(0);

                // assign new items
                Object.assign(draft, data.connections);
              });
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

    // Offers
    getAllOffers: build.query<OfferTradeRecord[], undefined>({
      query: () => ({
        command: 'getAllOffers',
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
        endpoint: () => walletApi.endpoints.getAllOffers,
      }, {
        command: 'onCoinRemoved',
        endpoint: () => walletApi.endpoints.getAllOffers,
      }, {
        command: 'onPendingTransaction',
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
        args: [tradeId, secure, fee],
      }),
      invalidatesTags: (result, error, { tradeId }) => [{ type: 'OfferTradeRecord', id: tradeId }],
    }),

    checkOfferValidity: build.mutation<any, string>({
      query: (offerData: string) => ({
        command: 'checkOfferValidity',
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
        args: [offer, fee],
      }),
      invalidatesTags: [{ type: 'OfferTradeRecord', id: 'LIST' }],
    }),

    getOfferSummary: build.mutation<any, string>({
      query: (offerData: string) => ({
        command: 'getOfferSummary',
        args: [offerData],
      }),
    }),

    getOfferData: build.mutation<any, string>({
      query: (offerId: string) => ({
        command: 'getOfferData',
        args: [offerId],
      }),
    }),

    getOfferRecord: build.mutation<any, OfferTradeRecord>({
      query: (offerId: string) => ({
        command: 'getOfferRecord',
        args: [offerId],
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
      transformResponse: (response: any) => response?.colour,
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
      tail: string;
      name: string;
      fee: string;
      host?: string;
    }>({
      async queryFn({ tail, name, fee, host }, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          const { data, error } = await fetchWithBQ({
            command: 'createWalletForExisting',
            service: CAT,
            args: [tail, fee, host],
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
  useGetTransactionsCountQuery,
  useGetCurrentAddressQuery,
  useGetNextAddressMutation,
  useFarmBlockMutation,
  useGetHeightInfoQuery,
  useGetNetworkInfoQuery,
  useGetSyncStatusQuery,
  useGetConnectionsQuery,
  useCreateBackupMutation,
  useGetAllOffersQuery,
  useCreateOfferForIdsMutation,
  useCancelOfferMutation,
  useCheckOfferValidityMutation,
  useTakeOfferMutation,
  useGetOfferSummaryMutation,
  useGetOfferDataMutation,
  useGetOfferRecordMutation,

  // CAT
  useCreateNewCATWalletMutation,
  useCreateCATWalletForExistingMutation,
  useGetCATTailQuery,
  useGetCatListQuery,
  useGetCATNameQuery,
  useSetCATNameMutation,
  useSpendCATMutation,
  useAddCATTokenMutation,
} = walletApi;
