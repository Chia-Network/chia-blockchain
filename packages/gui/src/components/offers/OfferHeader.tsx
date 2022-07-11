import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Link, useColorModeValue } from '@chia/core';
import { Typography } from '@mui/material';
import styled from 'styled-components';

/* ========================================================================== */
/*                                   Styles                                   */
/* ========================================================================== */

const StyledHeaderBox = styled.div`
  padding-top: ${({ theme }) => `${theme.spacing(1)}`};
  padding-bottom: ${({ theme }) => `${theme.spacing(1)}`};
  padding-left: ${({ theme }) => `${theme.spacing(2)}`};
  padding-right: ${({ theme }) => `${theme.spacing(2)}`};
  border-radius: 4px;
  border: ${({ theme }) => `1px solid ${useColorModeValue(theme, 'border')}`};
  background-color: ${({ theme }) => theme.palette.background.paper};
`;

/* ========================================================================== */
/*                                Offer Header                                */
/* ========================================================================== */

type OfferHeaderProps = {
  isMyOffer: boolean;
  isInvalid: boolean;
  isComplete: boolean;
};

export default function OfferHeader(props: OfferHeaderProps) {
  const { isMyOffer, isInvalid, isComplete } = props;
  let headerElement: React.ReactElement | undefined = undefined;

  if (isMyOffer) {
    headerElement = (
      <Typography variant="subtitle1" color="primary">
        <Trans>You created this offer</Trans>
      </Typography>
    );
  }

  if (!headerElement && isInvalid) {
    headerElement = (
      <Typography variant="subtitle1" color="error">
        <Trans>
          {'This offer is no longer valid. To understand why, click '}
          <Link
            target="_blank"
            href="https://chialisp.com/docs/tutorials/offers_gui_tutorial/#taker-attempts-to-accept-an-invalid-offer"
          >
            here
          </Link> to learn more.
        </Trans>
      </Typography>
    );
  }

  if (!headerElement && isComplete) {
    headerElement = (
      <Typography variant="subtitle1" color="primary">
        <Trans>This offer has completed successfully</Trans>
      </Typography>
    );
  }

  return headerElement ? (
    <StyledHeaderBox>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        {headerElement}
      </Flex>
    </StyledHeaderBox>
  ) : (
    <></>
  );
}

OfferHeader.defaultProps = {
  isMyOffer: false,
  isInvalid: false,
  isComplete: false,
};
