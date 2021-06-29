import { useSelector } from 'react-redux';
import { RootState } from '../modules/rootReducer';
import type Peak from '../types/Peak';

export default function usePeak(): {
  peak?: Peak;
  loading: boolean;
} {
  const height = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.peak?.height,
  );

  const timestamp = useSelector(
    (state: RootState) => state.full_node_state.latest_peak_timestamp,
  );

  const loading = height === undefined || timestamp === undefined;

  return { 
    peak: loading 
      ? undefined
      : {
        height,
        timestamp,
      }, 
    loading,
  };
}
