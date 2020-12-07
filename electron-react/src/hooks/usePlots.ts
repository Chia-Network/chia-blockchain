import { useMemo } from 'react';
import { sumBy } from 'lodash';
import { useSelector } from 'react-redux';
import Plot from 'types/Plot';
import PlotQueueItem from 'types/PlotQueueItem';
import type { RootState } from '../modules/rootReducer';

export default function usePlots(): {
  loading: boolean;
  plots?: Plot[];
  hasPlots: boolean;
  queue?: PlotQueueItem[];
  hasQueue: boolean;
  size: number;
} {
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );

  const queue = useSelector((state: RootState) => state.plot_queue.queue);

  const size = useMemo(() => {
    if (plots && plots.length) {
      return sumBy(plots, (plot) => plot.file_size);
    }

    return 0;
  }, [plots]);

  return {
    plots,
    size,
    queue,
    loading: !plots,
    hasPlots: !!plots && plots.length > 0,
    hasQueue: !!queue.length,
  };
}
