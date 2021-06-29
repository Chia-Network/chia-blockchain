import React from 'react';
import { Trans } from '@lingui/macro';
import { Typography } from '@material-ui/core';
import type PoolInfoType from '../../types/PoolInfo';
import { CardKeyValue, Flex, Link } from '@chia/core';

type Props = {
  poolInfo: PoolInfoType;
};

export default function PoolInfo(props: Props) {
  const { poolInfo } = props;

  const rows = [
    {
      key: 'fee',
      label: <Trans>Fee</Trans>,
      value: poolInfo.fee,
    },
    {
      key: 'protocol_version',
      label: <Trans>Protocol Version</Trans>,
      value: poolInfo.protocol_version,
    },
    {
      key: 'minimum_difficulty',
      label: <Trans>Minimum Difficulty</Trans>,
      value: poolInfo.minimum_difficulty,
    },
    {
      key: 'relative_lock_height',
      label: <Trans>Relative Lock Height</Trans>,
      value: poolInfo.relative_lock_height,
    },
    {
      key: 'target_puzzle_hash',
      label: <Trans>Target Puzzle Hash</Trans>,
      value: poolInfo.target_puzzle_hash,
    },
  ].filter((row) => row.value !== undefined);

  return (
    <Flex flexDirection="column" gap={2}>
      {/* 
      <Box>
        <StyledLogo src={poolInfo.logo_url} alt={t`Pool logo`} />
      </Box>
      */}
      <Flex flexDirection="column" gap={1}>
        <Typography gutterBottom variant="h5" component="h2">
          {poolInfo.name}
        </Typography>
        <Typography
          gutterBottom
          variant="body2"
          color="textSecondary"
          component="p"
        >
          <Link href={poolInfo.pool_url} target="_blank">
            {poolInfo.pool_url}
          </Link>
        </Typography>
        <Typography variant="body2" color="textSecondary" component="p">
          {poolInfo.description}
        </Typography>
      </Flex>
      <CardKeyValue rows={rows} hideDivider />
    </Flex>
  );
}
