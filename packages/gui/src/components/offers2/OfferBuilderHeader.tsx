import React, { ReactNode } from 'react';
import { Flex } from '@chia/core';
import { Typography } from '@mui/material';

export type OfferBuilderHeaderProps = {
  icon: ReactNode;
  title: ReactNode;
  subtitle: ReactNode;
};

export default function OfferBuilderHeader(props: OfferBuilderHeaderProps) {
  const { icon, title, subtitle } = props;

  return (
    <Flex
      gap={2}
      sx={{
        borderRadius: 2,
        backgroundColor: 'action.hover',
        border: '1px solid',
        borderColor: 'divider',
        paddingY: 2,
        paddingX: 3,
      }}
    >
      <Flex
        alignItems="center"
        justifyContent="center"
        flexShrink={0}
        sx={{
          backgroundColor: 'background.card',
          width: '72px',
          height: '72px',
          borderRadius: 9999,
        }}
      >
        {icon}
      </Flex>
      <Flex flexDirection="column" justifyContent="center" minWidth={0}>
        <Typography variant="h6" fontWeight="500">
          {title}
        </Typography>
        <Typography variant="body2" color="textSecondary">
          {subtitle}
        </Typography>
      </Flex>
    </Flex>
  );
}
