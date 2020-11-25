import { useSelector } from 'react-redux';
import Plot from 'types/Plot';
import type { RootState } from '../modules/rootReducer';

export default function usePlots(): {
  loading: boolean;
  plots?: Plot[];
  hasPlots: boolean;
  hasQueue: boolean;
} {
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );

  const queue = useSelector((state: RootState) => state.plot_queue.queue);

  const loading = !plots;
  const hasPlots = !!plots && plots.length > 0;
  const hasQueue = !!queue.length;

  return {
    loading,
    plots,
    hasPlots,
    hasQueue,
  };
}
