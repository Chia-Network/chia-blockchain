import {
  createPoolWalletMessage,
  pwAbsorbRewardsMessage,
  pwSelfPoolMessage,
  pwJoinPoolMessage,
  async_api,
} from './message';
import { getPoolState } from './farmerMessages';
import { getWallets, getPwStatus, getWalletBalance } from './incoming';
import WalletType from '../constants/WalletType';
import type PlotNFT from '../types/PlotNFT';
import type Wallet from '../types/Wallet';
import type WalletBalance from '../types/WalletBalance';
import type PoolState from '../types/PoolState';
import type PoolWalletStatus from '../types/PoolWalletStatus';
import type InitialTargetState from '../types/InitialTargetState';
import PlotNFTExternal from 'types/PlotNFTExternal';

export function getPlotNFTs() {
  return async (dispatch) => {
    const [wallets, poolStates] = await Promise.all<Wallet[], PoolState[]>([
      dispatch(getWallets()),
      dispatch(getPoolState()),
    ]);

    // filter pool wallets
    const poolWallets =
      wallets?.filter((wallet) => wallet.type === WalletType.POOLING_WALLET) ??
      [];

    const [poolWalletStates, walletBalances] = await Promise.all([
      await Promise.all<PoolWalletStatus>(
        poolWallets.map((wallet) => dispatch(getPwStatus(wallet.id))),
      ),
      await Promise.all<WalletBalance>(
        poolWallets.map((wallet) => dispatch(getWalletBalance(wallet.id))),
      ),
    ]);

    console.log('poolWalletStates', poolWalletStates);
    console.log('walletBalances', walletBalances);

    // combine poolState and poolWalletState
    const nfts: PlotNFT[] = [];
    const external: PlotNFTExternal[] = [];

    poolStates.forEach((poolStateItem) => {
      const poolWalletStatus = poolWalletStates.find(
        (item) => item.launcher_id === poolStateItem.pool_config.launcher_id,
      );
      if (!poolWalletStatus) {
        external.push({
          pool_state: poolStateItem,
        });
        return;
      }

      const walletBalance = walletBalances.find(
        (item) => item.wallet_id === poolWalletStatus.wallet_id,
      );
      if (!walletBalance) {
        throw new Error('Wallet balance is not defined');
      }

      nfts.push({
        pool_state: poolStateItem,
        pool_wallet_status: poolWalletStatus,
        wallet_balance: walletBalance,
      });
    });

    dispatch(updatePlotNFTs(nfts, external));

    return {
      nfts,
      external,
    };
  };
}

export function createPlotNFT(
  initialTargetState: InitialTargetState,
  fee?: string,
) {
  return async (dispatch) => {
    const { data } = await async_api(
      dispatch,
      createPoolWalletMessage(initialTargetState, fee),
      false,
    );

    await dispatch(getPlotNFTs());

    return data;
  };
}

export function pwAbsorbRewards(walletId: number, fee?: string) {
  return async (dispatch) => {
    const { data } = await async_api(
      dispatch,
      pwAbsorbRewardsMessage(walletId, fee),
      false,
    );

    await dispatch(getPlotNFTs());

    return data;
  };
}

export function pwSelfPool(walletId: number) {
  return async (dispatch) => {
    const { data } = await async_api(
      dispatch,
      pwSelfPoolMessage(walletId),
      false,
    );

    console.log('join self pool response', data);

    await dispatch(getPlotNFTs());

    return data;
  };
}

export function pwJoinPool(
  walletId: number,
  poolUrl: string,
  relativeLockHeight: number,
  targetPuzzlehash?: string,
) {
  return async (dispatch) => {
    const { data } = await async_api(
      dispatch,
      pwJoinPoolMessage(
        walletId,
        poolUrl,
        relativeLockHeight,
        targetPuzzlehash,
      ),
      false,
    );

    console.log('join pool response', data);

    await dispatch(getPlotNFTs());

    return data;
  };
}

export function updatePlotNFTs(items: PlotNFT[], external: PlotNFTExternal[]) {
  return {
    type: 'PLOT_NFT_UPDATE',
    items,
    external,
  };
}

type PlotNFTState = {
  items?: PlotNFT[];
  external?: PlotNFTExternal[];
};

const initialState: PlotNFTState = {};

export default function groupReducer(
  state = { ...initialState },
  action: any,
): PlotNFTState {
  switch (action.type) {
    case 'LOG_OUT':
      return { ...initialState };
    case 'PLOT_NFT_UPDATE':
      return {
        ...state,
        items: action.items,
        external: action.external,
      };
    default:
      return state;
  }
}
