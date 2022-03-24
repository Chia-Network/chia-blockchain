import React, { type ReactNode } from 'react';
import styled from 'styled-components';
import { Flex, Box } from '@chia/core';

const StyledRoot = styled(Flex)`
  width: 100%;
  height: 100%;
`;

const StyledSidebar = styled(Box)`
  height: 100%;
  overflow: auto;
  
`;

const StyledContent = styled(Box)`
  height: 100%;
  overflow: auto;
  flex-grow: 1;
  width: 100%;
`;

export type DashboardLayoutProps = {
  sidebar?: ReactNode;
  children?: ReactNode;
};

export default function DashboardLayout(props: DashboardLayoutProps) {
  const { sidebar, children } = props;
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
        {children}
      </StyledContent>
    </StyledRoot> 
  );
}