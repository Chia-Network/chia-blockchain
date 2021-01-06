import React, { ReactNode, ReactElement } from 'react';
import { Box, Card as CardMaterial, CardContent, CardHeader, Grid } from '@material-ui/core';
import Flex from '../Flex';
import TooltipIcon from '../TooltipIcon';

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
        <CardHeader title={headerTitle} action={action} />
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
