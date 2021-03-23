import PlotStatus from '../constants/PlotStatus';

type PlotQueueItem = {
  id: string;
  queue: string;
  size: number;
  parallel: boolean;
  delay: number;
  state: PlotStatus;
  error?: string;
  log?: string;
  progress?: number;
};

export default PlotQueueItem;
