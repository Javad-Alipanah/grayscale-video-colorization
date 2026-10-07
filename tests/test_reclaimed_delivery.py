import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
import tempfile
from pathlib import Path
from unittest import TestCase,main,mock
import production as p
import delivery as d

class ReclaimedProvenanceTests(TestCase):
    def test_missing_media_is_not_accepted_without_deleted_replacement_proof(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p,'HERE',Path(tmp)),mock.patch.object(d,'BASE',Path(tmp)/'delivery'):
            shot=dict(id='shot_test',start_frame=2,end_frame=3,mode='colorize')
            attempt=dict(attempt=1,output_sha256='prediction');identity=dict(sha256='source')
            folder=d.BASE/'shots/shot_test/attempt_001_prediction';marker=folder/'merge.json'
            p.atomic_json(marker,dict(status='draft_verified',fingerprint=p.json_digest(dict(prediction='prediction',source='source',start=2,end=3,method=d.MERGE_METHOD,mode='colorize')),
                output=str(folder/'missing.mkv'),output_sha256='old-container',exact_source_y=True,full_decode_verified=True))
            treatment=Path(tmp)/'treatment.json';p.atomic_json(treatment,dict(base_output_sha256='old-container',output_sha256='replacement'))
            p.atomic_json(p.HERE/'source_y_overrides.json',{'shot_test':dict(status='active_pending_quality_review',receipt=str(treatment),output_sha256='replacement')})
            self.assertIsNone(d.reviewed_reclaimed_base(shot,attempt,identity))

    def test_historical_only_record_cannot_be_used_as_deliverable_without_override(self):
        with self.assertRaisesRegex(ValueError,'preserved reviewed override'):
            d.apply_source_y_override(dict(shot_id='removed',historical_base_media_reclaimed=True),{})

if __name__=='__main__':main(verbosity=2)
