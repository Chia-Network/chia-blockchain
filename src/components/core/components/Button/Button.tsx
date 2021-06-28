import React from 'react';
import styled from 'styled-components';
import { darken } from 'polished';
import { useHistory } from 'react-router-dom';
import { Button as BaseButton, ButtonProps as BaseButtonProps } from '@material-ui/core';

const StyledBaseButton = styled(BaseButton)`
  white-space: ${({ nowrap }) => nowrap ? 'nowrap' : 'normal'};
`;

function getColor(theme, variant) {
  switch (variant) {
    case 'contained':
      return theme.palette.danger.contrastText;
    default:
      return theme.palette.danger.main;
  }
}

const DangerButton = styled(StyledBaseButton)`
  color: ${({ theme, variant }) => getColor(theme, variant)};
  ${({ theme, variant }) => variant === 'contained'
    ? `background-color: ${theme.palette.danger.main};`
    : undefined}

  &:hover {
    color: ${({ theme, variant }) =>  getColor(theme, variant)};
    ${({ theme, variant }) => variant === 'contained'
      ? `background-color: ${theme.palette.danger.main};`
      : undefined}
  }
`;

export type ButtonProps = Omit<BaseButtonProps, 'color'> & {
  color?: BaseButtonProps['color'] | 'danger';
  to?: string | Object;
};

export default function Button(props: ButtonProps) {
  const { color, to, onClick, ...rest } = props;

  const history = useHistory();

  function handleClick(...args) {
    if (to) {
      history.push(to);
    }

    if (onClick) {
      onClick(...args);
    }
  }

  switch (color) {
    case 'danger':
      return <DangerButton onClick={handleClick} {...rest} />;
    case 'primary':
      return <StyledBaseButton onClick={handleClick} color="primary" {...rest} />;
    case 'secondary':
      return <StyledBaseButton onClick={handleClick} color="secondary" {...rest} />;
    default:
      return <StyledBaseButton onClick={handleClick} {...rest} />;
  }
}
