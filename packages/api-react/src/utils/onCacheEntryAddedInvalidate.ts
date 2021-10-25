type Invalidate = {
  command: string;
  endpoint: () => Object;
  skip?: (data: any, args: any) => boolean;
} | {
  command: string;
  onUpdate: (draft, data) => void;
  skip?: (data: any, args: any) => boolean;
};

export default function onCacheEntryAddedInvalidate(rtkQuery, invalidates: Invalidate[]) {
  return async (args, api) => {
    const { cacheDataLoaded, cacheEntryRemoved, updateCachedData, dispatch } = api;
    const unsubscribes: Function[] = [];
    try {
      await cacheDataLoaded;

      await Promise.all(invalidates.map(async(invalidate) => {
        const { command, endpoint, onUpdate, skip } = invalidate;

        const response = await rtkQuery({
          command: command,
          args: [(data) => {
            if (skip && !skip(data, args)) {
              return;
            }

            if (onUpdate) {
              updateCachedData((draft) => {
                onUpdate(draft, data, args);
              });
            }

            if (endpoint) {
              const currentEndpoint = endpoint();
              dispatch(currentEndpoint.initiate(args, { 
                subscribe: false,
                forceRefetch: true,
              }));
            }
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
