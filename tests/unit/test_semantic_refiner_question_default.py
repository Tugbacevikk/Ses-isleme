import uuid
import pytest
from audio_analyzer.domain.models import TranscriptUtterance
from audio_analyzer.services.semantic_refiner import SemanticRefiner


def test_split_on_questions_default_false():
    """
    split_on_questions varsayılan olarak False olduğu için soru işareti içeren diyalogların
    sahte ikinci bir konuşmacıya bölünmediğini ve tek kart olarak kaldığını doğrular.
    """
    refiner = SemanticRefiner()  # varsayılan olarak split_on_questions=False
    utt = TranscriptUtterance(
        id=uuid.uuid4(),
        speaker_id="SPEAKER_00",
        start_time=0.0,
        end_time=10.0,
        text="Sipariş neden gecikti? Bilmiyorum ama çok kızgınım.",
    )

    result = refiner.refine([utt])

    # Tek konuşmacı kartında kalmalı, bölünmemeli!
    assert len(result) == 1
    assert result[0].speaker_id == "SPEAKER_00"
    assert result[0].text == "Sipariş neden gecikti? Bilmiyorum ama çok kızgınım."
