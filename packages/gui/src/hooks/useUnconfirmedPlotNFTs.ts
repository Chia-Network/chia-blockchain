import { useMemo } from 'react';
import { useLocalStorage, writeStorage } from '@rehooks/local-storage';
import { useGetLoggedInFingerprintQuery } from '@chia/api-react';
import UnconfirmedPlotNFT from '../types/UnconfirmedPlotNFT';

const LOCAL_STORAGE_KEY = 'unconfirmedPlotNFTsV2';

export default function useUnconfirmedPlotNFTs(): {
  isLoading: boolean;
  unconfirmed: UnconfirmedPlotNFT[];
  add: (item: UnconfirmedPlotNFT) => void;
  remove: (transactionId: string) => void;
} {
  const { data: fingerprint, isLoading } = useGetLoggedInFingerprintQuery();
  const [unconfirmed] = useLocalStorage<UnconfirmedPlotNFT[]>(
    LOCAL_STORAGE_KEY,
    [],
  );

  const currentUnconfirmed = useMemo(() => {
    return unconfirmed.filter(item => item.fingerprint === fingerprint);
  }, [fingerprint, unconfirmed]);

  function handleAdd(item: Omit<UnconfirmedPlotNFT, 'fingerprint'>) {
    if (!fingerprint) {
      throw new Error('Wait for isLoading useUnconfirmedPlotNFTs');
    }
    writeStorage(LOCAL_STORAGE_KEY, [...unconfirmed, {
      ...item,
      fingerprint,
    }]);
  }

  function handleRemove(transactionId: string) {
    const newList = unconfirmed.filter(
      (item) => item.transactionId !== transactionId,
    );
    writeStorage(LOCAL_STORAGE_KEY, newList);
  }

  return {
    isLoading,
    add: handleAdd,
    remove: handleRemove,
    unconfirmed: currentUnconfirmed,
  };
}
