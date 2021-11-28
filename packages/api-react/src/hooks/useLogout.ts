import { walletApi } from '../services/wallet';
import { useAppDispatch } from '../store';

export default function useLogout() {
  const dispatch = useAppDispatch();

  async function handleLogout() {
    return dispatch(walletApi.util.resetApiState());
  }

  return handleLogout;
}
