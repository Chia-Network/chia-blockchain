import React, { SyntheticEvent } from 'react';
import styled from 'styled-components';
import {
  Link as BaseLink,
  LinkProps as BaseLinkProps,
} from '@material-ui/core';
import {
  Link as RouterLink,
  LinkProps as RouterLinkProps,
} from 'react-router-dom';
import useOpenExternal from '../../../../hooks/useOpenExternal';

type Props = BaseLinkProps & ({
  to?: string | Object;
  fullWidth?: boolean;
} | RouterLinkProps);

const StyledBadeLink = styled(({ fullWidth, ...rest }) => (
  <BaseLink {...rest} />
))`
  width: ${({ fullWidth }) => (fullWidth ? '100%' : 'inherit')};
`;

export default function Link(props: Props) {
  const { target, href } = props;
  const openExternal = useOpenExternal();
  const newProps = {
    ...props,
  };

  function handleOpenExternal(event: SyntheticEvent) {
    if (href) {
      event.preventDefault();
      event.stopPropagation();
      openExternal(href);
    }
  }

  if (target === '_blank') {
    newProps.onClick = handleOpenExternal;
  }

  return <StyledBadeLink component={RouterLink} {...newProps} fullWidth />;
}
