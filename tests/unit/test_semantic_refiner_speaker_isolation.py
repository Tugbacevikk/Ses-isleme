import uuid
from audio_analyzer.domain.models import TranscriptUtterance
from audio_analyzer.services.semantic_refiner import SemanticRefiner

def test_semantic_refiner_prevents_different_speaker_merge():
    refiner = SemanticRefiner()
    
    # S0 "Ben de dün gittim" (noktalanmamış, sonraki küçük harfle başlıyor) ve S1 "hayır öyle değil."
    # FARKLI konuşmacılar kesinlikle birleştirilmemeli, 2 ayrı kart olarak kalmalı.
    utts = [
        TranscriptUtterance(
            id=uuid.uuid4(),
            speaker_id="SPEAKER_00",
            start_time=0.0,
            end_time=1.0,
            text="Ben de dün gittim"
        ),
        TranscriptUtterance(
            id=uuid.uuid4(),
            speaker_id="SPEAKER_01",
            start_time=1.2,
            end_time=2.0,
            text="hayır öyle değil."
        )
    ]
    
    refined = refiner.refine(utts)
    assert len(refined) == 2, f"Farklı konuşmacılar birleştirilmemeli. Beklenen 2, alınan {len(refined)}"
    assert refined[0].speaker_id == "SPEAKER_00"
    assert refined[1].speaker_id == "SPEAKER_01"

def test_semantic_refiner_merges_same_speaker_clause():
    refiner = SemanticRefiner()
    
    # Aynı konuşmacı "Ürün dün elime" + "ulaştı ama kırıktı." tek karta birleşmeli.
    utts = [
        TranscriptUtterance(
            id=uuid.uuid4(),
            speaker_id="SPEAKER_00",
            start_time=0.0,
            end_time=1.0,
            text="Ürün dün elime"
        ),
        TranscriptUtterance(
            id=uuid.uuid4(),
            speaker_id="SPEAKER_00",
            start_time=1.2,
            end_time=2.0,
            text="ulaştı ama kırıktı."
        )
    ]
    
    refined = refiner.refine(utts)
    assert len(refined) == 1, f"Aynı konuşmacının yarım cümlesi birleşmeli. Beklenen 1, alınan {len(refined)}"
    assert refined[0].text == "Ürün dün elime ulaştı ama kırıktı."
    assert refined[0].speaker_id == "SPEAKER_00"
