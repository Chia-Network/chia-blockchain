import { useCallback } from 'react';
import { useLocalStorage, writeStorage } from '@rehooks/local-storage';

const LOCAL_STORAGE_KEY = 'skipMigration';

export default function useSkipMigration(): [boolean, (skip: boolean) => void] {
  let [skip] = useLocalStorage<boolean>(LOCAL_STORAGE_KEY, false);

  const handleSetSkipMigration = useCallback((newSkip: boolean) => {
    writeStorage('locale', newSkip);
  }, []);

  return [skip, handleSetSkipMigration];
}
