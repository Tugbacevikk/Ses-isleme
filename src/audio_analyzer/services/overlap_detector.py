import logging
from typing import List

from audio_analyzer.domain.models import DiarizationSegment, OverlapSegment, OverlapSummary

logger = logging.getLogger(__name__)


class OverlapDetector:
    """
    Konuşmacı zaman aralıkları arasındaki çakışmaları (söz kesme / interrupt)
    ve kalite kontrol metriklerini hesaplayan servis.
    """

    @staticmethod
    def detect_overlaps(
        diarization_segments: List[DiarizationSegment], total_audio_duration: float = 0.0
    ) -> OverlapSummary:
        if not diarization_segments or len(diarization_segments) < 2:
            return OverlapSummary()

        # Segmentleri başlama zamanına göre sırala
        sorted_segs = sorted(diarization_segments, key=lambda s: s.start_time)
        overlaps: List[OverlapSegment] = []
        total_overlap_seconds = 0.0

        for i in range(len(sorted_segs)):
            for j in range(i + 1, len(sorted_segs)):
                seg1 = sorted_segs[i]
                seg2 = sorted_segs[j]

                # Eğer seg2, seg1 bitişinden sonra başlıyorsa, seg1 ile sonraki segmentlerin çakışması olamaz
                if seg2.start_time >= seg1.end_time:
                    break

                # Farklı konuşmacılar çakışıyorsa
                if seg1.speaker_id != seg2.speaker_id:
                    o_start = max(seg1.start_time, seg2.start_time)
                    o_end = min(seg1.end_time, seg2.end_time)
                    o_dur = o_end - o_start

                    # 50 ms altındaki minik çakışmaları (gürültü) ele
                    if o_dur > 0.05:
                        total_overlap_seconds += o_dur
                        speakers = sorted(list({seg1.speaker_id, seg2.speaker_id}))
                        overlaps.append(
                            OverlapSegment(
                                speakers=speakers,
                                start_time=round(o_start, 2),
                                end_time=round(o_end, 2),
                                duration=round(o_dur, 2),
                            )
                        )

        overlap_percentage = 0.0
        if total_audio_duration > 0:
            overlap_percentage = round((total_overlap_seconds / total_audio_duration) * 100, 2)

        summary = OverlapSummary(
            total_overlap_seconds=round(total_overlap_seconds, 2),
            overlap_percentage=overlap_percentage,
            interrupt_count=len(overlaps),
            overlaps=overlaps,
        )

        logger.info(
            "Çakışma analizi tamamlandı: Toplam %s sn (%s%%), %s kesinti saptandı.",
            summary.total_overlap_seconds,
            summary.overlap_percentage,
            summary.interrupt_count,
        )
        return summary
