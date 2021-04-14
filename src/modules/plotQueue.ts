import { Action } from 'redux';
import { ThunkAction } from 'redux-thunk';
import type { RootState } from './rootReducer';
import type PlotAdd from '../types/PlotAdd';
import type PlotQueueItem from '../types/PlotQueueItem';
import { startPlotting } from './plotter_messages';
import PlotStatus from '../constants/PlotStatus';
import { stopService } from './daemon_messages';
import { service_plotter } from '../util/service_names';

const FINISHED_LOG_LINES = 2626; // 128
// const FINISHED_LOG_LINES_64 = 1379; // 64
// const FINISHED_LOG_LINES_32 = 754; // 32

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
      queue,
      fingerprint,
      parallel,
      delay,
      disableBitfieldPlotting,
      excludeFinalDir,
      overrideK,
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
        queue,
        fingerprint,
        parallel,
        delay,
        disableBitfieldPlotting,
        excludeFinalDir,
        overrideK,
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
  deleting: string[];
};

const initialState: PlotQueueState = {
  queue: [],
  deleting: [],
};

function addPlotProgress(queue: PlotQueueItem[]): PlotQueueItem[] {
  if (!queue) {
    return queue;
  }

  return queue.map((item) => {
    const { log, state } = item;
    if (state !== 'RUNNING') {
      return item;
    }

    let progress = 0;

    if (log) {
      const lines = log.trim().split(/\r\n|\r|\n/).length;
      progress = lines > FINISHED_LOG_LINES ? 1 : lines / FINISHED_LOG_LINES;
    }

    return {
      ...item,
      progress,
    };
  });
}

export default function plotQueueReducer(
  state = { ...initialState },
  action: any,
): PlotQueueState {
  switch (action.type) {
    case 'PLOT_QUEUE_UPDATE':
      const { queue } = action;

      return {
        ...state,
        queue: addPlotProgress(queue),
      };
    default:
      return state;
  }
}
