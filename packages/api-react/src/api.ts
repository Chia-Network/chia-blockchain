import { createApi } from '@reduxjs/toolkit/query/react';
import { Client } from '@chia/api';
import { chiaBaseQuery } from './chiaBaseQuery';

const client = new Client();

// initialize an empty api service that we'll inject endpoints into later as needed
export default createApi({
  baseQuery: chiaBaseQuery({
    client,
  }),
  endpoints: () => ({}),
});
