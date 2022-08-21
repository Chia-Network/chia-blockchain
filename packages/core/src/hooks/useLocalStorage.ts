import { useState, useCallback, useEffect } from 'react';
import EventEmitter from '../utils/EventEmitter';

const eventEmitter = new EventEmitter();

function getValueFromLocalStorage<T>(key: string, defaultValue: T) {
  try {
    // Get from local storage by key
    const item = window.localStorage.getItem(key);

    if (item !== undefined) {
      try {
        return JSON.parse(item);
      } catch (error) {
        return item;
      }
    }

    return defaultValue;
  } catch (error) {
    return defaultValue;
  }
}

export default function useLocalStorage<T>(key: string, initialValue: T) {
  const [storedValue, setStoredValue] = useState<T>(
    getValueFromLocalStorage(key, initialValue)
  );

  const setValue = (value: (value: T) => T | T) => {
    const newValue = value instanceof Function ? value(storedValue) : value;

    const newStoredValue = JSON.stringify(newValue);
    const oldStoredValue = JSON.stringify(storedValue);
    if (newStoredValue === oldStoredValue) {
      return;
    }

    setStoredValue(newValue);

    window.localStorage.setItem(key, newStoredValue);

    eventEmitter.emit('storage', { key, newValue });
  };

  const changeHandler = useCallback(
    (e) => {
      const { key: changeKey, newValue } = e;
      if (key === changeKey) {
        setStoredValue(newValue);
      }
    },
    [key]
  );

  // Listen changes
  useEffect(() => {
    eventEmitter.on('storage', changeHandler);
    return () => {
      eventEmitter.remove('storage', changeHandler);
    };
  }, [changeHandler]);

  return [storedValue, setValue];
}
