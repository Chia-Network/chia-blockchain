import React, { ReactNode, ReactElement } from 'react';
import { Flex } from '@chia/core';
import { Box, CardActionArea, Collapse, Typography } from '@mui/material';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';

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
