import { useGetBlockchainStateQuery } from '@chia/api-react';
import FullNodeState from '../constants/FullNodeState';

export default function useFullNodeState(): FullNodeState {
  const { data: blockchainState, isLoading } = useGetBlockchainStateQuery();
  const blockchainSynced = blockchainState?.sync?.synced;
  const blockchainSynching = blockchainState?.sync?.syncMode;

  if (blockchainSynching) {
    return FullNodeState.SYNCHING;
  }

  if (!blockchainSynced) {
    return FullNodeState.ERROR;
  }

  return FullNodeState.SYNCED;
}
