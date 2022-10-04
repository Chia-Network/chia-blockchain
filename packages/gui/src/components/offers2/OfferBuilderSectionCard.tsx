import React, { ReactNode, ReactElement, cloneElement } from 'react';
import { Flex } from '@chia/core';
import { Box, CardActionArea, Collapse, Typography } from '@mui/material';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';

/*
const CONTAINER_BACKGROUND_NORMAL = ['#212121', '#FFFFFF']; // dark mode, light mode
const CONTAINER_BACKGROUND_DISABLED = ['#1C1C1C', '#F5F5F5']; // dark mode, light mode
const ICON_BACKGROUND_NORMAL = ['#333333', '#FFFFFF']; // dark mode, light mode
const ICON_BACKGROUND_DISABLED = ['#2E2E2E', '#F5F5F5']; // dark mode, light mode

function getStyle(
  theme: Theme,
  canToggleExpansion: boolean,
): OfferBuilderSectionStyle {
  const isDarkMode = theme.palette.mode === 'dark';
  const containerBackgroundColor = canToggleExpansion
    ? CONTAINER_BACKGROUND_NORMAL[isDarkMode ? 0 : 1]
    : CONTAINER_BACKGROUND_DISABLED[isDarkMode ? 0 : 1];
  const iconBackgroundColor = canToggleExpansion
    ? ICON_BACKGROUND_NORMAL[isDarkMode ? 0 : 1]
    : ICON_BACKGROUND_DISABLED[isDarkMode ? 0 : 1];

  return {
    container: {
      border: `1px solid ${getColorModeValue(theme, 'border')}`,
      borderRadius: '8px',
      backgroundColor: containerBackgroundColor,
      width: '100%',
      p: '20px 28px',
    },
    icon: {
      backgroundColor: iconBackgroundColor,
      width: '40px',
      height: '40px',
    },
  };
}
*/

export type OfferBuilderSectionCardProps = {
  name: string;
  icon: ReactElement;
  title: ReactNode;
  subtitle: ReactNode;
  children?: ReactNode;
};

export default function OfferBuilderSectionCard(
  props: OfferBuilderSectionCardProps,
) {
  const { icon, title, subtitle, children, name } = props;
  const { isExpanded, expand, readOnly } = useOfferBuilderContext();

  const expanded = readOnly ? true : isExpanded(name);

  function handleToggleExpansion() {
    if (!readOnly) {
      expand(name, !expanded);
    }
  }

  const Tag = readOnly ? Box : CardActionArea;

  return (
    <Tag onClick={handleToggleExpansion} borderRadius={8}>
      <Flex flexDirection="column">
        <Flex flexDirection="row" gap={2}>
          <Flex width={40} height={40}>
            {icon}
          </Flex>
          <Flex flexDirection="column">
            <Typography variant="h6" fontWeight="500">
              {title}
            </Typography>
            <Typography variant="body2" color="textSecondary">
              {subtitle}
            </Typography>
          </Flex>
        </Flex>
        <Collapse in={expanded} timeout="auto" unmountOnExit>
          {children}
        </Collapse>
      </Flex>
    </Tag>
  );
}
