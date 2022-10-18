import {
  CAT,
  DID,
  Farmer,
  NFT,
  OfferTradeRecord,
  Pool,
  Wallet,
  WalletType,
  toBech32m,
} from '@chia/api';
import type {
  CalculateRoyaltiesRequest,
  CalculateRoyaltiesResponse,
  CATToken,
  NFTInfo,
  PlotNFT,
  PlotNFTExternal,
  Transaction,
  WalletBalance,
  WalletConnections,
} from '@chia/api';
import BigNumber from 'bignumber.js';
import onCacheEntryAddedInvalidate from '../utils/onCacheEntryAddedInvalidate';
import normalizePoolState from '../utils/normalizePoolState';
import api, { baseQuery } from '../api';

const apiWithTag = api.enhanceEndpoints({
  addTagTypes: [
    'Address',
    'DID',
    'DIDCoinInfo',
    'DIDName',
    'DIDPubKey',
    'DIDRecoveryInfo',
    'DIDRecoveryList',
    'DIDWallet',
    'Keys',
    'LoggedInFingerprint',
    'NFTInfo',
    'NFTRoyalties',
    'NFTWalletWithDID',
    'OfferCounts',
    'OfferTradeRecord',
    'PlotNFT',
    'PoolWalletStatus',
    'TransactionCount',
    'Transactions',
    'WalletBalance',
    'WalletConnections',
    'Wallets',
    'DerivationIndex',
    'CATs',
    'DaemonKey',
  ],
});

type OfferCounts = {
  total: number;
  my_offers: number;
  taken_offers: number;
};

