import React, { ReactNode, ReactElement } from 'react';
import styled from 'styled-components';
import { Box, Card as CardMaterial, CardContent, Grid, Typography } from '@material-ui/core';
import Flex from '../Flex';
import TooltipIcon from '../TooltipIcon';

const StyledCardTitle = styled(Box)`
  padding: ${({ theme }) => `${theme.spacing(2)}px ${theme.spacing(2)}px`};
`;

type Props = {
  children?: ReactNode;
  title?: ReactNode;
  tooltip?: ReactElement<any>;
  actions?: ReactNode;
  gap?: number;
  interactive?: boolean;
  action?: ReactNode,
};

export default function Card(props: Props) {
  const { children, title, tooltip, actions, gap, interactive, action } = props;

  const headerTitle = tooltip ? (
    <Flex alignItems="center" gap={1}>
      <Box>
        {title}
      </Box>
      <TooltipIcon interactive={interactive}>
        {tooltip}
      </TooltipIcon>
    </Flex>
  ) : title;

  return (
    <CardMaterial>
      {title && (
        <StyledCardTitle>
          <Flex gap={2} alignItems="center" flexWrap="wrap">
            <Box flexGrow={1}>
              <Typography variant="h5">
                {headerTitle}
              </Typography>
            </Box>
            {action && (
              <Box>
                {action}
              </Box>
            )}
          </Flex>
        </StyledCardTitle>
      )}
      <CardContent>
        <Flex flexDirection="column" gap={3}>
          <Flex flexDirection="column" gap={gap}>
            {children}
          </Flex>
          {actions && (
            <Grid xs={12} item>
              <Flex gap={2}>
                {actions}
              </Flex>
            </Grid>
          )}
        </Flex>
      </CardContent>
    </CardMaterial>
  );
}

Card.defaultProps = {
  gap: 2,
  children: undefined,
  title: undefined,
  tooltip: undefined,
  actions: undefined,
  interactive: false,
};
