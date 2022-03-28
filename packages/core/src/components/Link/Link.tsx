import React, { SyntheticEvent } from 'react';
import styled from 'styled-components';
import {
  Link as BaseLink,
  LinkProps as BaseLinkProps,
} from '@mui/material';
import {
  Link as RouterLink,
  LinkProps as RouterLinkProps,
} from 'react-router-dom';
import useOpenExternal from '../../hooks/useOpenExternal';

type Props = BaseLinkProps &
  (
    | {
        to?: string | Object;
        fullWidth?: boolean;
        noWrap?: boolean;
      }
    | RouterLinkProps
  );

const StyledBaseLink = styled(({ fullWidth, noWrap, ...rest }) => (
  <BaseLink {...rest} />
))`
  width: ${({ fullWidth }) => (fullWidth ? '100%' : 'inherit')};
  ${({ noWrap }) => `white-space: nowrap;`}
  cursor: pointer;
`;

export default function Link(props: Props) {
  const { target, href, to, onClick } = props;
  const openExternal = useOpenExternal();
  const newProps = {
    ...props,
  };

  function handleClick(event: SyntheticEvent) {
    if (onClick) {
      event.preventDefault();
      event.stopPropagation();
      onClick(event);
      return;
    }

    if (href && target === '_blank') {
      event.preventDefault();
      event.stopPropagation();
      openExternal(href);
      return;
    }
  }

  return (
    <StyledBaseLink
      component={to ? RouterLink : BaseLink}
      {...newProps}
      onClick={handleClick}
    />
  );
}
