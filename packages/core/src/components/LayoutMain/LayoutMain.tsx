import React, { ReactElement, ReactNode } from 'react';
import { Container } from '@material-ui/core';
import styled from 'styled-components';
import { Flex } from '@chia/core';
import { Outlet } from 'react-router-dom';
import DashboardTitle from '../DashboardTitle';
import LayoutFooter from './LayoutFooter';

const StyledContainer = styled(Container)`
  padding-top: ${({ theme }) => `${theme.spacing(3)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
  flex-grow: 1;
  display: flex;
`;

const StyledInnerContainer = styled(Flex)`
  box-shadow: inset 6px 0 8px -8px rgba(0, 0, 0, 0.2);
  flex-grow: 1;
`;

const StyledBody = styled(Flex)`
  min-width: 0;
`;

type Props = {
  children?: ReactElement<any>;
  title?: ReactNode;
  bodyHeader?: ReactNode;
  outlet?: boolean;
};

export default function LayoutMain(props: Props) {
  const { children, title, bodyHeader, outlet } = props;

  return (
    <>
      <DashboardTitle>{title}</DashboardTitle>

      <StyledInnerContainer flexDirection="column">
        {bodyHeader}
        <StyledContainer maxWidth="lg">
          <StyledBody flexDirection="column" gap={2} flexGrow="1">
            {outlet ? <Outlet /> : children}
          </StyledBody>
        </StyledContainer>
      </StyledInnerContainer>
      <LayoutFooter />
    </>
  );
}

LayoutMain.defaultProps = {
  children: undefined,
  bodyHeader: undefined,
  outlet: false,
};
