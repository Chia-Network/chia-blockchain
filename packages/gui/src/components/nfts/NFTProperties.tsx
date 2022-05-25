import React, { useMemo } from 'react';
import type { NFTAttribute } from '@chia/api';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { Box, Grid, Typography } from '@mui/material';
import isRankingAttribute from '../../util/isRankingAttribute';

export type NFTRankingsProps = {
  attributes?: NFTAttribute[];
};

export default function NFTProperties(props: NFTRankingsProps) {
  const { attributes } = props;

  const valueAttributes = useMemo(() => {
    return attributes?.filter((attribute) => !isRankingAttribute(attribute));
  }, [attributes]);

  if (!valueAttributes?.length) {
    return null;
  }

  return (
    <Flex flexDirection="column" gap={1}>
      <Typography variant="h6">
        <Trans>Properties</Trans>
      </Typography>
      <Grid spacing={2} container>
        {valueAttributes.map((attribute, index) => {
          const { name, trait_type, value } = attribute;
          const title = trait_type ?? name;

          return (
            <Grid xs={12} sm={6} key={`${attribute?.name}-${index}`} item>
              <Box border={1} borderRadius={1} borderColor="black" p={2}>
                <Typography variant="body1" noWrap>
                  {title}
                </Typography>
                <Typography variant="h6" noWrap>
                  {value}
                </Typography>
              </Box>
            </Grid>
          );
        })}
      </Grid>
    </Flex>
  );
}
