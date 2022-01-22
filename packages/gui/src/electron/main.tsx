import { app, dialog, net, shell, ipcMain, BrowserWindow, IncomingMessage, Menu, session } from 'electron';
require('@electron/remote/main').initialize()
import path from 'path';
import React from 'react';
import url from 'url';
import os from 'os';
import ReactDOMServer from 'react-dom/server';
import { ServerStyleSheet, StyleSheetManager } from 'styled-components';
// handle setupevents as quickly as possible
import '../config/env';
import handleSquirrelEvent from './handleSquirrelEvent';
import config from '../config/config';
import dev_config from '../dev_config';
import chiaEnvironment from '../util/chiaEnvironment';
import chiaConfig from '../util/config';
import { i18n } from '../config/locales';
import About from '../components/about/About';
import packageJson from '../../package.json';

let isSimulator = process.env.LOCAL_TEST === 'true';

function renderAbout(): string {
  const sheet = new ServerStyleSheet();
  const about = ReactDOMServer.renderToStaticMarkup(
    <StyleSheetManager sheet={sheet.instance}>
      <About
        packageJson={packageJson}
        versions={process.versions}
        version={app.getVersion()}
      />
    </StyleSheetManager>,
  );

  const tags = sheet.getStyleTags();
  const result = about.replace('{{CSS}}', tags); // .replaceAll('/*!sc*/', ' ');

  sheet.seal();

  return result;
}

const openedWindows = new Set<BrowserWindow>();

function openAbout() {
  const about = renderAbout();

  const aboutWindow = new BrowserWindow({
    width: 400,
    height: 460,
    useContentSize: true,
    titleBarStyle: 'hiddenInset',
  });
  aboutWindow.loadURL(`data:text/html;charset=utf-8,${about}`);

  aboutWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url);
    return { action: 'deny' }
  });

  aboutWindow.once('closed', () => {
    openedWindows.delete(aboutWindow);
  });

  aboutWindow.setMenu(null);

  openedWindows.add(aboutWindow);

  // aboutWindow.webContents.openDevTools({ mode: 'detach' });
}

const { local_test } = config;

