interface CommonOptions {
  kSizes: number[];
  haveNumBuckets: boolean;
  canDisableBitfieldPlotting: boolean;
  canPlotInParallel: boolean;
  canDelayParallelPlots: boolean;
  canSetBufferSize: boolean;
}

interface BladeBitOptions extends CommonOptions {
  haveBladebitWarmStart: boolean;
  haveBladebitDisableNUMA: boolean;
  haveBladebitNoCpuAffinity: boolean;
  haveBladebitOutputDir: boolean;
}

interface BladeBit2Options extends BladeBitOptions {
  haveBladebit2Cache: boolean;
  haveBladebit2F1Threads: boolean;
  haveBladebit2FpThreads: boolean;
  haveBladebit2CThreads: boolean;
  haveBladebit2P2Threads: boolean;
  haveBladebit2P3Threads: boolean;
  haveBladebit2Alternate: boolean;
  haveBladebit2NoT1Direct: boolean;
  haveBladebit2NoT2Direct: boolean;
}

interface MadMaxOptions extends CommonOptions {
  haveMadmaxNumBucketsPhase3: boolean;
  haveMadmaxThreadMultiplier: boolean;
  haveMadmaxTempToggle: boolean;
}

export type PlotterOptions = CommonOptions & BladeBitOptions & BladeBit2Options & MadMaxOptions;

interface CommonDefaults {
  plotterName: string,
  plotSize: number;
  numThreads: number;
  numBuckets?: number;
  disableBitfieldPlotting?: boolean;
  parallel?: boolean;
  delay?: number;
}

interface BladeBitDefaults extends CommonDefaults {
  bladebitWarmStart?: boolean;
  bladebitDisableNUMA?: boolean;
  bladebitNoCpuAffinity?: boolean;
}

interface BladeBit2Defaults extends BladeBitDefaults {
  bladebit2Cache?: number;
  bladebit2F1Threads?: number;
  bladebit2FpThreads?: number;
  bladebit2CThreads?: number;
  bladebit2P2Threads?: number;
  bladebit2P3Threads?: number;
  bladebit2Alternate?: boolean;
  bladebit2NoT1Direct?: boolean;
  bladebit2NoT2Direct?: boolean;
}

interface MadMaxDefaults extends CommonDefaults {
  madmaxNumBucketsPhase3?: number;
  madmaxThreadMultiplier?: number;
  madmaxWaitForCopy?: boolean;
  madmaxTempToggle?: boolean;
}

export type PlotterDefaults = CommonDefaults & BladeBitDefaults & BladeBit2Defaults & MadMaxDefaults;

type PlotterInstallInfo = {
  version?: string;
  installed: boolean;
  canInstall?: boolean;
  bladebitMemoryWarning?: string;
};

type Plotter = {
  displayName: string;
  version?: string;
  options: PlotterOptions;
  defaults: PlotterDefaults;
  installInfo: PlotterInstallInfo;
};

export type PlotterMap<T extends string, U> = {
  [K in T]?: U;
};

export default Plotter;
