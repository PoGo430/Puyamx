"""PyInstaller entry point."""
import multiprocessing

from puya_studio.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
