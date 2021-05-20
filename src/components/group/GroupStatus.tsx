import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, State, StateTypography, TooltipIcon } from '@chia/core';
import { Typography } from '@material-ui/core';
import type Group from '../../types/Group';

type Props = {
  group: Group;
};

export default function GroupStatus(props: Props) {
  const { 
    group: {
      state, 
      self,
    },
  } = props;

  if (state === 'NOT_CREATED' || state === 'ESCAPING') {
    return (
      <Flex alignItems="center" gap={1}>
        <StateTypography variant='body1' state={State.WARNING}>
          <Trans>Pending</Trans>
        </StateTypography>
        <TooltipIcon>
          <Trans>Unconfirmed transaction</Trans>
        </TooltipIcon>
      </Flex>
    );
  }

  return (
    <Typography variant="body1">
      {self ? (
        <Trans>Self Pooling</Trans>
      ) : (
        <Trans>Pooling</Trans>
      )}
    </Typography>
  );
}
