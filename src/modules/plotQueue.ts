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

const LOG_CHECKPOINTS: Record<string, number> = {
  'Computing table 1': 0.01,
  'Computing table 2': 0.06,
  'Computing table 3': 0.12,
  'Computing table 4': 0.2,
  'Computing table 5': 0.28,
  'Computing table 6': 0.36,
  'Computing table 7': 0.42,
  'Backpropagating on table 7': 0.43,
  'Backpropagating on table 6': 0.48,
  'Backpropagating on table 5': 0.51,
  'Backpropagating on table 4': 0.55,
  'Backpropagating on table 3': 0.58,
  'Backpropagating on table 2': 0.61,
  'Compressing tables 1 and 2': 0.66,
  'Compressing tables 2 and 3': 0.73,
  'Compressing tables 3 and 4': 0.79,
  'Compressing tables 4 and 5': 0.85,
  'Compressing tables 5 and 6': 0.92,
  'Compressing tables 6 and 7': 0.98,
};

type PlotQueueItemPartial = PlotQueueItem & {
  log_new?: string;
};

function mergeQueue(
  currentQueue: PlotQueueItem[],
  partialQueue: PlotQueueItemPartial[],
  event: string,
): PlotQueueItem[] {
  let result = [...currentQueue];

  partialQueue.forEach((item) => {
    const { id, log, log_new, ...rest } = item;

    const index = currentQueue.findIndex((queueItem) => queueItem.id === id);
    if (index === -1) {
      result = [...currentQueue, item];
      return;
    }

    const originalItem = currentQueue[index];

    const newItem = {
      ...originalItem,
      ...rest,
    };

    if (event === 'log_changed' && log_new !== undefined) {
      const newLog = originalItem.log
        ? `${originalItem.log}${log_new}`
        : log_new;

      newItem.log = newLog;
    }

    result = Object.assign([...result], { [index]: newItem });
  });

  return addPlotProgress(result);
}

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
      farmerPublicKey,
      poolPublicKey,
      c,
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
        farmerPublicKey,
        poolPublicKey,
        c,
      ),
    );
  };
}

export function plotQueueInit(
  queue: PlotQueueItem[],
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch) => {
    dispatch({
      type: 'PLOT_QUEUE_INIT',
      queue,
    });
  };
}

export function plotQueueUpdate(
  queue: PlotQueueItem[],
  event: string,
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch) => {
    dispatch({
      type: 'PLOT_QUEUE_UPDATE',
      queue,
      event,
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
  event?: string;
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
      const lines = log.trim().split(/\r\n|\r|\n/);
      const lineSet = new Set(lines);

      // Find the last checkpoint the log has reached, then increment
      // additional progress based on the log length of a 128 bucket plot.
      let currentCheckpoint: string | undefined;
      let nextCheckpoint: string | undefined;
      for (const checkpoint in LOG_CHECKPOINTS) {
        if (lineSet.has(checkpoint)) {
          currentCheckpoint = checkpoint;
          progress = LOG_CHECKPOINTS[checkpoint];
        } else {
          nextCheckpoint = checkpoint;
          break;
        }
      }

      if (currentCheckpoint) {
        progress +=
          (lines.length -
            lines.findIndex((line) => line === currentCheckpoint)) /
          FINISHED_LOG_LINES;

        // Once buckets can be > 128, this prevents the progress bar from
        // ever decreasing
        progress = nextCheckpoint
          ? Math.min(progress, LOG_CHECKPOINTS[nextCheckpoint])
          : progress;
      }

      progress = Math.min(1, progress);
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
  const { queue } = action;

  switch (action.type) {
    case 'PLOT_QUEUE_INIT':
      return {
        ...state,
        queue: addPlotProgress(queue),
      };
    case 'PLOT_QUEUE_UPDATE':
      return {
        ...state,
        queue: mergeQueue(state.queue, queue, action.event),
        event: action.event,
      };
    default:
      return state;
  }
}
