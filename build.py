import os
import subprocess

VERSION_MAJOR = 0
if os.path.exists("dist"):
    VERSION_MINOR = len(os.listdir("dist")) + 1
else:
    VERSION_MINOR = 0

version_string = f"v{VERSION_MAJOR}.{VERSION_MINOR}"
app_name = f"Termdle_{version_string}"

print(f"Launching build for {app_name}...")

pyinstaller_path = os.path.join(".venv", "Scripts", "pyinstaller.exe")

command = [
    pyinstaller_path,
    "--onefile",
    "--icon=termdle.ico",
    f"--name={app_name}",
    "--add-data=valid_wordle_words.txt;.",
    "main.py"
]

try:
    subprocess.run(command, check=True)
    print(f"\n✅ Build success: '{app_name}.exe'")
except subprocess.CalledProcessError as e:
    print(f"\n❌ Error: Return code {e.returncode}")
except FileNotFoundError:
    print("\n❌ PyInstaller not found!")
