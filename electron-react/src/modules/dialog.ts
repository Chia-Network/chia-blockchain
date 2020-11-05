import { ReactNode } from 'react';
import { Action } from 'redux';
import { ThunkAction } from 'redux-thunk';
import type { RootState } from './rootReducer';

let nextId = 1;

export function closeDialog(id: number) {
  return {
    type: 'DIALOG_CLOSE',
    id,
  };
}

export function openDialog(options: {
  title?: ReactNode;
  body?: ReactNode;
}): ThunkAction<void, RootState, unknown, Action<Object>> {
  return (dispatch) => {
    const id = nextId++;

    dispatch({
      type: 'DIALOG_OPEN',
      ...options,
      id,
    });

    return () => {
      return dispatch(closeDialog(id));
    };
  };
}

type DialogState = {
  dialogs: {
    id: number;
    title?: ReactNode;
    body?: ReactNode;
  }[];
};

const initialState: DialogState = {
  dialogs: [],
};

export default function dialogReducer(
  state = { ...initialState },
  action: any,
): DialogState {
  switch (action.type) {
    case 'DIALOG_OPEN':
      const { title, body, id } = action;

      return {
        ...state,
        dialogs: [
          ...state.dialogs,
          {
            title,
            body,
            id,
          },
        ],
      };
    case 'DIALOG_CLOSE':
      return {
        ...state,
        dialogs: state.dialogs.filter((dialog) => dialog.id !== action.id),
      };
    default:
      return state;
  }
}
