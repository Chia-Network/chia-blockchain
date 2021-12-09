import { useMemo } from 'react';
import { sumBy, uniqBy } from 'lodash';
import type { Plot } from '@chia/api';
import PlotQueueItem from 'types/PlotQueueItem';
import { useGetCombinedPlotsQuery, useGetPlotQueueQuery, useThrottleQuery } from '@chia/api-react';
// import useThrottleSelector from './useThrottleSelector';

export default function usePlots(): {
  loading: boolean;
  plots?: Plot[];
  uniquePlots?: Plot[];
  hasPlots: boolean;
  queue?: PlotQueueItem[];
  hasQueue: boolean;
  size: number;
} {
  const { data: plots, isLoading: isLoadingPlots } = useGetCombinedPlotsQuery();
  const { data: queue, isLoading: isLoadingQueue, error } = useThrottleQuery(useGetPlotQueueQuery, undefined, undefined, {
    wait: 5000,
  });

  const isLoading = isLoadingPlots || isLoadingQueue;

  const uniquePlots = useMemo(() => {
    if (!plots) {
      return plots;
    }

    return uniqBy(plots, (plot) => plot.plotId);
  }, [plots]);

  const updatedPlots = useMemo(() => {
    if (!plots) {
      return plots;
    }

    return plots.map((plot) => {
      const duplicates = plots.filter(
        (item) => plot.plotId === item.plotId && item !== plot,
      );

      return {
        ...plot,
        duplicates,
      };
    });
  }, [plots]);

  const size = useMemo(() => {
    if (uniquePlots && uniquePlots.length) {
      return sumBy(uniquePlots, (plot) => plot.fileSize);
    }

    return 0;
  }, [uniquePlots]);

  return {
    plots: updatedPlots,
    uniquePlots,
    size,
    queue,
    loading: isLoading,
    hasPlots: !!plots && plots.length > 0,
    hasQueue: !!queue?.length,
  };
}
