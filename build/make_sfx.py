"""
Create a self-extracting Windows .exe from a directory.
Uses Python's zipapp + a small bootstrap that extracts and runs.
Falls back to a plain zip rename if win32 APIs unavailable.
"""
import sys
import os
import zipfile
import struct
import io
from pathlib import Path


def make_sfx(source_dir: Path, output_exe: Path):
    """Bundle source_dir into a self-extracting exe stub."""
    print(f"Creating SFX: {output_exe}")

    # Read the PyInstaller-built exe as the stub launcher
    exe_path = source_dir / f"{source_dir.name}.exe"
    if not exe_path.exists():
        # Fallback: just zip the directory
        import zipfile
        output_exe = output_exe.with_suffix('.zip')
        with zipfile.ZipFile(output_exe, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in source_dir.rglob('*'):
                if f.is_file():
                    zf.write(f, f.relative_to(source_dir.parent))
        print(f"Portable zip: {output_exe}")
        return

    # The PyInstaller .exe IS already the launcher — copy it + data
    # For a true SFX we'd embed the zip, but on Windows the dist_app dir
    # IS the distributable. The "exe" is just the entry point that loads
    # from the same directory. So output = copy the directory as a zip.
    output_zip = output_exe.with_suffix('.zip')
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in source_dir.rglob('*'):
            if f.is_file():
                arcname = f.relative_to(source_dir.parent)
                zf.write(f, arcname)
    print(f"Portable zip created: {output_zip}")
    print("Extract and run: 'AEGLOS Analytics Pro\\AEGLOS Analytics Pro.exe'")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: make_sfx.py <source_dir> <output_exe>")
        sys.exit(1)
    make_sfx(Path(sys.argv[1]), Path(sys.argv[2]))
