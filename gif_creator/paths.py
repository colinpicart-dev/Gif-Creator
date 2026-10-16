import os
import subprocess


def downloads_dir():
    try:
        result = subprocess.run(
            ["xdg-user-dir", "DOWNLOAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        folder = result.stdout.strip()
        if folder and os.path.isdir(folder):
            return folder
    except (OSError, subprocess.CalledProcessError):
        pass
    home = os.path.expanduser("~")
    for name in ("Téléchargements", "Downloads"):
        folder = os.path.join(home, name)
        if os.path.isdir(folder):
            return folder
    return home
