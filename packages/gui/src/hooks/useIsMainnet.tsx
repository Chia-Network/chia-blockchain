import { useSelector } from 'react-redux';
import type { RootState } from '../modules/rootReducer';

export default function useIsMainnet(): boolean | undefined {
  const networkPrefix = useSelector(
    (state: RootState) => state.wallet_state.network_info?.network_prefix,
  );

  if (!networkPrefix) {
    return undefined;
  }

  return networkPrefix.toLowerCase() === 'xch';
}
