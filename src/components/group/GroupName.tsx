import { Typography } from '@material-ui/core';
import React from 'react';
import { get } from 'lodash';
import type Group from '../../types/Group';

type Props = {
  group: Group;
  variant?: string;
};

export default function GroupName(props: Props) {
  const {
    variant,
    group: {
      pool_config: {
        pool_url,
        launcher_id,
      },
      pool_info,
    }
  } = props;

  const poolName = get(pool_info, 'name');
  const showedName = poolName || launcher_id;

  return (
    <Typography variant={variant}>
      {pool_url
        ? `${showedName}: ${pool_url}`
        : showedName}
    </Typography>
  );
}

GroupName.defaultProps = {
  variant: 'body1',
};
