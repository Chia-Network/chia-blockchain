import React from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { ModalDialogs } from '@chia/core';
import { closeDialog } from '../../modules/dialog';
import { RootState } from '../../modules/rootReducer';

export default function AppModalDialogs() {
  const dialogs = useSelector((state: RootState) => state.dialog_state.dialogs);
  const dispatch = useDispatch();

  function handleCloseDialog(id: number) {
    dispatch(closeDialog(id));
  }

  return (
    <ModalDialogs dialogs={dialogs} onClose={handleCloseDialog} />
  );
}
