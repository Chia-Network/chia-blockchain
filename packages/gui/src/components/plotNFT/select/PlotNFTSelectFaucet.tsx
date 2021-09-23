import React from 'react';
import { Trans } from '@lingui/macro';
import { Button, Flex, CardStep } from '@chia/core';
import { Box, Typography } from '@material-ui/core';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import useOpenExternal from '../../../hooks/useOpenExternal';

type Props = {
  step?: number;
  onCancel?: () => void;
};

export default function PlotNFTSelectFaucet(props: Props) {
  const { step, onCancel } = props;
  const currencyCode = useCurrencyCode();
  const openExternal = useOpenExternal();

  function handleClick() {
    openExternal('https://faucet.chia.net/');
  }

  return (
    <CardStep
      step={step}
      title={
        <Flex gap={1} alignItems="center">
          <Flex flexGrow={1}>Want to Join a Pool?</Flex>
          {onCancel && (
            <Button onClick={onCancel}>
              <Trans>Cancel</Trans>
            </Button>
          )}
        </Flex>
      }
    >
      <Typography variant="subtitle1">
        <Trans>You need {currencyCode} to join a pool.</Trans>
      </Typography>

      <Box>
        <Button onClick={handleClick} color="primary" variant="contained">
          <Trans>Add {currencyCode} from the Faucet</Trans>
        </Button>
      </Box>
    </CardStep>
  );
}

PlotNFTSelectFaucet.defaultProps = {
  step: 1,
};
