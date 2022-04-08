import React, { type ReactNode } from 'react';
import { AppBar, Toolbar, Box } from '@mui/material';
import styled from 'styled-components';
import { Outlet, Link } from 'react-router-dom';
import Flex from '../Flex';
import { ArrowBackIos as ArrowBackIosIcon } from '@mui/icons-material';

const StyledWrapper = styled(Box)`
  padding-top: ${({ theme }) => `${theme.spacing(3)}`};
  display: flex;
  flex-direction: column;
  flex-grow: 1;
  background: ${({ theme }) =>
    theme.palette.mode === 'dark'
      ? `linear-gradient(45deg, #222222 30%, #333333 90%)`
      : `linear-gradient(45deg, #ffffff 30%, #fdfdfd 90%)`};
`;

const StyledBody = styled(Box)`
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  flex-grow: 1;
  padding-bottom: 1rem;
`;

export type LayoutHeroProps = {
  children?: ReactNode;
  header?: ReactNode;
  back?: boolean;
  outlet?: boolean;
};

export default function LayoutHero(props: LayoutHeroProps) {
  const {
    children,
    header,
    back = false,
    outlet = false,
  } = props;

  return (
    <StyledWrapper>
      <AppBar color="transparent" elevation={0}>
        <Toolbar>
          {header}
          {back && (
            <Link to="-1">
              <ArrowBackIosIcon fontSize="large" color="secondary" />
            </Link>
          )}
          <Flex flexGrow={1} />
          {/*!hideSettings && (
            <Settings>
              {settings}
            </Settings>
          )*/}
        </Toolbar>
      </AppBar>
      <StyledBody>
        <Flex flexDirection="column" gap={2} alignItems="center" alignSelf="stretch">
          {outlet ? <Outlet /> : children}
        </Flex>
      </StyledBody>
    </StyledWrapper>
  );
}
