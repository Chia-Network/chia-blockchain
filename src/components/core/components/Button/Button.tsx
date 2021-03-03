import React from 'react';
import styled from 'styled-components';
import { darken } from 'polished';
import { Button as BaseButton, ButtonProps } from '@material-ui/core';

const DangerButton = styled(BaseButton)`
  color: ${({ theme }) => theme.palette.danger.contrastText};
  background-color: ${({ theme }) => theme.palette.danger.main};

  &:hover {
    color: ${({ theme }) => theme.palette.danger.contrastText};
    background-color: ${({ theme }) => darken(0.1, theme.palette.danger.main)};
  }
`;

type Props = Omit<ButtonProps, 'color'> & {
  color?: ButtonProps['color'] | 'danger';
};

export default function Button(props: Props) {
  const { color, ...rest } = props;

  switch (color) {
    case 'danger':
      return <DangerButton {...rest} />;
    case 'primary':
      return <BaseButton color="primary" {...rest} />;
    case 'secondary':
      return <BaseButton color="secondary" {...rest} />;
    default:
      return <BaseButton {...rest} />;
  }
}
