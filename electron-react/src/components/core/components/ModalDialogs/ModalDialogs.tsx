import React, { cloneElement } from 'react';
import type { Dialog } from '../../../../modules/dialog';

type Props = {
  dialogs: Dialog[];
};

export default function ModalDialogs(props: Props) {
  const { dialogs } = props;

  function handleClose(value: any, dialog: Dialog) {
    const { resolve, reject } = dialog;

    if (value instanceof Error) {
      reject(value);
      return;
    }

    resolve(value);
  }

  return (
    <>
      {dialogs.map((dialog) => cloneElement(// @ts-ignore
        dialog.element, {
          key: dialog.id,
          open: true,
          onClose: (value: any) => handleClose(value, dialog),
        }
      ))}
    </>
  );
}
