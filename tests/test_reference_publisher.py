import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Atomic guide publication preserves exact PNG bytes and old readable files."""
import importlib.util
import io
from pathlib import Path
import tempfile
from unittest import TestCase, main, mock
from PIL import Image

path=Path(__file__).resolve().parents[1]/'engine/prepare_references.py'
spec=importlib.util.spec_from_file_location('reference_publisher',path)
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


class AtomicPublisherTests(TestCase):
    def test_atomic_png_matches_existing_encoder_and_keeps_old_file_until_replace(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            target=Path(directory)/'ref.png';original=Image.new('RGB',(4,3),(40,80,120));original.save(target)
            old=target.read_bytes();updated=Image.new('RGB',(4,3),(180,100,20))
            expected=io.BytesIO();updated.save(expected,format='PNG')
            replace=publisher.os.replace;observed=[]
            def inspect(temp,destination):
                observed.append(Path(destination).read_bytes())
                if len(observed)==1:raise PermissionError('Temporary Windows read handle')
                replace(temp,destination)
            with mock.patch.object(publisher.os,'replace',side_effect=inspect),mock.patch.object(publisher.time,'sleep'):
                digest=publisher.atomic_png(target,updated)
            self.assertEqual(observed,[old,old])
            self.assertEqual(target.read_bytes(),expected.getvalue())
            self.assertEqual(digest,publisher.digest(target))

    def test_unchanged_png_never_replaces_published_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            target=Path(directory)/'ref.png';image=Image.new('RGB',(4,3),(40,80,120));image.save(target)
            initial=target.stat().st_mtime_ns
            with mock.patch.object(publisher.os,'replace',side_effect=AssertionError('Unchanged guide should not be rewritten')):
                publisher.atomic_png(target,image)
            self.assertEqual(initial,target.stat().st_mtime_ns)


if __name__=='__main__':main(verbosity=2)
