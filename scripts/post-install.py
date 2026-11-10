#!/usr/bin/env python3
import os
import shutil
import subprocess
if not os.environ.get('DESTDIR'):
    prefix = os.environ['MESON_INSTALL_PREFIX']
    for command in (['gtk-update-icon-cache', '-q', '-t', '-f', prefix + '/share/icons/hicolor'], ['update-desktop-database', prefix + '/share/applications']):
        if shutil.which(command[0]):
            subprocess.run(command, check=False)
