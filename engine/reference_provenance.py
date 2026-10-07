"""Consume explicit, source-bound native guide reviews; never infer approval."""
import hashlib
import json
from pathlib import Path
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_marker(shot, source, marker, workspace):
    if not source or not source.get('sha256') or marker.get('source_sha256') != source['sha256']:
        raise ValueError('Reference marker must bind the current source checksum')
    path=Path(marker.get('review_path',''));path=path if path.is_absolute() else Path(workspace)/path
    if not path.is_file() or digest(path)!=marker.get('review_sha256'):
        raise ValueError('Reference review missing or changed')
    review=json.loads(path.read_text(encoding='utf-8-sig'))
    if review.get('status')!='approved' or review.get('shot_id')!=shot['id'] or review.get('source_sha256')!=source['sha256']:
        raise ValueError('Stored reference review source/scope mismatch')
    if any(review.get(k) is not True for k in ['geometry_checked','palette_checked','source_y_recombined_checked']):
        raise ValueError('Stored reference review lacks explicit native visual checks')
    if not review.get('notes') or any(not marker.get(k) or review.get(k)!=marker[k] for k in ['approved_by','approved_at']):
        raise ValueError('Reference reviewer attribution mismatch')
    refs=marker.get('references',[])
    def signature(row):return (row.get('source_frame'),row.get('sha256'),row.get('view'),tuple(row.get('materials',[])))
    if len(refs)!=len(review.get('references',[])) or sorted(map(signature,refs))!=sorted(map(signature,review.get('references',[]))):
        raise ValueError('Stored review does not bind this exact reference set')
    for row in refs:
        image_path=Path(row['path']);image_path=image_path if image_path.is_absolute() else Path(workspace)/image_path
        # Content hashes are checked first by the consumer, so a publication
        # race remains a pending-publication error rather than a geometry error.
        with Image.open(image_path) as image:
            image.load()
            if image.format!='PNG' or image.mode!='RGB' or image.size!=(source['width'],source['height']):
                raise ValueError('Reviewed reference must be a native-size RGB PNG')
