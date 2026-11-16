# SPDX-License-Identifier: GPL-3.0-or-later
"""The times-os command (and python -m times_os): finds the runner's code and the data folder, and starts the runner."""
import os
import sys

from . import __version__


def tree():
    """-> the folder of the runner's code: the package's own copy (_tree), or the clone this package folder is in
    (pip install -e .: the clone's own code runs, as it is edited, and its state goes to the data folder, as for any
    installed package; `python TIMES.py` in the same clone keeps its state in the clone)."""
    here = os.path.dirname(os.path.abspath(__file__))
    own = os.path.join(here, "_tree")
    if os.path.isfile(os.path.join(own, "TIMES.py")):
        return own
    up = os.path.dirname(here)
    if os.path.isfile(os.path.join(up, "TIMES.py")):
        return up
    raise SystemExit(f"times-os: the runner (TIMES.py) is neither in {own} nor in {up}: reinstall the package "
                     "(pip install --force-reinstall times-os)")


def package_family():
    """Windows: the package family name when this Python runs as a packaged app (MSIX), else None."""
    try:
        import ctypes
        n = ctypes.c_uint32(0)
        k = ctypes.windll.kernel32
        if k.GetCurrentPackageFamilyName(ctypes.byref(n), None) != 122:   # ERROR_INSUFFICIENT_BUFFER: packaged
            return None
        buf = ctypes.create_unicode_buffer(n.value)
        return buf.value if k.GetCurrentPackageFamilyName(ctypes.byref(n), buf) == 0 else None
    except (AttributeError, OSError):
        return None


def data_folder():
    """Where the installed runner keeps what it makes: TIMES_DATA when set; else Windows %LOCALAPPDATA%\\times-os,
    macOS ~/Library/Application Support/times-os, Linux and the rest $XDG_DATA_HOME/times-os (~/.local/share/times-os)."""
    if os.environ.get("TIMES_DATA"):
        return os.path.abspath(os.path.expanduser(os.environ["TIMES_DATA"]))
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        family = package_family()
        if family:
            # a Python that Windows runs as a packaged app (the Microsoft Store's Python): its writes in AppData go to
            # the package's own folder, which other programs (Julia) do not see under AppData; that folder is named
            # here as it is, so that every program finds the same files
            base = os.path.join(base, "Packages", family, "LocalCache", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, "times-os")


MARKER = "times-os-data.txt"     # marks a data folder as times-os's own (TIMES.py's clean looks for the same name)
WRITES = ("setup", "check", "run", "verify")     # the commands that write in the data folder


def adopt(state):
    """-> True when `state` is times-os's data folder: marked, or new or empty and then marked now. False when it holds
    other things and no marker: it is not times-os's, and nothing is written in it."""
    mark = os.path.join(state, MARKER)
    if os.path.isfile(mark):
        return True
    if os.path.isdir(state) and os.listdir(state):
        return False
    os.makedirs(state, exist_ok=True)
    with open(mark, "w", encoding="utf-8") as f:
        f.write("The data folder of times-os (pip install times-os): its settings, its Julia environment and its setup. "
                "`times-os clean` removes it, and removes only a folder that has this file.\n")
    return True


def not_ours(state):
    """The message for a data folder that holds other things and no marker."""
    how = ("TIMES_DATA must name a new or empty folder, or one that times-os made" if os.environ.get("TIMES_DATA") else
           "remove it, or set TIMES_DATA to a new or empty folder")
    return (f"times-os: {state} is not empty and is not a data folder that times-os made (it has no {MARKER}), so "
            f"nothing was written in it: {how}.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    src = tree()
    prog = "python -m times_os" if os.path.basename(sys.argv[0]) in ("__main__.py", "-m") else "times-os"
    state = data_folder()
    if argv and argv[0] in WRITES and not adopt(state):
        print(not_ours(state), file=sys.stderr)
        return 2
    if os.path.isfile(os.path.join(state, MARKER)):
        # Python's compiled files of the runner's code go to the data folder too: the package folder may be read-only
        cache = os.path.join(state, "pycache")
        sys.pycache_prefix = cache
        os.environ["PYTHONPYCACHEPREFIX"] = cache
    else:           # no data folder of times-os (yet): --version, help, example and clean write none
        sys.dont_write_bytecode = True
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # the runner sees itself as TIMES.py (a checkout's runner starts itself again in its .venv by sys.argv)
    sys.argv = [os.path.join(src, "TIMES.py")] + list(argv)
    sys.path.insert(0, src)
    import TIMES
    TIMES.launched(prog, __version__, state)
    return TIMES.main(list(argv))


if __name__ == "__main__":
    sys.exit(main())
