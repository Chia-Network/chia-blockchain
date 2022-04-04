import useLocalStorage from './useLocalStorage';

export default function useSkipMigration(): [boolean, (skip: boolean) => void] {
  const [skip, setSkip] = useLocalStorage<boolean>('skipMigration', false);

  return [skip, setSkip];
}
