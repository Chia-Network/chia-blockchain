import PlotStatus from '../constants/PlotStatus';
import type PlotAdd from './PlotAdd';

type PlotQueueItem = {
  id: number;
  config: PlotAdd;
  status: PlotStatus;
  added: number; // timestamp when added
  log: string;
};

export default PlotQueueItem;
