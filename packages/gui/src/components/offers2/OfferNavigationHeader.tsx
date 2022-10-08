import React from 'react';
import { Back, Flex } from '@chia/core';
import { Trans } from '@lingui/macro';
import { Typography } from '@mui/material';

export type OfferNavigationHeaderProps = {
  referrerPath?: string;
};

export default function OfferNavigationHeader(
  props: OfferNavigationHeaderProps,
) {
  const { referrerPath } = props;

  const content = (
    <Flex flexDirection="column">
      <Typography variant="h5">
        <Trans>Offer Builder</Trans>
      </Typography>
      <Typography color="textSecondary" variant="body2">
        <Trans>
          Offers are a way to trade assets in a genuinely peer-to-peer way that
          eliminates counterparty risk.
        </Trans>
      </Typography>
    </Flex>
  );

  if (referrerPath) {
    return (
      <Back
        to={referrerPath}
        alignItems="flex-start"
        iconStyle={{ marginTop: -0.5 }}
      >
        {content}
      </Back>
    );
  }

  return content;
}
