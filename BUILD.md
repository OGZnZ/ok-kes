# Build Guide

## Prerequisites

The build environment for this project is the conda `oknikke` environment (Python 3.12). Run the build commands with that environment's python and pip.

```bash
pip install -r requirements.txt
pip install pyinstaller
```

## Build Steps

### 1. Inline dependencies

Inline the ok-script and pyappify runtime libraries into the project:

```bash
python -m ok.update.inline_ok_requirements
```

### 2. Run the PyInstaller build

```bash
pyinstaller --onefile --noconsole --uac-admin --noupx --runtime-tmpdir "C:\Temp\MBG_Kes" --name "MBG-Kes-win32-portable-v1.3.1" --icon icons/icon.ico ^
  --add-data assets;assets ^
  --add-data i18n;i18n ^
  --add-data ok_tasks;ok_tasks ^
  --add-data "C:\Users\baoxin\miniconda3\envs\oknikke\Lib\site-packages\opencc\clib;opencc\clib" ^
  --add-data "C:\Users\baoxin\miniconda3\envs\oknikke\Lib\site-packages\opencc\clib\share\opencc;opencc\lib\share\opencc" ^
  --hidden-import ok_tasks.SortieMode ^
  --hidden-import ok_tasks.ChaosMode ^
  --hidden-import utils_sortie ^
  --hidden-import utils_chaos ^
  --hidden-import src.globals ^
  --hidden-import src.tasks.MyOneTimeTask ^
  --hidden-import onnxocr ^
  --hidden-import onnxocr_ppocrv5 ^
  --exclude-module PySide6.translations ^
  --collect-all onnxocr ^
  --collect-all onnxruntime ^
  --collect-all pyappify ^
  main.py
```

### 3. Clean up temporary files

```bash
rmdir /s /q build
del "MBG-Kes-win32-portable-v1.3.1.spec"
```

### 4. Build output

The output is at `dist\MBG-Kes-win32-portable-v1.3.1.exe`, about 265 MB.

## Key Notes

> **⚠️ Note**: `build_exe.bat` must be saved with **GBK/ANSI encoding** so CMD can parse Chinese file names correctly. With UTF-8 encoding, the packaged exe name shows up as garbled text.

| Flag | Purpose |
|---|---|
| `--onefile` | Single-file exe, ready to use after download |
| `--noconsole` | No console window |
| `--uac-admin` | Request administrator privileges |
| `--add-data ok_tasks;ok_tasks` | Bundle task files, located at runtime via `os.chdir(sys._MEIPASS)` |
| `--hidden-import src.globals` | Dynamically referenced globals module |
| `--collect-all onnxruntime` | Include the ONNX Runtime libraries and CPU execution provider |
| `--collect-all onnxocr` | Include OCR model files (.onnx) and code |
| `--runtime-tmpdir` | Use a pure-ASCII temp extraction path, avoiding OpenCC C library fopen failures under Chinese user names |
| `--add-data opencc\clib;opencc\clib` | Bundle the OpenCC dynamic libraries and dictionary files |
| `--add-data opencc\lib\share\opencc` | Extra mapping of the dictionary directory to the lib path, fixing C library `t2s.json` lookup failures under Chinese paths |
| `--exclude-module PySide6.translations` | Exclude PySide6 translation files (.qm), avoiding extraction CRC check failures on some systems |

## Required Code Changes

Make sure the following changes exist before building:

### `main.py`
```python
import sys
import os

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(sys._MEIPASS)  # Switch to the temp extraction dir so data files like ok_tasks can be found
        config["config_folder"] = os.path.join(exe_dir, "configs")  # Keep config files next to the exe so they are not wiped with the temp dir
```

### `ok/gui/MainWindow.py`
- Add `import sys` at the top

### `ok/gui/tasks/TaskManger.py`
Add an encoding fallback to the `find_and_instantiate_class` method, fixing `utf-8' codec can't decode byte` errors caused by GBK/ANSI-encoded files:
```python
def find_and_instantiate_class(self, file_path, base_class):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            tree = ast.parse(file.read(), filename=file_path)
    except UnicodeDecodeError:
        with open(file_path, 'r', encoding=sys.getfilesystemencoding()) as file:
            tree = ast.parse(file.read(), filename=file_path)
```
