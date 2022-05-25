import React, { useMemo } from 'react';
import type { NFTAttribute } from '@chia/api';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { styled } from '@mui/material/styles';
import { Grid, Typography, LinearProgress } from '@mui/material';
import isRankingAttribute from '../../util/isRankingAttribute';

const BorderLinearProgress = styled(LinearProgress)(() => ({
  height: 8,
  borderRadius: 4,
}));

export type NFTRankingsProps = {
  attributes?: NFTAttribute[];
};

export default function NFTRankings(props: NFTRankingsProps) {
  const { attributes } = props;

  const rankingsAttributes = useMemo(() => {
    return attributes?.filter(isRankingAttribute);
  }, [attributes]);

  if (!rankingsAttributes?.length) {
    return null;
  }

  return (
    <Flex flexDirection="column" gap={1}>
      <Typography variant="h6">
        <Trans>Rankings</Trans>
      </Typography>
      <Grid spacing={2} container>
        {rankingsAttributes.map((attribute, index) => {
          const { name, trait_type, value, min_value = 0, max_value } = attribute;

          const title = trait_type ?? name;
          const percentage = (value - min_value) / (max_value - min_value);
          const progress = Math.floor(percentage * 100);

          return (
            <Grid xs={12} sm={6} key={`${attribute?.name}-${index}`} item>
              <Flex flexDirection="column" gap={0.5} key={`${title}-${index}`}>
                <Flex justifyContent="space-between">
                  <Typography variant="body2">{title}</Typography>
                  <Typography variant="body2" color="textSecondary">
                    <Trans>{value} of {max_value}</Trans>
                  </Typography>
                </Flex>
                <BorderLinearProgress variant="determinate" value={progress} />
              </Flex>
            </Grid>
          );
        })}
      </Grid>
    </Flex>
  );
}
