import Client from '../Client';
import Service from './Service';
import type { Options } from './Service';
import ServiceName from '../constants/ServiceName';


function parseProgressUpdate(line: string, currentProgress: number): number {
  let progress: number = currentProgress;
  if (line.startsWith("Progress update: ")) {
    progress = Math.min(1, parseFloat(line.substr("Progress update: ".length)));
  }
  return progress;
}

function addPlotProgress(queue: PlotQueueItem[]): PlotQueueItem[] {
  if (!queue) {
    return queue;
  }

  return queue.map((item) => {
    const { log, state } = item;
    if (state === 'FINISHED') {
      return {
        ...item,
        progress: 1.0,
      };
    } else if (state !== 'RUNNING') {
      return item;
    }

    let progress = item.progress || 0;

    if (log) {
      const lines = log.trim().split(/\r\n|\r|\n/);
      const lastLine = lines[lines.length - 1];

      progress = parseProgressUpdate(lastLine, progress);
    }

    return {
      ...item,
      progress,
    };
  });
}

function mergeQueue(
  currentQueue: PlotQueueItem[],
  partialQueue: PlotQueueItemPartial[],
  isLogChange: boolean,
): PlotQueueItem[] {
  let result = [...currentQueue];

  partialQueue.forEach((item) => {
    const { id, log, logNew, ...rest } = item;

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

    if (isLogChange && logNew !== undefined) {
      const newLog = originalItem.log
        ? `${originalItem.log}${logNew}`
        : logNew;

      newItem.log = newLog;
    }

    result = Object.assign([...result], { [index]: newItem });
  });

  return addPlotProgress(result);
}


export default class Plotter extends Service {
  private queue: Object[] | undefined;

  constructor(client: Client, options?: Options) {
    super(ServiceName.PLOTTER, client, options, async () => {
      this.onLogChanged((data: any) => {
        const { queue } = data;
        this.queue = mergeQueue(this.queue, queue, true);
        this.emit('queue_changed', this.queue, null);
      });

      this.onPlotQueueStateChange((data: any) => {
        const { queue } = data;
        this.queue = mergeQueue(this.queue, queue);
        this.emit('queue_changed', this.queue, null);
      });
  
      const { queue } = await this.register();
      if (queue) {
        this.queue = queue;
      }
    });
  }
/*
  startPlotting(
    plotterName, // plotterName
    k, // plotSize
    n, // plotCount
    t, // workspaceLocation
    t2, // workspaceLocation2
    d, // finalLocation
    b, // maxRam
    u, // numBuckets
    r, // numThreads,
    queue, // queue
    a, // fingerprint
    parallel, // parallel
    delay, // delay
    e, // disableBitfieldPlotting
    x, // excludeFinalDir
    overrideK, //overrideK
    f, // farmerPublicKey
    p, // poolPublicKey
    c, // poolContractAddress
    m, // bladebitDisableNUMA,
    w, // bladebitWarmStart,
    v, // madmaxNumBucketsPhase3,
    G, // madmaxTempToggle,
    K, // madmaxThreadMultiplier,
  ) {
    const args = {
      plotter: plotterName,
      k,
      n,
      t,
      t2,
      d,
      b,
      u,
      r,
      queue,
      parallel,
      delay,
      e,
      x,
      overrideK,
    };
  
    if (a) {
      args.a = a;
    }
  
    if (f) {
      args.f = f;
    }
  
    if (p) {
      args.p = p;
    }
  
    if (c) {
      args.c = c;
    }
  
    if (m) { // bladebitDisableNUMA
      args.m = m;
    }
  
    if (w) { // bladebitWarmStart
      args.w = w;
    }
  
    if (v) { // madmaxNumBucketsPhase3
      args.v = v;
    }
  
    if (G) { // madmaxTempToggle
      args.G = G;
    }
  
    if (K) { // madmaxThreadMultiplier
      args.K = K;
    }

    return this.command('start_plotting', args, undefined, undefined, true);  
  }

  stopPlotting(id: string) {
    return this.command('stop_plotting', {
      id,
    });
  }
  */

  async getQueue() {
    await this.whenReady();
    return this.queue;
  }

  onQueueChanged(
    callback: (data: any, message?: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('queue_changed', callback, processData);
  }

  onLogChanged(
    callback: (data: any, message?: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onStateChanged('log_changed', callback, processData);
  }

  onPlotQueueStateChange(
    callback: (data: any, message?: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onStateChanged('state_changed', callback, processData);
  }
}
