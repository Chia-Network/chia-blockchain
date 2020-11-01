import React, { ReactNode } from 'react';
import { Typography } from '@material-ui/core';
import LayoutHero from '../layout/LayoutHero';
import Loading from './Loading';

type Props = {
  children: ReactNode;
};

export default function LoadingScreen(props: Props) {
  const { children } = props;

  return (
    <LayoutHero>
      <Typography variant="h6">{children}</Typography>
      <Loading />
    </LayoutHero>
  );
}
