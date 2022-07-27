import React, { type ReactNode, ReactElement } from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import Flex from '../Flex';
import TooltipIcon from '../TooltipIcon';
import {
  Box,
  Card,
  CardContent,
  Typography,
  TypographyProps,
  CircularProgress,
} from '@mui/material';

const StyledCard = styled(Card)`
  height: 100%;
  overflow: visible;
  margin-bottom: -0.5rem;
`;

const StyledTitle = styled(Box)`
  margin-bottom: 0.5rem;
`;

const StyledValue = styled(Typography)`
  font-size: 1.25rem;
`;

export type CardSimpleProps = {
  title: ReactNode;
  actions?: ReactNode;
  value?: ReactNode;
  valueColor?: TypographyProps['color'];
  description?: ReactNode;
  loading?: boolean;
  tooltip?: ReactElement<any>;
  error?: Error;
  children?: ReactNode;
};

export default function CardSimple(props: CardSimpleProps) {
  const { title, value, description, valueColor, loading, tooltip, error, actions, children } = props;

  return (
    <StyledCard>
      <CardContent sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <StyledTitle>
          <Flex flexGrow={1} justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={0.5}>
            <Flex gap={1} alignItems="center">
              <Typography color="textSecondary">{title}</Typography>
              {tooltip && <TooltipIcon>{tooltip}</TooltipIcon>}
            </Flex>
            {actions}
          </Flex>
        </StyledTitle>
        {loading ? (
          <Box>
            <CircularProgress color="secondary" size={25} />
          </Box>
        ) : error ? (
          <Flex alignItems="center">
            <StyledValue variant="h5" color="error">
              <Trans>Error</Trans>
            </StyledValue>
            &nbsp;
            <TooltipIcon>{error?.message}</TooltipIcon>
          </Flex>
        ) : (
          <StyledValue variant="h5" color={valueColor}>
            {value}
          </StyledValue>
        )}
        {description && (
          <Typography variant="caption" color="textSecondary" flexGrow={1}>
            {description}
          </Typography>
        )}
        {children}
      </CardContent>
    </StyledCard>
  );
}

CardSimple.defaultProps = {
  valueColor: 'primary',
  description: undefined,
  loading: false,
  value: undefined,
  error: undefined,
};
