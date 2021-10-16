import React, { cloneElement, useContext } from 'react';
import ModalDialogsContext from './ModalDialogsContext';

export default function ModalDialogs() {
  const { dialogs } = useContext(ModalDialogsContext);

  return (
    <>
      {dialogs.map((item) => {
        const { id, dialog, handleClose } = item;

        return cloneElement(dialog, {
          key: id,
          show: true,
          onClose: handleClose,
          open: true,
        });
      })}
    </>
  );
}
