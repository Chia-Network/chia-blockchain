import { ReactNode } from 'react';
import { useDispatch } from 'react-redux';
import { openDialog } from '../modules/dialog';

export default function useOpenDialog() {
  const dispatch = useDispatch();

  function handleOpen(dialog: ReactNode) {
    return dispatch(openDialog(dialog));
  }

  return handleOpen;
}
