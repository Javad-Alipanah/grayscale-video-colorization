"""Publish only a hash-bound independently completed technical/scoped-QA master."""
from pathlib import Path
import shutil,os
import production as p
REVIEW=p.PROJECT/'scenes/qc/final_lecture_technical_review.json'
OUT=p.WORKSPACE/'outputs/Lecture_01_Colorized'
def bind(path,expected):
 path=Path(path);assert p.sha256(path)==expected,f'Changed reviewed artifact: {path}'
 return path
def copy_exact(src,dst,digest):
 bind(src,digest)
 if dst.exists():assert p.sha256(dst)==digest;return
 temp=dst.with_name(dst.name+'.partial');shutil.copyfile(src,temp)
 assert p.sha256(temp)==digest;os.replace(temp,dst)
def main():
 review=p.read_json(REVIEW)
 assert review['status']=='technical_and_scoped_QA_complete'
 for key in ['exact_original_Y_all80026_frames','exact_original_decoded_PCM_through_natural_EOF','all_video_PTS_and_native_cadence_verified','immutable_pilot_all4320_native_YUV_exact','final_selected_hashes_and_scoped_reviews_verified','preview_full_decode_verified']:
  assert review.get(key) is True,'Missing final gate: '+key
 assert review['continuous_viewing_review']['status']=='deferred_to_user' and review['continuous_viewing_review']['performed_by_assistant'] is False
 assert review['immutable_pilot_global_frame_range_half_open']==[21579,25899]
 ap=bind(review['assembly_receipt'],review['assembly_receipt_sha256']);assembly=p.read_json(ap)
 assert assembly['frames']==80026 and assembly['start_frame']==0 and assembly['end_frame']==80026
 assert assembly['master_sha256']==review['master_sha256'] and assembly['preview_sha256']==review['preview_sha256']
 assert all(assembly[k] for k in ['exact_source_y','exact_source_pcm','full_decode_verified'])
 for evidence in review['evidence']:bind(evidence['path'],evidence['sha256'])
 OUT.mkdir(exist_ok=True,parents=True)
 master=OUT/'Lecture_01_Colorized_Lossless.mkv';preview=OUT/'Lecture_01_Colorized_Viewing.mp4'
 # Explicit space for both user-facing copies, without touching accepted work.
 extra=sum(Path(assembly[k]).stat().st_size for k,dest in [('master',master),('preview',preview)] if not dest.exists())
 assert shutil.disk_usage(OUT).free>10*2**30+1.3*extra,'Publication reserve would be violated'
 copy_exact(assembly['master'],master,assembly['master_sha256']);copy_exact(assembly['preview'],preview,assembly['preview_sha256'])
 verification=OUT/'Verification';verification.mkdir(exist_ok=True)
 proof=verification/'Final_Technical_and_Scoped_Review.json';copy_exact(REVIEW,proof,p.sha256(REVIEW))
 evidence_export=[]
 for index,item in enumerate(review['evidence']):
  src=Path(item['path']);assert src.suffix.lower()=='.json','Export only bound diagnosticJSON here'
  dest=verification/f'{index+1:02d}_{src.name}';copy_exact(src,dest,item['sha256']);evidence_export.append(dict(path=str(dest),sha256=item['sha256'],source=str(src)))
 receipt=dict(status='technical_and_scoped_QA_complete_full_viewing_deferred_to_user',published_at=p.utc(),frames=80026,width=960,height=720,fps='24000/1001',duration_seconds=80026*1001/24000,master=str(master),master_sha256=p.sha256(master),master_bytes=master.stat().st_size,viewing_copy=str(preview),viewing_copy_sha256=p.sha256(preview),viewing_copy_bytes=preview.stat().st_size,independent_review=str(proof),independent_review_sha256=p.sha256(proof),evidence=evidence_export,continuous_viewing_review=review['continuous_viewing_review'],retained_limitations=review['retained_limitations'],historical_color_authenticity='interpretive_not_verified')
 p.atomic_json(OUT/'Delivery_Receipt.json',receipt)
 (OUT/'SHA256SUMS.txt').write_text(f"{receipt['master_sha256']}  {master.name}\n{receipt['viewing_copy_sha256']}  {preview.name}\n",encoding='utf-8')
 notes=['# Lecture 1 - delivery and review notes','', '**Technical/scoped-QA complete; full viewing review deferred to you.**','',f'The complete lecture contains 80,026 frames at native 960x720 and 24000/1001 fps, lasting 55:37.751.','',f'- Lossless preservation master: [{master.name}]({master.name}). Original decoded brightness and unfiltered source PCM are preserved exactly.',f'- Viewing copy: [{preview.name}]({preview.name}). H.264/AAC compression is convenient for viewing; exact pixel/audio equality applies to the lossless master.','', 'Every frame\'s brightness and presentation timing, all original decoded audio samples through natural EOF, and all 4,320 approved pilot frames were independently checked. Scientific photographs/diagrams, repaired transitions and changed material regions received scoped native-frame review. Colors remain interpretive.','', 'Continuous full-length viewing has not been performed by the assistant, as requested. Review the following retained limitations while watching:','']
 for item in review['retained_limitations']:
  if isinstance(item,dict):notes.append('- '+str(item.get('timestamp',''))+' - '+str(item['note']))
  else:notes.append('- '+str(item))
 notes+=['','Checksums are in `SHA256SUMS.txt`; the bound verification receipts are in `Verification/`. Source lectures, approved guides, selected working media and provenance remain retained.','']
 (OUT/'Review_Notes.md').write_text('\n'.join(notes),encoding='utf-8')
 status=['# Lecture 1 color production','','**Complete: technical preservation and scoped native QA. Full viewing review is deferred to the user.**','',f'Published: {receipt["published_at"]}.','',f'- [Complete viewing copy](Lecture_01_Colorized_Viewing.mp4)',f'- [Lossless preservation master](Lecture_01_Colorized_Lossless.mkv)',f'- [Review notes and retained limitations](Review_Notes.md)',f'- [Delivery receipt](Delivery_Receipt.json)','','All 80,026 source frames are present. Original brightness, decoded source PCM, native geometry/timing and the immutable approved pilot were independently verified. Full continuous viewing was intentionally assigned to the user and is not claimed passed. Earlier partial review drafts remain under `Review_Drafts/`.','']
 (OUT/'Production_Status.md').write_text('\n'.join(status),encoding='utf-8')
 finish=p.read_json(p.HERE/'final_assembly/finish_scope.json');finish.update(final_delivery_complete=True,completed_at=p.utc(),delivery_receipt=str(OUT/'Delivery_Receipt.json'),delivery_receipt_sha256=p.sha256(OUT/'Delivery_Receipt.json'));p.atomic_json(p.HERE/'final_assembly/finish_scope.json',finish)
 p.atomic_json(p.HERE/'final_assembly/publication.json',receipt)
 print(str(OUT/'Delivery_Receipt.json'))
if __name__=='__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    main()
