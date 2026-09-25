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


def test_semantic_refiner_domain_mode_greeting_lock_scope():
    u1 = TranscriptUtterance(id=uuid.uuid4(), speaker_id="SPEAKER_00", start_time=1.0, end_time=3.0, text="Hoş geldiniz efendim.")
    u2 = TranscriptUtterance(id=uuid.uuid4(), speaker_id="SPEAKER_01", start_time=3.2, end_time=5.0, text="Hoş geldiniz, nasılsınız?")

    # 1. domain_mode=None (genel amaçlı) modunda iki ayrı konuşmacı korunmalı
    refiner_general = SemanticRefiner(domain_mode=None)
    res_general = refiner_general.refine([u1, u2])
    assert len(res_general) == 2
    assert res_general[0].speaker_id == "SPEAKER_00"
    assert res_general[1].speaker_id == "SPEAKER_01"

    # 2. domain_mode="call_center" modunda açılış selamlaması tek temsilci kartına birleştirilmeli
    refiner_cc = SemanticRefiner(domain_mode="call_center")
    res_cc = refiner_cc.refine([u1, u2])
    assert len(res_cc) == 1
    assert res_cc[0].speaker_id == "SPEAKER_00"

