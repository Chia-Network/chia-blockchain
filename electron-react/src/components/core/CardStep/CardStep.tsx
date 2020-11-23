import React, { ReactNode } from 'react';
import styled from 'styled-components';
import { Avatar, Card, CardContent, CardHeader, Divider, Grid, Typography } from '@material-ui/core';
import Flex from '../Flex';

const StyledCardContent = styled(CardContent)`
  padding-left: 72px;
`;

const StyledStep = styled(Avatar)`
  width: 2rem;
  height: 2rem;
`;

type Props = {
  children: ReactNode,
  title: ReactNode,
  step: ReactNode,
};

export default function CardStep(props: Props) {
  const { children, step, title } = props;

  return (
    <Card>
      <CardHeader
        avatar={
          <StyledStep aria-label="step">
            {step}
          </StyledStep>
        }
        title={(
          <Typography variant="h6">
            {title}
          </Typography>
        )}
      />
      <Divider />
      <StyledCardContent>
        <Grid container>
          <Grid md={10} lg={8} item>
            <Flex flexDirection="column" gap={2}>
              {children}
            </Flex>
          </Grid>
        </Grid>
      </StyledCardContent>
    </Card>
  );
}