if (!handleSquirrelEvent()) {
  // squirrel event handled and app will exit in 1000ms, so don't do anything else
  const ensureSingleInstance = () => {
    const gotTheLock = app.requestSingleInstanceLock();

    if (!gotTheLock) {
      console.log('Second instance. Quitting.');
      app.quit();
      return false;
    }
    app.on('second-instance', (event, commandLine, workingDirectory) => {
      // Someone tried to run a second instance, we should focus our window.
      if (mainWindow) {
        if (mainWindow.isMinimized()) {
          mainWindow.restore();
        }
        mainWindow.focus();
      }
    });

    return true;
  };

  const ensureCorrectEnvironment = () => {
    // check that the app is either packaged or running in the python venv
    if (!chiaEnvironment.guessPackaged() && !('VIRTUAL_ENV' in process.env)) {
      console.log('App must be installed or in venv');
      app.quit();
      return false;
    }

    return true;
  };

  let mainWindow = null;

  const createMenu = () => Menu.buildFromTemplate(getMenuTemplate());

  function toggleSimulatorMode() {
    isSimulator = !isSimulator;

    if (mainWindow) {
      mainWindow.webContents.send('simulator-mode', isSimulator);
    }

    if (app) {
      app.applicationMenu = createMenu();
    }
  }

  // if any of these checks return false, don't do any other initialization since the app is quitting
  if (ensureSingleInstance() && ensureCorrectEnvironment()) {
    // this needs to happen early in startup so all processes share the same global config
    global.sharedObj = { local_test };

    const exitPyProc = (e) => {};

    app.on('will-quit', exitPyProc);

    /** ***********************************************************
     * window management
     ************************************************************ */
    let decidedToClose = false;
    let isClosing = false;

    const createWindow = async () => {
      if (chiaConfig.manageDaemonLifetime()) {
        chiaEnvironment.startChiaDaemon();
      }

      ipcMain.handle('getConfig', () => chiaConfig.loadConfig('mainnet'));

      ipcMain.handle('getTempDir', () => app.getPath('temp'));

      ipcMain.handle('getVersion', () => app.getVersion());

      ipcMain.handle('fetchTextResponse', async (_event, requestOptions, requestHeaders, requestData) => {
        const request = net.request(requestOptions as any);

        Object.entries(requestHeaders || {}).forEach(([header, value]) => {
          request.setHeader(header, value as any);
        });

        let err: any | undefined = undefined;
        let statusCode: number | undefined = undefined;
        let statusMessage: string | undefined = undefined;
        let responseBody: string | undefined = undefined;

        try {
          responseBody = await new Promise((resolve, reject) => {
            request.on('response', (response: IncomingMessage) => {
              statusCode = response.statusCode;
              statusMessage = response.statusMessage;

              response.on('data', (chunk) => {
                const body = chunk.toString('utf8');

                resolve(body);
              });

              response.on('error', (e: string) => {
                reject(new Error(e));
              });
            });

            request.on('error', (error: any) => {
              reject(error);
            })

            request.write(requestData);
            request.end();
          });
        }
        catch (e) {
          console.error(e);
          err = e;
        }

        return { err, statusCode, statusMessage, responseBody };
      });

      ipcMain.handle('showMessageBox', async (_event, options) => {
        return await dialog.showMessageBox(mainWindow, options);
      });

      ipcMain.handle('showOpenDialog', async (_event, options) => {
        return await dialog.showOpenDialog(options);
      });

      ipcMain.handle('showSaveDialog', async (_event, options) => {
        return await dialog.showSaveDialog(options);
      });

      decidedToClose = false;
      mainWindow = new BrowserWindow({
        width: 1200,
        height: 1200,
        minWidth: 500,
        minHeight: 500,
        backgroundColor: '#ffffff',
        show: false,
        webPreferences: {
          preload: `${__dirname}/preload.js`,
          nodeIntegration: true,
          contextIsolation: false,
          nativeWindowOpen: true
        },
      });

      if (dev_config.redux_tool) {
        const reduxDevToolsPath = path.join(os.homedir(), dev_config.react_tool)
        await app.whenReady();
        await session.defaultSession.loadExtension(reduxDevToolsPath)
      }

      if (dev_config.react_tool) {
        const reactDevToolsPath = path.join(os.homedir(), dev_config.redux_tool);
        await app.whenReady();
        await session.defaultSession.loadExtension(reactDevToolsPath)
      }

      mainWindow.once('ready-to-show', () => {
        mainWindow.show();
      });

      // don't show remote daeomn detials in the title bar
      if (!chiaConfig.manageDaemonLifetime()) {
        mainWindow.webContents.on('did-finish-load', () => {
          mainWindow.setTitle(`${app.getName()} [${global.daemon_rpc_ws}]`);
        });
      }
      // Uncomment this to open devtools by default
      // if (!guessPackaged()) {
      //   mainWindow.webContents.openDevTools();
      // }
      mainWindow.on('close', (e) => {
        // if the daemon isn't local we aren't going to try to start/stop it
        if (decidedToClose || !chiaConfig.manageDaemonLifetime()) {
          return;
        }
        e.preventDefault();
        if (!isClosing) {
          isClosing = true;
          const choice = dialog.showMessageBoxSync({
            type: 'question',
            buttons: [
              i18n._(/* i18n */ {id: 'No'}),
              i18n._(/* i18n */ {id: 'Yes'}),
            ],
            title: i18n._(/* i18n */ {id: 'Confirm'}),
            message: i18n._(
              /* i18n */ {
                id: 'Are you sure you want to quit? GUI Plotting and farming will stop.',
              },
            ),
          });
          if (choice == 0) {
            isClosing = false;
            return;
          }
          isClosing = false;
          decidedToClose = true;
          mainWindow.webContents.send('exit-daemon');
          mainWindow.setBounds({height: 500, width: 500});
          mainWindow.center();
          ipcMain.on('daemon-exited', (event, args) => {
            mainWindow.close();

            openedWindows.forEach((win) => win.close());
          });
        }
      });



      const startUrl =
      process.env.NODE_ENV === 'development'
        ? 'http://localhost:3000'
        : url.format({
          pathname: path.join(__dirname, '/../renderer/index.html'),
          protocol: 'file:',
          slashes: true,
        });

      mainWindow.loadURL(startUrl);
      require("@electron/remote/main").enable(mainWindow.webContents)

    };

    const appReady = async () => {
      createWindow();
      app.applicationMenu = createMenu();
    };

    app.on('ready', appReady);

    app.on('window-all-closed', () => {
      app.quit();
    });

    ipcMain.on('load-page', (_, arg: { file: string; query: string }) => {
      mainWindow.loadURL(
        require('url').format({
          pathname: path.join(__dirname, arg.file),
          protocol: 'file:',
          slashes: true,
        }) + arg.query,
      );
    });

    ipcMain.handle('setLocale', (_event, locale: string) => {
      i18n.activate(locale);
      app.applicationMenu = createMenu();
    });

    ipcMain.on('isSimulator', (event) => {
      console.log('isSimulator', isSimulator);
      event.returnValue = isSimulator;
    });
  }

  const getMenuTemplate = () => {
    const template = [
      {
        label: i18n._(/* i18n */ { id: 'File' }),
        submenu: [
          {
            role: 'quit',
          },
        ],
      },
      {
        label: i18n._(/* i18n */ { id: 'Edit' }),
        submenu: [
          {
            role: 'undo',
          },
          {
            role: 'redo',
          },
          {
            type: 'separator',
          },
          {
            role: 'cut',
          },
          {
            role: 'copy',
          },
          {
            role: 'paste',
          },
          {
            role: 'delete',
          },
          {
            type: 'separator',
          },
          {
            role: 'selectall',
          },
        ],
      },
      {
        label: i18n._(/* i18n */ { id: 'View' }),
        submenu: [
          {
            role: 'reload',
          },
          {
            role: 'forcereload',
          },
          {
            label: i18n._(/* i18n */ { id: 'Developer' }),
            submenu: [
              {
                label: i18n._(/* i18n */ { id: 'Developer Tools' }),
                accelerator:
                  process.platform === 'darwin'
                    ? 'Alt+Command+I'
                    : 'Ctrl+Shift+I',
                click: () => mainWindow.toggleDevTools(),
              },
              {
                label: isSimulator 
                  ? i18n._(/* i18n */ { id: 'Disable Simulator' })
                  : i18n._(/* i18n */ { id: 'Enable Simulator' }),
                click: () => toggleSimulatorMode(),
              },
            ],
          },
          {
            type: 'separator',
          },
          {
            role: 'resetzoom',
          },
          {
            role: 'zoomin',
          },
          {
            role: 'zoomout',
          },
          {
            type: 'separator',
          },
          {
            label: i18n._(/* i18n */ { id: 'Full Screen' }),
            accelerator:
              process.platform === 'darwin' ? 'Ctrl+Command+F' : 'F11',
            click: () => mainWindow.setFullScreen(!mainWindow.isFullScreen()),
          },
        ],
      },
      {
        label: i18n._(/* i18n */ { id: 'Window' }),
        submenu: [
          {
            role: 'minimize',
          },
          {
            role: 'zoom',
          },
          {
            role: 'close',
          },
        ],
      },
      {
        label: i18n._(/* i18n */ { id: 'Help' }),
        role: 'help',
        submenu: [
          {
            label: i18n._(/* i18n */ { id: 'Chia Blockchain Wiki' }),
            click: () => {
              openExternal(
                'https://github.com/Chia-Network/chia-blockchain/wiki',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Frequently Asked Questions' }),
            click: () => {
              openExternal(
                'https://github.com/Chia-Network/chia-blockchain/wiki/FAQ',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Release Notes' }),
            click: () => {
              openExternal(
                'https://github.com/Chia-Network/chia-blockchain/releases',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Contribute on GitHub' }),
            click: () => {
              openExternal(
                'https://github.com/Chia-Network/chia-blockchain/blob/master/CONTRIBUTING.md',
              );
            },
          },
          {
            type: 'separator',
          },
          {
            label: i18n._(/* i18n */ { id: 'Report an Issue...' }),
            click: () => {
              openExternal(
                'https://github.com/Chia-Network/chia-blockchain/issues',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Chat on KeyBase' }),
            click: () => {
              openExternal('https://keybase.io/team/chia_network.public');
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Follow on Twitter' }),
            click: () => {
              openExternal('https://twitter.com/chia_project');
            },
          },
        ],
      },
    ];

    if (process.platform === 'darwin') {
      // Chia Blockchain menu (Mac)
      template.unshift({
        label: i18n._(/* i18n */ { id: 'Chia' }),
        submenu: [
          {
            label: i18n._(/* i18n */ { id: 'About Chia Blockchain' }),
            click: () => {
              openAbout();
            },
          },
          {
            type: 'separator',
          },
          {
            role: 'services',
          },
          {
            type: 'separator',
          },
          {
            role: 'hide',
          },
          {
            role: 'hideothers',
          },
          {
            role: 'unhide',
          },
          {
            type: 'separator',
          },
          {
            role: 'quit',
          },
        ],
      });

      // File menu (MacOS)
      template.splice(1, 1, {
        label: i18n._(/* i18n */ { id: 'File' }),
        submenu: [
          {
            role: 'close',
          },
        ],
      });

      // Edit menu (MacOS)
      template[2].submenu.push(
        {
          type: 'separator',
        },
        {
          label: i18n._(/* i18n */ { id: 'Speech' }),
          submenu: [
            {
              role: 'startspeaking',
            },
            {
              role: 'stopspeaking',
            },
          ],
        },
      );

      // Window menu (MacOS)
      template.splice(4, 1, {
        role: 'window',
        submenu: [
          {
            role: 'minimize',
          },
          {
            role: 'zoom',
          },
          {
            type: 'separator',
          },
          {
            role: 'front',
          },
        ],
      });
    }

    if (process.platform === 'linux' || process.platform === 'win32') {
      // Help menu (Windows, Linux)
      template[4].submenu.push(
        {
          type: 'separator',
        },
        {
          label: i18n._(/* i18n */ { id: 'About Chia Blockchain' }),
          click() {
            openAbout();
          },
        },
      );
    }

    return template;
  };

  /**
   * Open the given external protocol URL in the desktop’s default manner.
   */
  const openExternal = (url) => {
    // console.log(`openExternal: ${url}`)
    shell.openExternal(url);
  };
}
