import React from 'react';
import { LoadingButton, type LoadingButtonProps } from '@mui/lab';

export type ButtonLoadingProps = LoadingButtonProps & {
  loading?: boolean;
  mode?: 'autodisable' | 'hidecontent';
};

export default function ButtonLoading(props: ButtonLoadingProps) {
  const { loading, onClick, ...rest } = props;

  function handleClick(...args: any[]) {
    if (!loading && onClick) {
      onClick(...args);
    }
  }

  return (
    <LoadingButton onClick={handleClick} loading={loading} {...rest} />
  );
}

