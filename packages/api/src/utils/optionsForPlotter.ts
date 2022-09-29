import PlotterName from '../constants/PlotterName';
import { PlotterOptions } from '../@types/Plotter';
import {
  bladebitOptions,
  bladebit2Options,
  madmaxOptions,
  chiaposOptions,
} from '../constants/Plotters';

export default function optionsForPlotter(plotterName: PlotterName): PlotterOptions {
  switch (plotterName) {
    case PlotterName.BLADEBIT:
      return bladebitOptions;
    case PlotterName.BLADEBIT2:
      return bladebit2Options;
    case PlotterName.MADMAX:
      return madmaxOptions;
    case PlotterName.CHIAPOS: // fallthrough
    default:
      return chiaposOptions;
  }
};

