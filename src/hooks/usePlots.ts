import { useMemo } from 'react';
import { sumBy, uniqBy } from 'lodash';
import { useSelector } from 'react-redux';
import Plot from 'types/Plot';
import PlotQueueItem from 'types/PlotQueueItem';
import type { RootState } from '../modules/rootReducer';

export default function usePlots(): {
  loading: boolean;
  plots?: Plot[];
  uniquePlots?: Plot[];
  hasPlots: boolean;
  queue?: PlotQueueItem[];
  hasQueue: boolean;
  size: number;
} {
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );

  const queue = useSelector((state: RootState) => state.plot_queue.queue);
  const uniquePlots = useMemo(() => {
    if (!plots) {
      return plots;
    }

    return uniqBy(plots, (plot) => plot['plot-seed']);
  }, [plots]);

  const updatedPlots = useMemo(() => {
    if (!plots) {
      return plots;
    }

    return plots.map((plot) => {
      const duplicates = plots.filter(
        (item) => plot['plot-seed'] === item['plot-seed'] && item !== plot,
      );

      return {
        ...plot,
        duplicates,
      };
    });
  }, [plots]);

  const size = useMemo(() => {
    if (uniquePlots && uniquePlots.length) {
      return sumBy(uniquePlots, (plot) => plot.file_size);
    }

    return 0;
  }, [uniquePlots]);

  return {
    plots: updatedPlots,
    uniquePlots,
    size,
    queue,
    loading: !plots,
    hasPlots: !!plots && plots.length > 0,
    hasQueue: !!queue.length,
  };
}
