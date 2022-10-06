import React, { useState, useRef } from 'react';
import { Trans } from '@lingui/macro';
import { Flex, ButtonLoading } from '@chia/core';
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
  const offerBuilderRef = useRef<{ submit: () => void } | undefined>(undefined);

  function handleChange() {
    setReadOnly(!readOnly);
  }

  async function handleSubmit() {
    await offerBuilderRef.current?.submit();
  }

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex alignItems="center" justifyContent="space-between" gap={2}>
          <OfferNavigationHeader
            title={<Trans>Offer Builder</Trans>}
            referrerPath={referrerPath}
          />
          <ButtonLoading
            variant="contained"
            color="primary"
            onClick={handleSubmit}
          >
            <Trans>Create Offer</Trans>
          </ButtonLoading>
          {/*
          <Box>
            Read only
            <Switch checked={readOnly} onChange={handleChange} />
          </Box>
          */}
        </Flex>
        <OfferBuilder readOnly={readOnly} ref={offerBuilderRef} {...rest} />
      </Flex>
    </Grid>
  );
}
