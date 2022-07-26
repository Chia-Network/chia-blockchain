import React, { createContext, type ReactNode, useState, useCallback, useMemo, useContext, memo, forwardRef } from 'react';

export const PersistContext = createContext<{
  getValue: (defaultValue: any, namespace?: string) => any;
  setValue: (value: any, namespace?: string) => void;
} | undefined>(undefined);

export type PersistProps = {
  children?: ReactNode;
  value?: any;
  onChange?: (value: any) => void;
} & ({
  namespace: string;
} | {
  persist: (namespace?: string) => string;
});

function Persist(props: PersistProps, ref: any) {
  const { 
    children, 
    value: defaultValue = {}, 
    onChange,
  } = props;

  const persistNamespace = 'namespace' in props ? props.namespace : props.persist();

  const parentPersistContext = useContext(PersistContext);

  const [state] = useState<{
    [key: string]: any;
  }>(defaultValue);


  const getValue = useCallback((defaultValue: any, namespace?: string) => {
    const currentNamespace = namespace 
      ? `${persistNamespace}.${namespace}` 
      : persistNamespace;

    if (parentPersistContext) {
      return parentPersistContext.getValue(defaultValue, currentNamespace);
    }

    return state[currentNamespace] ?? defaultValue;
  }, [state, persistNamespace, parentPersistContext]);


  const setValue = useCallback((value: any, namespace?: string) => {
    const currentNamespace = namespace
      ? `${persistNamespace}.${namespace}`
      : persistNamespace;

    if (parentPersistContext) {
      parentPersistContext.setValue(value, currentNamespace);
    } else {
      state[currentNamespace] = value;
    }

    if (onChange) {
      onChange(value);
    }

  }, [state, persistNamespace, parentPersistContext, onChange]);

  const context = useMemo(() => ({
    getValue,
    setValue,
  }), [getValue]);

  return (
    <PersistContext.Provider value={context} ref={ref}>
      {children}
    </PersistContext.Provider>
  );
}

export default memo(forwardRef(Persist));
