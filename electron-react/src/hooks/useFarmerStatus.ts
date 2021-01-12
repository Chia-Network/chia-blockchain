import { useSelector } from 'react-redux';
import type { RootState } from '../modules/rootReducer';
import FarmerStatus from '../constants/FarmerStatus';

function getFarmerStatus(
  connected: boolean,
  running: boolean,
  blockchainSynced: boolean,
  blockchainSynching: boolean,
): FarmerStatus {
  if (blockchainSynching) {
    return FarmerStatus.SYNCHING;
  }

  if (!blockchainSynced) {
    return FarmerStatus.ERROR;
  }

  if (!blockchainSynching && blockchainSynced && connected && running) {
    return FarmerStatus.FARMING;
  }

  return FarmerStatus.ERROR;
}

export default function useFarmerStatus(): FarmerStatus {
  const blockchainSynced = useSelector(
    (state: RootState) =>
      !!state.full_node_state.blockchain_state?.sync?.synced,
  );
  const blockchainSynching = useSelector(
    (state: RootState) =>
      !!state.full_node_state.blockchain_state?.sync?.sync_mode,
  );
  const connected = useSelector(
    (state: RootState) => state.daemon_state.farmer_connected,
  );
  const running = useSelector(
    (state: RootState) => state.daemon_state.farmer_running,
  );

  return getFarmerStatus(
    connected,
    running,
    blockchainSynced,
    blockchainSynching,
  );
}
