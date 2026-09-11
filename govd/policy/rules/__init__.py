"""Rule registry.

Shared rules are listed explicitly below and ship with the repo. Personal rules are
gitignored `*.local.py` files in this directory: each is discovered and loaded at
startup, so you can run your own policies without editing this file or committing them.
A fresh clone has none, and loads only the shared set.

Add a personal rule by copying any shared rule to `<name>.local.py` (the relative
imports stay identical) and restarting the daemon.
"""
import importlib.util
import os
import sys
import traceback

from .base import Rule
from .no_narrative_comments import NoNarrativeComments
from .typecheck_lock import TypecheckLock
from .dangerous_bash import DangerousBash
from .protect_governor import ProtectGovernor

# Shared, committed rules. protect_governor stays first; the engine takes the most
# restrictive decision regardless of order, so order is for readability only.
SHARED_RULES = [ProtectGovernor, TypecheckLock, DangerousBash, NoNarrativeComments]

_HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL_SUFFIX = ".local.py"


def _local_rule_classes():
    """Rule subclasses defined in gitignored `*.local.py` modules in this package.

    Each file is loaded by path under a real dotted name inside this package, so its
    relative imports (`from ..engine`, `from .base`, `from ._shell`) resolve exactly as
    a shared rule's do. A file that fails to import is skipped with a warning rather
    than taking the whole daemon down — governance stays up on the shared rules.
    """
    out = []
    for fn in sorted(os.listdir(_HERE)):
        if not fn.endswith(_LOCAL_SUFFIX) or fn.startswith("."):
            continue
        modname = __name__ + "." + fn[:-3].replace(".", "_")
        try:
            spec = importlib.util.spec_from_file_location(modname, os.path.join(_HERE, fn))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
        except Exception:
            sys.stderr.write(f"govd: skipping personal rule {fn}:\n{traceback.format_exc()}")
            continue
        for val in vars(mod).values():
            if (isinstance(val, type) and issubclass(val, Rule) and val is not Rule
                    and val.__module__ == modname and getattr(val, "name", "rule") != "rule"):
                out.append(val)
    return out


def default_rules():
    return [cls() for cls in SHARED_RULES] + [cls() for cls in _local_rule_classes()]
