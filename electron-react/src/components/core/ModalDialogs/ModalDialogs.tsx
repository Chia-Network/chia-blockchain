import React, { ReactNode } from 'react';
import ModalDialog from './ModalDialog';

type Props = {
  dialogs: {
    id: number;
    body?: ReactNode;
    title?: ReactNode;
  }[];
  onClose: (id: number) => void;
};

export default function ModalDialogs(props: Props): JSX.Element {
  const { dialogs, onClose } = props;

  return (
    <>
      {dialogs.map((dialog) => (
        <ModalDialog key={dialog.id} onClose={onClose} {...dialog} />
      ))}
    </>
  );
}
