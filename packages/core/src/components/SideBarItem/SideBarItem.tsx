import React, { type ReactNode } from 'react';
import { useNavigate, useMatch } from 'react-router-dom';
import { ListItem, ListItemIcon, ListItemText } from '@mui/material';
import { styled } from '@mui/system'; 
import useColorModeValue from '../../utils/useColorModeValue';
import { useTheme } from '@mui/styles';

const StyledListItemIcon = styled(ListItemIcon)`
  min-width: auto;
  background-color: ${({ theme, selected }) => selected 
    ? useColorModeValue(theme, 'sidebarBackground')
    : 'transparent'};
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
    border-color: #4CAF50;
    box-shadow: 0px -2px 4px rgba(104, 249, 127, 0.41), 0px 1px 8px rgba(145, 247, 53, 0.45);
  }
`;

const StyledListItemText = styled(ListItemText)`
  white-space: initial !important;
  text-align: center;
`;

export type SideBarItemProps = {
  to: string;
  title: ReactNode;
  icon: any;
  onSelect?: () => void;
  end?: boolean;
};

export default function SideBarItem(props: SideBarItemProps) {
  const { to, title, icon: Icon, end = false, onSelect } = props;
  const navigate = useNavigate();
  const match = useMatch({
    path: to,
    end,
  });
  const theme = useTheme();

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
        <Icon
          stroke={isSelected ? theme.palette.primary.main : theme.palette.text.primary}
          fill={isSelected ? theme.palette.primary.main : theme.palette.text.primary}
          fontSize="large"
        />
      </StyledListItemIcon>
      <StyledListItemText primary={title} />
    </StyledListItem>
  );
}
