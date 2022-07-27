import React from 'react';
import { InputBase } from '@mui/material';
import styled from 'styled-components';
import SearchIcon from '@mui/icons-material/Search';

const SearchBase = styled('div')(({ theme }) => ({
  position: 'relative',
  borderRadius: theme.shape.borderRadius,
  backgroundColor: theme.palette.action.selected,
  '&:hover': {
    backgroundColor: theme.palette.action.hover,
  },
  paddingLeft: theme.spacing(1),
  paddingRight: theme.spacing(1),
}));

const SearchIconWrapper = styled('div')(({ theme }) => ({
  padding: theme.spacing(0, 0),
  height: '100%',
  position: 'absolute',
  pointerEvents: 'none',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}));

const StyledInputBase = styled(InputBase)(({ theme }) => ({
  color: 'inherit',
  width: '100%',
  '& .MuiInputBase-input': {
    padding: theme.spacing(1, 1, 1, 0),
    paddingLeft: `calc(1em + ${theme.spacing(2)})`,
    transition: theme.transitions.create('width'),
    width: '100%',
  },
}));

export type SearchProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
};

export default function Search(props: SearchProps) {
  const { value, onChange, placeholder } = props;

  return (
    <SearchBase>
      <SearchIconWrapper>
        <SearchIcon />
      </SearchIconWrapper>
      <StyledInputBase
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </SearchBase>
  );
}
