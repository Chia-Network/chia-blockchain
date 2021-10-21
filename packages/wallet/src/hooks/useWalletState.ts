import getWalletSyncingStatus from '../utils/getWalletSyncingStatus';
import { useGetSyncStatusQuery } from '@chia/api-react';
import SyncingStatus from '../constants/SyncingStatus';

export default function useWalletState(): {
  isLoading: boolean;
  state?: SyncingStatus;
} {
  const { data: walletState, isLoading } = useGetSyncStatusQuery();

  return {
    isLoading,
    state: walletState && getWalletSyncingStatus(walletState),
  }
}
