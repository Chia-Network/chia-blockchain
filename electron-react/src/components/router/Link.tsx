import React from 'react';
import { Link as BaseLink, LinkProps as BaseLinkProps } from "@material-ui/core";
import { Link as RouterLink, LinkProps as RouterLinkProps } from 'react-router-dom'; 

type Props = BaseLinkProps & RouterLinkProps & {
  to?: string | Object,
  fullWidth?: boolean,
};

export default function Link(props: Props) {
  return (
    <BaseLink  {...props} fullWidth />
  );
}
