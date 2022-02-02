import React, { ReactNode } from 'react';
import { Typography } from '@material-ui/core';
import Flex from '../Flex';
import { createTeleporter } from 'react-teleporter';

const DashboardTitleTeleporter = createTeleporter();

export function DashboardTitleTarget() {
  return (
    <Typography component="h1" variant="h6" noWrap>
      <DashboardTitleTeleporter.Target />
    </Typography>
  );
}

type Props = {
  children?: ReactNode;
};

export default function DashboardTitle(props: Props) {
  const { children } = props;

  return (
    <DashboardTitleTeleporter.Source>
      <Flex alignItems="center">{children}</Flex>
    </DashboardTitleTeleporter.Source>
  );
}

DashboardTitle.defaultProps = {
  children: undefined,
};
