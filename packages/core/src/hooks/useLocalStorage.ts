import { useCallback } from 'react';
import { useLocalStorage as useLocalStorageBase, writeStorage } from '@rehooks/local-storage';

type NewValueCallback<T> = (value: T) => T;

export default function useLocalStorage<T>(storageKey: string, defaultValue: T): [
  value: T,
  setValue: (value: T | NewValueCallback<T>) => void,
] {
  const [value] = useLocalStorageBase<T>(storageKey, defaultValue);

  const setValue = useCallback((newValue: T | NewValueCallback<T>) => {
    const newValueToStore = typeof newValue === 'function'
      ? newValue(value)
      : newValue;

    writeStorage(storageKey, newValueToStore);
  }, [storageKey, value]);

  return [value, setValue];
}
