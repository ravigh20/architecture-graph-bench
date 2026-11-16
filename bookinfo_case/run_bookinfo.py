#!/usr/bin/env python3
"""Final-paper Bookinfo reconstruction and held-out confidence entry point."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from process import main
if __name__=='__main__':raise SystemExit(main(['--study','bookinfo',*sys.argv[1:]]))
