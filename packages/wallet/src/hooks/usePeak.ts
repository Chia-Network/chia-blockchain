import type Peak from '../types/Peak';
import { useGetBlockchainStateQuery } from '@chia/api-react';

export default function usePeak(): {
  peak?: Peak;
  loading: boolean;
} {
  const { data: blockchainState, isLoading, error } = useGetBlockchainStateQuery();
  console.log('blockchainState', blockchainState, isLoading, error);

  /*
  const timestamp = useSelector(
    (state: RootState) => state.full_node_state.latest_peak_timestamp,
  );
  */

  if (isLoading || !blockchainState) {
    return {
      loading: isLoading,
    };
  }

  return {
    peak: {
      height: blockchainState.peak?.height,
      timestamp: undefined,
    },
    loading: isLoading,
  };
}
