import { Box, Typography } from '@material-ui/core';
import React from 'react';
import { get } from 'lodash';
import styled from 'styled-components';
import type Group from '../../types/Group';

const StyledTypography = styled(Typography)`
  text-overflow: ellipsis;
  overflow: hidden;
`;

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
    <StyledTypography variant={variant}>
      {pool_url
        ? `${showedName}: ${pool_url}`
        : showedName}
    </StyledTypography>
  );
}

GroupName.defaultProps = {
  variant: 'body1',
};
