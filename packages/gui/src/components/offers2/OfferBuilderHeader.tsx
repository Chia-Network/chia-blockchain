import React from 'react';
import { Flex, getColorModeValue } from '@chia/core';
import { Theme, Typography, useTheme } from '@mui/material';
import type { Variant } from '@mui/material/styles/createTypography';

type OfferBuilderHeaderStyle = {
  container: any;
  icon: any;
  title: any;
  subtitle: any;
};

function getStyle(theme: Theme): OfferBuilderHeaderStyle {
  return {
    container: {
      border: `1px solid ${getColorModeValue(theme, 'border')}`,
      borderRadius: '16px',
      backgroundColor: theme.palette.mode === 'dark' ? '#212121' : '#F5F5F5',
      width: '100%',
      p: '16px 32px 20px 28px',
    },
    icon: {
      backgroundColor: theme.palette.mode === 'dark' ? '#333333' : '#FFFFFF',
      width: '72px',
      height: '72px',
      borderRadius: '82px',
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

type Props = {
  icon: React.ReactNode;
  title: string | React.ReactNode;
  titleVariant?: Variant;
  subtitle: string | React.ReactNode;
  subtitleVariant?: Variant;
};

export default function OfferBuilderHeader(props: Props): JSX.Element {
  const {
    icon,
    title,
    titleVariant = 'h6',
    subtitle,
    subtitleVariant = 'body2',
  } = props;
  const theme = useTheme();
  const style = getStyle(theme);

  return (
    <Flex gap={2} sx={style.container}>
      <Flex
        alignItems="center"
        justifyContent="center"
        flexShrink={0}
        sx={style.icon}
      >
        {icon}
      </Flex>
      <Flex flexDirection="column" justifyContent="center" minWidth={0}>
        <Typography variant={titleVariant} sx={style.title}>
          {title}
        </Typography>
        <Typography variant={subtitleVariant} sx={style.subtitle}>
          {subtitle}
        </Typography>
      </Flex>
    </Flex>
  );
}
