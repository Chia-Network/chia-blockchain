import os
import subprocess
import sys

for filename in os.listdir('.\win_build'):
    subprocess.check_call([sys.executable, "-m", "pip", "install", f".\win_build\{filename}"])
