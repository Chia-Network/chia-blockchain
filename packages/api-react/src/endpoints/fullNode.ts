import type { EndpointBuilder } from '@reduxjs/toolkit';
import { ServiceName } from '@chia/api';

interface Block {}
interface BlockRecord {}
interface BlockHeader {}
interface BlockchainState {}
interface BlockchainConnection {}

export default (build: EndpointBuilder) => ({
  getBlockRecords: build.query<BlockRecord[], { 
    end: number; 
    count?: number;
  }>({
    query: ({ end, count }) => ({
      service: ServiceName.FULL_NODE,
      command: 'getBlockRecords',
      args: [end, count],
    }),
    // transformResponse: (response: PostResponse) => response.data.post,
  }),
  getUnfinishedBlockHeaders: build.query<BlockHeader[]>({
    query: () => ({
      service: ServiceName.FULL_NODE,
      command: 'getUnfinishedBlockHeaders',
    }),
    // transformResponse: (response: PostResponse) => response.data.post,
  }),
  getBlockchainState: build.query<BlockchainState>({
    query: () => ({
      service: ServiceName.FULL_NODE,
      command: 'getBlockchainState',
    }),
    // transformResponse: (response: PostResponse) => response.data.post,
  }),
  getFullNodeConnections: build.query<BlockchainConnection[]>({
    query: () => ({
      service: ServiceName.FULL_NODE,
      command: 'getConnections',
    }),
    // transformResponse: (response: PostResponse) => response.data.post,
  }),
  getBlock: build.query<Block, { 
    headerHash: string;
  }>({
    query: ({ headerHash }) => ({
      service: ServiceName.FULL_NODE,
      command: 'getBlock',
      args: [headerHash],
    }),
    // transformResponse: (response: PostResponse) => response.data.post,
  }),
  getBlockRecord: build.query<BlockRecord, { 
    headerHash: string;
  }>({
    query: ({ headerHash }) => ({
      service: ServiceName.FULL_NODE,
      command: 'getBlockRecord',
      args: [headerHash],
    }),
    // transformResponse: (response: PostResponse) => response.data.post,
  }),
  openFullNodeConnection: build.mutation<BlockchainConnection, { 
    host: string;
    port: number;
  }>({
    query: ({ host, port }) => ({
      service: ServiceName.FULL_NODE,
      command: 'openConnection',
      args: [host, port],
    }),
    invalidatesTags: ['FullNodeConnection'],
  }),
  closeFullNodeConnection: build.mutation<BlockchainConnection, { 
    nodeId: number;
  }>({
    query: ({ nodeId }) => ({
      service: ServiceName.FULL_NODE,
      command: 'closeConnection',
      args: [nodeId],
    }),
    invalidatesTags: ['FullNodeConnection'],
  }),
});
