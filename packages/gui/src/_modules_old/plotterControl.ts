type PlotterControlState = {
  plotting_in_proggress: boolean;
  // workspace_location: string;
  t2: string;
  // final_location: string;
  progress_location: string;
  progress: string;
  plotting_stopped: boolean;
};

const initialState: PlotterControlState = {
  plotting_in_proggress: false,
  // workspace_location: '',
  t2: '',
  // final_location: '',
  progress_location: '',
  progress: '',
  plotting_stopped: false,
};

export default function plotControlReducer(
  state: PlotterControlState = { ...initialState },
  action: any,
): PlotterControlState {
  switch (action.type) {
    case 'LOG_OUT':
      return { ...initialState };
    case 'PLOTTER_CONTROL':
      /*
      if (action.command === 'workspace_location') {
        return { ...state, workspace_location: action.location };
      }
      if (action.command === 'final_location') {
        return { ...state, final_location: action.location };
      }
      */
      if (action.command === 'reset_progress') {
        return { ...state, progress: '' };
      }
      if (action.command === 'add_progress') {
        return { ...state, progress: `${state.progress}\n${action.progress}` };
      }
      if (action.command === 'plotting_started') {
        return {
          ...state,
          plotting_in_proggress: true,
          plotting_stopped: false,
        };
      }
      if (action.command === 'progress_location') {
        return { ...state, progress_location: action.location };
      }
      if (action.command === 'plotting_stopped') {
        return {
          ...state,
          plotting_in_proggress: false,
          plotting_stopped: true,
        };
      }
      return state;
    default:
      return state;
  }
}
