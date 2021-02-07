import Fingerprint from './Fingerprint';

type PlotAdd = {
  plotSize: number;
  plotCount: number;
  maxRam: number;
  numThreads: number;
  numBuckets: number;
  stripeSize: number;
  finalLocation: string;
  workspaceLocation: string;
  workspaceLocation2: string;
  parallel: boolean;
  delay: number;
  fingerprint?: Fingerprint;
  disableBitfieldPlotting?: boolean;
};

export default PlotAdd;
