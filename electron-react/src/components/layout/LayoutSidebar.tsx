import React, { ReactElement, ReactNode } from 'react';
import { Box, Container, Drawer, Toolbar } from '@material-ui/core';
import styled from 'styled-components';
import { Flex } from '@chia/core';
import DashboardTitle from '../dashboard/DashboardTitle';

const StyledSideBarContainer = styled(Box)`
  min-width: 180px;
  position: relative;
`;

const StyledSidebar = styled(Drawer)`
  > div {
    left: 100px;
    width: 180px;
  }
/*
  width: 100%;
  overflow: auto;
  height: 100%;
  position: fixed;
  left: 100px;

  > div {
    // position: relative;
  }
  */
`;

const StyledContainer = styled(Container)`
  padding-top: ${({ theme }) => `${theme.spacing(2)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(2)}px`};
`;

type Props = {
  children: ReactElement<any>;
  sidebar: ReactNode,
  title?: ReactNode;
};

export default function LayoutSidebar(props: Props): JSX.Element {
  const { children, title, sidebar } = props;

  return (
    <>
      <DashboardTitle>{title}</DashboardTitle>
      <Flex flexGrow={1}>
        <StyledSideBarContainer>
          <StyledSidebar
            variant="permanent"
            open
          >
            <Toolbar />
            {sidebar}
          </StyledSidebar>
        </StyledSideBarContainer>
        <Box flexGrow={1}>
          <StyledContainer maxWidth="lg">{children}</StyledContainer>
        </Box>
      </Flex>
    </>
  );
}
