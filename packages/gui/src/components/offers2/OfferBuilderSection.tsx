import React, {
  ReactNode,
  ReactElement,
  cloneElement,
  MouseEvent,
} from 'react';
import { Flex } from '@chia/core';
import { Box, IconButton, Collapse, Typography } from '@mui/material';
import { Add } from '@mui/icons-material';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';

export type OfferBuilderSectionCardProps = {
  icon: ReactElement;
  title: ReactNode;
  subtitle: ReactNode;
  children?: ReactNode;
  onAdd?: () => void;
  expanded?: boolean;
  muted?: boolean;
  disableReadOnly?: boolean;
};

export default function OfferBuilderSectionCard(
  props: OfferBuilderSectionCardProps,
) {
  const {
    icon,
    title,
    subtitle,
    children,
    onAdd,
    expanded = false,
    muted = false,
    disableReadOnly = false,
  } = props;
  const { readOnly: builderReadOnly } = useOfferBuilderContext();

  const readOnly = disableReadOnly ? false : builderReadOnly;

  const isAddVisible = !readOnly && !!onAdd;
  const isMuted = muted && !expanded;

  function handleClick() {
    if (onAdd && !expanded) {
      onAdd();
    }
  }

  function handleAdd(event: MouseEvent) {
    event.stopPropagation();
    onAdd?.();
  }

  return (
    <Box
      onClick={handleClick}
      sx={{
        borderRadius: 1,
        paddingX: 3,
        paddingY: isMuted ? 1.5 : 3,
        backgroundColor: isMuted ? 'transparent' : 'background.card',
        border: '1px solid',
        borderColor: 'divider',
        transition: '0.25s padding ease-out',
        '&:hover': {
          backgroundColor: 'background.card',
        },
      }}
    >
      <Flex flexDirection="column">
        <Flex flexDirection="row" gap={2}>
          <Flex flexGrow={1}>
            <Flex
              sx={{
                width: muted && !expanded ? 0 : 'auto',
                transition: '0.25s width ease-out, 0.25s margin ease-out',
                overflow: 'hidden',
                marginRight: muted && !expanded ? 0 : 2,
                flexShrink: 0,
              }}
            >
              {cloneElement(icon, {
                fontSize: 'large',
              })}
            </Flex>
            <Flex flexDirection="row" gap={1} flexGrow={1} alignItems="center">
              <Flex flexDirection="column" flexGrow={1}>
                <Typography variant="h6" fontWeight="500">
                  {title}
                </Typography>
                <Typography
                  variant="body2"
                  color="textSecondary"
                  sx={{
                    height: muted || expanded ? 0 : 'auto',
                    transition: '0.25s height ease-out',
                    overflow: 'hidden',
                  }}
                >
                  {subtitle}
                </Typography>
              </Flex>
            </Flex>
            <Box
              sx={{
                opacity: !isAddVisible ? 0 : 1,
                pointerEvents: !isAddVisible ? 'none' : 'auto',
              }}
            >
              <IconButton onClick={handleAdd}>
                <Add />
              </IconButton>
            </Box>
          </Flex>
        </Flex>
        <Collapse in={expanded} timeout="auto" unmountOnExit>
          <Box sx={{ marginTop: 4 }}>{children}</Box>
        </Collapse>
      </Flex>
    </Box>
  );
}
