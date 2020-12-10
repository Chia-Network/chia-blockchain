import React, { ReactNode } from 'react';
import { Typography } from '@material-ui/core';
import LayoutHero from './LayoutHero';
import Loading from '../core/Loading/Loading';

type Props = {
  children?: ReactNode;
};

export default function LayoutLoading(props: Props) {
  const { children } = props;

  return (
    <LayoutHero>
      <Typography variant="h6">{children}</Typography>
      <Loading />
    </LayoutHero>
  );
}

LayoutLoading.defaultProps = {
  children: undefined,
};
