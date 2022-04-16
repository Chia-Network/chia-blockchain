import React, { type ReactNode } from 'react';
import styled from 'styled-components';
import { Box } from '@mui/material';
import Flex from '../Flex';
import { Outlet } from 'react-router';

const StyledRoot = styled(Flex)`
  width: 100%;
  height: 100%;
`;

const StyledSidebar = styled(Box)`
  height: 100%;
  position: relative;
`;

const StyledContent = styled(Box)`
  height: 100%;
  flex-grow: 1;
  overflow-y: scroll;

  padding-top: ${({ theme }) => `${theme.spacing(3)}`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}`};
  padding-right: ${({ theme }) => `${theme.spacing(3)}`};

  padding-left: ${({ theme, sidebar }) => !sidebar ? `${theme.spacing(3)}` : '10px'};
  margin-left: ${({ sidebar }) => !sidebar ? `0` : '-10px'};
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
    <StyledRoot>
      {sidebar && (
        <StyledSidebar>
          {sidebar}
        </StyledSidebar>
      )}
      <StyledContent sidebar={!!sidebar}>
        {outlet ? <Outlet /> : children}
      </StyledContent>
    </StyledRoot>
  );
}
