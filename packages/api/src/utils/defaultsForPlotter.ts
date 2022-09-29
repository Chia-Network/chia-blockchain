import PlotterName from '../constants/PlotterName';
import { PlotterDefaults } from '../@types/Plotter';
import {
  bladebitDefaults,
  bladebit2Defaults,
  madmaxDefaults,
  chiaposDefaults,
} from '../constants/Plotters';

export default function defaultsForPlotter(plotterName: PlotterName): PlotterDefaults {
  switch (plotterName) {
    case PlotterName.BLADEBIT:
      return bladebitDefaults;
    case PlotterName.BLADEBIT2:
      return bladebit2Defaults;
    case PlotterName.MADMAX:
      return madmaxDefaults;
    case PlotterName.CHIAPOS: // fallthrough
    default:
      return chiaposDefaults;
  }
}
