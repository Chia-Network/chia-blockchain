const createDMG = require('electron-installer-dmg');

// Return positioning params for the DMG contents. x,y coordinates represent the
// item's center point.
function getContents(opts) {
    return [
        {
            x: 466,
            y: 344,
            type: 'link',
            path: '/Applications',
        },
        {
            x: 192,
            y: 344,
            type: 'file',
            path: opts.appPath,
        }
    ]
}

async function main(opts) {
    console.log(`DMG creation options: ${JSON.stringify(opts, null, 2)}`);

    const { appPath, appName, dmgIcon, dmgBackground, outputDir, appVersion } = opts;
    const dmgName = appName + (appVersion ? `-${appVersion}` : '');
    const dmgTitle = dmgName;

    console.log(`DMG name set to: ${dmgName}`);
    console.log(`DMG title set to: ${dmgTitle}`);

    console.log('Creating DMG...');
    await createDMG({
        appPath: appPath,
        name: dmgName,
        title: dmgTitle,
        icon: dmgIcon,
        background: dmgBackground,
        contents: getContents,
        overwrite: true,
        out: outputDir,
    });

    console.log('Finished');
}

const appName = 'Chia';
const dmgIcon = '../chia-blockchain-gui/packages/gui/src/assets/img/Chia.icns';
const dmgBackground = './assets/dmg/background.tiff';
const outputDir = './final_installer';
const appPath = process.argv[2]; // required
const appVersion = process.argv[3]; // undefined is ok

if (!appPath) {
    console.error('appPath is required');
    process.exit(1);
}

main({
    appPath,
    appName,
    dmgIcon,
    dmgBackground,
    outputDir,
    appVersion,
});
