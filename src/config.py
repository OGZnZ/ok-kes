import json
import os
import platform
import sys

import numpy as np
from ok import ConfigOption

version = "dev"
# Do not modify version; the GitHub Action updates it automatically when packaging

OCR_BACKEND_AUTO = "Auto"
OCR_BACKEND_ONNX = "ONNX Runtime"
OCR_BACKEND_OPENVINO = "OpenVINO"


def _get_config_folder():
    """Return the config directory actually used for this launch."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "configs")
    return os.path.join(os.getcwd(), "configs")


def _read_ocr_backend():
    """OCR is created before GUI init, so read the global config file early."""
    config_names = ["OCR Settings.json", "OCR设置.json"]
    value = OCR_BACKEND_AUTO
    for c_name in config_names:
        config_path = os.path.join(_get_config_folder(), c_name)
        try:
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
                value = data.get("OCR Backend", data.get("OCR后端", OCR_BACKEND_AUTO))
                break
        except (FileNotFoundError, OSError, ValueError, TypeError):
            continue
    if value in {"自动", "Auto"}:
        return OCR_BACKEND_AUTO
    if value not in {OCR_BACKEND_AUTO, OCR_BACKEND_ONNX, OCR_BACKEND_OPENVINO}:
        return OCR_BACKEND_AUTO
    return value


def _openvino_is_available():
    try:
        import openvino  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


def _auto_use_openvino():
    """Auto mode stays conservative: only enable OpenVINO on Intel devices with ample resources."""
    processor = " ".join(filter(None, (
        platform.processor(),
        os.environ.get("PROCESSOR_IDENTIFIER", ""),
    ))).lower()
    if "intel" not in processor:
        return False
    try:
        import psutil
        if psutil.virtual_memory().total < 12 * 1024 ** 3:
            return False
    except (ImportError, OSError):
        return False
    return _openvino_is_available()


def resolve_use_openvino():
    backend = _read_ocr_backend()
    if backend == OCR_BACKEND_OPENVINO:
        if _openvino_is_available():
            print("OCR backend: OpenVINO (user specified)")
            return True
        print("OpenVINO unavailable, OCR backend falls back to ONNX Runtime")
        return False
    if backend == OCR_BACKEND_AUTO:
        use_openvino = _auto_use_openvino()
        selected_backend = OCR_BACKEND_OPENVINO if use_openvino else OCR_BACKEND_ONNX
        print(f"OCR backend: {selected_backend} (auto selected)")
        return use_openvino
    print("OCR backend: ONNX Runtime (user specified)")
    return False

key_config_option = ConfigOption('Game Hotkey Config', { # Global config example
    'Echo Key': 'q',
    'Liberation Key': 'r',
    'Resonance Key': 'e',
    'Tool Key': 't',
}, description='In Game Hotkey for Skills')

# Config upload options
upload_config_option = ConfigOption('Upload Config', {
    'Upload Config Info': True,
}, description='Automatically uploads anonymous config info and win rates every 5 minutes to help compile popular configs.\nUploads no personal info, game accounts, screenshots, IP addresses, or other private data.\nOnly config contents and win-rate statistics are uploaded.')

ocr_backend_option = ConfigOption('OCR Settings', {
    'OCR Backend': OCR_BACKEND_AUTO,
}, config_type={
    'OCR Backend': {
        'type': 'drop_down',
        'options': [OCR_BACKEND_AUTO, OCR_BACKEND_ONNX, OCR_BACKEND_OPENVINO],
    },
}, description='Auto mode uses OpenVINO only on Intel devices with at least 12GB of RAM; other devices use ONNX Runtime. Takes effect after restart.')


def make_bottom_right_black(frame): # Optional. Masks the UID in screenshots for some games
    """
    Changes a portion of the frame's pixels at the bottom right to black.

    Args:
        frame: The input frame (NumPy array) from OpenCV.

    Returns:
        The modified frame with the bottom-right corner blackened.  Returns the original frame
        if there's an error (e.g., invalid frame).
    """
    try:
        height, width = frame.shape[:2]  # Get height and width

        # Calculate the size of the black rectangle
        black_width = int(0.13 * width)
        black_height = int(0.025 * height)

        # Calculate the starting coordinates of the rectangle
        start_x = width - black_width
        start_y = height - black_height

        # Create a black rectangle (NumPy array of zeros)
        black_rect = np.zeros((black_height, black_width, frame.shape[2]), dtype=frame.dtype)  # Ensure same dtype

        # Replace the bottom-right portion of the frame with the black rectangle
        frame[start_y:height, start_x:width] = black_rect

        return frame
    except Exception as e:
        print(f"Error processing frame: {e}")
        return frame

config = {
    'custom_tasks':True, # enable creating and editing custom tasks
    'debug': False,  # Optional, default: False
    'use_gui': True, # Only True is supported for now
    'config_folder': 'configs', # Prefer not to modify
    'global_configs': [key_config_option, upload_config_option, ocr_backend_option],
    'screenshot_processor': make_bottom_right_black, # Modifies the frame when taking screenshots, optional
    'gui_icon': 'icons/icon.png', # Window icon, prefer keeping the file name unchanged
    'wait_until_before_delay': 0,
    'wait_until_check_delay': 0,
    'wait_until_settle_time': 0, # When wait_until first meets its condition, it waits and checks again to avoid detecting sliding animations mid-path before they settle
    'ocr': { # Optional, OCR library in use
        'lib': 'onnxocr',
        'auto_simplify': True, # Auto-convert Traditional to Simplified Chinese, requires a library that recognizes Traditional such as ppocrv5
        'params': {
            'use_openvino': resolve_use_openvino(),
        }
    },
    'windows': {  # Fill in these settings for Windows games
        'exe': ['ssr-xcent.exe', 'ssr-stove-shield.exe'],
        # optional, if set, will search the exe only
        # 'hwnd_class': 'UnrealWindow', # Improves duplicate-name check accuracy
        'interaction': ['PostMessage'], # Genshin: some actions can run in the background. Some games support PostMessage: background clicks. Very few games support ForegroundPostMessage: PostMessage in the foreground. Pynput/PyDirect: foreground only
        'capture_method': ['WGC', 'BitBlt_RenderFull', 'BitBlt'],  # Prefer WGC when the Windows version supports it, otherwise use BitBlt_Full. Supported captures: BitBlt, WGC, BitBlt_RenderFull, DXGI
        'check_hdr': False, # Warn the user when AutoHDR is on, but do not block usage
        'force_no_hdr': False, # True = block usage when the user has AutoHDR on
        'require_bg': True # Require background capture
    },
    'adb': {  # Fill in these settings for Windows games. The MuMu emulator uses native capture and input, which is very fast. Other emulators and real devices use adb, with slower capture
        # optional, if set, will start the pacakge and ensure installed
        #'packages': ['com.abc.efg1', 'com.abc.efg1']
    },
    'start_timeout': 120,  # default 60
    'window_size': { # ok-script window size
        'width': 1200,
        'height': 800,
        'min_width': 600,
        'min_height': 450,
    },
    'supported_resolution': {
        'ratio': '16:9', # Supported game resolutions
        'resize_to': [(2560, 1440), (1920, 1080), (1600, 900), (1280, 720)], # When the ratio or minimum resolution is not met, try resizing the Windows window in order
        'min_size': (1280, 720), # Only requires 16:9 and at least 720p; the window is not forced to resize when the condition is met
        'force_ratio': True, # No resolution error popup; handled by resize_to
    },
    'links': { # Links shown in the About page, optional
            'default': {
                'github': 'https://github.com/OGZnZ/ok-kes',
                'share': 'GitHub: https://github.com/OGZnZ/ok-kes/releases',
                'faq': 'https://github.com/OGZnZ/ok-kes',
                'sponsor': 'local'
            }
        },
    'screenshots_folder': "screenshots", # Screenshot folder; cleared on every restart
    'gui_title': 'MBG-Kes',  # Window title
    'template_matching': { # Optional, for OpenCV template matching
        'coco_feature_json': os.path.join('ok_tasks/assets', 'coco_annotations.json'), # COCO-format annotations, requires PNG images. After running in debug mode, images are cropped to keep only annotated parts to reduce size
        'default_horizontal_variance': 0.002, # Default x variance; when find is called without a box, it matches within the box offset from the COCO coordinates
        'default_vertical_variance': 0.002, # Default y variance
        'default_threshold': 0.8, # Default threshold
    },
    'version': version, # Version
    'my_app': ['src.globals', 'Globals'], # Optional. Global singleton object; can hold loaded models, accessed via og.my_app
    'onetime_tasks': [  # Tasks triggered by user clicks
        ["src.tasks.MyOneTimeTask", "MyOneTimeTask"],
        ["ok", "DiagnosisTask"],
    ],
}
