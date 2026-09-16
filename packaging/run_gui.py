"""PyInstaller entry-point script for ``ibackup-gui``.

PyInstaller's ``Analysis`` needs a real script to trace imports from; the
project instead exposes a ``project.gui-scripts`` entry point
(``iphone_archive.gui.application:application_main``) for normal installs.
This tiny shim just calls that same function so both paths run identical
code - the frozen build is never a second implementation to keep in sync.
"""

import sys

from iphone_archive.gui.application import application_main

if __name__ == "__main__":
    sys.exit(application_main())
