import React, { ReactNode } from 'react';
import { Card, CardContent, CardProps } from '@mui/material';
import Flex from '../Flex';

export type CardHeroProps = {
  children?: ReactNode;
  fullHeight?: boolean;
  variant?: CardProps['variant'];
};

export default function CardHero(props: CardHeroProps) {
  const { children, fullHeight, variant } = props;

  return (
    <Card variant={variant} sx={{ height: fullHeight ? '100%' : 'auto' }}>
      <CardContent sx={{ padding: 3, height: fullHeight ? '100%' : 'auto' }}>
        <Flex flexDirection="column" gap={3} height="100%">
          {children}
        </Flex>
      </CardContent>
    </Card>
  );
}
