import { createApi } from '@reduxjs/toolkit/query/react';
import chiaLazyBaseQuery from './chiaLazyBaseQuery';

export const baseQuery = chiaLazyBaseQuery({});

export default createApi({
  reducerPath: 'chiaApi',
  baseQuery,
  endpoints: () => ({}),
});
