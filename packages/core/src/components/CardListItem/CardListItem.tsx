import React, { type ReactNode } from 'react';
import { Card, CardContent, CardActionArea } from '@mui/material';
import { styled } from '@mui/system';
import useColorModeValue from '../../utils/useColorModeValue';

const StyledCard = styled(Card, {
  shouldForwardProp: prop => !['selected'].includes(prop.toString()),
})(({ theme, selected }) => `
  width: 100%;
  border-radius: ${theme.spacing(1)};
  border: 1px solid ${selected
    ? theme.palette.highlight.main
    : theme.palette.divider};
  background-color: ${selected ? useColorModeValue(theme, 'sidebarBackground') : theme.palette.background.paper};
  margin-bottom: ${theme.spacing(1)};

  &:hover {
    border-color: ${theme.palette.highlight.main};
  }
`);

const StyledCardContent = styled(CardContent)(({ theme }) => `
  padding-bottom: ${theme.spacing(2)} !important;
`);

export type CardListItemProps = {
  children: ReactNode;
  selected?: boolean;
  onSelect?: () => void;
};

export default function CardListItem(props: CardListItemProps) {
  const { children, selected, onSelect } = props;

  const content = (
    <StyledCardContent>
      {children}
    </StyledCardContent>
  );

  return (
    <StyledCard variant="outlined" selected={selected}>
      {onSelect ? (
        <CardActionArea onClick={onSelect}>
          {content}
        </CardActionArea>
      ) : content}
    </StyledCard>
  );
}
