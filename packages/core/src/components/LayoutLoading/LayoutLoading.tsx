import React, { ReactNode } from 'react';
import { Typography } from '@material-ui/core';
import Loading from '../Loading';
import LayoutHero from '../LayoutHero';

type Props = {
  children?: ReactNode;
};

export default function LayoutLoading(props: Props) {
  const { children } = props;

  return (
    <LayoutHero>
      <Loading center/>
      <Typography variant="body1">{children}</Typography>
    </LayoutHero>
  );
}

LayoutLoading.defaultProps = {
  children: undefined,
};
