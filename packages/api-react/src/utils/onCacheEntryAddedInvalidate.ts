import type { Service } from '@chia/api';

type Invalidate = {
  command: string;
  service: Service;
  endpoint: () => Object;
  skip?: (draft: any, data: any, args: any) => boolean;
} | {
  command: string;
  service: Service;
  onUpdate: (draft: any, data, args: any) => void;
  skip?: (draft: any, data: any, args: any) => boolean;
};

export default function onCacheEntryAddedInvalidate(rtkQuery, invalidates: Invalidate[]) {
  return async (args, api) => {
    const { cacheDataLoaded, cacheEntryRemoved, updateCachedData, dispatch } = api;
    const unsubscribes: Function[] = [];
    try {
      await cacheDataLoaded;

      await Promise.all(invalidates.map(async (invalidate) => {
        const { command, service, endpoint, onUpdate, skip } = invalidate;

        const response = await rtkQuery({
          command,
          service,
          args: [async (data) => {
            updateCachedData((draft) => {
              if (skip?.(draft, data, args)) {
                return;
              }

              if (onUpdate) {
                onUpdate(draft, data, args);
              }

              if (endpoint) {
                const currentEndpoint = endpoint();
                dispatch(currentEndpoint.initiate(args, {
                  subscribe: false,
                  forceRefetch: true,
                }));
              }
            });
          }],
        }, api, {});

        if (response.data) {
          unsubscribes.push(response.data);
        }
      }));
    } finally {
      await cacheEntryRemoved;
      unsubscribes.forEach((unsubscribe) => unsubscribe());
    }
  }
}
