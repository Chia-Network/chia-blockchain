import React, { ReactNode } from 'react';
import styled from 'styled-components';
import { Card, CardContent } from '@material-ui/core';
import { Flex } from '@chia/core';

const StyledContent = styled(CardContent)`
  padding: ${({ theme }) => `${theme.spacing(5)}px ${theme.spacing(4)}px !important`};
`;

type Props = {
  children?: ReactNode,
};

export default function CardHero(props: Props) {
  const { children } = props;

  return (
    <Card>
      <StyledContent>
        <Flex flexDirection="column" gap={3}>
          {children}
        </Flex>
      </StyledContent>
    </Card>
  );
}

CardHero.defaultProps = {
  children: undefined,
};
