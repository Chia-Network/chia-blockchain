import React, { ReactNode } from 'react';
import { Action } from 'redux';
import { ThunkAction } from 'redux-thunk';
import { AlertDialog } from '@chia/core';
import type { RootState } from './rootReducer';

let nextId = 1;

export function closeDialog(id: number) {
  return {
    type: 'DIALOG_CLOSE',
    id,
  };
}

export function openDialog(
  element: ReactNode,
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch) => {
    const id = nextId;
    nextId += 1;

    const promise = new Promise((resolve, reject) => {
      dispatch({
        type: 'DIALOG_OPEN',
        id,
        element,
        resolve,
        reject,
      });
    }).finally(() => {
      // remove dialog from the list
      dispatch(closeDialog(id));
    });

    // @ts-ignore
    promise.close = () => {
      dispatch(closeDialog(id));
    };

    return promise;
  };
}

export function openErrorDialog(
  error: string,
): ThunkAction<any, RootState, unknown, Action<Object>> {
  return (dispatch) => dispatch(openDialog(<AlertDialog>{error}</AlertDialog>));
}

export type Dialog = {
  id: number;
  element: ReactNode;
  resolve: (value?: any) => void;
  reject: (error: Error) => void;
};

type DialogState = {
  dialogs: Dialog[];
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
      const { id, element, resolve, reject } = action;

      return {
        ...state,
        dialogs: [
          ...state.dialogs,
          {
            id,
            element,
            resolve,
            reject,
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
