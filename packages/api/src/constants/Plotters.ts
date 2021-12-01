import PlotterName from './PlotterName';
import { PlotterOptions, PlotterDefaults } from '../@types/Plotter';

export const bladebitOptions: PlotterOptions = {
  kSizes: [32],
  haveNumBuckets: false,
  haveMadmaxNumBucketsPhase3: false,
  haveMadmaxThreadMultiplier: false,
  haveMadmaxTempToggle: false,
  haveBladebitWarmStart: true,
  haveBladebitDisableNUMA: true,
  haveBladebitOutputDir: true,
  canDisableBitfieldPlotting: false,
  canPlotInParallel: false,
  canDelayParallelPlots: false,
  canSetBufferSize: false,
};

export const bladebitDefaults: PlotterDefaults = {
  plotterName: PlotterName.BLADEBIT,
  plotSize: 32,
  numThreads: 0,
  numBuckets: undefined,
  madmaxNumBucketsPhase3: undefined,
  madmaxThreadMultiplier: undefined,
  madmaxWaitForCopy: undefined,
  madmaxTempToggle: undefined,
  bladebitWarmStart: false,
  bladebitDisableNUMA: false,
  disableBitfieldPlotting: undefined,
  parallel: false,
  delay: 0,
};

export const chiaposOptions: PlotterOptions = {
  kSizes: [25, 32, 33, 34, 35],
  haveNumBuckets: true,
  haveMadmaxNumBucketsPhase3: false,
  haveMadmaxThreadMultiplier: false,
  haveMadmaxTempToggle: false,
  haveBladebitWarmStart: false,
  haveBladebitDisableNUMA: false,
  haveBladebitOutputDir: false,
  canDisableBitfieldPlotting: true,
  canPlotInParallel: true,
  canDelayParallelPlots: true,
  canSetBufferSize: true,
};

export const chiaposDefaults: PlotterDefaults = {
  plotterName: PlotterName.CHIAPOS,
  plotSize: 32,
  numThreads: 2,
  numBuckets: 128,
  madmaxNumBucketsPhase3: undefined,
  madmaxThreadMultiplier: undefined,
  madmaxWaitForCopy: undefined,
  madmaxTempToggle: undefined,
  bladebitWarmStart: undefined,
  bladebitDisableNUMA: undefined,
  disableBitfieldPlotting: false,
  parallel: false,
  delay: 0,
};

export const madmaxOptions: PlotterOptions = {
  kSizes: [25, 32, 33, 34],
  haveNumBuckets: true,
  haveMadmaxNumBucketsPhase3: true,
  haveMadmaxThreadMultiplier: true,
  haveMadmaxTempToggle: true,
  haveBladebitWarmStart: false,
  haveBladebitDisableNUMA: false,
  haveBladebitOutputDir: false,
  canDisableBitfieldPlotting: false,
  canPlotInParallel: false,
  canDelayParallelPlots: false,
  canSetBufferSize: false,
};

export const madmaxDefaults: PlotterDefaults = {
  plotterName: PlotterName.MADMAX,
  plotSize: 32,
  numThreads: 4,
  numBuckets: 256,
  madmaxNumBucketsPhase3: 256,
  madmaxThreadMultiplier: 1,
  madmaxWaitForCopy: true,
  madmaxTempToggle: false,
  bladebitWarmStart: undefined,
  bladebitDisableNUMA: undefined,
  disableBitfieldPlotting: undefined,
  parallel: false,
  delay: 0,
};
