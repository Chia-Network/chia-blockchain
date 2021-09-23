import { ReactNode } from 'react';
import { useDispatch } from 'react-redux';

export default function useOpenDialog() {
  // const dispatch = useDispatch();

  function handleOpen<T>(dialog: ReactNode): Promise<T> {
    // return dispatch(openDialog(dialog));
  }

  return handleOpen;
}
