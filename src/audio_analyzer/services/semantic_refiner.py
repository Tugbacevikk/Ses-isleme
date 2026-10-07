import uuid

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
        domain_mode: str | None = None,
        use_llm: bool | None = None,
        ollama_url: str | None = None,
        model_name: str | None = None,
        custom_triggers: dict[str, list[str]] | None = None,
        split_on_questions: bool | None = None,
    ):
        import os

        from audio_analyzer.config import get_settings

        settings = get_settings()
        self.domain_mode = domain_mode if domain_mode is not None else settings.domain_mode
        self.use_llm = use_llm if use_llm is not None else settings.use_llm
        self.ollama_url = ollama_url or settings.ollama_url
        self.model_name = model_name or settings.ollama_model
        self.split_on_questions = (
            split_on_questions
            if split_on_questions is not None
            else (os.getenv("SPLIT_ON_QUESTIONS", "false").lower() == "true")
        )

        # Varsayılan genel amaçlı modda alan tetikleyicileri boştur (domain-agnostic).
        self.agent_triggers: list[str] = []
        self.customer_triggers: list[str] = []

        # Yalnızca çağrı merkezi veya özel bir alan seçildiğinde kuralları yükle
        if self.domain_mode == "call_center":
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

    def _query_ollama_llm(self, prompt: str) -> str | None:
        """
        Yerel Ollama LLM servisine (Llama-3.2 / Qwen-2.5) istek atarak anlamsal analiz yaptırır.
        Ollama erişilebilir değilse None döner.
        """
        try:
            import json
            import os
            import urllib.request

            timeout_sec = float(os.getenv("OLLAMA_TIMEOUT_SEC", "10.0"))
            req = urllib.request.Request(
                self.ollama_url,
                data=json.dumps(
                    {"model": self.model_name, "prompt": prompt, "stream": False}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("response")
        except Exception:
            return None

    def refine(self, utterances: list[TranscriptUtterance]) -> list[TranscriptUtterance]:
        """
        Utterance listesini anlamsal cümle, hizalama ve tekrar temizliği kontrolüne sokar.
        """
        if not utterances:
            return []

        # 0. Halüsinatif kelime/sözcük grubu tekrarlarını ve imla hatalarını temizle
        cleaned_utterances: list[TranscriptUtterance] = []
        for u in utterances:
            cleaned_txt = self._clean_repetitive_text(u.text)
            cleaned_txt = self._normalize_turkish_text(cleaned_txt)
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

        # 1. LLM Modu aktifse ve PIPELINE_PROFILE != 'feedback' ise LLM adımını çağır
        import os
        pipeline_profile = os.getenv("PIPELINE_PROFILE", "full").lower()
        if self.use_llm and pipeline_profile != "feedback":
            self._refine_with_llm(utterances)

        # 2. Alan odaklı (domain_mode) kural tetikleyicileri tanımlıysa bölme kurallarını uygula
        refined: list[TranscriptUtterance] = []
        for utt in utterances:
            if self.agent_triggers or self.customer_triggers:
                split_result = self._split_if_role_transition(utt)
            else:
                split_result = [utt]

            # Soru işareti sonrası diyalog ve konuşmacı dönüşümlerini ayrıştır
            dialogue_split: list[TranscriptUtterance] = []
            for item in split_result:
                dialogue_split.extend(self._split_dialogue_turns(item))

            refined.extend(dialogue_split)

        # 3. Yalnızca çağrı merkezi (call_center) modunda açılış selamlamasını kitle (Role Anchoring)
        if self.domain_mode == "call_center":
            anchored_utterances = self._lock_opening_greetings(refined)
        else:
            anchored_utterances = refined

        return self._normalize_short_gaps(anchored_utterances)

    def _split_dialogue_turns(
        self, utt: TranscriptUtterance
    ) -> list[TranscriptUtterance]:
        """
        Diyalog kiti: Tek bir konuşmacı kartına birleştirilmiş olan
        soru-cevap ve diyalog cümlelerini ('?' işareti ve takip eden cümleler)
        alternatif konuşmacılara (SPEAKER_00 / SPEAKER_01) böler.
        """
        if not self.split_on_questions:
            return [utt]

        import re

        text = utt.text.strip()
        if not text or "?" not in text:
            return [utt]

        # '?' karakterinden sonra metin var mı kontrol et
        parts = re.split(r'(\?+)', text)
        if len(parts) <= 2:
            return [utt]

        segments: list[str] = []
        i = 0
        while i < len(parts):
            seg_text = parts[i].strip()
            if not seg_text:
                i += 1
                continue
            if i + 1 < len(parts) and parts[i + 1].startswith("?"):
                seg_text += "?"
                i += 2
            else:
                i += 1
            if seg_text:
                segments.append(seg_text)

        if len(segments) <= 1:
            return [utt]

        total_chars = max(len(text), 1)
        total_duration = utt.end_time - utt.start_time

        result: list[TranscriptUtterance] = []
        current_time = utt.start_time

        spk_0 = utt.speaker_id
        spk_1 = "SPEAKER_01" if spk_0 == "SPEAKER_00" else "SPEAKER_00"

        for idx, seg in enumerate(segments):
            seg_duration = (len(seg) / total_chars) * total_duration
            seg_end = round(current_time + seg_duration, 2)
            if idx == len(segments) - 1:
                seg_end = utt.end_time

            seg_spk = spk_0 if (idx % 2 == 0) else spk_1

            result.append(
                TranscriptUtterance(
                    id=uuid.uuid4(),
                    speaker_id=seg_spk,
                    start_time=round(current_time, 2),
                    end_time=seg_end,
                    text=seg,
                )
            )
            current_time = seg_end

        return result

    def _clean_repetitive_text(self, text: str) -> str:
        """
        Ardışık 3 veya daha fazla olan halüsinatif kelime ve kelime öbeği tekrarlarını temizler.
        "yavaş yavaş", "evet evet", "güzel güzel" gibi 2'li ikilemelere dokunmaz.
        """
        if not text:
            return text

        words = text.strip().split()
        if not words:
            return text

        # 1. Ardışık 3+ kelime öbeği tekrarlarını temizle (örn: "bu sefer bu sefer bu sefer bu sefer" -> "bu sefer")
        if len(words) >= 6:
            new_words = []
            i = 0
            while i < len(words):
                if i + 5 < len(words):
                    p1 = [w.lower() for w in words[i:i+2]]
                    p2 = [w.lower() for w in words[i+2:i+4]]
                    p3 = [w.lower() for w in words[i+4:i+6]]
                    if p1 == p2 == p3:
                        new_words.extend(words[i:i+2])
                        i += 6
                        while i + 1 < len(words) and [w.lower() for w in words[i:i+2]] == p1:
                            i += 2
                        continue
                new_words.append(words[i])
                i += 1
            words = new_words

        # 2. Ardışık 3+ tekil kelimeleri temizle (2'li ikilemelere dokunma)
        if len(words) >= 3:
            new_words = []
            i = 0
            while i < len(words):
                j = i
                while j < len(words) and words[j].lower() == words[i].lower():
                    j += 1
                repeat_count = j - i
                if repeat_count >= 3:
                    new_words.append(words[i])
                else:
                    new_words.extend(words[i:j])
                i = j
            words = new_words

        text = " ".join(words)

        parts = [p.strip() for p in text.split(",") if p.strip()]
        if parts:
            cleaned_parts = []
            i = 0
            while i < len(parts):
                j = i
                while j < len(parts) and parts[j].lower() == parts[i].lower():
                    j += 1
                repeat_count = j - i
                if repeat_count >= 3:
                    cleaned_parts.append(parts[i])
                else:
                    cleaned_parts.extend(parts[i:j])
                i = j
            text = ", ".join(cleaned_parts)

        return text

    def _normalize_turkish_text(self, text: str) -> str:
        """
        Türkçe imla ve birleşik kelime hatalarını (örn: "mi ?" -> "mi?") otomatik düzeltir.
        """
        if not text:
            return text

        import re

        # Soru işaretleri ve noktalamalardan önceki boşlukları temizle ("mi ?" -> "mi?")
        text = re.sub(r'\s+([\?\!\,\.\:\;])', r'\1', text)

        # Birleşik gün isimlerini ayır
        days = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
        for day in days:
            text = re.sub(rf'\b({day})(günü|gün|sabahı|akşamı)\b', r'\1 \2', text, flags=re.IGNORECASE)

        # Common phonetic STT typo corrections (Zero latency post-processing)
        replacements = [
            (r'\bbeyni\b(?=\s+(bırak|bırakır|yap|buton|atar|ver))', 'beğeni'),
            (r'\bbir\s+beyni\b', 'bir beğeni'),
            (r'\bArkadaşıar\b', 'Arkadaşlar'),
            (r'\barkadaşıar\b', 'arkadaşlar'),
            (r'\btüpçeyi\b', 'Türkçeyi'),
            (r'\btüpçe\b', 'Türkçe'),
            (r'\bakıcık\b', 'Akıcı'),
        ]
        for pattern, repl in replacements:
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

        return text

    def _refine_with_llm(self, utterances: list[TranscriptUtterance]) -> list[TranscriptUtterance] | None:
        """
        Ollama LLM kullanarak diyalog bloklarını anlamsal olarak gözden geçirir (deneysel).
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "UYARI: LLM iyileştirme adımı deneyseldir; üretilen ham yanıt henüz yapılandırılmış çıktıya dönüştürülüp uygulanmamaktadır."
        )
        transcript_text = "\n".join([f"{u.speaker_id}: {u.text}" for u in utterances])
        prompt = (
            f"Aşağıdaki konuşma dökümünde konuşmacı geçişlerini kontrol et:\n\n{transcript_text}\n\n"
            "Düzeltilmiş konuşmacı bloklarını formatla."
        )
        self._query_ollama_llm(prompt)
        return None

    def _split_if_role_transition(self, utt: TranscriptUtterance) -> list[TranscriptUtterance]:
        text = utt.text.strip()
        text_lower = text.lower()

        all_triggers = self.agent_triggers + self.customer_triggers
        found_trigger = None
        split_idx = -1

        for trg in all_triggers:
            idx = text_lower.find(trg)
            if idx >= 10:
                split_idx = idx
                found_trigger = trg
                break

        if split_idx > 0 and found_trigger:
            part1 = text[:split_idx].strip()
            part2 = text[split_idx:].strip()

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

    def _lock_opening_greetings(
        self, utterances: list[TranscriptUtterance]
    ) -> list[TranscriptUtterance]:
        """
        Çağrı merkezi açılış selamlama cümlelerini (ilk 12 saniye içindeki 'buyurun', 'müşteri hizmetleri',
        'nasıl yardımcı olabilirim' vb.) tek bir temsilci (SPEAKER_00) kartına kilitler ve birleştirir.
        """
        if len(utterances) <= 1:
            return utterances

        greeting_keywords = [
            "müşteri hizmetleri",
            "hizmetleri birimi",
            "hoş geldiniz",
            "çağrı merkezi",
            "temsilciniz",
        ]

        # İlk 12 saniye içindeki selamlama kartlarını tespit et
        opening_indices = []
        for idx, u in enumerate(utterances):
            if u.start_time <= 12.0:
                txt_lower = u.text.lower()
                if any(kw in txt_lower for kw in greeting_keywords):
                    opening_indices.append(idx)
            else:
                break

        # Eğer ilk 12 saniyede ardışık selamlama parçaları varsa hepsini SPEAKER_00 olarak birleştir
        if len(opening_indices) >= 2 and opening_indices == list(range(len(opening_indices))):
            primary_spk = utterances[0].speaker_id
            combined_text = " ".join(utterances[i].text.strip() for i in opening_indices)
            start_t = utterances[0].start_time
            end_t = utterances[opening_indices[-1]].end_time

            anchored_utt = TranscriptUtterance(
                id=utterances[0].id,
                speaker_id=primary_spk,
                start_time=start_t,
                end_time=end_t,
                text=combined_text,
            )
            return [anchored_utt] + utterances[len(opening_indices):]

        return utterances

    def _normalize_short_gaps(
        self, utterances: list[TranscriptUtterance]
    ) -> list[TranscriptUtterance]:
        """
        Aynı konuşmacının 0.6 saniyeden kısa aralıklı parçalanmış cümlelerini ve
        noktalama ile bitmemiş yarım cümleleri (mid-sentence split) tek bir konuşmacı kartında birleştirir.
        """
        if len(utterances) <= 1:
            return utterances

        import os

        max_silence_threshold = float(os.getenv("MAX_SILENCE_THRESHOLD", "1.5"))
        max_clause_gap = float(os.getenv("MAX_CLAUSE_GAP", "1.5"))

        merged: list[TranscriptUtterance] = []
        i = 0
        while i < len(utterances):
            curr = utterances[i]
            while i + 1 < len(utterances):
                nxt = utterances[i + 1]
                gap = nxt.start_time - curr.end_time
                curr_text = curr.text.strip()
                nxt_text = nxt.text.strip()

                if not curr_text or not nxt_text:
                    break

                # Birleştirme yalnızca aynı konuşmacı (nxt.speaker_id == curr.speaker_id) ise yapılır
                is_same_speaker = (gap <= max_silence_threshold and nxt.speaker_id == curr.speaker_id)

                curr_is_unpunctuated = not curr_text.endswith((".", "?", "!", ":", ";", "…"))

                is_clause_split = (
                    gap <= max_clause_gap
                    and curr_is_unpunctuated
                    and nxt.speaker_id == curr.speaker_id
                )

                if is_same_speaker or is_clause_split:
                    combined_text = (curr_text + " " + nxt_text).strip()
                    curr = TranscriptUtterance(
                        id=curr.id,
                        speaker_id=curr.speaker_id,
                        start_time=curr.start_time,
                        end_time=nxt.end_time,
                        text=combined_text,
                    )
                    i += 1
                else:
                    break
            merged.append(curr)
            i += 1

        return merged
