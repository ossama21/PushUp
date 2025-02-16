import PyInstaller.__main__
import os
from pathlib import Path

current_dir = Path(__file__).parent
assets_dir = current_dir / 'assets' / 'icons'

# Ensure assets directory exists
assets_dir.mkdir(parents=True, exist_ok=True)

# PyInstaller command arguments
args = [
    'pushup_reminder.py',
    '--name=PushupReminderPro',
    '--windowed',  # No console window
    '--onefile',   # Single executable
    f'--icon={assets_dir}/logo.ico',
    '--noconfirm',  # Overwrite existing
    '--clean',      # Clean cache
    f'--add-data={assets_dir};assets/icons/',  # Include assets
    '--hidden-import=PIL._tkinter_finder',
]

# Run PyInstaller
PyInstaller.__main__.run(args)