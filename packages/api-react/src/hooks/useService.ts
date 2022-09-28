import { useEffect, useState, useMemo } from 'react';
import { ServiceName } from '@chia/api';
import { useClientStartServiceMutation } from '../services/client';
import {
  useStopServiceMutation,
  useRunningServicesQuery,
} from '../services/daemon';

export type ServiceState = 'starting' | 'running' | 'stopping' | 'stopped';

type Options = {
  keepState?: ServiceState;
  disabled?: boolean;
  disableWait?: boolean; // Don't wait for ping when starting service
};

export default function useService(
  service: ServiceName,
  options: Options = {}
): {
  isLoading: boolean;
  isProcessing: boolean;
  isRunning: boolean;
  state: ServiceState;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  error?: Error | unknown;
  service: ServiceName;
} {
  const { keepState, disabled = false, disableWait = false } = options;

  const [isStarting, setIsStarting] = useState<boolean>(false);
  const [isStopping, setIsStopping] = useState<boolean>(false);
  const [startService] = useClientStartServiceMutation();
  const [stopService] = useStopServiceMutation();
  const [latestIsProcessing, setLatestIsProcessing] = useState<boolean>(false);

  // isRunning is not working when stopService is called (backend issue)
  const {
    data: runningServices,
    isLoading: isLoading,
    refetch,
    error,
  } = useRunningServicesQuery(
    {},
    {
      pollingInterval: latestIsProcessing ? 1_000 : 10_000,
      skip: disabled,
      selectFromResult: (state) => {
        return {
          data: state.data,
          refetch: state.refetch,
          error: state.error,
          isLoading: state.isLoading,
        };
      },
    }
  );

  const isRunning = useMemo(
    () => !!(runningServices && runningServices?.includes(service)),
    [runningServices, service]
  );

  const isProcessing = isStarting || isStopping;

  useEffect(() => {
    setLatestIsProcessing(isProcessing);
  }, [isProcessing]);

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
        disableWait,
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

    if (
      keepState === 'running' &&
      keepState !== state &&
      !isProcessing &&
      isRunning === false
    ) {
      handleStart();
    } else if (
      keepState === 'stopped' &&
      keepState !== state &&
      !isProcessing &&
      isRunning === true
    ) {
      handleStop();
    }
  }, [keepState, state, isProcessing, disabled, isRunning]);

  return {
    state,
    isLoading,
    isProcessing,
    isRunning,
    error,
    start: handleStart,
    stop: handleStop,
    service,
  };
}
