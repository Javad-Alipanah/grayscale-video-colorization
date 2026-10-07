"""Verify effective decoded sample timing, including AAC encoder priming."""
from fractions import Fraction
import json
import subprocess


def verify_audio_clock(stream, frames):
    if not frames: raise ValueError('Full decoded audio frame/sample census required')
    samples = 0
    tick, rate = Fraction(stream['time_base']), int(stream['sample_rate'])
    tolerance=min(tick,Fraction(1,1000))
    for index, frame in enumerate(frames):
        if 'best_effort_timestamp' not in frame or int(frame.get('nb_samples', 0)) <= 0:
            raise ValueError('Missing decoded audio timestamp/sample count')
        observed=int(frame['best_effort_timestamp']) * tick
        if (index==0 and observed!=0) or abs(observed-Fraction(samples,rate))>tolerance:
            raise ValueError('Decoded audio must start at zero and follow the sample clock within min(container tick, 1ms)')
        samples += int(frame['nb_samples'])
    return samples


def probe_clock(path, stream, ffprobe):
    frames = json.loads(subprocess.check_output([str(ffprobe), '-v', 'error', '-select_streams', 'a:0',
        '-show_frames', '-show_entries', 'frame=best_effort_timestamp,nb_samples', '-of', 'json', str(path)]))['frames']
    count=verify_audio_clock(stream, frames);samples=0;errors=[];tick=Fraction(stream['time_base'])
    for frame in frames:
        errors.append(abs(int(frame['best_effort_timestamp'])*tick-Fraction(samples,int(stream['sample_rate']))))
        samples+=int(frame['nb_samples'])
    return {'decoded_samples': count, 'effective_start_sample': 0,
            'metadata_start_time': stream.get('start_time', '0'), 'sample_clock_within_container_tick': True,
            'exact_decoded_sample_clock': max(errors)==0,'max_error_seconds':float(max(errors)),
            'tolerance_seconds':float(min(tick,Fraction(1,1000))),'container_tick_seconds':float(tick)}
