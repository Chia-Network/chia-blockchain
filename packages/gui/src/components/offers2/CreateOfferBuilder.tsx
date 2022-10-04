import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { Grid, Switch, Box } from '@mui/material';
import type { OfferBuilderProps } from './OfferBuilder';
import OfferBuilder from './OfferBuilder';
import OfferNavigationHeader from './OfferNavigationHeader';

type CreateOfferBuilderProps = OfferBuilderProps & {
  referrerPath?: string;
};

export default function CreateOfferBuilder(props: CreateOfferBuilderProps) {
  const { referrerPath, ...rest } = props;
  const [readOnly, setReadOnly] = useState(false);

  function handleChange() {
    setReadOnly(!readOnly);
  }

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex alignItems="center" justifyContent="space-between" gap={2}>
          <OfferNavigationHeader
            title={<Trans>Offer Builder</Trans>}
            referrerPath={referrerPath}
          />
          <Box>
            Read only
            <Switch checked={readOnly} onChange={handleChange} />
          </Box>
        </Flex>
        <OfferBuilder readOnly={readOnly} {...rest} />
      </Flex>
    </Grid>
  );
}
