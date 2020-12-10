import PlotStatus from '../constants/PlotStatus';

type PlotQueueItem = {
  id: string;
  size: number;
  parallel: boolean;
  delay: number;
  state: PlotStatus;
  error?: string;
  log?: string;
};

export default PlotQueueItem;
