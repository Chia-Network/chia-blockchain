import React, { ReactNode, cloneElement } from 'react';
import styled from 'styled-components';
import { useNavigate, useMatch } from 'react-router-dom';
import { ListItem, ListItemIcon, ListItemText } from '@material-ui/core';

const StyledListItem = styled(ListItem)`
  display: flex;
  flex-direction: column;
  white-space: nowrap;
  align-items: center;
  padding-left: 0;
  padding-right: 0;
`;

const StyledListItemIcon = styled(ListItemIcon)`
  min-width: auto;
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
    <StyledListItem button selected={isSelected} onClick={() => handleClick()}>
      <StyledListItemIcon>
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
