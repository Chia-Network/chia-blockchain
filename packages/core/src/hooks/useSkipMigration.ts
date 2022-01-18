import { useCallback } from 'react';
import { useLocalStorage, writeStorage } from '@rehooks/local-storage';

const LOCAL_STORAGE_KEY = 'skipMigration';

export default function useSkipMigration(): [boolean, (skip: boolean) => void] {
  const [skip] = useLocalStorage<boolean>(LOCAL_STORAGE_KEY, false);

  const handleSetSkipMigration = useCallback((newSkip: boolean) => {
    writeStorage(LOCAL_STORAGE_KEY, newSkip);
  }, []);

  return [skip, handleSetSkipMigration];
}
