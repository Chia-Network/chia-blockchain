import React from 'react';
import { Flex, getColorModeValue } from '@chia/core';
import {
  CardActionArea,
  Collapse,
  Theme,
  Typography,
  useTheme,
} from '@mui/material';
import type { Variant } from '@mui/material/styles/createTypography';
import OfferBuilderSectionType from './OfferBuilderSectionType';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';
import useOfferBuilderContext from './useOfferBuilderContext';

type OfferBuilderSectionStyle = {
  container: any;
  icon: any;
  title: any;
  subtitle: any;
};

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
    title: {
      color: getColorModeValue(theme, 'secondary'),
      fontWeight: '500',
    },
    subtitle: {
      color: getColorModeValue(theme, 'secondary'),
    },
  };
}

export type OfferBuilderSectionProps = {
  side: OfferBuilderTradeSide;
  canToggleExpansion?: boolean;
};

export type Props = OfferBuilderSectionProps & {
  icon: React.ReactNode;
  title: string | React.ReactNode;
  titleVariant?: Variant;
  subtitle: string | React.ReactNode;
  subtitleVariant?: Variant;
  sectionType: OfferBuilderSectionType;
  children: React.ReactNode;
};

export default function OfferBuilderSection(props: Props): JSX.Element {
  const {
    icon,
    title,
    titleVariant = 'h6',
    subtitle,
    subtitleVariant = 'body2',
    side,
    sectionType,
    canToggleExpansion = false,
    children,
  } = props;
  const { expandedSections, updateExpandedSections } = useOfferBuilderContext();
  const theme = useTheme();
  const style = getStyle(theme, canToggleExpansion);
  const expanded = expandedSections[side]?.includes(sectionType) ?? false;
  const OuterContainer = canToggleExpansion ? CardActionArea : React.Fragment;

  function handleClick() {
    updateExpandedSections(side, sectionType, !expanded);
  }

  return (
    <OuterContainer {...(canToggleExpansion ? { onClick: handleClick } : {})}>
      <Flex flexDirection="column" sx={style.container}>
        <Flex flexDirection="row" gap={2}>
          <Flex
            alignItems="center"
            justifyContent="center"
            flexShrink={0}
            sx={style.icon}
          >
            {icon}
          </Flex>
          <Flex flexDirection="column" justifyContent="center">
            <Typography variant={titleVariant} sx={style.title}>
              {title}
            </Typography>
            <Typography variant={subtitleVariant} sx={style.subtitle}>
              {subtitle}
            </Typography>
          </Flex>
        </Flex>
        <Collapse in={expanded} timeout="auto" unmountOnExit>
          {children}
        </Collapse>
      </Flex>
    </OuterContainer>
  );
}
