import React, { useState } from 'react';
import ModalDialogsContext from './ModalDialogsContext';

type Props = {
  children: Node,
};

let nextId = 1;

export default function ModalDialogsProvider(props: Props) {
  const { children } = props;
  const [dialogs, setDialogs] = useState([]);

  function hide(dialog) {
    setDialogs((dialogs) => dialogs.filter((d) => d.dialog !== dialog));
  }

  function show(dialog) {
    const id = nextId;
    nextId += 1;

    return new Promise((resolve, reject) => {
      function handleClose(value) {
        // remove modal from dom
        hide(dialog);
        if (value instanceof Error) {
          reject(value);
        }
        resolve(value);
      }

      setDialogs((dialogs) => [...dialogs, {
        id,
        dialog,
        handleClose,
      }]);
    });
  }

  const value = {
    show,
    hide,
    dialogs,
  };

  return (
    <ModalDialogsContext.Provider value={value}>
      {children}
    </ModalDialogsContext.Provider>
  );
}
