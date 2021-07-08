import { useSelector } from 'react-redux';
import type { RootState } from '../modules/rootReducer';

export default function useCurrencyCode(): string | undefined {
  const networkPrefix = useSelector(
    (state: RootState) => state.wallet_state.network_info?.network_prefix,
  );

  return networkPrefix && networkPrefix.toUpperCase();
}
