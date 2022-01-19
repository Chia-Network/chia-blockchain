const path = require('path');
const child_process = require('child_process');
const fs = require('fs');

/*************************************************************
 * py process
 *************************************************************/

const PY_MAC_DIST_FOLDER = '../../../app.asar.unpacked/daemon';
const PY_WIN_DIST_FOLDER = '../../../app.asar.unpacked/daemon';
const PY_DIST_FILE = 'daemon';
const PY_FOLDER = '../../../chia/daemon';
const PY_MODULE = 'server'; // without .py suffix

let pyProc = null;
let have_cert = null;

const guessPackaged = () => {
  let packed;
  if (process.platform === 'win32') {
    const fullPath = path.join(__dirname, PY_WIN_DIST_FOLDER);
    packed = fs.existsSync(fullPath);
    return packed;
  }
  const fullPath = path.join(__dirname, PY_MAC_DIST_FOLDER);
  packed = fs.existsSync(fullPath);
  return packed;
};

const getScriptPath = (dist_file) => {
  if (!guessPackaged()) {
    return path.join(PY_FOLDER, PY_MODULE + '.py');
  }
  return getExecutablePath(dist_file);
};

const getExecutablePath = (dist_file) => {
  if (process.platform === 'win32') {
    return path.join(__dirname, PY_WIN_DIST_FOLDER, dist_file + '.exe');
  }
  return path.join(__dirname, PY_MAC_DIST_FOLDER, dist_file);
};

const getChiaVersion = () => {
  let version = null;
  const exePath = getExecutablePath('chia');
  // first see if we can get a chia exe in a standard location relative to where we are
  try {
    version = child_process
      .execFileSync(exePath, ['version'], {
        encoding: 'UTF-8',
      })
      .trim();
  } catch (e1) {
    // that didn't work, let's try as if we're in the venv or chia is on the path
    try {
      version = child_process
        .execFileSync(path.basename(exePath), ['version'], {
          encoding: 'UTF-8',
        })
        .trim();
    } catch (e2) {
      // that didn't work either - give up
    }
  }

  return version;
};

const startChiaDaemon = () => {
  let script = getScriptPath(PY_DIST_FILE);
  let processOptions = {};
  //processOptions.detached = true;
  //processOptions.stdio = "ignore";
  pyProc = null;
  if (guessPackaged()) {
    try {
      console.log('Running python executable: ');
      const Process = child_process.spawn;
      pyProc = new Process(script, ["--wait-for-unlock"], processOptions);
    } catch (e) {
      console.log('Running python executable: Error: ');
      console.log('Script ' + script);
    }
  } else {
    console.log('Running python script');
    console.log('Script ' + script);

    const Process = child_process.spawn;
    pyProc = new Process('python', [script, "--wait-for-unlock"], processOptions);
  }
  if (pyProc != null) {
    pyProc.stdout.setEncoding('utf8');

    pyProc.stdout.on('data', function (data) {
      if (!have_cert) {
        process.stdout.write('No cert\n');
        // listen for ssl path message
        try {
          let str_arr = data.toString().split('\n');
          for (var i = 0; i < str_arr.length; i++) {
            let str = str_arr[i];
            try {
              let json = JSON.parse(str);
              global.cert_path = json['cert'];
              global.key_path = json['key'];
              if (cert_path && key_path) {
                have_cert = true;
                process.stdout.write('Have cert\n');
                return;
              }
            } catch (e) {}
          }
        } catch (e) {}
      }

      process.stdout.write(data.toString());
    });

    pyProc.stderr.setEncoding('utf8');
    pyProc.stderr.on('data', function (data) {
      //Here is where the error output goes
      process.stdout.write('stderr: ' + data.toString());
    });

    pyProc.on('close', function (code) {
      //Here you can get the exit code of the script
      console.log('closing code: ' + code);
    });

    console.log('child process success');
  }
  //pyProc.unref();
};

module.exports = {
  startChiaDaemon,
  getChiaVersion,
  guessPackaged,
};
