import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { Grid } from '@mui/material';
import type { OfferBuilderProps } from './OfferBuilder';
import OfferBuilder from './OfferBuilder';
import OfferNavigationHeader from './OfferNavigationHeader';

type CreateOfferBuilderProps = OfferBuilderProps & {
  referrerPath?: string;
};

export default function CreateOfferBuilder(
  props: CreateOfferBuilderProps,
): JSX.Element {
  const { referrerPath, ...rest } = props;
  const navTitle = <Trans>Offer Builder</Trans>;
  const navHeaderElem = (
    <OfferNavigationHeader title={navTitle} referrerPath={referrerPath} />
  );

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        {navHeaderElem}
        <OfferBuilder {...rest} />
      </Flex>
    </Grid>
  );
}
