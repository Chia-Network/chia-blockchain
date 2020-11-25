import React from 'react';
import { Backdrop, CircularProgress } from '@material-ui/core';

type Props = {
  show: boolean;
};

export default function Spinner(props: Props) {
  const { show } = props;

  return (
    <Backdrop open={show}>
      <CircularProgress color="inherit" />
    </Backdrop>
  );
}
