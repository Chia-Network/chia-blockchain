import { ReactNode } from 'react';
import { useDispatch } from 'react-redux';
import { openDialog } from '../modules/dialog';

export default function useOpenDialog() {
  const dispatch = useDispatch();

  function handleOpen(options: {
    title?: ReactNode,
    body?: ReactNode,
  }) {
    return dispatch(openDialog(options));
  }

  return handleOpen;
}
