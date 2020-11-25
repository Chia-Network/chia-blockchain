import React from 'react';
import { useSelector } from 'react-redux';
import { ModalDialogs } from '@chia/core';
import { RootState } from '../../modules/rootReducer';

export default function AppModalDialogs() {
  const dialogs = useSelector((state: RootState) => state.dialog_state.dialogs);

  return <ModalDialogs dialogs={dialogs} />;
}
