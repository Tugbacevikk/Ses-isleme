from audio_analyzer.domain.models import DiarizationSegment
from audio_analyzer.services.overlap_detector import OverlapDetector


def test_no_overlaps_when_single_speaker():
    segments = [
        DiarizationSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=2.0),
        DiarizationSegment(speaker_id="SPEAKER_00", start_time=2.0, end_time=5.0),
    ]
    summary = OverlapDetector.detect_overlaps(segments, total_audio_duration=5.0)

    assert summary.interrupt_count == 0
    assert summary.total_overlap_seconds == 0.0
    assert summary.overlap_percentage == 0.0
    assert len(summary.overlaps) == 0


def test_detect_overlap_between_two_speakers():
    segments = [
        DiarizationSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=3.0),
        DiarizationSegment(speaker_id="SPEAKER_01", start_time=2.0, end_time=5.0),
    ]
    summary = OverlapDetector.detect_overlaps(segments, total_audio_duration=10.0)

    assert summary.interrupt_count == 1
    assert summary.total_overlap_seconds == 1.0  # 2.0 to 3.0
    assert summary.overlap_percentage == 10.0
    assert len(summary.overlaps) == 1
    assert summary.overlaps[0].speakers == ["SPEAKER_00", "SPEAKER_01"]
    assert summary.overlaps[0].start_time == 2.0
    assert summary.overlaps[0].end_time == 3.0
    assert summary.overlaps[0].duration == 1.0


def test_empty_segments():
    summary = OverlapDetector.detect_overlaps([], total_audio_duration=10.0)

    assert summary.interrupt_count == 0
    assert summary.total_overlap_seconds == 0.0
    assert summary.overlap_percentage == 0.0
