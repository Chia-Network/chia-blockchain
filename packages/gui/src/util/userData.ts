import { app } from 'electron';
import { getConfigRootDir } from '../util/loadConfig';
import path from 'path';
import fs from 'fs';

export function getUserDataDir(): string {
  const chiaRootPath = getConfigRootDir();
  const appName = app.getName();
  const userDataDir = path.join(chiaRootPath, 'gui', appName);
  return userDataDir;
}

export function setUserDataDir(): void {
  const chiaRootUserDataPath = getUserDataDir();

  migrateUserDataIfNecessary();

  console.info(`Setting user data directory to ${chiaRootUserDataPath}`);
  app.setPath('userData', chiaRootUserDataPath);
}

export function migrateUserDataIfNecessary() {
  const defaultUserDataPath = app.getPath('userData');
  const chiaRootUserDataPath = getUserDataDir();
  const leveldbSrcPath = path.join(
    defaultUserDataPath,
    'Local Storage',
    'leveldb',
  );
  const leveldbDestPath = path.join(
    chiaRootUserDataPath,
    'Local Storage',
    'leveldb',
  );
  const leveldbMigratedMarker = path.join(leveldbSrcPath, 'migrated');
  const sourceExists = fs.existsSync(leveldbSrcPath);
  const destinationExists = fs.existsSync(leveldbDestPath);
  const migrationMarkerExists = fs.existsSync(leveldbMigratedMarker);
  const migrationNeeded =
    sourceExists && !destinationExists && !migrationMarkerExists;

  console.info(`Checking if userData migration is needed`);
  console.info(`${leveldbSrcPath} exists: ${sourceExists}`);
  console.info(`${leveldbDestPath} exists: ${destinationExists}`);
  console.info(`${leveldbMigratedMarker} exists: ${migrationMarkerExists}`);
  console.info(`Migration needed: ${migrationNeeded}`);

  if (migrationNeeded) {
    try {
      console.info(`Beginning migration of user data from ${leveldbSrcPath}`);
      createIntermediateDirectories(leveldbDestPath);
      shallowCopyDirectoryContents(leveldbSrcPath, leveldbDestPath);

      fs.writeFileSync(leveldbMigratedMarker, leveldbDestPath);

      console.info('Finished migrating user data');
    } catch (err) {
      console.error(err);
    }
  }
}

function createIntermediateDirectories(pathToCreate: string) {
  console.info(`Creating intermediate directories for ${pathToCreate}`);
  const pathParts: string[] = pathToCreate.split(path.sep);

  let currentPath = '';
  while (pathParts.length > 0) {
    let pathPart: string | undefined = pathParts.shift();

    if (pathPart === undefined) {
      continue;
    }

    if (pathPart === '') {
      pathPart = path.sep;
    }

    if (currentPath) {
      currentPath = path.join(currentPath, pathPart);
    } else {
      currentPath = pathPart;
    }

    if (!fs.existsSync(currentPath)) {
      fs.mkdirSync(currentPath);
    }
  }
}

function shallowCopyDirectoryContents(
  source: string,
  destination: string,
): void {
  if (!fs.existsSync(destination)) {
    fs.mkdirSync(destination);
  }
  console.info(`Copying contents of ${source} to ${destination}`);
  const files = fs.readdirSync(source);
  files.forEach((file) => {
    const sourcePath = path.join(source, file);
    const destinationPath = path.join(destination, file);
    console.info(`Copying ${sourcePath}`);
    fs.copyFileSync(sourcePath, destinationPath);
  });
}
