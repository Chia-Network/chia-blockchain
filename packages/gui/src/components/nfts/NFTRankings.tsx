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

export type NFTRankingProps = {
  attribute: NFTAttribute;
  size?: 'small' | 'regular';
  color?: 'primary' | 'secondary';
  progressColor?: 'primary' | 'secondary';
};

export type NFTRankingsProps = {
  attributes?: NFTAttribute[];
};

export function NFTRanking(props: NFTRankingProps) {
  const {
    attribute,
    size = 'regular',
    color = 'secondary',
    progressColor = 'primary',
  } = props;
  const { name, trait_type, value, min_value = 0, max_value } = attribute;
  const title = trait_type ?? name;
  const percentage = (value - min_value) / (max_value - min_value);
  const progress = Math.floor(percentage * 100);

  return (
    <Grid xs={12} sm={6} item>
      <Flex flexDirection="column" gap={0.5}>
        <Flex justifyContent="space-between" gap={0.5}>
          <Typography
            variant={size === 'small' ? 'caption' : 'body2'}
            color={color}
          >
            {title}
          </Typography>
          <Typography
            variant={size === 'small' ? 'caption' : 'body2'}
            color="textSecondary"
          >
            <Trans>
              {value} of {max_value}
            </Trans>
          </Typography>
        </Flex>
        <BorderLinearProgress
          variant="determinate"
          value={progress}
          color={progressColor}
        />
      </Flex>
    </Grid>
  );
}

export default function NFTRankings(props: NFTRankingsProps) {
  const { attributes } = props;

  const rankingsAttributes = useMemo(() => {
    if (Array.isArray(attributes)) {
      return attributes.filter(isRankingAttribute);
    }
    return [];
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
          return (
            <React.Fragment key={`${attribute?.name}-${index}`}>
              <NFTRanking attribute={attribute} />
            </React.Fragment>
          );
        })}
      </Grid>
    </Flex>
  );
}
