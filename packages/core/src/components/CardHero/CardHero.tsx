import React, { ReactNode } from 'react';
import { Card, CardContent } from '@mui/material';
import Flex from '../Flex';

type CardHeroProps = {
  children?: ReactNode;
};

export default function CardHero(props: CardHeroProps) {
  const { children } = props;

  return (
    <Card variant="outlined">
      <CardContent sx={{ padding: 3 }}>
        <Flex flexDirection="column" gap={3}>
          {children}
        </Flex>
      </CardContent>
    </Card>
  );
}
