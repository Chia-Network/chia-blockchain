const progressControl = () => ({ type: 'PROGRESS_CONTROL' });

export const openProgress = () => ({
  ...progressControl(),
  open: true,
});

export const closeProgress = () => ({
  ...progressControl(),
  open: false,
});

type ProgressState = {
  progress_indicator: boolean;
};

const initialState: ProgressState = {
  progress_indicator: false,
};

export default function progressReducer(
  state: ProgressState = { ...initialState },
  action: any,
): ProgressState {
  switch (action.type) {
    case 'PROGRESS_CONTROL':
      return { ...state, progress_indicator: action.open };
    default:
      return state;
  }
}
