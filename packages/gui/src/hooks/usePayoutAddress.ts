import { useSelector, useDispatch } from 'react-redux';
import PlotNFT from '../types/PlotNFT';
import { setPayoutInstructions } from '../modules/farmerMessages';
import toBech32m, { decode } from '../util/toBech32m';

export default function usePayoutAddress(nft: PlotNFT): {
  loading: boolean;
  setPayoutAddress: (newPayoutAddress: string) => Promise<void>;
  payoutAddress?: string;
} {
  const {
    pool_state: {
      pool_config: { launcher_id, payout_instructions },
    },
  } = nft;

  const dispatch = useDispatch();
  const networkPrefix = useSelector(
    (state: RootState) => state.wallet_state.network_info?.network_prefix,
  );

  async function handleSetPayoutAddress(newPayoutAddress: string) {
    if (!networkPrefix) {
      throw new Error('Please wait for network prefix');
    }


    let newPayoutInstructions: string;

    try {
      newPayoutInstructions = decode(newPayoutAddress)
    } catch {
      newPayoutInstructions = newPayoutAddress;
    }

    await dispatch(setPayoutInstructions(launcher_id, newPayoutInstructions));
  }

  if (!networkPrefix) {
    return {
      loading: true,
      payoutAddress: '',
      setPayoutAddress: handleSetPayoutAddress,
    };
  }

  let payoutAddress: string;

  try {
    payoutAddress = toBech32m(payout_instructions, networkPrefix)
  } catch {
    payoutAddress = payout_instructions;
  }

  return {
    payoutAddress,
    loading: false,
    setPayoutAddress: handleSetPayoutAddress,
  };
}
