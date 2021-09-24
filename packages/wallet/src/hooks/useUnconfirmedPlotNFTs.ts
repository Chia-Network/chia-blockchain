import { useLocalStorage, writeStorage } from '@rehooks/local-storage';
import UnconfirmedPlotNFT from '../types/UnconfirmedPlotNFT';

const LOCAL_STORAGE_KEY = 'unconfirmedPlotNFTs';

export default function useUnconfirmedPlotNFTs(): {
  unconfirmed: UnconfirmedPlotNFT[];
  add: (item: UnconfirmedPlotNFT) => void;
  remove: (transactionId: string) => void;
} {
  const [unconfirmed] = useLocalStorage<UnconfirmedPlotNFT[]>(
    LOCAL_STORAGE_KEY,
    [],
  );

  function handleAdd(item: UnconfirmedPlotNFT) {
    writeStorage(LOCAL_STORAGE_KEY, [...unconfirmed, item]);
  }

  function handleRemove(transactionId: string) {
    const newList = unconfirmed.filter(
      (item) => item.transactionId !== transactionId,
    );
    writeStorage(LOCAL_STORAGE_KEY, newList);
  }

  return {
    add: handleAdd,
    remove: handleRemove,
    unconfirmed,
  };
}
