import { Action } from 'redux';
import { last } from 'lodash';
import { ThunkAction, ThunkDispatch } from 'redux-thunk';
import type { RootState } from './rootReducer';
import PlotStatus from '../constants/PlotStatus';
import type PlotAdd from '../types/PlotAdd';
import type PlotQueueItem from '../types/PlotQueueItem';
import { startPlotting } from './plotter_messages';
import { stopService } from './daemon_messages';
import { service_plotter } from '../util/service_names';

function plotNow(
  dispatch: ThunkDispatch<PlotQueueState, undefined, any>,
  config: PlotAdd,
) {
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
    ),
  );
}

export function plotQueueProcess(): ThunkAction<
  any,
  RootState,
  unknown,
  Action<Object>
> {
  return async (dispatch, getState) => {
    const {
      plot_queue: { queue },
      plot_control: { plotting_in_proggress },
    } = getState();

    if (plotting_in_proggress) {
      return;
    }

    const newQueue = queue.filter(
      (item) => item.status !== PlotStatus.IN_PROGRESS,
    );
    if (queue.length === newQueue.length) {
      return;
    }

    const [first, ...rest] = newQueue;
    if (first) {
      await plotNow(dispatch, first.config);

      dispatch({
        type: 'PLOT_QUEUE_REPLACE',
        queue: [
          {
            ...first,
            status: PlotStatus.IN_PROGRESS,
          },
          ...rest,
        ],
      });
      return;
    }

    dispatch({
      type: 'PLOT_QUEUE_REPLACE',
      queue: newQueue,
    });
  };
}

export function plotQueueAdd(
  config: PlotAdd,
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return async (dispatch, getState) => {
    const {
      plot_queue: { queue },
      plot_control: { plotting_in_proggress },
    } = getState();

    const lastId = last(queue)?.id ?? 1;

    if (plotting_in_proggress) {
      // add config into the queue
      dispatch({
        type: 'PLOT_QUEUE_ADD',
        id: lastId + 1,
        config,
        status: PlotStatus.WAITING,
      });
    } else {
      await plotNow(dispatch, config);

      dispatch({
        type: 'PLOT_QUEUE_ADD',
        id: lastId + 1,
        config,
        status: PlotStatus.IN_PROGRESS,
      });
    }
  };
}

export function plotQueueDelete(
  id: number,
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch, getState) => {
    const {
      plot_queue: { queue },
    } = getState();

    const queueItem = queue.find((item) => item.id === id);
    if (!queueItem) {
      return;
    }

    if (queueItem.status === PlotStatus.IN_PROGRESS) {
      dispatch(stopService(service_plotter));
    } else {
      dispatch({
        type: 'PLOT_QUEUE_REPLACE',
        queue: queue.filter((item) => item.id !== id),
      });
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
  const { queue } = state;
  const { id, status } = action;

  switch (action.type) {
    case 'PLOT_QUEUE_ADD':
      const { config } = action;

      return {
        ...state,
        queue: [
          ...queue,
          {
            id,
            config,
            status,
            added: new Date().getTime(),
            log: '',
          },
        ],
      };
    case 'PLOT_QUEUE_CHANGE_STATUS':
      return {
        ...state,
        queue: queue.map((item) => {
          if (id !== item.id) {
            return item;
          }

          return {
            ...item,
            status,
          };
        }),
      };

    case 'PLOT_QUEUE_REPLACE':
      return {
        ...state,
        queue: action.queue,
      };
    case 'PLOTTER_CONTROL':
      if (action.command === 'add_progress') {
        return {
          ...state,
          queue: queue.map((item) => {
            if (item.status !== PlotStatus.IN_PROGRESS) {
              return item;
            }

            return {
              ...item,
              log: `${item.log}\n${action.progress}`,
            };
          }),
        };
      }
      return state;
    default:
      return state;
  }
}
