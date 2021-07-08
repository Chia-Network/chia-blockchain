import { ReactNode } from 'react';
import { useDispatch } from 'react-redux';
import { openDialog } from '../modules/dialog';

export default function useOpenDialog() {
  const dispatch = useDispatch();

  function handleOpen<T>(dialog: ReactNode): Promise<T> {
    return dispatch(openDialog(dialog));
  }

  return handleOpen;
}
