import { ServiceName } from '@chia/api';
import useService, { ServiceState } from './useService';

type Options = {
  keepRunning?: ServiceName[];
  keepStopped?: ServiceName[];
  disabled?: boolean;
};

function getServiceKeepState(service: ServiceName, options: Options): ServiceState | undefined {
  const { keepRunning, keepStopped } = options;
  if (keepRunning && keepRunning.includes(service)) {
    return 'running';
  } else if (keepStopped && keepStopped.includes(service)) {
    return 'stopped';
  }
  return undefined;
}

function getServiceDisabled(service: ServiceName, services: ServiceName[], options: Options) {
  const { disabled } = options;
  return disabled || !services.includes(service);
}

function getServiceOptions(service: ServiceName, services: ServiceName[], options: Options) {
  const keepState = getServiceKeepState(service, options);
  const disabled = getServiceDisabled(service, services, options);

  return {
    keepState,
    disabled,
  };
}

export default function useMonitorServices(
  services: ServiceName[],
  options: Options = {},
): {
  isLoading: boolean;
  error?: Error | unknown;
  starting: ServiceName[];
  stopping: ServiceName[];
  running: ServiceName[];
} {
  const walletState = useService(
    ServiceName.WALLET, 
    getServiceOptions(ServiceName.WALLET, services, options),
  );

  const fullNodeState = useService(
    ServiceName.FULL_NODE,
    getServiceOptions(ServiceName.FULL_NODE, services, options),
  );

  const farmerState = useService(
    ServiceName.FARMER,
    getServiceOptions(ServiceName.FARMER, services, options),
  );

  const harvesterState = useService(
    ServiceName.HARVESTER,
    getServiceOptions(ServiceName.HARVESTER, services, options),
  );

  const simulatorState = useService(
    ServiceName.SIMULATOR, 
    getServiceOptions(ServiceName.SIMULATOR, services, options),
  );

  const plotterState = useService(
    ServiceName.PLOTTER,
    getServiceOptions(ServiceName.PLOTTER, services, options),
  );

  const timelordState = useService(
    ServiceName.TIMELORD,
    getServiceOptions(ServiceName.TIMELORD, services, options),
  );

  const introducerState = useService(
    ServiceName.INTRODUCER,
    getServiceOptions(ServiceName.INTRODUCER, services, options),
  );

  const states = [
    walletState,
    fullNodeState,
    farmerState,
    harvesterState,
    simulatorState,
    plotterState,
    timelordState,
    introducerState,
  ];

  const isLoading = !!states.find((state) => state.isLoading);
  const error = states.find((state) => state.error)?.error;
  
  const starting = states.filter(state => state.state === 'starting');
  const stopping = states.filter(state => state.state === 'stopping');
  const running = states.filter(state => state.state === 'running');

  return {
    isLoading,
    error,
    starting,
    stopping,
    running,
  };
}
