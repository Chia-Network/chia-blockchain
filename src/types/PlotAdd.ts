import Fingerprint from './Fingerprint';

type PlotAdd = {
  plotSize: number;
  plotCount: number;
  maxRam: number;
  numThreads: number;
  numBuckets: number;
  queue: string;
  finalLocation: string;
  workspaceLocation: string;
  workspaceLocation2: string;
  parallel: boolean;
  delay: number;
  fingerprint?: Fingerprint;
  disableBitfieldPlotting?: boolean;
  excludeFinalDir?: boolean;
  overrideK?: boolean;
};

export default PlotAdd;
