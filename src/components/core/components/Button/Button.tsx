import React from 'react';
import styled from 'styled-components';
import { darken } from 'polished';
import { Button as BaseButton, ButtonProps } from '@material-ui/core';

const StyledBaseButton = styled(BaseButton)`
  white-space: ${({ nowrap }) => nowrap ? 'nowrap' : 'normal'};
`;

const DangerButton = styled(StyledBaseButton)`
  color: ${({ theme }) => theme.palette.danger.contrastText};
  background-color: ${({ theme }) => theme.palette.danger.main};

  &:hover {
    color: ${({ theme }) => theme.palette.danger.contrastText};
    background-color: ${({ theme }) => darken(0.1, theme.palette.danger.main)};
  }
`;

type Props = Omit<ButtonProps, 'color'> & {
  color?: ButtonProps['color'] | 'danger';
  nowrap?: boolean;
};

export default function Button(props: Props) {
  const { color, ...rest } = props;

  switch (color) {
    case 'danger':
      return <DangerButton {...rest} />;
    case 'primary':
      return <StyledBaseButton color="primary" {...rest} />;
    case 'secondary':
      return <StyledBaseButton color="secondary" {...rest} />;
    default:
      return <StyledBaseButton {...rest} />;
  }
}
