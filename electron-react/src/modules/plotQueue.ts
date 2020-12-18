import { Action } from 'redux';
import { ThunkAction } from 'redux-thunk';
import type { RootState } from './rootReducer';
import type PlotAdd from '../types/PlotAdd';
import type PlotQueueItem from '../types/PlotQueueItem';
import { startPlotting } from './plotter_messages';
import PlotStatus from '../constants/PlotStatus';
import { stopService } from './daemon_messages';
import { service_plotter } from '../util/service_names';

export function plotQueueAdd(
  config: PlotAdd,
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch) => {
    const {
      plotSize,
      plotCount,
      workspaceLocation,
      workspaceLocation2,
      finalLocation,
      maxRam,
      numBuckets,
      numThreads,
      stripeSize,
      fingerprint,
      parallel,
      delay,
      disableBitfieldPlotting,
    } = config;

    return dispatch(
      startPlotting(
        plotSize,
        plotCount,
        workspaceLocation,
        workspaceLocation2 || workspaceLocation,
        finalLocation,
        maxRam,
        numBuckets,
        numThreads,
        stripeSize,
        fingerprint,
        parallel,
        delay,
        disableBitfieldPlotting,
      ),
    );
  };
}

export function plotQueueUpdate(
  queue: PlotQueueItem[],
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch) => {
    dispatch({
      type: 'PLOT_QUEUE_UPDATE',
      queue,
    });
  };
}

export function plotQueueDelete(
  id: string,
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch, getState) => {
    const {
      plot_queue: { queue },
    } = getState();

    const queueItem = queue.find((item) => item.id === id);
    if (!queueItem) {
      return;
    }

    if (queueItem.state === PlotStatus.RUNNING) {
      dispatch(stopService(service_plotter)); // TODO replace with stopPlotting(id)
    }
  };
}

type PlotQueueState = {
  queue: PlotQueueItem[];
};

const initialState: PlotQueueState = {
  queue: [],
};

export default function plotQueueReducer(
  state = { ...initialState },
  action: any,
): PlotQueueState {
  switch (action.type) {
    case 'PLOT_QUEUE_UPDATE':
      const { queue } = action;

      return {
        ...state,
        queue,
      };
    default:
      return state;
  }
}
