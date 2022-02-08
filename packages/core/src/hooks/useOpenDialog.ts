import { useContext, useEffect, useState, ReactNode } from 'react';
import ModalDialogsContext from '../components/ModalDialogs/ModalDialogsContext';

export default function useOpenDialog() {
  const [dialogs, setDialogs] = useState<ReactNode[]>([]);
  const context = useContext(ModalDialogsContext);
  if (!context) {
    throw new Error('Use ModalDialogsProvider provider');
  }

  const { hide, show } = context; 

  // remove all modals after unmount
  useEffect(() => () => {
    dialogs.forEach((dialog) => {
      hide(dialog);
    });

    // todo maybe remove ecause it is uneccessary
    setDialogs([]);
  }, []);

  async function handleOpen<T>(dialog: ReactNode): Promise<T> {
    setDialogs((dialogs) => [...dialogs, dialog]);

    const result = await show(dialog);

    setDialogs((dialogs) => dialogs.filter((d) => d !== dialog));

    return result;
  }

  return handleOpen;
}
