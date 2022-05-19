import { toBech32m, fromBech32m } from '@chia/api';
import type { PlotNFT } from '@chia/api';
import { useSetPayoutInstructionsMutation, useGetNetworkInfoQuery } from '@chia/api-react';

export default function usePayoutAddress(nft: PlotNFT): {
  loading: boolean;
  setPayoutAddress: (newPayoutAddress: string) => Promise<void>;
  payoutAddress?: string;
} {
  const {
    poolState: {
      poolConfig: { launcherId, payoutInstructions },
    },
  } = nft;

  const [setPayoutInstructions] = useSetPayoutInstructionsMutation();
  const { data: networkInfo, isLoading } = useGetNetworkInfoQuery(); 
  const networkPrefix = networkInfo?.networkPrefix;

  async function handleSetPayoutAddress(newPayoutAddress: string) {
    if (!networkPrefix) {
      throw new Error('Please wait for network prefix');
    }

    let newPayoutInstructions: string;

    try {
      newPayoutInstructions = fromBech32m(newPayoutAddress)
    } catch {
      newPayoutInstructions = newPayoutAddress;
    }

    await setPayoutInstructions({
      launcherId, 
      payoutInstructions: newPayoutInstructions,
    }).unwrap();
  }

  if (isLoading) {
    return {
      loading: true,
      payoutAddress: '',
      setPayoutAddress: handleSetPayoutAddress,
    };
  }

  let payoutAddress: string;

  try {
    payoutAddress = toBech32m(payoutInstructions, networkPrefix)
  } catch {
    payoutAddress = payoutInstructions;
  }

  return {
    payoutAddress,
    loading: false,
    setPayoutAddress: handleSetPayoutAddress,
  };
}
