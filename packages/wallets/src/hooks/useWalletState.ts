import { useGetSyncStatusQuery } from '@chia/api-react';
import { SyncingStatus } from '@chia/api';
import getWalletSyncingStatus from '../utils/getWalletSyncingStatus';

export default function useWalletState(): {
  isLoading: boolean;
  state?: SyncingStatus;
} {
  const { data: walletState, isLoading } = useGetSyncStatusQuery({}, {
    pollingInterval: 10000,
  });

  return {
    isLoading,
    state: walletState && getWalletSyncingStatus(walletState),
  };
}
