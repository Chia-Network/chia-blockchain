import { useState, useCallback, useContext } from 'react';
import { PersistContext } from '../components/Persist';

export default function usePersistState<T>(defaultValue: T, namespace?: string): [T, (value: T) => void] {
  const persistContext = useContext(PersistContext);

  const [value, setStateValue] = useState(namespace && persistContext
    ? persistContext.getValue(defaultValue, namespace)
    : defaultValue
  );

  const setValue = useCallback((value: T) => {
    if (namespace && persistContext) {
      persistContext.setValue(value, namespace);
    }

    setStateValue(value);
  }, []);

  return [value, setValue];
}
