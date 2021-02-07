import { useSelector } from 'react-redux';
import type { RootState } from '../modules/rootReducer';
import FarmerStatus from '../constants/FarmerStatus';
import FullNodeState from '../constants/FullNodeState';
import useFullNodeState from './useFullNodeState';

export default function useFarmerStatus(): FarmerStatus {
  const fullNodeState = useFullNodeState();
  const farmerConnected = useSelector(
    (state: RootState) => state.daemon_state.farmer_connected,
  );
  const farmerRunning = useSelector(
    (state: RootState) => state.daemon_state.farmer_running,
  );

  if (fullNodeState === FullNodeState.SYNCHING) {
    return FarmerStatus.SYNCHING;
  }

  if (fullNodeState === FullNodeState.ERROR) {
    return FarmerStatus.NOT_AVAILABLE;
  }

  if (!farmerConnected) {
    return FarmerStatus.NOT_CONNECTED;
  }

  if (!farmerRunning) {
    return FarmerStatus.NOT_RUNNING;
  }

  return FarmerStatus.FARMING;
}
