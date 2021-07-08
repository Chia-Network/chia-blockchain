import { app, dialog, shell, ipcMain, BrowserWindow, Menu } from 'electron';
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
import hddcoinEnvironment from '../util/hddcoinEnvironment';
import hddcoinConfig from '../util/config';
import { i18n } from '../config/locales';
import About from '../components/about/About';
import packageJson from '../../package.json';

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

  aboutWindow.webContents.on('will-navigate', (e, url) => {
    e.preventDefault();
    shell.openExternal(url);
  });
  aboutWindow.webContents.on('new-window', (e, url) => {
    e.preventDefault();
    shell.openExternal(url);
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
    if (!hddcoinEnvironment.guessPackaged() && !('VIRTUAL_ENV' in process.env)) {
      console.log('App must be installed or in venv');
      app.quit();
      return false;
    }

    return true;
  };

  let mainWindow = null;

  // if any of these checks return false, don't do any other initialization since the app is quitting
  if (ensureSingleInstance() && ensureCorrectEnvironment()) {
    // this needs to happen early in startup so all processes share the same global config
    hddcoinConfig.loadConfig('mainnet');
    global.sharedObj = { local_test };

    const exitPyProc = (e) => {};

    app.on('will-quit', exitPyProc);

    /** ***********************************************************
     * window management
     ************************************************************ */
    let decidedToClose = false;
    let isClosing = false;

    const createWindow = () => {
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
          enableRemoteModule: true,
        },
      });

      if (dev_config.redux_tool) {
        BrowserWindow.addDevToolsExtension(
          path.join(os.homedir(), dev_config.redux_tool),
        );
      }

      if (dev_config.react_tool) {
        BrowserWindow.addDevToolsExtension(
          path.join(os.homedir(), dev_config.react_tool),
        );
      }

      const startUrl =
        process.env.NODE_ENV === 'development'
          ? 'http://localhost:3000'
          : url.format({
              pathname: path.join(__dirname, '/../renderer/index.html'),
              protocol: 'file:',
              slashes: true,
            });

      console.log('startUrl', startUrl);

      mainWindow.loadURL(startUrl);

      mainWindow.once('ready-to-show', () => {
        mainWindow.show();
      });

      // don't show remote daeomn detials in the title bar
      if (!hddcoinConfig.manageDaemonLifetime()) {
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
        if (decidedToClose || !hddcoinConfig.manageDaemonLifetime()) {
          return;
        }
        e.preventDefault();
        if (!isClosing) {
          isClosing = true;
          const choice = dialog.showMessageBoxSync({
            type: 'question',
            buttons: [
              i18n._(/* i18n */ { id: 'No' }),
              i18n._(/* i18n */ { id: 'Yes' }),
            ],
            title: i18n._(/* i18n */ { id: 'Confirm' }),
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
          mainWindow.setBounds({ height: 500, width: 500 });
          ipcMain.on('daemon-exited', (event, args) => {
            mainWindow.close();

            openedWindows.forEach((win) => win.close());
          });
        }
      });
    };

    const createMenu = () => Menu.buildFromTemplate(getMenuTemplate());

    const appReady = async () => {
      createWindow();
      app.applicationMenu = createMenu();
      // if the daemon isn't local we aren't going to try to start/stop it
      if (hddcoinConfig.manageDaemonLifetime()) {
        hddcoinEnvironment.startHDDcoinDaemon();
      }
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

    ipcMain.on('set-locale', (_, locale = 'en-US') => {
      i18n.activate(locale);
      app.applicationMenu = createMenu();
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
            label: i18n._(/* i18n */ { id: 'HDDcoin Blockchain Wiki' }),
            click: () => {
              openExternal(
                'https://github.com/HDDcoin-Network/hddcoin-blockchain/wiki',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Frequently Asked Questions' }),
            click: () => {
              openExternal(
                'https://github.com/HDDcoin-Network/hddcoin-blockchain/wiki/FAQ',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Release Notes' }),
            click: () => {
              openExternal(
                'https://github.com/HDDcoin-Network/hddcoin-blockchain/releases',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Contribute on GitHub' }),
            click: () => {
              openExternal(
                'https://github.com/HDDcoin-Network/hddcoin-blockchain/blob/master/CONTRIBUTING.md',
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
                'https://github.com/HDDcoin-Network/hddcoin-blockchain/issues',
              );
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Chat on KeyBase' }),
            click: () => {
              openExternal('https://keybase.io/team/hddcoin_network.public');
            },
          },
          {
            label: i18n._(/* i18n */ { id: 'Follow on Twitter' }),
            click: () => {
              openExternal('https://twitter.com/hddcoin_project');
            },
          },
        ],
      },
    ];

    if (process.platform === 'darwin') {
      // HDDcoin Blockchain menu (Mac)
      template.unshift({
        label: i18n._(/* i18n */ { id: 'HDDcoin' }),
        submenu: [
          {
            label: i18n._(/* i18n */ { id: 'About HDDcoin Blockchain' }),
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
          label: i18n._(/* i18n */ { id: 'About HDDcoin Blockchain' }),
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
