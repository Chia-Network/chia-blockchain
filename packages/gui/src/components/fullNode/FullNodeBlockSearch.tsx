import React from 'react';
import { t } from '@lingui/macro';
import { Box, IconButton, Paper } from '@mui/material';
import { Search as SearchIcon } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import styled from 'styled-components';
import { Flex, Form, InputBase } from '@chia/core';
import { useForm } from 'react-hook-form';

const StyledInputBase = styled(InputBase)`
  min-width: 15rem;
`;

type FormData = {
  hash: string;
};

export default function FullNodeBlockSearch() {
  const navigate = useNavigate();
  const methods = useForm<FormData>({
    defaultValues: {
      hash: '',
    },
  });

  function handleSubmit(values: FormData) {
    const { hash } = values;
    if (hash) {
      navigate(`/dashboard/block/${hash}`);
    }
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Paper elevation={0} variant="outlined">
        <Flex alignItems="center" gap={1}>
          <Box />
          <StyledInputBase
            name="hash"
            placeholder={t`Search block by header hash`}
            fullWidth
          />
          <IconButton type="submit" aria-label="search">
            <SearchIcon />
          </IconButton>
        </Flex>
      </Paper>
    </Form>
  );
}
