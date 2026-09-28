"""Isolate network filesystem hangs from the watcher and scanner processes."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.folder_watch_sources import list_source

if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        result = list_source(**request)
        print(json.dumps({'files': result}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
