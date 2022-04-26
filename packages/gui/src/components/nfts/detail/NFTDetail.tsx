import React from 'react';
import { Trans } from '@lingui/macro';
import moment from 'moment';
import { Back, Flex, LayoutDashboardSub, Loading, Table, mojoToChia, FormatLargeNumber, CardKeyValue } from '@chia/core';
import { useNFTMetadata } from '@chia/api-react';
import { Box, CardMedia, Grid, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';

const cols = [{
  field: ({ date }) => (
    <Typography color="textSecondary" variant="body2">
      {moment(date).format('LLL')}
    </Typography>
  ),
  title: <Trans>Date</Trans>,
}, {
  field: 'from',
  title: <Trans>From</Trans>,
}, {
  field: 'to',
  title: <Trans>To</Trans>,
}, {
  field: ({ amount }) => (
    <strong>
      <FormatLargeNumber value={mojoToChia(amount)} />
      &nbsp;
      XCH
    </strong>
  ),
  title: <Trans>Amount</Trans>,
}];

export default function NFTDetail() {
  const { nftId } = useParams();
  const { metadata, isLoading } = useNFTMetadata({ id: nftId });

  if (isLoading) {
    return (
      <Loading center />
    );
  }

  const details = [{
    key: 'id',
    label: <Trans>Token ID</Trans>,
    value: nftId,
  }, {
    key: 'contract',
    label: <Trans>Contract Address</Trans>,
    value: metadata.contractAddress,
  }, {
    key: 'tokenStandard',
    label: <Trans>Token Standard</Trans>,
    value: metadata.standard,
  }, {
    key: 'belongs',
    label: <Trans>Belongs To</Trans>,
    value: metadata.owner,
  }, {
    key: 'dataHash',
    label: <Trans>Data Hash</Trans>,
    value: metadata.hash,
  }];

  return (
    <LayoutDashboardSub>
      <Flex flexDirection="column" gap={2}>
        <Back variant="h5">
          {metadata.name}
        </Back>
        <Grid spacing={2} alignItems="stretch" container>
          <Grid xs={12} md={6} item>
            <Box border={1} borderColor="grey.300" borderRadius={4} height="100%" overflow="hidden" display="flex" alignItems="center">
              <CardMedia src={metadata.image} component="img" height="500px" />
            </Box>
          </Grid>
          <Grid xs={12} md={6} item>
            <Flex flexDirection="column" gap={3}>
              <Flex flexDirection="column" gap={1}>
                <Typography variant="h6">
                  <Trans>Description</Trans>
                </Typography>

                <Typography>
                  {metadata.description}
                </Typography>
              </Flex>
              <Flex flexDirection="column" gap={1}>
                <Typography variant="h6">
                  <Trans>Details</Trans>
                </Typography>

                <CardKeyValue rows={details} hideDivider />
              </Flex>
            </Flex>
          </Grid>
        </Grid>
        <Flex flexDirection="column" gap={1}>
          <Typography variant="h6">
            <Trans>Item Activity</Trans>
          </Typography>
          <Table cols={cols} rows={metadata.activity} />
        </Flex>
      </Flex>
    </LayoutDashboardSub>
  );
}
