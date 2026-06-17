# YOLOv5 🚀 by Ultralytics, AGPL-3.0 license
"""
utils/initialization
"""

import contextlib
import platform
import threading


def emojis(str=''):
    # Return platform-dependent emoji-safe version of string
    return str.encode().decode('ascii', 'ignore') if platform.system() == 'Windows' else str


class TryExcept(contextlib.ContextDecorator):
    # YOLOv5 TryExcept class. Usage: @TryExcept() decorator or 'with TryExcept():' context manager
    def __init__(self, msg=''):
        self.msg = msg

    def __enter__(self):
        pass

    def __exit__(self, exc_type, value, traceback):
        if value:
            print(emojis(f"{self.msg}{': ' if self.msg else ''}{value}"))
        return True


def threaded(func):
    # Multi-threads a target function and returns thread. Usage: @threaded decorator
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread

    return wrapper


def notebook_init(verbose=True):
    # Check system software and hardware
    print('Checking setup...')

    import os
    import shutil

    import psutil
    import torch
    from utils.general import check_requirements

    from utils.torch_utils import select_device

    if shutil.which('nvidia-smi'):
        os.system('nvidia-smi')
    if verbose:
        print(f'psutil {psutil.__version__}')
        print(f'torch {torch.__version__}')
    check_requirements(('psutil', 'IPython'))
    select_device()
