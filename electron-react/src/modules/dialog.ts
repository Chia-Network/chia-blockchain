import { ReactNode } from 'react';
import createDialog from '../util/createDialog';

export const openDialog = (title: ReactNode, body?: ReactNode) => {
  return {
    type: 'DIALOG_CONTROL',
    open: true,
    title,
    body,
  };
};

export const closeDialog = (id: number) => {
  return {
    type: 'DIALOG_CONTROL',
    open: false,
    id,
  };
};

type DialogState = {
  dialogs: {
    id: number;
    title: ReactNode;
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
    case 'DIALOG_CONTROL':
      if (action.open) {
        const { title, body } = action;

        return {
          ...state,
          dialogs: [...state.dialogs, createDialog(Date.now(), title, body)],
        };
      }
      return {
        ...state,
        dialogs: state.dialogs.filter((dialog) => dialog.id !== action.id),
      };

    default:
      return state;
  }
}
