import React, { Fragment, type ReactNode } from 'react';
import { Card, CardContent, CardActionArea } from '@mui/material';
import { styled } from '@mui/system';

const StyledCard = styled(Card, {
  shouldForwardProp: prop => !['selected'].includes(prop.toString()),
})(({ theme, selected }) => `
  width: 100%;
  border-radius: ${theme.spacing(1)};
  border: 1px solid ${selected
    ? theme.palette.action.active
    : theme.palette.divider};
  margin-bottom: ${theme.spacing(1)};

  &:hover {
    border-color: ${theme.palette.highlight.main};
  }
`);

export type CardListItemProps = {
  children: ReactNode;
  selected?: boolean;
  onSelect?: () => void;
};

export default function CardListItem(props: CardListItemProps) {
  const { children, selected, onSelect } = props;
  const ActionCard = onSelect ? CardActionArea : Fragment;

  return (
    <StyledCard variant="outlined" selected={selected}>
      <ActionCard onClick={onSelect}>
        <CardContent>
          {children}
        </CardContent>
      </ActionCard>
    </StyledCard>
  );
}
