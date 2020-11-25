import React from 'react';
import styled from 'styled-components';
import {
  Link as BaseLink,
  LinkProps as BaseLinkProps,
} from '@material-ui/core';
import {
  Link as RouterLink,
  LinkProps as RouterLinkProps,
} from 'react-router-dom';

type Props = BaseLinkProps &
  RouterLinkProps & {
    to?: string | Object;
    fullWidth?: boolean;
  };

const StyledBadeLink = styled(({ fullWidth, ...rest }) => (
  <BaseLink {...rest} />
))`
  width: ${({ fullWidth }) => (fullWidth ? '100%' : 'inherit')};
`;

export default function Link(props: Props) {
  return <StyledBadeLink component={RouterLink} {...props} fullWidth />;
}
