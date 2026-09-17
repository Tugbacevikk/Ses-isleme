import uuid

import pytest

from audio_analyzer.domain.models import TranscriptUtterance
from audio_analyzer.services.semantic_refiner import SemanticRefiner


def test_semantic_refiner_splits_merged_utterance():
    refiner = SemanticRefiner(domain_mode="call_center")

    # Müşteri şikayeti ve Temsilci kapanışının tek bir SPEAKER_00 bloğunda birleştiği durum
    merged_text = "Merhaba, ben Elif Çevik. Bilgisayar yavaş çalışıyor. Şikayetinizi not aldım ve konuyu en kısa sürede çözmek için gerekli adımları atacağız."
    utt = TranscriptUtterance(
        id=uuid.uuid4(), speaker_id="SPEAKER_00", start_time=6.58, end_time=59.43, text=merged_text
    )

    result = refiner.refine([utt])

    # 2 ayrı parçaya bölünmüş olmalı
    assert len(result) == 2
    assert result[0].speaker_id == "SPEAKER_00"
    assert "Elif Çevik" in result[0].text
    assert result[1].speaker_id == "SPEAKER_01"
    assert "Şikayetinizi not aldım" in result[1].text
