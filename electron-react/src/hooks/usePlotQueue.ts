import { useLocalStorage, writeStorage } from '@rehooks/local-storage';
import { last } from 'lodash';
import PlotStatus from '../constants/PlotStatus';
import type PlotAdd from '../types/PlotAdd';

type QueueItem = {
  id: number,
  config: PlotAdd;
  status: PlotStatus;
  added: number, // timestamp when added
};

type Queue = QueueItem[];

const LOCAL_STORAGE_NAME = 'plotQueue';

export default function usePlotQueue(): {
  add: (config: PlotAdd) => void,
  remove: (id: number) => void,
} {
  const [queue] = useLocalStorage<Queue>(LOCAL_STORAGE_NAME, []);

  function handleAdd(config: PlotAdd) {
    const lastId = last(queue)?.id ?? 1;

    writeStorage(LOCAL_STORAGE_NAME, [
      ...queue,
      {
        id: lastId + 1,
        config,
        status: PlotStatus.WAITING,
        added: new Date().getTime(),
      }
    ]);
  }

  function handleRemove(id: number) {
    writeStorage(LOCAL_STORAGE_NAME, queue.filter(queueItem => queueItem.id !== id));
  }

  return {
    add: handleAdd,
    remove: handleRemove,
  };
}
