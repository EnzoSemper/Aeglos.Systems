# PyInstaller runtime hook — runs before launcher.py
# Poisons tkinter/tcl/tk so any import raises ImportError instead of panicking
import sys

_blocked = ["tkinter", "_tkinter", "tk", "tcl",
            "Tkinter", "_tkinter_fix", "tkColorChooser",
            "tkCommonDialog", "tkFileDialog", "tkFont",
            "tkMessageBox", "tkSimpleDialog"]

class _Blocker:
    def find_module(self, name, path=None):
        if any(name == b or name.startswith(b + ".") for b in _blocked):
            return self
    def load_module(self, name):
        raise ImportError(f"tkinter is disabled in this build ({name})")

sys.meta_path.insert(0, _Blocker())
for name in list(sys.modules):
    if any(name == b or name.startswith(b + ".") for b in _blocked):
        del sys.modules[name]
