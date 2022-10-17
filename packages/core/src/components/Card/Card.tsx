import React, { ReactNode, ReactElement } from 'react';
import styled from 'styled-components';
import {
  Box,
  Card as CardMaterial,
  CardProps as CardMaterialProps,
  CardContent,
  Grid,
  Typography,
} from '@mui/material';
import Flex from '../Flex';
import TooltipIcon from '../TooltipIcon';

const StyledCardTitle = styled(({ transparent, ...rest }) => <Box {...rest} />)`
  padding: ${({ theme, transparent }) =>
    !transparent
      ? `${theme.spacing(2)} ${theme.spacing(2)}`
      : `0 0 ${theme.spacing(2)} 0`};
`;

const StyledCardMaterial = styled(
  ({
    cursor,
    opacity,
    clickable,
    fullHeight,
    highlight,
    transparent,
    ...rest
  }) => <CardMaterial {...rest} />
)`
  cursor: ${({ clickable }) => (clickable ? 'pointer' : 'default')};
  opacity: ${({ disabled }) => (disabled ? '0.5' : '1')};
  height: ${({ fullHeight }) => (fullHeight ? '100%' : 'auto')};
  border: ${({ clickable }) => (clickable ? '1px solid transparent' : 'none')};
  border-radius: ${({ theme, highlight }) =>
    highlight
      ? `0 0 ${theme.shape.borderRadius}px ${theme.shape.borderRadius}px`
      : `${theme.shape.borderRadius}px`};

  &:hover {
    border-color: ${({ theme, clickable }) =>
      clickable ? theme.palette.primary.main : 'transparent'};
  }

  ${({ transparent }) =>
    transparent
      ? `
    background-color: transparent;
    background-image: none;
    border: none;
    box-shadow: none;
    overflow: visible;

    &:hover {
      border-color: transparent;
    }
  }
  `
      : ''}
`;

const StyledCardContent = styled(({ fullHeight, transparent, ...rest }) => (
  <CardContent {...rest} />
))`
  display: flex;
  flex-direction: column;
  height: ${({ fullHeight }) => (fullHeight ? '100%' : 'auto')};
  padding-bottom: ${({ theme, transparent }) =>
    !transparent ? theme.spacing(2) : '0'} !important;

  ${({ transparent }) =>
    transparent
      ? `
    padding-left: 0;
    padding-right: 0;
    padding-top: 0;
  `
      : ''}
`;

const StyledRoot = styled(({ fullHeight, ...rest }) => <Flex {...rest} />)`
  display: flex;
  flex-direction: column;
  height: ${({ fullHeight }) => (fullHeight ? '100%' : 'auto')};
`;

const StyledHighlight = styled(Box)`
  background-color: ${({ theme }) => theme.palette.primary.main};
  padding: ${({ theme }) => theme.spacing(1)}px;
  color: ${({ theme }) => theme.palette.primary.contrastText};
  font-weight: 500;
  text-align: center;
  text-transform: uppercase;
  font-size: 0.75rem;
  visibility: ${({ empty }) => (empty ? 'hidden' : 'visible')};
  border-radius: ${({ theme }) => theme.shape.borderRadius}px
    ${({ theme }) => theme.shape.borderRadius}px 0 0;
`;

export type CardProps = {
  children?: ReactNode;
  title?: ReactNode;
  tooltip?: ReactElement<any>;
  actions?: ReactNode;
  gap?: number;
  disableInteractive?: boolean;
  action?: ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
  fullHeight?: boolean;
  highlight?: ReactNode | false;
  transparent?: boolean;
  titleVariant?: string;
  variant?: CardMaterialProps['variant'];
};

export default function Card(props: CardProps) {
  const {
    children,
    highlight,
    title,
    tooltip,
    actions,
    gap = 2,
    disableInteractive = false,
    titleVariant = 'h5',
    action,
    onSelect,
    disabled,
    fullHeight,
    transparent = false,
    variant,
  } = props;

  const headerTitle = tooltip ? (
    <Flex alignItems="center" gap={1}>
      <Box>{title}</Box>
      <TooltipIcon disableInteractive={disableInteractive}>
        {tooltip}
      </TooltipIcon>
    </Flex>
  ) : (
    title
  );

  function handleClick() {
    if (onSelect) {
      onSelect();
    }
  }

  return (
    <StyledRoot fullHeight={fullHeight}>
      {highlight === false && <StyledHighlight empty>&nbsp;</StyledHighlight>}
      {highlight && <StyledHighlight>{highlight}</StyledHighlight>}
      <StyledCardMaterial
        onClick={handleClick}
        clickable={!!onSelect}
        disabled={disabled}
        fullHeight={fullHeight}
        highlight={!!highlight}
        transparent={transparent}
        variant={variant}
      >
        {title && (
          <StyledCardTitle transparent={transparent}>
            <Flex gap={2} alignItems="center" flexWrap="wrap">
              <Box flexGrow={1}>
                <Typography variant={titleVariant}>{headerTitle}</Typography>
              </Box>
              {action && <Box>{action}</Box>}
            </Flex>
          </StyledCardTitle>
        )}
        <StyledCardContent fullHeight={fullHeight} transparent={transparent}>
          <Flex flexDirection="column" gap={3} flexGrow={1}>
            <Flex flexDirection="column" gap={gap} flexGrow={1}>
              {children}
            </Flex>
            {actions && (
              <Grid xs={12} item>
                <Flex gap={2}>{actions}</Flex>
              </Grid>
            )}
          </Flex>
        </StyledCardContent>
      </StyledCardMaterial>
    </StyledRoot>
  );
}
