import api from './api';
import fullNodeEndpoints from '../endpoints/fullNode';

const walletApi = api.injectEndpoints({
  endpoints: fullNodeEndpoints,
  overrideExisting: false,
});

export const { 
  useExampleQuery
} = walletApi;