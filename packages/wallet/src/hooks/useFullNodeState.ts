import { useSelector } from 'react-redux';
import type { RootState } from '../modules/rootReducer';
import FullNodeState from '../constants/FullNodeState';

export default function useFullNodeState(): FullNodeState {
  const blockchainSynced = useSelector(
    (state: RootState) =>
      !!state.full_node_state.blockchain_state?.sync?.synced,
  );
  const blockchainSynching = useSelector(
    (state: RootState) =>
      !!state.full_node_state.blockchain_state?.sync?.sync_mode,
  );

  if (blockchainSynching) {
    return FullNodeState.SYNCHING;
  }

  if (!blockchainSynced) {
    return FullNodeState.ERROR;
  }

  return FullNodeState.SYNCED;
}
