import React from 'react';
import { Trans } from '@lingui/macro';
import { Card, CardContent, Typography } from '@material-ui/core';
import Flex from '../flex/Flex';
import TooltipIcon from '../tooltip/TooltipIcon';

export default function FarmLastAttemptedProof() {
  // height, date/ time
  return (
    <Card>
      <CardContent>
        <Flex gap={1}>
          <Typography variant="h5">
            <Trans id="FarmLastAttemptedProof.title">
              Last Attempted Proof
            </Trans>
            <TooltipIcon
              value={(
                <Trans id="FarmLastAttemptedProof.tooltip">
                  tooltip
                </Trans>
              )}
            />
          </Typography>
        </Flex>
      </CardContent>
    </Card>
  );
}
