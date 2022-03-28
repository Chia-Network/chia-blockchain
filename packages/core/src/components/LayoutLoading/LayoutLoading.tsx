import React, { type ReactNode } from 'react';
import { Typography } from '@mui/material';
import Loading from '../Loading';
import LayoutHero from '../LayoutHero';

export type LayoutLoadingProps = {
  children?: ReactNode;
  hideSettings?: boolean;
};

export default function LayoutLoading(props: LayoutLoadingProps) {
  const { children, hideSettings } = props;

  return (
    <LayoutHero hideSettings={hideSettings}>
      <Loading center/>
      <Typography variant="body1">{children}</Typography>
    </LayoutHero>
  );
}
