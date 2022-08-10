import { ServiceName } from '@chia/api';
import { useIsServiceRunningQuery } from '@chia/api-react';
import FarmerStatus from '../constants/FarmerStatus';
import FullNodeState from '../constants/FullNodeState';
import useFullNodeState from './useFullNodeState';

export default function useFarmerStatus(): FarmerStatus {
  const { state: fullNodeState, isLoading: isLoadingFullNodeState } =
    useFullNodeState();

  const { data: isRunning, isLoading: isLoadingIsRunning } =
    useIsServiceRunningQuery(
      {
        service: ServiceName.FARMER,
      },
      {
        pollingInterval: 1000,
      },
    );

  const isLoading = isLoadingIsRunning || isLoadingFullNodeState;

  if (fullNodeState === FullNodeState.SYNCHING) {
    return FarmerStatus.SYNCHING;
  }

  if (fullNodeState === FullNodeState.ERROR) {
    return FarmerStatus.NOT_AVAILABLE;
  }

  if (isLoading /* || !farmerConnected */) {
    return FarmerStatus.NOT_CONNECTED;
  }

  if (!isRunning) {
    return FarmerStatus.NOT_RUNNING;
  }

  return FarmerStatus.FARMING;
}
