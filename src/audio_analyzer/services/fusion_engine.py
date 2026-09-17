import uuid
from typing import List, Optional

from audio_analyzer.domain.models import (
    DiarizationSegment,
    TranscriptUtterance,
    WordSegment,
)


class FusionEngine:
    """
    Speech-to-Text kelime zaman damgaları ile Speaker Diarization zaman aralıklarını
    birleştiren ve çakışma/sessizlik kurallarını uygulayan hizalama motoru.
    """

    def __init__(self, max_silence_threshold: float = 1.5):
        """
        :param max_silence_threshold: Aynı konuşmacı bu süreden (saniye) fazla susarsa yeni paragraf başlatır.
        """
        self.max_silence_threshold = max_silence_threshold

    def align(
        self, words: List[WordSegment], diarization_segments: List[DiarizationSegment]
    ) -> List[TranscriptUtterance]:
        """
        Kelime seviyesindeki STT çıktılarını konuşmacı aralıklarıyla IoU ve Midpoint kurallarına göre eşler.
        """
        if not words:
            return []

        if not diarization_segments:
            # Konuşmacı bilgisi yoksa tek bir varsayılan konuşmacı ("SPEAKER_UNKNOWN") atar.
            return self._build_single_speaker_utterances(words, "SPEAKER_UNKNOWN")

        # 1. Her kelimeye en uygun konuşmacıyı atama (Midpoint + IoU)
        attributed_words = []
        for word in words:
            best_speaker = self._find_best_speaker_for_word(word, diarization_segments)
            attributed_words.append((word, best_speaker))

        # 1b. Gürültü ve anlık sıçramaları önlemek için 1-kelimelik spikeleri yumuşatma (Smoothing Pass)
        attributed_words = self._smooth_attributed_words(attributed_words)

        # 2. Kelimeleri Konuşmacı ve Sessizlik eşiğine göre gruplayarak Utterance blokları oluşturma
        return self._group_words_into_utterances(attributed_words)

    def _find_best_speaker_for_word(
        self, word: WordSegment, diarization_segments: List[DiarizationSegment]
    ) -> str:
        # 1. Kelimenin orta noktası hangi segmente düşüyorsa öncelikli olarak o konuşmacıyı ata
        for seg in diarization_segments:
            if seg.contains_timestamp(word.midpoint):
                return seg.speaker_id

        # 2. Orta nokta eşleşmezse, en yüksek kesişim süresine (max overlap duration) sahip segmente ata
        best_speaker = "SPEAKER_UNKNOWN"
        max_overlap = 0.0

        for seg in diarization_segments:
            overlap_start = max(word.start_time, seg.start_time)
            overlap_end = min(word.end_time, seg.end_time)
            overlap_len = max(0.0, overlap_end - overlap_start)

            if overlap_len > max_overlap:
                max_overlap = overlap_len
                best_speaker = seg.speaker_id

        return best_speaker

    def _group_words_into_utterances(
        self, attributed_words: List[tuple[WordSegment, str]]
    ) -> List[TranscriptUtterance]:
        utterances: List[TranscriptUtterance] = []
        if not attributed_words:
            return utterances

        current_speaker = attributed_words[0][1]
        current_words: List[WordSegment] = [attributed_words[0][0]]

        for word, speaker in attributed_words[1:]:
            last_word = current_words[-1]
            silence_gap = word.start_time - last_word.end_time

            # Bölümleme kriterleri: Konuşmacı değişimi VEYA 1.5s üzerindeki sessizlik
            if speaker != current_speaker or silence_gap > self.max_silence_threshold:
                # Mevcut bloğu sonlandırıp listeye ekle
                utt = self._create_utterance(current_speaker, current_words)
                if utt.text.strip():
                    utterances.append(utt)
                current_speaker = speaker
                current_words = [word]
            else:
                current_words.append(word)

        # Son kalan bloğu ekle
        if current_words:
            utt = self._create_utterance(current_speaker, current_words)
            if utt.text.strip():
                utterances.append(utt)

        return utterances

    def _create_utterance(self, speaker_id: str, words: List[WordSegment]) -> TranscriptUtterance:
        start_time = words[0].start_time
        end_time = words[-1].end_time
        text = " ".join(w.word for w in words).strip()
        return TranscriptUtterance(
            id=uuid.uuid4(),
            speaker_id=speaker_id,
            start_time=start_time,
            end_time=end_time,
            text=text,
        )

    def _build_single_speaker_utterances(
        self, words: List[WordSegment], speaker_id: str
    ) -> List[TranscriptUtterance]:
        attributed = [(w, speaker_id) for w in words]
        return self._group_words_into_utterances(attributed)

    def _smooth_attributed_words(
        self, attributed_words: List[tuple[WordSegment, str]]
    ) -> List[tuple[WordSegment, str]]:
        if len(attributed_words) < 3:
            return attributed_words

        smoothed = list(attributed_words)
        for i in range(1, len(attributed_words) - 1):
            prev_spk = smoothed[i - 1][1]
            next_spk = smoothed[i + 1][1]
            curr_spk = smoothed[i][1]

            # Eğer sağındaki ve solundaki konuşmacı aynı ise ancak ortadaki tek kelime farklıysa ortadakini düzelt
            if prev_spk == next_spk and curr_spk != prev_spk:
                smoothed[i] = (smoothed[i][0], prev_spk)

        return smoothed
