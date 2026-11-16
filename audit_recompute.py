#!/usr/bin/env python3
"""Final-paper diagnostic entry point; calculations use the local test settings."""
from process import main
import sys
if __name__=='__main__':raise SystemExit(main(['--study','diagnostics',*sys.argv[1:]]))
