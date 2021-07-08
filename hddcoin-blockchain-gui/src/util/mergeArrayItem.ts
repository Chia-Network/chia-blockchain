export default function mergeArrayItem<T>(
  array: T[],
  identity: (item: T) => boolean,
  object: Partial<T>,
): T[] {
  return array?.map((item) => {
    if (identity(item)) {
      return {
        ...item,
        ...object,
      };
    }

    return item;
  });
}
