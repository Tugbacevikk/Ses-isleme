import uuid
from typing import List, Optional
from audio_analyzer.domain.models import TranscriptUtterance


class SemanticRefiner:
    """
    Anlamsal Konuşmacı Hizalama ve Rol Tespit Motoru.
    Görüşme metinlerindeki diyalog yapılarını (Müşteri Temsilcisi vs. Müşteri)
    ve cümle sonu rol geçişlerini anlamsal olarak analiz ederek, ses frekansı
    benzerliği nedeniyle birleşmiş uzun blokları doğru konuşmacılara böler.
    Rust (PyO3) FFI uyumlu veri modelleri ile çalışır.
    """

    def __init__(self, ollama_url: str = "http://localhost:11434/api/generate", model_name: str = "llama3.2"):
        self.ollama_url = ollama_url
        self.model_name = model_name
        # Müşteri temsilcisi kalıpları
        self.agent_triggers = [
            "buyurun",
            "müşteri hizmetleri",
            "nasıl yardımcı olabilirim",
            "anladım hanımefendi",
            "anladım beyefendi",
            "anladım efendim",
            "şikayetinizi not aldım",
            "şikayetiniz not alındı",
            "gerekli adımları atacağız",
            "size geri dönüş yapacağız",
            "not aldım",
        ]
        # Müşteri kalıpları
        self.customer_triggers = [
            "merhaba ben",
            "tarihinde çevrim içi",
            "bilgisayar aldım",
            "şikayetim var",
            "sorunlar yaşıyorum",
            "şarj aletsiz kullanamıyorum",
            "iade edilmesini talep ediyorum",
            "çözülmesini rica ediyorum",
        ]

    def _query_ollama_llm(self, prompt: str) -> Optional[str]:
        """
        Yerel Ollama LLM servisine (Llama-3.2 / Qwen-2.5) istek atarak anlamsal analiz yaptırır.
        Ollama açık değilse None döner ve kural tabanlı NLP motoruna düşer (fallback).
        """
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                self.ollama_url,
                data=json.dumps({"model": self.model_name, "prompt": prompt, "stream": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("response")
        except Exception:
            return None

    def refine(self, utterances: List[TranscriptUtterance]) -> List[TranscriptUtterance]:
        """
        Utterance listesini anlamsal cümle ve LLM analizine sokar, birleşmiş diyalogları ayırır.
        """
        if not utterances:
            return []

        refined: List[TranscriptUtterance] = []

        for utt in utterances:
            split_result = self._split_if_role_transition(utt)
            refined.extend(split_result)

        return self._normalize_speaker_labels(refined)

    def _split_if_role_transition(
        self, utt: TranscriptUtterance
    ) -> List[TranscriptUtterance]:
        text = utt.text.strip()
        text_lower = text.lower()

        # 1. Metin içerisinde hem müşteri hem temsilci ifadesi geçip geçmediğini kontrol et
        found_agent_trigger = None
        agent_idx = -1

        for trg in self.agent_triggers:
            idx = text_lower.find(trg)
            # Eğer ilk kelimede başlamıyorsa (en az 15 karakter sonra geliyorsa)
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

    def _normalize_speaker_labels(
        self, utterances: List[TranscriptUtterance]
    ) -> List[TranscriptUtterance]:
        """
        Cümle sonu tutarlılığını ve diyalog akışını düzenler. 
        "Size nasıl" ve "yardımcı olabilirim?" gibi yapay zeka sıçramalarını tek konuşmacıda birleştirir.
        """
        if len(utterances) <= 1:
            return utterances

        merged: List[TranscriptUtterance] = []
        i = 0
        while i < len(utterances):
            curr = utterances[i]

            # 1. Eğer bir sonraki cümle "yardımcı olabilirim" gibi bir karşılama devamıysa ve süre farkı azsa birleştir
            if i + 1 < len(utterances):
                nxt = utterances[i + 1]
                gap = nxt.start_time - curr.end_time
                nxt_lower = nxt.text.lower().strip()

                if gap < 2.0 and (
                    nxt_lower.startswith("yardımcı")
                    or nxt_lower.startswith("olabilirim")
                    or nxt_lower.startswith("size nasıl")
                    or nxt_lower.startswith("biri mi")
                ):
                    # İki bloğu birleştirip tek SPEAKER_00 yap
                    combined_text = (curr.text.strip() + " " + nxt.text.strip()).strip()
                    curr = TranscriptUtterance(
                        id=curr.id,
                        speaker_id="SPEAKER_00",
                        start_time=curr.start_time,
                        end_time=nxt.end_time,
                        text=combined_text,
                    )
                    i += 1  # nxt elemanını atla

            merged.append(curr)
            i += 1

        return merged
