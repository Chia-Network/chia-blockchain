import React from 'react';
import { Trans } from '@lingui/macro';
import { Typography } from '@mui/material';
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
      key: 'protocolVersion',
      label: <Trans>Protocol Version</Trans>,
      value: poolInfo.protocolVersion,
    },
    {
      key: 'minimumDifficulty',
      label: <Trans>Minimum Difficulty</Trans>,
      value: poolInfo.minimumDifficulty,
    },
    {
      key: 'relativeLockHeight',
      label: <Trans>Relative Lock Height</Trans>,
      value: poolInfo.relativeLockHeight,
    },
    {
      key: 'targetPuzzleHash',
      label: <Trans>Target Puzzle Hash</Trans>,
      value: poolInfo.targetPuzzleHash,
    },
  ].filter((row) => row.value !== undefined);

  return (
    <Flex flexDirection="column" gap={2}>
      {/*
      <Box>
        <StyledLogo src={poolInfo.logoUrl} alt={t`Pool logo`} />
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
          <Link href={poolInfo.poolUrl} target="_blank">
            {poolInfo.poolUrl}
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
