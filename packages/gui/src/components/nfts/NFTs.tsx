import React, { useMemo } from 'react';
import { randomBytes } from 'crypto';
import type { NFT } from '@chia/api';
import { Flex, toBech32m } from '@chia/core';
import { Routes, Route } from 'react-router-dom';
import {
  Box,
  Checkbox,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import NFTSelection from '../../types/NFTSelection';
import NFTContextualActions from './NFTContextualActions';
import NFTGallery from './gallery/NFTGallery';
import NFTDetail from './detail/NFTDetail';
/* ========================================================================== */

// Temporary: Used by getFakeNFTName
import seedrandom from 'seedrandom';
import {
  uniqueNamesGenerator,
  adjectives,
  colors,
  animals,
} from 'unique-names-generator';

/* ========================================================================== */

function NFTMockGalleryTableHeader() {
  const headers = [
    { id: 'id', label: 'ID' },
    { id: 'name', label: 'Name' },
    { id: 'description', label: 'Description' },
  ];

  return (
    <TableHead>
      <TableRow>
        <TableCell padding="checkbox">
          <Checkbox color="primary" disabled={true} />
        </TableCell>
        {headers.map((header) => (
          <TableCell key={header.id}>{header.label}</TableCell>
        ))}
      </TableRow>
    </TableHead>
  );
}

/* ========================================================================== */

function NFTMockGalleryView() {
  const [selected, setSelected] = React.useState<readonly string[]>([]);

  const rows: NFT[] = useMemo(() => {
    return [...Array(5)].map((_, i) => {
      const walletId = 5;
      const id = toBech32m(randomBytes(32).toString('hex'), 'nft');
      const name = getFakeNFTName(id);
      const description = `NFT ${i} description`;

      return { walletId, id, name, description };
    });
  }, []);

  const selection: NFTSelection = useMemo(() => {
    const idSet = new Set(selected);
    return {
      items: rows.filter((row) => idSet.has(row.id)),
    };
  }, [selected]);

  function isSelected(id: string) {
    return selected.indexOf(id) !== -1;
  }

  function handleClick(event: React.MouseEvent<unknown>, id: string) {
    const selectedIndex = selected.indexOf(id);
    let newSelected: readonly string[] = [];

    if (selectedIndex === -1) {
      newSelected = newSelected.concat(selected, id);
    } else if (selectedIndex === 0) {
      newSelected = newSelected.concat(selected.slice(1));
    } else if (selectedIndex === selected.length - 1) {
      newSelected = newSelected.concat(selected.slice(0, -1));
    } else if (selectedIndex > 0) {
      newSelected = newSelected.concat(
        selected.slice(0, selectedIndex),
        selected.slice(selectedIndex + 1),
      );
    }

    setSelected(newSelected);
  }

  return (
    <Flex flexDirection="column" flexGrow={1} gap={1}>
      <Flex flexDirection="row" flexGrow={1} justifyContent="flex-end">
        <Flex gap={1} alignItems="center">
          <NFTContextualActions selection={selection} />
        </Flex>
      </Flex>

      <Box sx={{ width: '100%' }}>
        <Paper sx={{ width: '100%', mb: 2 }}>
          <TableContainer>
            <Table sx={{ minWidth: 750 }} size={'medium'}>
              <NFTMockGalleryTableHeader />
              <TableBody>
                {rows.map((row, index) => {
                  const isItemSelected = isSelected(row.id);

                  return (
                    <TableRow
                      key={row.id}
                      onClick={(event) => handleClick(event, row.id)}
                    >
                      <TableCell padding="checkbox">
                        <Checkbox color="primary" checked={isItemSelected} />
                      </TableCell>
                      <TableCell>{row.id}</TableCell>
                      <TableCell>{row.name}</TableCell>
                      <TableCell>{row.description}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      </Box>
    </Flex>
  );
}

/* ========================================================================== */

export default function NFTs() {
  return (
    <Routes>
      <Route index element={<NFTGallery />} />
      <Route path=":nftId" element={<NFTDetail />} />
    </Routes>
  );

  return (
    <Box sx={{ width: '100%', paddingLeft: '1.5rem', paddingRight: '1.5rem' }}>
      <Flex
        flexDirection="column"
        flexGrow={1}
        gap={3}
        style={{ paddingTop: '1.5rem' }}
      >
        <Typography variant="h5">NFTs</Typography>
        <Flex>
          <NFTMockGalleryView />
        </Flex>
      </Flex>
    </Box>
  );
}

/* ========================================================================== */
/*                              Utility Functions                             */
/* ========================================================================== */

const uniqueNames: {
  [key: string]: string;
} = {};

function getFakeNFTName(seed: string, iteration = 0): string {
  const computedName = Object.keys(uniqueNames).find(
    (key) => uniqueNames[key] === seed,
  );
  if (computedName) {
    return computedName;
  }

  const generator = seedrandom(iteration ? `${seed}-${iteration}` : seed);

  const uniqueName = uniqueNamesGenerator({
    dictionaries: [colors, animals, adjectives],
    length: 2,
    seed: generator.int32(),
    separator: ' ',
    style: 'capital',
  });

  if (uniqueNames[uniqueName] && uniqueNames[uniqueName] !== seed) {
    return getFakeNFTName(seed, iteration + 1);
  }

  uniqueNames[uniqueName] = seed;

  return uniqueName;
}
