import React from 'react';
import { Trans } from '@lingui/macro';
import { Box } from '@mui/material';
import styled from 'styled-components';
import StateColor from '../../constants/StateColor';
import Amount, { AmountProps } from '../Amount';

const StyledWarning = styled(Box)`
  color: ${StateColor.WARNING};
`;

const StyledError = styled(Box)`
  color: ${StateColor.ERROR};
`;

type FeeProps = AmountProps;

export default function Fee(props: FeeProps) {
  return (
    <Amount {...props}>
      {({ value, mojo }) => {
        const isHigh = mojo.gte('100000000000');
        const isLow = mojo.gt('0') && mojo.lt('1');

        if (!value) {
          return;
        }

        if (isHigh) {
          return (
            <StyledWarning>
              <Trans>Value seems high</Trans>
            </StyledWarning>
          );
        }

        if (isLow) {
          return (
            <StyledError>
              <Trans>Incorrect value</Trans>
            </StyledError>
          );
        }

        return null;
      }}
    </Amount>
  );
}

Fee.defaultProps = {
  label: <Trans>Fee</Trans>,
  name: 'fee',
};
