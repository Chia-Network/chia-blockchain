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
  haveBladebitOutputDir: boolean;
}

interface MadMaxOptions extends CommonOptions {
  haveMadmaxNumBucketsPhase3: boolean;
  haveMadmaxThreadMultiplier: boolean;
  haveMadmaxTempToggle: boolean;
}

export type PlotterOptions = CommonOptions & BladeBitOptions & MadMaxOptions;

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
}

interface MadMaxDefaults extends CommonDefaults {
  madmaxNumBucketsPhase3?: number;
  madmaxThreadMultiplier?: number;
  madmaxWaitForCopy?: boolean;
  madmaxTempToggle?: boolean;
}

export type PlotterDefaults = CommonDefaults & BladeBitDefaults & MadMaxDefaults;

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