export const walletApi = apiWithTag.injectEndpoints({
  endpoints: (build) => ({
    walletPing: build.query<boolean, {}>({
      query: () => ({
        command: 'ping',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.success,
    }),

    getLoggedInFingerprint: build.query<string | undefined, {}>({
      query: () => ({
        command: 'getLoggedInFingerprint',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.fingerprint,
      providesTags: ['LoggedInFingerprint'],
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
            data: await Promise.all(
              wallets.map(async (wallet: Wallet) => {
                const { type } = wallet;
                const meta = {};
                if (type === WalletType.CAT) {
                  // get CAT asset
                  const { data: assetData, error: assetError } =
                    await fetchWithBQ({
                      command: 'getAssetId',
                      service: CAT,
                      args: [wallet.id],
                    });

                  if (assetError) {
                    throw assetError;
                  }

                  meta.assetId = assetData.assetId;

                  // get CAT name
                  const { data: nameData, error: nameError } =
                    await fetchWithBQ({
                      command: 'getName',
                      service: CAT,
                      args: [wallet.id],
                    });

                  if (nameError) {
                    throw nameError;
                  }

                  meta.name = nameData.name;
                } else if (type === WalletType.NFT) {
                  // get DID assigned to the NFT Wallet (if any)
                  const { data: didData, error: didError } = await fetchWithBQ({
                    command: 'getNftWalletDid',
                    service: NFT,
                    args: [wallet.id],
                  });

                  if (didError) {
                    throw didError;
                  }

                  meta.did = didData.didId;
                }

                return {
                  ...wallet,
                  meta,
                };
              })
            ),
          };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
      // transformResponse: (response: any) => response?.wallets,
      providesTags(result) {
        return result
          ? [
              ...result.map(({ id }) => ({ type: 'Wallets', id } as const)),
              { type: 'Wallets', id: 'LIST' },
            ]
          : [{ type: 'Wallets', id: 'LIST' }];
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onWalletCreated',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getWallets,
        },
      ]),
    }),

    getTransaction: build.query<
      Transaction,
      {
        transactionId: string;
      }
    >({
      query: ({ transactionId }) => ({
        command: 'getTransaction',
        service: Wallet,
        args: [transactionId],
      }),
      transformResponse: (response: any) => response?.transaction,
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onTransactionUpdate',
          service: Wallet,
          onUpdate: (draft, data, { transactionId }) => {
            const {
              additionalData: { transaction },
            } = data;

            if (transaction.name === transactionId) {
              Object.assign(draft, transaction);
            }
          },
        },
      ]),
    }),

    getPwStatus: build.query<
      any,
      {
        walletId: number;
      }
    >({
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
        return result ? [{ type: 'PoolWalletStatus', id: walletId }] : [];
      },
    }),

    pwAbsorbRewards: build.mutation<
      any,
      {
        walletId: number;
        fee: string;
      }
    >({
      query: ({ walletId, fee }) => ({
        command: 'pwAbsorbRewards',
        service: Wallet,
        args: [walletId, fee],
      }),
      invalidatesTags: [
        { type: 'Transactions', id: 'LIST' },
        { type: 'PlotNFT', id: 'LIST' },
      ],
    }),

    pwJoinPool: build.mutation<
      any,
      {
        walletId: number;
        poolUrl: string;
        relativeLockHeight: number;
        targetPuzzleHash?: string;
        fee?: string;
      }
    >({
      query: ({
        walletId,
        poolUrl,
        relativeLockHeight,
        targetPuzzleHash,
        fee,
      }) => ({
        command: 'pwJoinPool',
        service: Wallet,
        args: [walletId, poolUrl, relativeLockHeight, targetPuzzleHash, fee],
      }),
      invalidatesTags: [
        { type: 'Transactions', id: 'LIST' },
        { type: 'PlotNFT', id: 'LIST' },
      ],
    }),

    pwSelfPool: build.mutation<
      any,
      {
        walletId: number;
        fee?: string;
      }
    >({
      query: ({ walletId, fee }) => ({
        command: 'pwSelfPool',
        service: Wallet,
        args: [walletId, fee],
      }),
      invalidatesTags: [
        { type: 'Transactions', id: 'LIST' },
        { type: 'PlotNFT', id: 'LIST' },
      ],
    }),

    createNewWallet: build.mutation<
      any,
      {
        walletType: 'pool_wallet' | 'rl_wallet' | 'did_wallet' | 'cat_wallet';
        options?: Object;
      }
    >({
      query: ({ walletType, options }) => ({
        command: 'createNewWallet',
        service: Wallet,
        args: [walletType, options],
      }),
      invalidatesTags: [
        { type: 'Wallets', id: 'LIST' },
        { type: 'DIDWallet', id: 'LIST' },
      ],
    }),

    deleteUnconfirmedTransactions: build.mutation<
      any,
      {
        walletId: number;
      }
    >({
      query: ({ walletId }) => ({
        command: 'deleteUnconfirmedTransactions',
        service: Wallet,
        args: [walletId],
      }),
      invalidatesTags: (_result, _error, { walletId }) => [
        { type: 'Transactions', id: 'LIST' },
        { type: 'TransactionCount', id: walletId },
      ],
    }),

    getWalletBalance: build.query<
      {
        confirmedWalletBalance: number;
        maxSendAmount: number;
        pendingChange: number;
        pendingCoinRemovalCount: number;
        spendableBalance: number;
        unconfirmedWalletBalance: number;
        unspentCoinCount: number;
        walletId: number;
        pendingBalance: BigNumber;
        pendingTotalBalance: BigNumber;
      },
      {
        walletId: number;
      }
    >({
      query: ({ walletId }) => ({
        command: 'getWalletBalance',
        service: Wallet,
        args: [walletId],
      }),
      transformResponse: (response) => {
        const {
          walletBalance,
          walletBalance: { confirmedWalletBalance, unconfirmedWalletBalance },
        } = response;

        const pendingBalance = new BigNumber(unconfirmedWalletBalance).minus(
          confirmedWalletBalance
        );
        const pendingTotalBalance = new BigNumber(confirmedWalletBalance).plus(
          pendingBalance
        );

        return {
          ...walletBalance,
          pendingBalance,
          pendingTotalBalance,
        };
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onCoinAdded',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getWalletBalance,
        },
        {
          command: 'onCoinRemoved',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getWalletBalance,
        },
        {
          command: 'onPendingTransaction',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getWalletBalance,
        },
        {
          command: 'onOfferAdded',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getWalletBalance,
        },
        {
          command: 'onOfferUpdated',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getWalletBalance,
        },
      ]),
    }),

    getFarmedAmount: build.query<any, undefined>({
      query: () => ({
        command: 'getFarmedAmount',
        service: Wallet,
      }),
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onCoinAdded',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getFarmedAmount,
        },
        {
          command: 'onCoinRemoved',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getFarmedAmount,
        },
      ]),
    }),

    sendTransaction: build.mutation<
      any,
      {
        walletId: number;
        amount: string;
        fee: string;
        address: string;
        waitForConfirmation?: boolean;
      }
    >({
      async queryFn(args, queryApi, _extraOptions, fetchWithBQ) {
        let subscribeResponse:
          | {
              data: Function;
            }
          | undefined;

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

                const transaction = updatedTransactions.find((trx) => {
                  if (trx.name !== transactionName) {
                    return false;
                  }

                  if (!trx?.sentTo?.length) {
                    return false;
                  }

                  const validSentTo = trx.sentTo.find(
                    (record: [string, number, string | null]) => {
                      const [, , error] = record;

                      if (error === 'NO_TRANSACTIONS_WHILE_SYNCING') {
                        return false;
                      }

                      return true;
                    }
                  );

                  return !!validSentTo;
                });

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
                subscribeResponse = await baseQuery(
                  {
                    command: 'onTransactionUpdate',
                    service: Wallet,
                    args: [
                      (data: any) => {
                        const {
                          additionalData: { transaction },
                        } = data;

                        updatedTransactions.push(transaction);
                        processUpdates();
                      },
                    ],
                  },
                  queryApi,
                  {}
                );
              }

              // make transaction
              const { data: sendTransactionData, error } = await fetchWithBQ({
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
          console.log('error trx', error);
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
      providesTags: (keys) =>
        keys
          ? [
              ...keys.map((key) => ({ type: 'Keys', id: key } as const)),
              { type: 'Keys', id: 'LIST' },
            ]
          : [{ type: 'Keys', id: 'LIST' }],
    }),

    addKey: build.mutation<
      number,
      {
        mnemonic: string[];
        type: 'new_wallet' | 'skip' | 'restore_backup';
        filePath?: string;
      }
    >({
      query: ({ mnemonic, type, filePath }) => ({
        command: 'addKey',
        service: Wallet,
        args: [mnemonic, type, filePath],
      }),
      transformResponse: (response: any) => response?.fingerprint,
      invalidatesTags: [
        { type: 'Keys', id: 'LIST' },
        { type: 'DaemonKey', id: 'LIST' },
      ],
    }),

    deleteKey: build.mutation<
      any,
      {
        fingerprint: number;
      }
    >({
      query: ({ fingerprint }) => ({
        command: 'deleteKey',
        service: Wallet,
        args: [fingerprint],
      }),
      invalidatesTags: (_result, _error, { fingerprint }) => [
        { type: 'Keys', id: fingerprint },
        { type: 'Keys', id: 'LIST' },
        { type: 'DaemonKey', id: fingerprint },
        { type: 'DaemonKey', id: 'LIST' },
      ],
    }),

    checkDeleteKey: build.mutation<
      {
        fingerprint: number;
        success: boolean;
        usedForFarmerRewards: boolean;
        usedForPoolRewards: boolean;
        walletBalance: boolean;
      },
      {
        fingerprint: string;
      }
    >({
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
      invalidatesTags: [
        { type: 'Keys', id: 'LIST' },
        { type: 'DaemonKey', id: 'LIST' },
      ],
    }),

    logIn: build.mutation<
      any,
      {
        fingerprint: string;
        type?: 'normal' | 'skip' | 'restore_backup';
        host?: string;
        filePath?: string;
      }
    >({
      query: ({ fingerprint, type, filePath, host }) => ({
        command: 'logIn',
        service: Wallet,
        args: [fingerprint, type, filePath, host],
      }),
      invalidatesTags: ['LoggedInFingerprint'],
    }),

    logInAndSkipImport: build.mutation<
      any,
      {
        fingerprint: string;
        host?: string;
      }
    >({
      query: ({ fingerprint, host }) => ({
        command: 'logInAndSkipImport',
        service: Wallet,
        args: [fingerprint, host],
      }),
      invalidatesTags: ['LoggedInFingerprint'],
    }),

    logInAndImportBackup: build.mutation<
      any,
      {
        fingerprint: string;
        filePath: string;
        host?: string;
      }
    >({
      query: ({ fingerprint, filePath, host }) => ({
        command: 'logInAndImportBackup',
        service: Wallet,
        args: [fingerprint, filePath, host],
      }),
    }),

    getBackupInfo: build.query<
      any,
      {
        filePath: string;
        options: { fingerprint: string } | { words: string };
      }
    >({
      query: ({ filePath, options }) => ({
        command: 'getBackupInfo',
        service: Wallet,
        args: [filePath, options],
      }),
    }),

    getBackupInfoByFingerprint: build.query<
      any,
      {
        filePath: string;
        fingerprint: string;
      }
    >({
      query: ({ filePath, fingerprint }) => ({
        command: 'getBackupInfoByFingerprint',
        service: Wallet,
        args: [filePath, fingerprint],
      }),
    }),

    getBackupInfoByWords: build.query<
      any,
      {
        filePath: string;
        words: string;
      }
    >({
      query: ({ filePath, words }) => ({
        command: 'getBackupInfoByWords',
        service: Wallet,
        args: [filePath, words],
      }),
    }),

    getPrivateKey: build.query<
      {
        farmerPk: string;
        fingerprint: number;
        pk: string;
        poolPk: string;
        seed?: string;
        sk: string;
      },
      {
        fingerprint: string;
      }
    >({
      query: ({ fingerprint }) => ({
        command: 'getPrivateKey',
        service: Wallet,
        args: [fingerprint],
      }),
      transformResponse: (response: any) => response?.privateKey,
    }),

    getTransactions: build.query<
      Transaction[],
      {
        walletId: number;
        start?: number;
        end?: number;
        sortKey?: 'CONFIRMED_AT_HEIGHT' | 'RELEVANCE';
        reverse?: boolean;
      }
    >({
      query: ({ walletId, start, end, sortKey, reverse }) => ({
        command: 'getTransactions',
        service: Wallet,
        args: [walletId, start, end, sortKey, reverse],
      }),
      transformResponse: (response: any) => response?.transactions,
      providesTags(result) {
        return result
          ? [
              ...result.map(
                ({ name }) => ({ type: 'Transactions', id: name } as const)
              ),
              { type: 'Transactions', id: 'LIST' },
            ]
          : [{ type: 'Transactions', id: 'LIST' }];
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onCoinAdded',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getTransactions,
        },
        {
          command: 'onCoinRemoved',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getTransactions,
        },
        {
          command: 'onPendingTransaction',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getTransactions,
        },
      ]),
    }),

    getTransactionsCount: build.query<
      number,
      {
        walletId: number;
      }
    >({
      query: ({ walletId }) => ({
        command: 'getTransactionsCount',
        service: Wallet,
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.count,
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'TransactionCount', id: walletId }] : [],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onCoinAdded',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getTransactionsCount,
        },
        {
          command: 'onCoinRemoved',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getTransactionsCount,
        },
        {
          command: 'onPendingTransaction',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getTransactionsCount,
        },
      ]),
    }),

    getCurrentAddress: build.query<
      string,
      {
        walletId: number;
      }
    >({
      query: ({ walletId }) => ({
        command: 'getNextAddress',
        service: Wallet,
        args: [walletId, false],
      }),
      transformResponse: (response: any) => response?.address,
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'Address', id: walletId }] : [],
    }),

    getNextAddress: build.mutation<
      string,
      {
        walletId: number;
        newAddress: boolean;
      }
    >({
      query: ({ walletId, newAddress }) => ({
        command: 'getNextAddress',
        service: Wallet,
        args: [walletId, newAddress],
      }),
      transformResponse: (response: any) => response?.address,
      invalidatesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'Address', id: walletId }] : [],
    }),

    farmBlock: build.mutation<
      any,
      {
        address: string;
      }
    >({
      query: ({ address }) => ({
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
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onSyncChanged',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getHeightInfo,
        },
        {
          command: 'onNewBlock',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getHeightInfo,
        },
      ]),
    }),

    getCurrentDerivationIndex: build.query<number, undefined>({
      query: () => ({
        command: 'getCurrentDerivationIndex',
        service: Wallet,
      }),
      providesTags: (result) => (result ? [{ type: 'DerivationIndex' }] : []),
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onNewDerivationIndex',
          service: Wallet,
          onUpdate: (draft, data) => {
            draft.index = data?.additionalData?.index;
          },
        },
      ]),
    }),
    extendDerivationIndex: build.mutation<
      undefined,
      {
        index: number;
      }
    >({
      query: ({ index }) => ({
        command: 'extendDerivationIndex',
        service: Wallet,
        args: [index],
      }),
      invalidatesTags: [{ type: 'DerivationIndex' }],
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
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onSyncChanged',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getSyncStatus,
        },
        {
          command: 'onNewBlock',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getSyncStatus,
        },
      ]),
    }),

    getWalletConnections: build.query<WalletConnections[], undefined>({
      query: () => ({
        command: 'getConnections',
        service: Wallet,
      }),
      transformResponse: (response: any) => response?.connections,
      providesTags: (connections) =>
        connections
          ? [
              ...connections.map(
                ({ nodeId }) =>
                  ({ type: 'WalletConnections', id: nodeId } as const)
              ),
              { type: 'WalletConnections', id: 'LIST' },
            ]
          : [{ type: 'WalletConnections', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onConnections',
          service: Wallet,
          onUpdate: (draft, data) => {
            // empty base array
            draft.splice(0);

            // assign new items
            Object.assign(draft, data.connections);
          },
        },
      ]),
    }),
    openWalletConnection: build.mutation<
      WalletConnections,
      {
        host: string;
        port: number;
      }
    >({
      query: ({ host, port }) => ({
        command: 'openConnection',
        service: Wallet,
        args: [host, port],
      }),
      invalidatesTags: [{ type: 'WalletConnections', id: 'LIST' }],
    }),
    closeWalletConnection: build.mutation<
      WalletConnections,
      {
        nodeId: string;
      }
    >({
      query: ({ nodeId }) => ({
        command: 'closeConnection',
        service: Wallet,
        args: [nodeId],
      }),
      invalidatesTags: (_result, _error, { nodeId }) => [
        { type: 'WalletConnections', id: 'LIST' },
        { type: 'WalletConnections', id: nodeId },
      ],
    }),
    createBackup: build.mutation<
      any,
      {
        filePath: string;
      }
    >({
      query: ({ filePath }) => ({
        command: 'createBackup',
        service: Wallet,
        args: [filePath],
      }),
    }),

    // Offers
    getAllOffers: build.query<
      OfferTradeRecord[],
      {
        start?: number;
        end?: number;
        sortKey?: 'CONFIRMED_AT_HEIGHT' | 'RELEVANCE';
        reverse?: boolean;
        includeMyOffers?: boolean;
        includeTakenOffers?: boolean;
      }
    >({
      query: ({
        start,
        end,
        sortKey,
        reverse,
        includeMyOffers,
        includeTakenOffers,
      }) => ({
        command: 'getAllOffers',
        service: Wallet,
        args: [
          start,
          end,
          sortKey,
          reverse,
          includeMyOffers,
          includeTakenOffers,
        ],
      }),
      transformResponse: (response: any) => {
        if (!response?.offers) {
          return response?.tradeRecords;
        }
        return response?.tradeRecords.map(
          (tradeRecord: OfferTradeRecord, index: number) => ({
            ...tradeRecord,
            _offerData: response?.offers?.[index],
          })
        );
      },
      providesTags(result) {
        return result
          ? [
              ...result.map(
                ({ tradeId }) =>
                  ({ type: 'OfferTradeRecord', id: tradeId } as const)
              ),
              { type: 'OfferTradeRecord', id: 'LIST' },
            ]
          : [{ type: 'OfferTradeRecord', id: 'LIST' }];
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onCoinAdded',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getAllOffers,
        },
        {
          command: 'onCoinRemoved',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getAllOffers,
        },
        {
          command: 'onPendingTransaction',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getAllOffers,
        },
      ]),
    }),

    getOffersCount: build.query<OfferCounts, undefined>({
      query: () => ({
        command: 'getOffersCount',
        service: Wallet,
      }),
      providesTags: ['OfferCounts'],
    }),

    createOfferForIds: build.mutation<
      any,
      {
        walletIdsAndAmounts: { [key: string]: number };
        feeInMojos: number;
        driverDict: any;
        validateOnly?: boolean;
        disableJSONFormatting?: boolean;
      }
    >({
      query: ({
        walletIdsAndAmounts,
        feeInMojos,
        driverDict,
        validateOnly,
        disableJSONFormatting,
      }) => ({
        command: 'createOfferForIds',
        service: Wallet,
        args: [
          walletIdsAndAmounts,
          feeInMojos,
          driverDict,
          validateOnly,
          disableJSONFormatting,
        ],
      }),
      invalidatesTags: [
        { type: 'OfferTradeRecord', id: 'LIST' },
        'OfferCounts',
      ],
    }),

    cancelOffer: build.mutation<
      any,
      {
        tradeId: string;
        secure: boolean;
        fee: number | string;
      }
    >({
      query: ({ tradeId, secure, fee }) => ({
        command: 'cancelOffer',
        service: Wallet,
        args: [tradeId, secure, fee],
      }),
      invalidatesTags: (result, error, { tradeId }) => [
        { type: 'OfferTradeRecord', id: tradeId },
      ],
    }),

    checkOfferValidity: build.mutation<any, string>({
      query: (offerData: string) => ({
        command: 'checkOfferValidity',
        service: Wallet,
        args: [offerData],
      }),
    }),

    takeOffer: build.mutation<
      any,
      {
        offer: string;
        fee: number | string;
      }
    >({
      query: ({ offer, fee }) => ({
        command: 'takeOffer',
        service: Wallet,
        args: [offer, fee],
      }),
      invalidatesTags: [
        { type: 'OfferTradeRecord', id: 'LIST' },
        'OfferCounts',
      ],
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
    createNewPoolWallet: build.mutation<
      {
        transaction: Transaction;
        p2SingletonPuzzleHash: string;
      },
      {
        initialTargetState: Object;
        fee?: string;
        host?: string;
      }
    >({
      query: ({ initialTargetState, fee, host }) => ({
        command: 'createNewWallet',
        service: Pool,
        args: [initialTargetState, fee, host],
      }),
      invalidatesTags: [
        { type: 'Wallets', id: 'LIST' },
        { type: 'Transactions', id: 'LIST' },
      ],
    }),

    // CAT
    createNewCATWallet: build.mutation<
      any,
      {
        amount: string;
        fee: string;
        host?: string;
      }
    >({
      query: ({ amount, fee, host }) => ({
        command: 'createNewWallet',
        service: CAT,
        args: [amount, fee, host],
      }),
      invalidatesTags: [
        { type: 'Wallets', id: 'LIST' },
        { type: 'Transactions', id: 'LIST' },
      ],
    }),

    createCATWalletForExisting: build.mutation<
      any,
      {
        assetId: string;
        fee: string;
        host?: string;
      }
    >({
      query: ({ assetId, fee, host }) => ({
        command: 'createWalletForExisting',
        service: CAT,
        args: [assetId, fee, host],
      }),
      invalidatesTags: [
        { type: 'Wallets', id: 'LIST' },
        { type: 'Transactions', id: 'LIST' },
      ],
    }),

    getCATAssetId: build.query<
      string,
      {
        walletId: number;
      }
    >({
      query: ({ walletId }) => ({
        command: 'getAssetId',
        service: CAT,
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.assetId,
    }),

    getCatList: build.query<CATToken[], undefined>({
      query: () => ({
        command: 'getCatList',
        service: CAT,
      }),
      transformResponse: (response: any) => response?.catList,
      providesTags(result) {
        return result
          ? [
              ...result.map(({ id }) => ({ type: 'CATs', id } as const)),
              { type: 'CATs', id: 'LIST' },
            ]
          : [{ type: 'CATs', id: 'LIST' }];
      },
    }),

    getCATName: build.query<
      string,
      {
        walletId: number;
      }
    >({
      query: ({ walletId }) => ({
        command: 'getName',
        service: CAT,
        args: [walletId],
      }),
      transformResponse: (response: any) => response?.name,
    }),

    setCATName: build.mutation<
      any,
      {
        walletId: number;
        name: string;
      }
    >({
      query: ({ walletId, name }) => ({
        command: 'setName',
        service: CAT,
        args: [walletId, name],
      }),
      invalidatesTags: [
        { type: 'Wallets', id: 'LIST' },
        { type: 'CATs', id: 'LIST' },
      ],
    }),

    getStrayCats: build.query<
      {
        assetId: string;
        name: string;
        firstSeenHeight: number;
        senderPuzzleHash: string;
        inTransaction: boolean;
      }[],
      undefined
    >({
      query: () => ({
        command: 'getStrayCats',
        service: CAT,
      }),
      transformResponse: (response: any) => response?.strayCats,
    }),

    spendCAT: build.mutation<
      any,
      {
        walletId: number;
        address: string;
        amount: string;
        fee: string;
        memos?: string[];
        waitForConfirmation?: boolean;
      }
    >({
      async queryFn(args, queryApi, _extraOptions, fetchWithBQ) {
        let subscribeResponse:
          | {
              data: Function;
            }
          | undefined;

        function unsubscribe() {
          if (subscribeResponse) {
            // console.log('Unsubscribing from tx_updates');
            subscribeResponse.data();
            subscribeResponse = undefined;
          }
        }

        try {
          const { walletId, address, amount, fee, memos, waitForConfirmation } =
            args;

          return {
            data: await new Promise(async (resolve, reject) => {
              const updatedTransactions: Transaction[] = [];
              let transactionName: string;

              function processUpdates() {
                if (!transactionName) {
                  console.log(
                    `Transaction name is not defined`,
                    updatedTransactions
                  );
                  return;
                }

                const transaction = updatedTransactions.find(
                  (trx) => trx.name === transactionName && !!trx?.sentTo?.length
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
                subscribeResponse = await baseQuery(
                  {
                    command: 'onTransactionUpdate',
                    service: Wallet,
                    args: [
                      (data: any) => {
                        const {
                          additionalData: { transaction },
                        } = data;

                        // console.log('update received');

                        updatedTransactions.push(transaction);
                        processUpdates();
                      },
                    ],
                  },
                  queryApi,
                  {}
                );
              }

              // make transaction
              // console.log('sending transaction');
              const {
                data: sendTransactionData,
                error,
                ...rest
              } = await fetchWithBQ({
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
          return {
            error,
          };
        } finally {
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

    addCATToken: build.mutation<
      any,
      {
        assetId: string;
        name: string;
        fee: string;
        host?: string;
      }
    >({
      async queryFn(
        { assetId, name, fee, host },
        _queryApi,
        _extraOptions,
        fetchWithBQ
      ) {
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
      invalidatesTags: [
        { type: 'Wallets', id: 'LIST' },
        { type: 'Transactions', id: 'LIST' },
      ],
    }),

    // PlotNFTs
    getPlotNFTs: build.query<Object, undefined>({
      async queryFn(_args, { signal }, _extraOptions, fetchWithBQ) {
        try {
          const [wallets, poolStates] = await Promise.all<
            Wallet[],
            PoolState[]
          >([
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
              (wallet) => wallet.type === WalletType.POOLING_WALLET
            ) ?? [];

          const [poolWalletStates, walletBalances] = await Promise.all([
            await Promise.all<PoolWalletStatus>(
              poolWallets.map(async (wallet) => {
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
              })
            ),
            await Promise.all<WalletBalance>(
              poolWallets.map(async (wallet) => {
                const { data, error } = await fetchWithBQ({
                  command: 'getWalletBalance',
                  service: Wallet,
                  args: [wallet.id],
                });

                if (error) {
                  throw error;
                }

                return data?.walletBalance;
              })
            ),
          ]);

          if (signal.aborted) {
            throw new Error('Query was aborted');
          }

          // combine poolState and poolWalletState
          const nfts: PlotNFT[] = [];
          const external: PlotNFTExternal[] = [];

          poolStates.forEach((poolStateItem) => {
            const poolWalletStatus = poolWalletStates.find(
              (item) => item.launcherId === poolStateItem.poolConfig.launcherId
            );
            if (!poolWalletStatus) {
              external.push({
                poolState: normalizePoolState(poolStateItem),
              });
              return;
            }

            const walletBalance = walletBalances.find(
              (item) => item?.walletId === poolWalletStatus.walletId
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
      providesTags: [{ type: 'PlotNFT', id: 'LIST' }],
    }),

    // DID
    createNewDIDWallet: build.mutation<
      any,
      {
        amount: string;
        fee: string;
        backupDids?: string[];
        numOfBackupIdsNeeded?: number;
        host?: string;
      }
    >({
      query: ({ amount, fee, backupDids, numOfBackupIdsNeeded, host }) => ({
        command: 'createNewWallet',
        service: DID,
        args: [amount, fee, backupDids, numOfBackupIdsNeeded, host],
      }),
      invalidatesTags: [
        { type: 'Wallets', id: 'LIST' },
        { type: 'DIDWallet', id: 'LIST' },
        { type: 'Transactions', id: 'LIST' },
      ],
    }),

    getDIDName: build.query<any, { walletId: number }>({
      query: ({ walletId }) => ({
        command: 'getDidName',
        service: DID,
        args: [walletId],
      }),
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'DIDName', id: walletId }] : [],
    }),

    setDIDName: build.mutation<
      any,
      {
        walletId: number;
        name: string;
      }
    >({
      query: ({ walletId, name }) => ({
        command: 'setDIDName',
        service: DID,
        args: [walletId, name],
      }),
      invalidatesTags: (_result, _error, { walletId }) => [
        { type: 'Wallets', id: walletId },
        { type: 'DIDWallet', id: walletId },
        { type: 'DIDName', id: walletId },
      ],
    }),

    updateDIDRecoveryIds: build.mutation<
      any,
      {
        walletId: number;
        newList: string[];
        numVerificationsRequired: number;
      }
    >({
      query: ({ walletId, newList, numVerificationsRequired }) => ({
        command: 'updateRecoveryIds',
        service: DID,
        args: [walletId, newList, numVerificationsRequired],
      }),
      invalidatesTags: (_result, _error, { walletId }) => [
        { type: 'Wallets', id: walletId },
        { type: 'DIDRecoveryList', id: walletId },
      ],
    }),

    getDIDPubKey: build.query<any, { walletId: number }>({
      query: ({ walletId }) => ({
        command: 'getPubKey',
        service: DID,
        args: [walletId],
      }),
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'DIDPubKey', id: walletId }] : [],
    }),

    getDID: build.query<any, { walletId: number }>({
      query: ({ walletId }) => ({
        command: 'getDid',
        service: DID,
        args: [walletId],
      }),
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'DID', id: walletId }] : [],
    }),

    getDIDs: build.query<Wallet[], undefined>({
      async queryFn(args, _queryApi, _extraOptions, fetchWithBQ) {
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
            throw new Error('Wallets are not defined');
          }

          const didWallets = wallets.filter(
            (wallet) => wallet.type === WalletType.DECENTRALIZED_ID
          );

          return {
            data: await Promise.all(
              didWallets.map(async (wallet: Wallet) => {
                const { data, error } = await fetchWithBQ({
                  command: 'getDid',
                  service: DID,
                  args: [wallet.id],
                });

                if (error) {
                  throw error;
                }

                const { myDid } = data;

                return {
                  ...wallet,
                  myDid,
                };
              })
            ),
          };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
      providesTags(result) {
        return result
          ? [
              ...result.map(({ id }) => ({ type: 'DIDWallet', id } as const)),
              { type: 'DIDWallet', id: 'LIST' },
            ]
          : [{ type: 'DIDWallet', id: 'LIST' }];
      },
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onWalletCreated',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getWallets,
        },
      ]),
    }),

    // spendDIDRecovery: did_recovery_spend needs an RPC change (attest_filenames -> attest_file_contents)

    getDIDRecoveryList: build.query<any, { walletId: number }>({
      query: ({ walletId }) => ({
        command: 'getRecoveryList',
        service: DID,
        args: [walletId],
      }),
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'DIDRecoveryList', id: walletId }] : [],
    }),

    // createDIDAttest: did_create_attest needs an RPC change (remove filename param, return file contents)

    getDIDInformationNeededForRecovery: build.query<any, { walletId: number }>({
      query: ({ walletId }) => ({
        command: 'getInformationNeededForRecovery',
        service: DID,
        args: [walletId],
      }),
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'DIDRecoveryInfo', id: walletId }] : [],
    }),

    getDIDCurrentCoinInfo: build.query<any, { walletId: number }>({
      query: ({ walletId }) => ({
        command: 'getCurrentCoinInfo',
        service: DID,
        args: [walletId],
      }),
      providesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'DIDCoinInfo', id: walletId }] : [],
    }),

    // createDIDBackup: did_create_backup_file needs an RPC change (remove filename param, return file contents)

    // NFTs
    calculateRoyaltiesForNFTs: build.query<
      CalculateRoyaltiesResponse,
      CalculateRoyaltiesRequest
    >({
      query: (request) => ({
        command: 'calculateRoyalties',
        service: NFT,
        args: [request],
      }),
      providesTags: ['NFTRoyalties'],
    }),

    getNFTsByNFTIDs: build.query<any, { nftIds: string[] }>({
      async queryFn(args, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          const nfts = await Promise.all(
            args.nftIds.map(async (nftId) => {
              const { data: nftData, error: nftError } = await fetchWithBQ({
                command: 'getNftInfo',
                service: NFT,
                args: [nftId],
              });

              if (nftError) {
                throw nftError;
              }

              // Add bech32m-encoded NFT identifier
              const updatedNFT = {
                ...nftData.nftInfo,
                $nftId: toBech32m(nftData.nftInfo.launcherId, 'nft'),
              };

              return updatedNFT;
            })
          );

          return {
            data: nfts,
          };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
    }),

    getNFTs: build.query<
      { [walletId: number]: NFTInfo[] },
      { walletIds: number[] }
    >({
      async queryFn(args, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          const nftData: { [walletId: number]: NFTInfo[] }[] =
            await Promise.all(
              args.walletIds.map(async (walletId) => {
                const { data: nftsData, error: nftsError } = await fetchWithBQ({
                  command: 'getNfts',
                  service: NFT,
                  args: [walletId],
                });

                if (nftsError) {
                  throw nftsError;
                }

                // Add bech32m-encoded NFT identifier
                const updatedNFTs = nftsData.nftList.map((nft) => {
                  return {
                    ...nft,
                    walletId,
                    $nftId: toBech32m(nft.launcherId, 'nft'),
                  };
                });

                return {
                  [walletId]: updatedNFTs,
                };
              })
            );
          const nftsByWalletId: { [walletId: number]: NFTInfo[] } = {};
          nftData.forEach((entry) => {
            Object.entries(entry).forEach(([walletId, nfts]) => {
              nftsByWalletId[walletId] = nfts;
            });
          });
          return {
            data: nftsByWalletId,
          };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
      providesTags: (nftsByWalletId, _error) =>
        nftsByWalletId
          ? [
              ...Object.entries(nftsByWalletId).flatMap(([_walletId, nfts]) => {
                return nfts.map(
                  (nft) => ({ type: 'NFTInfo', id: nft.launcherId } as const)
                );
              }),
              { type: 'NFTInfo', id: 'LIST' },
            ]
          : [{ type: 'NFTInfo', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onNFTCoinAdded',
          service: NFT,
          endpoint: () => walletApi.endpoints.getNFTs,
        },
        {
          command: 'onNFTCoinRemoved',
          service: NFT,
          endpoint: () => walletApi.endpoints.getNFTs,
        },
        {
          command: 'onNFTCoinTransferred',
          service: NFT,
          endpoint: () => walletApi.endpoints.getNFTs,
        },
      ]),
    }),

    getNFTWalletsWithDIDs: build.query<any, {}>({
      query: () => ({
        command: 'getNftWalletsWithDids',
        service: NFT,
        args: [],
      }),
      transformResponse: (response: any) => response?.nftWallets,
      providesTags: (result, _error) =>
        result
          ? [
              ...result.map(({ walletId }) => ({
                type: 'NFTWalletWithDID',
                id: walletId,
              })),
              { type: 'NFTWalletWithDID', id: 'LIST' },
            ]
          : [{ type: 'NFTWalletWithDID', id: 'LIST' }],
      onCacheEntryAdded: onCacheEntryAddedInvalidate(baseQuery, [
        {
          command: 'onWalletCreated',
          service: Wallet,
          endpoint: () => walletApi.endpoints.getNFTWalletsWithDIDs,
        },
      ]),
    }),

    getNFTInfo: build.query<any, { coinId: string }>({
      async queryFn(args, _queryApi, _extraOptions, fetchWithBQ) {
        try {
          // Slice off the '0x' prefix, if present
          const coinId = args.coinId.toLowerCase().startsWith('0x')
            ? args.coinId.slice(2)
            : args.coinId;

          if (coinId.length !== 64) {
            throw new Error('Invalid coinId');
          }

          const { data: nftData, error: nftError } = await fetchWithBQ({
            command: 'getNftInfo',
            service: NFT,
            args: [coinId],
          });

          if (nftError) {
            throw nftError;
          }

          // Add bech32m-encoded NFT identifier
          const updatedNFT = {
            ...nftData.nftInfo,
            $nftId: toBech32m(nftData.nftInfo.launcherId, 'nft'),
          };

          return { data: updatedNFT };
        } catch (error: any) {
          return {
            error,
          };
        }
      },
      providesTags: (result, _error) =>
        result ? [{ type: 'NFTInfo', id: result.launcherId }] : [],
    }),

    transferNFT: build.mutation<
      any,
      {
        walletId: number;
        nftCoinId: string;
        launcherId: string;
        targetAddress: string;
        fee: string;
      }
    >({
      query: ({ walletId, nftCoinId, targetAddress, fee }) => ({
        command: 'transferNft',
        service: NFT,
        args: [walletId, nftCoinId, targetAddress, fee],
      }),
      invalidatesTags: (result, _error, { launcherId }) =>
        result ? [{ type: 'NFTInfo', id: launcherId }] : [],
    }),

    setNFTDID: build.mutation<
      any,
      {
        walletId: number;
        nftLauncherId: string;
        nftCoinId: string;
        did: string;
        fee: string;
      }
    >({
      query: ({ walletId, nftLauncherId, nftCoinId, did, fee }) => ({
        command: 'setNftDid',
        service: NFT,
        args: [walletId, nftCoinId, did, fee],
      }),
      invalidatesTags: (result, _error, { nftLauncherId }) =>
        result
          ? [
              { type: 'NFTInfo', id: 'LIST' },
              { type: 'NFTWalletWithDID', id: 'LIST' },
              { type: 'DIDWallet', id: 'LIST' },
            ]
          : [],
    }),

    setNFTStatus: build.mutation<
      any,
      {
        walletId: number;
        nftLauncherId: string;
        nftCoinId: string;
        inTransaction: boolean;
      }
    >({
      query: ({ walletId, nftLauncherId, nftCoinId, inTransaction }) => ({
        command: 'setNftStatus',
        service: NFT,
        args: [walletId, nftCoinId, inTransaction],
      }),
      invalidatesTags: (result, _error, { nftLauncherId }) =>
        result ? [{ type: 'NFTInfo', id: 'LIST' }] : [],
    }),

    receiveNFT: build.mutation<
      any,
      {
        walletId: number;
        spendBundle: any;
        fee: number;
      }
    >({
      query: ({ walletId, spendBundle, fee }) => ({
        command: 'receiveNft',
        service: NFT,
        args: [walletId, spendBundle, fee],
      }),
      invalidatesTags: (result, _error, { walletId }) =>
        result ? [{ type: 'NFTInfo', id: 'LIST' }] : [],
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
  useGetOffersCountQuery,
  useCreateOfferForIdsMutation,
  useCancelOfferMutation,
  useCheckOfferValidityMutation,
  useTakeOfferMutation,
  useGetOfferSummaryMutation,
  useGetOfferDataMutation,
  useGetOfferRecordMutation,
  useGetCurrentDerivationIndexQuery,
  useExtendDerivationIndexMutation,

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
  useGetStrayCatsQuery,

  // PlotNFTS
  useGetPlotNFTsQuery,

  // DID
  useCreateNewDIDWalletMutation,
  useUpdateDIDRecoveryIdsQuery,
  useGetDIDPubKeyQuery,
  useGetDIDQuery,
  useGetDIDsQuery,
  useGetDIDNameQuery,
  useSetDIDNameMutation,
  useGetDIDRecoveryListQuery,
  useGetDIDInformationNeededForRecoveryQuery,
  useGetDIDCurrentCoinInfoQuery,

  // NFTs
  useCalculateRoyaltiesForNFTsQuery,
  useGetNFTsByNFTIDsQuery,
  useGetNFTsQuery,
  useGetNFTWalletsWithDIDsQuery,
  useGetNFTInfoQuery,
  useTransferNFTMutation,
  useSetNFTDIDMutation,
  useSetNFTStatusMutation,
  useReceiveNFTMutation,
} = walletApi;
