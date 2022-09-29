import React, { type ReactNode } from 'react';
import { useNavigate, useMatch } from 'react-router-dom';
import { ListItem, ListItemIcon, Typography } from '@mui/material';
import { styled } from '@mui/system';
import useColorModeValue from '../../utils/useColorModeValue';
import Flex from '../Flex';

const StyledListItemIcon = styled(ListItemIcon)`
  min-width: auto;
  position: relative;
  background-color: ${({ theme, selected }) =>
    selected ? useColorModeValue(theme, 'sidebarBackground') : 'transparent'};
  border-radius: ${({ theme }) => theme.spacing(1.5)};
  width: ${({ theme }) => theme.spacing(6)};
  height: ${({ theme }) => theme.spacing(6)};
  border: ${({ selected, theme }) =>
    `1px solid ${
      selected
        ? theme.palette.highlight.main
        : useColorModeValue(theme, 'border')
    }`};
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border 0.3s ease-in-out;

  &::after {
    content: '';
    border-radius: ${({ theme }) => theme.spacing(1.5)};
    position: absolute;
    z-index: -1;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    box-shadow: 0px -2px 4px rgba(104, 249, 127, 0.41),
      0px 1px 8px rgba(145, 247, 53, 0.45);
    opacity: 0;
    transition: opacity 0.3s ease-in-out;
  }

  svg {
    color: ${({ selected, theme }) =>
      selected
        ? useColorModeValue(theme, 'sidebarIconSelected')
        : useColorModeValue(theme, 'sidebarIcon')};
  }
`;

const StyledListItem = styled(ListItem)`
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-left: 0;
  padding-right: 0;
  padding-top: ${({ theme }) => theme.spacing(1)};
  padding-bottom: ${({ theme }) => theme.spacing(1)};

  &:hover {
    background-color: transparent;
  }

  &:hover ${StyledListItemIcon} {
    border-color: #4caf50;

    svg {
      color: ${({ theme }) =>
        useColorModeValue(theme, 'sidebarIconHover')} !important;
    }

    &::after {
      opacity: 1;
    }
  }
`;

const StyledListItemText = styled(Typography)`
  font-size: ${({ theme }) => theme.typography.pxToRem(10)} !important;
  font-weight: 500;
`;

export type SideBarItemProps = {
  to: string;
  title: ReactNode;
  icon: any;
  onSelect?: () => void;
  end?: boolean;
};

export default function SideBarItem(props: SideBarItemProps) {
  const { to, title, icon: Icon, end = false, onSelect, ...rest } = props;
  const navigate = useNavigate();
  const match = useMatch({
    path: to,
    end,
  });

  const isSelected = !!match;

  async function handleClick() {
    if (onSelect) {
      await onSelect();
    }
    navigate(to);
  }

  return (
    <StyledListItem button onClick={() => handleClick()} {...rest}>
      <Flex flexDirection="column" alignItems="center" gap={0.5}>
        <StyledListItemIcon selected={isSelected}>
          <Icon fontSize="sidebarIcon" />
        </StyledListItemIcon>
        <StyledListItemText align="center">{title}</StyledListItemText>
      </Flex>
    </StyledListItem>
  );
}
