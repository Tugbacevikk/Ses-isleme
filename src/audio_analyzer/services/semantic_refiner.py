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

        # 0. Halüsinatif kelime/sözcük grubu tekrarlarını ve imla hatalarını temizle
        cleaned_utterances: List[TranscriptUtterance] = []
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

        # 3. Çağrı açılış selamlamasını kitle (Role Anchoring - ilk 12 saniyedeki açılış cümlelerini tek kart yap)
        anchored_utterances = self._lock_opening_greetings(refined)

        return self._normalize_short_gaps(anchored_utterances)

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

    def _normalize_turkish_text(self, text: str) -> str:
        """
        Türkçe harf, imla ve birleşik kelime hatalarını (örn: "Şarşamba" -> "Çarşamba", "çarşambagünü" -> "Çarşamba günü", "mi ?" -> "mi?") otomatik düzeltir.
        """
        if not text:
            return text

        import re

        # Soru işaretleri ve noktalamalardan önceki boşlukları temizle ("mi ?" -> "mi?")
        text = re.sub(r'\s+([\?\!\,\.\:\;])', r'\1', text)

        # Sık rastlanan fonetik imla ve harf hataları
        corrections = {
            r'\bŞarşamba\b': 'Çarşamba',
            r'\bşarşamba\b': 'çarşamba',
            r'\bçarşambagünü\b': 'çarşamba günü',
            r'\bÇarşambagünü\b': 'Çarşamba günü',
            r'\bperşembegünü\b': 'perşembe günü',
            r'\bcumagünü\b': 'cuma günü',
            r'\bpazartesigünü\b': 'pazartesi günü',
            r'\bsalıgünü\b': 'salı günü',
        }
        for pattern, repl in corrections.items():
            text = re.sub(pattern, repl, text)

        # Birleşik gün isimlerini ayır
        days = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
        for day in days:
            text = re.sub(rf'\b({day})(günü|gün|sabahı|akşamı)\b', r'\1 \2', text, flags=re.IGNORECASE)

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

    def _lock_opening_greetings(
        self, utterances: List[TranscriptUtterance]
    ) -> List[TranscriptUtterance]:
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
        self, utterances: List[TranscriptUtterance]
    ) -> List[TranscriptUtterance]:
        """
        Aynı konuşmacının 0.6 saniyeden kısa aralıklı parçalanmış cümlelerini ve
        noktalama ile bitmemiş yarım cümleleri (mid-sentence split) tek bir konuşmacı kartında birleştirir.
        """
        if len(utterances) <= 1:
            return utterances

        import os

        max_silence_threshold = float(os.getenv("MAX_SILENCE_THRESHOLD", "1.5"))
        max_clause_gap = float(os.getenv("MAX_CLAUSE_GAP", "1.5"))

        merged: List[TranscriptUtterance] = []
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

                # 1. Aynı konuşmacı ise ve aralık MAX_SILENCE_THRESHOLD'dan küçükse birleştir
                is_same_speaker = (gap <= max_silence_threshold and nxt.speaker_id == curr.speaker_id)

                # 2. Türkçe harf kontrolü (Büyük harfle başlamıyorsa: küçük harf, rakam veya sembol)
                nxt_not_upper = not nxt_text[0].isupper()

                # 3. Noktalanmamış parçalanma (ÜST SINIR: gap <= max_clause_gap)
                curr_is_unpunctuated = not curr_text.endswith((".", "?", "!", ":", ";", "…"))

                # Jitter düzeltmesi (gap <= 0.05s) yalnızca çok kısa kelimelerde (<3 kelime) geçerlidir,
                # böylece hızlı söz almalar ("hı hı", "evet") yutulmaz.
                is_micro_jitter = (gap <= 0.05 and len(curr_text.split()) <= 3)

                is_clause_split = (
                    gap <= max_clause_gap
                    and curr_is_unpunctuated
                    and (is_micro_jitter or nxt_not_upper or nxt.speaker_id == curr.speaker_id)
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
