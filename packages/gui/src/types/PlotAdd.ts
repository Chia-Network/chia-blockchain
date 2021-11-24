import Fingerprint from './Fingerprint';

type PlotAdd = {
  bladebitDisableNUMA?: boolean;
  bladebitWarmStart?: boolean;
  c: string;
  delay: number;
  disableBitfieldPlotting?: boolean;
  excludeFinalDir?: boolean;
  farmerPublicKey?: string;
  finalLocation: string;
  fingerprint?: Fingerprint;
  madmaxNumBucketsPhase3?: number;
  madmaxTempToggle?: boolean;
  madmaxThreadMultiplier?: number;
  madmaxWaitForCopy?: boolean
  maxRam: number;
  numBuckets: number;
  numThreads: number;
  overrideK?: boolean;
  parallel: boolean;
  plotCount: number;
  plotSize: number;
  plotterName: string;
  poolPublicKey?: string;
  queue: string;
  workspaceLocation: string;
  workspaceLocation2: string;
};

export default PlotAdd;
