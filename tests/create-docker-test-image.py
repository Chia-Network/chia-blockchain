import os
import os.path
import shutil
import subprocess
import traceback
from stat import *

PYTHON_VERSIONS=["3.8", "3.9"]

def pyver_string(v):
    return v.replace('.', '_')

def writePythonEnv(targetDir,target):
    flat_ver = pyver_string(target)
    name = "python%s" % flat_ver
    f = open(os.path.join(targetDir,'environment%s.yml' % flat_ver),'w')
    f.write('name: %s\ndependencies:\n - python=%s' % (name,target))
    f.close()

if __name__ == '__main__':
    try:
        shutil.rmtree('../docker-stage')
    except:
        pass

    try:
        shutil.rmtree('./docker-compose')
    except:
        pass

    have_test_cache = False
    try:
        mode = os.stat('test-cache').st_mode
        have_test_cache = S_ISDIR(mode)
    except:
        pass

    if not have_test_cache:
        subprocess.check_call(['git', 'clone', '--depth', '1', 'https://github.com/Chia-Network/test-cache'])

    os.makedirs('../docker-stage')
    os.makedirs('./docker-compose')
    shutil.copytree('..', '../docker-stage/app', ignore=shutil.ignore_patterns('.git', 'docker-stage'))
    shutil.copy('docker/Dockerfile', '../docker-stage/Dockerfile')
    shutil.copy('docker/create-container.sh', '../docker-stage/app/create-container.sh')
    for pv in PYTHON_VERSIONS:
        writePythonEnv('../docker-stage/app', pv)

    versions_env = " ".join(map(pyver_string, PYTHON_VERSIONS))
    cmd = ['sh','-c','cd ../docker-stage && docker build --build-arg PYTHON_VERSIONS="%s" -t chia-test .' % versions_env]
    subprocess.check_call(cmd)
    subprocess.check_call(['python3', 'build-workflows.py', '-t', './docker-templates', '-d', 'docker-compose'])
