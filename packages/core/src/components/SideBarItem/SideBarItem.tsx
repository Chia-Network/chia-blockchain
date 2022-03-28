import React, { ReactNode, cloneElement } from 'react';
import styled from 'styled-components';
import { useNavigate, useMatch } from 'react-router-dom';
import { ListItem, ListItemIcon, ListItemText } from '@mui/material';
import useColorModeValue from '../../utils/useColorModeValue';

const StyledListItemIcon = styled(ListItemIcon)`
  min-width: auto;
  background-color: ${({ theme }) => theme.palette.action.hover};
  border-radius: ${({ theme }) => theme.spacing(1.5)};
  width: ${({ theme }) => theme.spacing(6)};
  height: ${({ theme }) => theme.spacing(6)};
  border: ${({ selected, theme }) => `1px solid ${selected 
    ? theme.palette.highlight.main 
    : useColorModeValue(theme, 'border')}`};
  display: flex;
  align-items: center;
  justify-content: center;
`;

const StyledListItem = styled(ListItem)`
  display: flex;
  flex-direction: column;
  white-space: nowrap;
  align-items: center;
  padding-left: 0;
  padding-right: 0;
  padding-top: ${({ theme }) => theme.spacing(1)};
  padding-bottom: ${({ theme }) => theme.spacing(1)};

  &:hover {
    background-color: transparent;
  }

  &:hover ${StyledListItemIcon} {
    border-color: #00C853;
    box-shadow: 0px 3px 3px -2px rgba(0, 200, 83, 0.17), 0px 3px 4px rgba(93, 225, 12, 0.2), 0px 1px 8px rgba(0, 200, 83, 0.36);
  }
`;

const StyledListItemText = styled(ListItemText)`
  white-space: initial !important;
  text-align: center;
`;

export type SideBarItemProps = {
  to: string;
  title: ReactNode;
  icon: ReactNode;
  exact?: boolean;
  onSelect?: () => void;
};

export default function SideBarItem(props: SideBarItemProps) {
  const { to, title, icon, end, onSelect } = props;
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
    <StyledListItem button onClick={() => handleClick()}>
      <StyledListItemIcon selected={isSelected}>
        {cloneElement(icon, {
          color: isSelected ? 'primary' : 'inherit',
        })}
      </StyledListItemIcon>
      <StyledListItemText primary={title} />
    </StyledListItem>
  );
}

SideBarItem.defaultProps = {
  end: false,
  onSelect: undefined,
};
