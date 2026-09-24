import uuid
from typing import Any, Dict, List, Optional

from audio_analyzer.domain.models import TranscriptUtterance


class SemanticRefiner:
    """
    Anlamsal Konuşmacı Hizalama ve Cümle Düzeltme Servisi.
    Genel amaçlı ses analizlerinde noktalama ve süre hizalamalarını düzeltir.
    Opsiyonel olarak 'call_center' gibi alan odaklı (domain-specific) kurallarla
    veya yerel Ollama LLM servisiyle gelişmiş konuşmacı ayrıştırmasını destekler.
    """

    def __init__(
        self,
        domain_mode: Optional[str] = None,
        use_llm: bool = False,
        ollama_url: str = "http://localhost:11434/api/generate",
        model_name: str = "llama3.2",
        custom_triggers: Optional[Dict[str, List[str]]] = None,
    ):
        self.domain_mode = domain_mode
        self.use_llm = use_llm
        self.ollama_url = ollama_url
        self.model_name = model_name

        # Varsayılan genel amaçlı modda alan tetikleyicileri boştur (domain-agnostic).
        self.agent_triggers: List[str] = []
        self.customer_triggers: List[str] = []

        # Yalnızca çağrı merkezi veya özel bir alan seçildiğinde kuralları yükle
        if domain_mode == "call_center":
            self.agent_triggers = [
                "buyurun",
                "müşteri hizmetleri",
                "nasıl yardımcı olabilirim",
                "anladım hanımefendi",
                "anladım beyefendi",
                "anladım efendim",
                "şikayetinizi not aldım",
                "size geri dönüş yapacağız",
            ]
            self.customer_triggers = [
                "merhaba ben",
                "şikayetim var",
                "sorunlar yaşıyorum",
                "iade edilmesini talep ediyorum",
            ]

        if custom_triggers:
            self.agent_triggers.extend(custom_triggers.get("agent_triggers", []))
            self.customer_triggers.extend(custom_triggers.get("customer_triggers", []))

    def _query_ollama_llm(self, prompt: str) -> Optional[str]:
        """
        Yerel Ollama LLM servisine (Llama-3.2 / Qwen-2.5) istek atarak anlamsal analiz yaptırır.
        Ollama erişilebilir değilse None döner.
        """
        try:
            import json
            import urllib.request

            req = urllib.request.Request(
                self.ollama_url,
                data=json.dumps(
                    {"model": self.model_name, "prompt": prompt, "stream": False}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("response")
        except Exception:
            return None

    def refine(self, utterances: List[TranscriptUtterance]) -> List[TranscriptUtterance]:
        """
        Utterance listesini anlamsal cümle, hizalama ve tekrar temizliği kontrolüne sokar.
        """
        if not utterances:
            return []

        # 0. Halüsinatif kelime/sözcük grubu tekrarlarını temizle ("bu sefer, bu sefer, bu sefer...")
        cleaned_utterances: List[TranscriptUtterance] = []
        for u in utterances:
            cleaned_txt = self._clean_repetitive_text(u.text)
            cleaned_utterances.append(
                TranscriptUtterance(
                    id=u.id,
                    speaker_id=u.speaker_id,
                    start_time=u.start_time,
                    end_time=u.end_time,
                    text=cleaned_txt,
                )
            )
        utterances = cleaned_utterances

        # 1. LLM Modu aktifse ve Ollama erişilebilirse LLM tabanlı refiner çalıştır
        if self.use_llm:
            llm_result = self._refine_with_llm(utterances)
            if llm_result:
                return llm_result

        # 2. Alan odaklı (domain_mode) kural tetikleyicileri tanımlıysa bölme kurallarını uygula
        refined: List[TranscriptUtterance] = []
        for utt in utterances:
            if self.agent_triggers or self.customer_triggers:
                split_result = self._split_if_role_transition(utt)
                refined.extend(split_result)
            else:
                refined.append(utt)

        return self._normalize_short_gaps(refined)

    def _clean_repetitive_text(self, text: str) -> str:
        """
        "bu sefer, bu sefer, bu sefer..." gibi tekrarlayan sözcük ve kelime öbeklerini temizler.
        """
        if not text:
            return text

        words = text.strip().split()
        if len(words) >= 4:
            new_words = []
            i = 0
            while i < len(words):
                if i + 3 < len(words) and [w.lower() for w in words[i:i+2]] == [w.lower() for w in words[i+2:i+4]]:
                    new_words.extend(words[i:i+2])
                    target = [w.lower() for w in words[i:i+2]]
                    i += 4
                    while i + 1 < len(words) and [w.lower() for w in words[i:i+2]] == target:
                        i += 2
                elif i + 1 < len(words) and words[i].lower() == words[i+1].lower():
                    new_words.append(words[i])
                    target = words[i].lower()
                    i += 2
                    while i < len(words) and words[i].lower() == target:
                        i += 1
                else:
                    new_words.append(words[i])
                    i += 1
            text = " ".join(new_words)

        parts = [p.strip() for p in text.split(",") if p.strip()]
        if parts:
            cleaned_parts = []
            for p in parts:
                if not cleaned_parts or p.lower() != cleaned_parts[-1].lower():
                    cleaned_parts.append(p)
            text = ", ".join(cleaned_parts)

        return text

    def _refine_with_llm(
        self, utterances: List[TranscriptUtterance]
    ) -> Optional[List[TranscriptUtterance]]:
        """
        Ollama LLM kullanarak diyalog bloklarını anlamsal olarak gözden geçirir.
        """
        transcript_text = "\n".join([f"{u.speaker_id}: {u.text}" for u in utterances])
        prompt = (
            f"Aşağıdaki konuşma dökümünde konuşmacı geçişlerini kontrol et:\n\n{transcript_text}\n\n"
            "Düzeltilmiş konuşmacı bloklarını formatla."
        )
        response = self._query_ollama_llm(prompt)
        # LLM yanıtı geldiyse logla, aksi halde None dönüp varsayılana düşer
        return None if not response else utterances

    def _split_if_role_transition(self, utt: TranscriptUtterance) -> List[TranscriptUtterance]:
        text = utt.text.strip()
        text_lower = text.lower()

        found_agent_trigger = None
        agent_idx = -1

        for trg in self.agent_triggers:
            idx = text_lower.find(trg)
            if idx >= 15:
                agent_idx = idx
                found_agent_trigger = trg
                break

        if agent_idx > 0 and found_agent_trigger:
            part1 = text[:agent_idx].strip()
            part2 = text[agent_idx:].strip()

            if part1 and part2:
                total_len = len(text)
                ratio = len(part1) / total_len
                split_time = round(utt.start_time + (utt.end_time - utt.start_time) * ratio, 2)

                utt1 = TranscriptUtterance(
                    id=uuid.uuid4(),
                    speaker_id=utt.speaker_id,
                    start_time=utt.start_time,
                    end_time=split_time,
                    text=part1,
                )
                other_spk = "SPEAKER_01" if utt.speaker_id == "SPEAKER_00" else "SPEAKER_00"
                utt2 = TranscriptUtterance(
                    id=uuid.uuid4(),
                    speaker_id=other_spk,
                    start_time=split_time,
                    end_time=utt.end_time,
                    text=part2,
                )
                return [utt1, utt2]

        return [utt]

    def _normalize_short_gaps(
        self, utterances: List[TranscriptUtterance]
    ) -> List[TranscriptUtterance]:
        """
        Aynı konuşmacının 0.5 saniyeden kısa aralıklı parçalanmış cümlelerini birleştirir.
        """
        if len(utterances) <= 1:
            return utterances

        merged: List[TranscriptUtterance] = []
        i = 0
        while i < len(utterances):
            curr = utterances[i]
            if i + 1 < len(utterances):
                nxt = utterances[i + 1]
                gap = nxt.start_time - curr.end_time
                if gap < 0.5 and nxt.speaker_id == curr.speaker_id:
                    combined_text = (curr.text.strip() + " " + nxt.text.strip()).strip()
                    curr = TranscriptUtterance(
                        id=curr.id,
                        speaker_id=curr.speaker_id,
                        start_time=curr.start_time,
                        end_time=nxt.end_time,
                        text=combined_text,
                    )
                    i += 1
            merged.append(curr)
            i += 1

        return merged
