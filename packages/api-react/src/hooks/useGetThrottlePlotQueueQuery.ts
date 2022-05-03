import PlotQueueItem from 'types/PlotQueueItem';
import useThrottleQuery from './useThrottleQuery';
import { useGetPlotQueueQuery } from '../services/plotter';

export default function useGetThrottlePlotQueueQuery(wait = 5000): {
  isLoading: boolean;
  queue?: PlotQueueItem[];
  hasQueue: boolean;
  error?: Error;
} {
  const { data: queue, isLoading, error } = useThrottleQuery(useGetPlotQueueQuery, undefined, undefined, {
    wait,
  });

  return {
    queue,
    isLoading,
    hasQueue: !!queue?.length,
    error,
  };
}
