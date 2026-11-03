"""Colored CLI logging with stable stage markers used by the GUI."""
import sys

_G, _Y, _R, _N = "\033[0;32m", "\033[1;33m", "\033[0;31m", "\033[0m"
_C = sys.stderr.isatty()


def _c(code, s):
    return f"{code}{s}{_N}" if _C else s


def log(msg):
    print(_c(_G, "[*]"), msg, file=sys.stderr, flush=True)


def warn(msg):
    print(_c(_Y, "[!]"), msg, file=sys.stderr, flush=True)


def step(n, total, msg):
    print(_c(_G, f"[{n}/{total}]"), msg, file=sys.stderr, flush=True)


def stage(name):
    """Enter a stage. Keep this marker compatible with gui.py SUB_LINE."""
    print(f"[>] {name}", file=sys.stderr, flush=True)


class Die(SystemExit):
    """Exit with a nonzero status that both GUI and CLI can detect."""


def die(msg):
    print(_c(_R, "[ERROR]"), msg, file=sys.stderr, flush=True)
    raise Die(1)
