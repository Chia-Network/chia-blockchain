import React, { type ReactNode } from 'react';
import styled from 'styled-components';
import { Box } from '@material-ui/core';
import Flex from '../Flex';
import { Outlet } from 'react-router';

const StyledRoot = styled(Flex)`
  width: 100%;
  height: 100%;
`;

const StyledSidebar = styled(Box)`
  height: 100%;
  padding-top: ${({ theme }) => `${theme.spacing(3)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
`;

const StyledContent = styled(Box)`
  height: 100%;
  overflow: auto;
  flex-grow: 1;
  width: 100%;
  padding-left: ${({ theme }) => theme.spacing(4)}px;
  padding-right: ${({ theme }) => theme.spacing(4)}px;
  padding-top: ${({ theme }) => `${theme.spacing(3)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
`;

export type DashboardLayoutProps = {
  sidebar?: ReactNode;
  children?: ReactNode;
  outlet?: boolean;
};

export default function DashboardLayout(props: DashboardLayoutProps) {
  const { sidebar, children, outlet = false } = props;
  // two layout column with always visible left column
  // and right column with content
  return (
    <StyledRoot gap="md">
      {sidebar && (
        <StyledSidebar>
          {sidebar}
        </StyledSidebar>
      )}
      <StyledContent>
        {outlet ? <Outlet /> : children}
      </StyledContent>
    </StyledRoot> 
  );
}