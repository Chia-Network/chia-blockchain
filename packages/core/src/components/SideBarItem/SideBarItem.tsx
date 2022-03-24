import React, { ReactNode, cloneElement } from 'react';
import styled from 'styled-components';
import { useNavigate, useMatch } from 'react-router-dom';
import { ListItem, ListItemIcon, ListItemText } from '@material-ui/core';

const StyledListItemIcon = styled(ListItemIcon)`
  min-width: auto;
  background-color: white;
  border-radius: ${({ theme }) => theme.spacing(1.5)}px;
  width: ${({ theme }) => theme.spacing(6)}px;
  height: ${({ theme }) => theme.spacing(6)}px;
  border: ${({ selected }) => `1px solid ${selected ? '#00C853' : '#E0E0E0'}`};
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
  padding-top: ${({ theme }) => theme.spacing(1)}px;
  padding-bottom: ${({ theme }) => theme.spacing(1)}px;

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
