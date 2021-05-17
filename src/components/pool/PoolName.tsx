import { Typography } from '@material-ui/core';
import React from 'react';
import type PoolGroup from '../../types//PoolGroup';

type Props = {
  pool: PoolGroup;
  variant?: string;
};

export default function PoolName(props: Props) {
  const {
    variant,
    pool: {
      name,
      poolUrl,
    }
  } = props;

  return (
    <Typography variant={variant}>
      {poolUrl
        ? `${name}: ${poolUrl}`
        : name}
    </Typography>
  );
}

PoolName.defaultProps = {
  variant: 'body1',
};
