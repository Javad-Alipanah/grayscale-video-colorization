"""Historical Lecture 1 entrypoints require deliberate opt-in and exact source."""
import os
from pathlib import Path

def require_lecture1_recipe():
    import production as p
    if os.environ.get('COLOR_ENABLE_LECTURE1_RECIPES') != '1':
        raise ValueError('Historical Lecture 1 recipe; use pipeline.py for portable batches. Explicit COLOR_ENABLE_LECTURE1_RECIPES=1 is required.')
    source=Path(os.environ.get('COLOR_LECTURE1_SOURCE',''))
    if not source.is_file() or p.sha256(source)!='37937a5485485f69edd209a84fde0f5522d1db085b540f2ff16b8a7aeceb1033':
        raise ValueError('Historical recipe requires COLOR_LECTURE1_SOURCE with the exact original Lecture 1 source hash')
