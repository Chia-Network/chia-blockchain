import React, { type ReactNode } from 'react';
import { Box, Card, CardContent, CardActionArea } from '@mui/material';
import { styled } from '@mui/system';
import Loading from '../Loading';
import useColorModeValue from '../../utils/useColorModeValue';

const StyledCard = styled(
  ({ selected, disabled, ...rest }) => <Card {...rest} />,
  {
    shouldForwardProp: (prop) => !['selected'].includes(prop.toString()),
  }
)(
  ({ theme, selected, disabled }) => `
  width: 100%;
  border-radius: ${theme.spacing(1)};
  border: 1px solid ${
    selected ? theme.palette.highlight.main : theme.palette.divider
  };
  background-color: ${
    selected
      ? useColorModeValue(theme, 'sidebarBackground')
      : theme.palette.background.paper
  };
  position: relative;

  &:hover {
    border-color: ${
      disabled
        ? theme.palette.divider
        : selected
        ? theme.palette.highlight.main
        : theme.palette.divider
    };
  }
`
);

const StyledCardContent = styled(CardContent)(
  ({ theme }) => `
  padding-bottom: ${theme.spacing(2)} !important;
`
);

export type CardListItemProps = {
  children: ReactNode;
  selected?: boolean;
  onSelect?: () => void;
  disabled?: boolean;
  loading?: boolean;
};

export default function CardListItem(props: CardListItemProps) {
  const { children, selected, onSelect, loading, disabled, ...rest } = props;

  const content = <StyledCardContent>{children}</StyledCardContent>;

  return (
    <StyledCard
      variant="outlined"
      selected={selected}
      disabled={disabled}
      {...rest}
    >
      {onSelect ? (
        <CardActionArea onClick={onSelect}>{content}</CardActionArea>
      ) : (
        content
      )}
      {(loading || disabled) && (
        <Box
          position="absolute"
          left={0}
          top={0}
          right={0}
          bottom={0}
          display="flex"
          alignItems="center"
          justifyContent="center"
          bgcolor={disabled ? 'rgba(0, 0, 0, 0.2)' : 'transparent'}
          zIndex={1}
        >
          {loading && <Loading center />}
        </Box>
      )}
    </StyledCard>
  );
}
