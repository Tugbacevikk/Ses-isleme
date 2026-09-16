from typing import List, Tuple, Optional
from audio_analyzer.domain.interfaces import ISTTEngine
from audio_analyzer.domain.models import WordSegment


class MockSTTAdapter(ISTTEngine):
    """
    Demo veya test amaçlı geliştirme ortamında kullanılabilecek Mock STT adaptörü.
    Production ortamında yalnızca ALLOW_MOCK_STT=true olduğunda çağrılmalıdır.
    """
    def transcribe(self, audio_path: str) -> Tuple[List[WordSegment], Optional[str]]:
        words = [
            WordSegment(word="Alo", start_time=0.0, end_time=0.4),
            WordSegment(word="buyurun", start_time=0.5, end_time=0.9),
            WordSegment(word="Nasıl", start_time=1.0, end_time=1.3),
            WordSegment(word="yardımcı", start_time=1.4, end_time=1.8),
            WordSegment(word="olabilirim", start_time=1.9, end_time=2.5),
        ]
        return words, "tr"
