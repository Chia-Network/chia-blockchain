import { Typography } from '@material-ui/core';
import React from 'react';
import type Group from '../../types/Group';

type Props = {
  group: Group;
  variant?: string;
};

export default function GroupName(props: Props) {
  const {
    variant,
    group: {
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

GroupName.defaultProps = {
  variant: 'body1',
};
