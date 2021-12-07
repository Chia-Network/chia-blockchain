import PlotterName from '../constants/PlotterName';
import { optionsForPlotter, defaultsForPlotter } from '../constants/Plotters';
import Plotter, { PlotterMap } from '../types/Plotter';

export const defaultPlotter = (): Plotter => {
  return {
    displayName: "Chia Proof of Space",
    options: optionsForPlotter(PlotterName.CHIAPOS),
    defaults: defaultsForPlotter(PlotterName.CHIAPOS),
    installInfo: { installed: true },
  }
}

type PlotterConfigurationState = {
  availablePlotters: PlotterMap<PlotterName, Plotter>;
  fetchedPlotters: boolean;
};

const initialState: PlotterConfigurationState = {
  availablePlotters: {
    [PlotterName.CHIAPOS]: defaultPlotter(),
  },
  fetchedPlotters: false,
}

export default function plotterConfigurationReducer(
  state: PlotterConfigurationState = { ...initialState },
  action: any,
): PlotterConfigurationState {
  switch (action.type) {
    case 'INCOMING_MESSAGE':
      const { message } = action;
      const { data } = message;
      const { command } = message;
      if (command === 'get_plotters') {
        if (data.success && data.plotters) {
          const { plotters } = data;
          const plotterNames = Object.keys(plotters) as PlotterName[];
          const availablePlotters: PlotterMap<PlotterName, Plotter> = {};
          plotterNames.forEach((plotterName) => {
            const installInfo = data.plotters[plotterName];

            availablePlotters[plotterName] = {
              displayName: installInfo.display_name || plotterName,
              version: installInfo.version,
              options: optionsForPlotter(plotterName),
              defaults: defaultsForPlotter(plotterName),
              installInfo: {
                installed: installInfo.installed,
                canInstall: installInfo.can_install,
                bladebitMemoryWarning: installInfo.bladebit_memory_warning,
              },
            };
          });
          return { ...state, availablePlotters, fetchedPlotters: true };
        }
        return { ...state }
      }
      return state;
    default:
      return state;
  }
}
