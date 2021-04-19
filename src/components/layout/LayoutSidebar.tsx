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
    box-shadow: inset 6px 0 8px -8px rgba(0,0,0,0.2);
  }
`;

const StyledBody = styled(Box)`
  min-width: 0;
`;

const StyledContainer = styled(Container)`
  padding-top: ${({ theme }) => `${theme.spacing(3)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
`;

const StyledInnerContainer = styled(Box)`
  box-shadow: inset 6px 0 8px -8px rgba(0,0,0,0.2);
`;

type Props = {
  children?: ReactElement<any>;
  sidebar: ReactNode,
  title?: ReactNode;
};

export default function LayoutSidebar(props: Props) {
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
        <StyledBody flexGrow={1}>
          <StyledInnerContainer>
            <StyledContainer maxWidth="lg">
              <Flex flexDirection="column" gap={2}>
                {children}
              </Flex>
            </StyledContainer>
          </StyledInnerContainer>
        </StyledBody>
      </Flex>
    </>
  );
}

LayoutSidebar.defaultProps = {
  children: undefined,
};
