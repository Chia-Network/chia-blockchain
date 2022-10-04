import React, { ReactNode, ReactElement, cloneElement } from 'react';
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
};

export default function OfferBuilderSectionCard(
  props: OfferBuilderSectionCardProps,
) {
  const { icon, title, subtitle, children, onAdd, expanded } = props;
  const { readOnly } = useOfferBuilderContext();

  const isAddVisible = !readOnly && !!onAdd;

  return (
    <Box
      sx={{
        borderRadius: 1,
        padding: 3,
        paddingBottom: 2,
        backgroundColor: 'background.paper',
        border: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Flex flexDirection="column">
        <Flex flexDirection="row" gap={2}>
          <Flex>
            {cloneElement(icon, {
              fontSize: 'large',
            })}
          </Flex>
          <Flex flexDirection="row" gap={1} flexGrow={1} alignItems="center">
            <Flex flexDirection="column" flexGrow={1}>
              <Typography variant="h6" fontWeight="500">
                {title}
              </Typography>
              <Typography variant="body2" color="textSecondary">
                {subtitle}
              </Typography>
            </Flex>
            <Box
              sx={{
                opacity: !isAddVisible ? 0 : 1,
                pointerEvents: !isAddVisible ? 'none' : 'auto',
              }}
            >
              <IconButton onClick={onAdd}>
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
