import type { IncomingState } from '../modules/incoming';
import SyncingStatus from '../constants/SyncingStatus';

export default function getWalletSyncingStatus(walletState: IncomingState) {
  const {
    status: { syncing, synced },
  } = walletState;

  if (syncing) {
    return SyncingStatus.SYNCING;
  } else if (synced) {
    return SyncingStatus.SYNCED;
  }

  return SyncingStatus.NOT_SYNCED;
}
