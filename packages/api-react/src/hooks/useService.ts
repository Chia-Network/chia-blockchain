import { useEffect, useState } from 'react';
import { ServiceName } from '@chia/api';
import { useClientStartServiceMutation } from '../services/client';
import { useIsServiceRunningQuery, useStopServiceMutation } from '../services/daemon';

export type ServiceState = 'starting' | 'running' | 'stopping' | 'stopped';

type Options = {
  keepState?: ServiceState,
  disabled?: boolean,
};

export default function useService(service: ServiceName, options: Options): {
  isLoading: boolean;
  isProcessing: boolean;
  state: ServiceState;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  error?: Error | unknown;
  service: ServiceName;
} {
  const { 
    keepState,
    disabled = false,
  } = options;

  const [isStarting, setIsStarting] = useState<boolean>(false);
  const [isStopping, setIsStopping] = useState<boolean>(false);
  const [startService] = useClientStartServiceMutation();
  const [stopService] = useStopServiceMutation();
  const { data: isRunning, isLoading, refetch, error } = useIsServiceRunningQuery({
    service,
  }, {
    pollingInterval: 1000,
    skip: disabled,
    selectFromResult: (state) => {
      return {
        data: state.data,
        refetch: state.refetch,
        error: state.error,
        isLoading: state.isLoading,
      };
    },
  });

  const isProcessing = isStarting || isStopping;

  let state: ServiceState = 'stopped';
  if (isStarting) {
    state = 'starting';
  } else if (isStopping) {
    state = 'stopping';
  } else if (isRunning) {
    state = 'running';
  }

  async function handleStart() {
    if (isProcessing) {
      return;
    }

    try {
      setIsStarting(true);
      await startService({
        service,
      }).unwrap();

      refetch();
    } finally {
      setIsStarting(false);
    }
  }

  async function handleStop() {
    if (isProcessing) {
      return;
    }

    try {
      setIsStopping(true);
      await stopService({
        service,
      }).unwrap();

      refetch();
    } finally {
      setIsStopping(false);
    }
  }

  useEffect(() => {
    if (disabled) {
      return;
    }

    if (keepState === 'running' && keepState !== state && !isProcessing && isRunning === false) {
      handleStart();
    } else if (keepState === 'stopped' && keepState !== state && !isProcessing && isRunning === true) {
      handleStop();
    }
  }, [keepState, state, isProcessing, disabled, isRunning]);

  return {
    state,
    isLoading,
    isProcessing,
    error,
    start: handleStart,
    stop: handleStop,
    service,
  };
}
