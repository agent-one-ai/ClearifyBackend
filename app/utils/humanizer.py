import random
import re
from collections import Counter, deque
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from abc import ABC, abstractmethod
import math

@dataclass
class TextAnalysis:
    """Analisi completa dello stile del testo"""
    formality_score: float
    technical_score: float
    avg_sentence_length: float
    vocabulary_complexity: float
    target_tone: str
    paragraph_count: int
    sentence_count: int
    word_count: int
    unique_word_ratio: float
    is_already_human: bool
    existing_colloquial_count: int

@dataclass
class ModificationConfig:
    """Configurazione delle modifiche basata sul contesto"""
    uncertainty_probability: float
    colloquial_probability: float
    sentence_variation: float
    personal_touches: float
    synonym_replacement: float
    structure_modification: float
    max_modifications_per_sentence: int

class LanguageProcessor(ABC):
    """Classe astratta per processori linguistici specifici"""
    
    @abstractmethod
    def get_synonyms(self) -> Dict[str, List[str]]:
        pass
    
    @abstractmethod
    def get_phrase_patterns(self) -> Dict[str, List[str]]:
        pass
    
    @abstractmethod
    def get_uncertainty_markers(self) -> List[str]:
        pass

class EnglishProcessor(LanguageProcessor):
    """Processore per lingua inglese - Ottimizzato per ZeroGPT"""
    
    def get_synonyms(self) -> Dict[str, List[str]]:
        return {
            # Sinonimi "imperfetti" ma umani
            "analyze": ["examine", "look at", "study", "review"],
            "demonstrate": ["show", "display", "reveal", "exhibit"],
            "indicate": ["suggest", "show", "point to", "signal"],
            "establish": ["set up", "create", "build", "form"],
            "facilitate": ["simplify", "enable", "help", "support"],
            "implement": ["apply", "use", "carry out", "deploy"],
            "optimize": ["maximize", "improve", "enhance"],
            "utilize": ["use", "employ", "apply"],
            
            # Aggettivi - versioni più umane
            "comprehensive": ["rich", "extensive", "broad", "wide"],
            "significant": ["important", "major", "actual", "real"],
            "substantial": ["actual", "real", "considerable", "major"],
            "efficient": ["effective", "productive", "smooth"],
            "robust": ["strong", "solid", "powerful", "reliable"],
            "innovative": ["creative", "new", "fresh", "original"],
            "crucial": ["vital", "key", "essential", "important"],
            "adequate": ["sufficient", "enough", "suitable"],
            "numerous": ["various", "many", "multiple"],
            
            # Sostantivi - varianti più naturali
            "methodology": ["method", "approach", "way"],
            "framework": ["structure", "system", "model"],
            "implementation": ["application", "use", "deployment"],
            "utilization": ["use", "usage", "application"],
            "paradigm": ["shift", "change", "model"],
            "infrastructure": ["system", "structure", "framework"],
            "datasets": ["data sets", "training sets"],
            "systems": ["machines", "solutions", "tools"],
            
            # Verbi più umani
            "subsequently": ["later", "then", "after that", "next"],
            "previously": ["before", "earlier", "prior"],
            "approximately": ["about", "around", "roughly"],
            "achieve": ["reach", "attain", "get to"],
            "require": ["need", "demand", "call for"],
            "enable": ["allow", "let", "permit"],
        }
    
    def get_phrase_patterns(self) -> Dict[str, List[str]]:
        return {
            r"\bWhat(?:'s| I've noticed| I noticed)?\s+(?:interesting|notable|cool|wild) is\b": [""],
            r"\bWhat I've (?:noticed|found|seen) is\b": [""],
            r"\bPersonally,?\s+I think\b": [""],
            r"\bWhat matters is\b": [""],
            r"\bThe thing is,?\b": [""],
            r"\bHere's the thing,?\b": [""],
            r"\bAt the end of the day,?\b": [""],
            r"\bIt is important to note that\b": [""],
            r"\bIt should be noted that\b": [""],
            r"\bIt is worth noting that\b": [""],
            r"\bIt is essential to\b": [""],
            r"\bIn conclusion\b": [""],
            r"\bIn summary\b": [""],
            r"\bFurthermore,?\b": [""],
            r"\bMoreover,?\b": [""],
            r"\bAdditionally,?\b": [""],
            r"\bConsequently,?\b": [""],
            r"\bNevertheless,?\b": ["However"],
            r"\bNotwithstanding,?\b": [""],
            r"\bSubsequently,?\b": [""],
            r"\bClearly,?\b": [""],
            r"\bUndoubtedly,?\b": [""],
            r"\bCertainly,?\b": [""],
            r"\bObviously,?\b": [""],
            r"\bAs an AI( language model)?\b": [""],
        }
    
    def get_uncertainty_markers(self) -> List[str]:
        return []  # Disabilitato per ZeroGPT

class TextAnalyzer:
    """Analizza il testo per determinare lo stile e il tono"""
    
    def __init__(self):
        self.formal_indicators = [
            'moreover', 'furthermore', 'consequently', 'thus', 'therefore',
            'nevertheless', 'notwithstanding', 'subsequently', 'accordingly',
            'hence', 'wherein', 'whereby', 'henceforth'
        ]
        
        self.technical_indicators = [
            'algorithm', 'function', 'parameter', 'variable', 'implementation',
            'methodology', 'framework', 'architecture', 'protocol', 'interface',
            'optimization', 'configuration', 'initialization', 'instantiation'
        ]
        
        self.casual_indicators = [
            "you know", "I mean", "like", "basically", "actually", "honestly",
            "really", "pretty", "quite", "just", "maybe", "kinda", "sorta"
        ]
        
        self.human_indicators_patterns = [
            r'[!]{1,3}', r'[?]', r'[\U0001F600-\U0001F64F]',
            r'\b(I\'m|I\'ve|I\'ll|can\'t|won\'t|don\'t)\b',
            r'\b(my|our|we|us)\b',
        ]
    
    def analyze(self, text: str) -> TextAnalysis:
        sentences = self._split_sentences(text)
        words = text.split()
        words_clean = [w.lower().strip('.,!?;:()[]{}') for w in words if w.strip()]
        
        word_count = len(words_clean)
        sentence_count = len(sentences)
        paragraph_count = text.count('\n\n') + 1
        avg_sentence_length = word_count / sentence_count if sentence_count > 0 else 0
        unique_words = len(set(words_clean))
        unique_word_ratio = unique_words / word_count if word_count > 0 else 0
        complex_words = [w for w in words_clean if len(w) > 12]
        vocabulary_complexity = len(complex_words) / word_count if word_count > 0 else 0
        
        formal_count = sum(1 for word in words_clean if word in self.formal_indicators)
        casual_count = sum(1 for word in words_clean if word in self.casual_indicators)
        formality_score = min(10, max(0, (formal_count / sentence_count * 30) - (casual_count / sentence_count * 20)))
        
        technical_count = sum(1 for word in words_clean if word in self.technical_indicators)
        technical_score = min(10, (technical_count / sentence_count) * 40 + vocabulary_complexity * 30)
        
        target_tone = self._determine_tone(formality_score, technical_score, casual_count)
        is_already_human = self._is_already_human(text, formality_score, casual_count)
        existing_colloquial = sum(1 for indicator in self.casual_indicators 
                                 if re.search(r'\b' + re.escape(indicator) + r'\b', text.lower()))
        
        return TextAnalysis(
            formality_score=formality_score,
            technical_score=technical_score,
            avg_sentence_length=avg_sentence_length,
            vocabulary_complexity=vocabulary_complexity,
            target_tone=target_tone,
            paragraph_count=paragraph_count,
            sentence_count=sentence_count,
            word_count=word_count,
            unique_word_ratio=unique_word_ratio,
            is_already_human=is_already_human,
            existing_colloquial_count=existing_colloquial
        )
    
    def _is_already_human(self, text: str, formality_score: float, casual_count: int) -> bool:
        human_score = 0
        for pattern in self.human_indicators_patterns:
            if re.search(pattern, text):
                human_score += 1
        if formality_score < 4:
            human_score += 1
        if casual_count >= 3:
            human_score += 1
        if re.search(r'\b(I|my|our)\b', text):
            human_score += 1
        return human_score >= 3
    
    def _split_sentences(self, text: str) -> List[str]:
        sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def _determine_tone(self, formality: float, technicality: float, casual_count: int) -> str:
        if formality > 7:
            return 'formal'
        elif technicality > 6:
            return 'technical'
        elif casual_count > 5 or formality < 3:
            return 'casual'
        elif formality > 5 and technicality > 4:
            return 'professional'
        else:
            return 'neutral'

class ModificationEngine:
    """Engine per applicare modifiche intelligenti al testo"""
    
    def __init__(self, language_processor: LanguageProcessor):
        self.lang = language_processor
        self.recently_used = deque(maxlen=50)
        self.used_in_current_text = set()
        
    def reset_current_text_tracking(self):
        self.used_in_current_text.clear()
        
    def get_config_for_tone(self, tone: str, is_already_human: bool) -> ModificationConfig:
        if is_already_human:
            return ModificationConfig(
                uncertainty_probability=0.0,
                colloquial_probability=0.0,
                sentence_variation=0.0,
                personal_touches=0.0,
                synonym_replacement=0.12,
                structure_modification=0.0,
                max_modifications_per_sentence=1
            )
        
        return ModificationConfig(
            uncertainty_probability=0.0,
            colloquial_probability=0.0,
            sentence_variation=0.0,
            personal_touches=0.0,
            synonym_replacement=0.40,  # Aumentato per più sostituzioni
            structure_modification=0.0,
            max_modifications_per_sentence=1
        )
    
    def replace_ai_phrases(self, text: str) -> str:
        """Sostituisce frasi tipicamente AI"""
        for pattern, replacements in self.lang.get_phrase_patterns().items():
            text = re.sub(pattern, lambda m: random.choice(replacements) if replacements else "", text, flags=re.IGNORECASE)
        return text
    
    def restructure_nominal_phrases(self, text: str) -> str:
        """NUOVO: Trasforma frasi nominali in verbali"""
        patterns = {
            r'The implementation of ([a-z\s]+)': r'\1 application',
            r'The optimization of ([a-z\s]+)': r'Optimizing \1',
            r'The development of ([a-z\s]+)': r'Developing \1',
            r'The establishment of ([a-z\s]+)': r'Establishing \1',
            r'The integration of ([a-z\s]+)': r'Integrating \1',
            r'The utilization of ([a-z\s]+)': r'Using \1',
        }
        
        for pattern, replacement in patterns.items():
            text = re.sub(pattern, replacement, text)
        
        return text
    
    def reduce_the_repetition(self, text: str) -> str:
        """NUOVO: Riduce 'The' ripetitivo all'inizio delle frasi"""
        sentences = self._split_sentences_advanced(text)
        the_count = 0
        result = []
        
        for sentence in sentences:
            if sentence.startswith('The '):
                the_count += 1
                if the_count > 2:  # Max 2 "The" consecutive
                    # Rimuovi "The" e adatta la frase
                    modified = sentence[4:]  # Rimuovi "The "
                    if modified:
                        modified = modified[0].upper() + modified[1:]
                        result.append(modified)
                        the_count = 0
                else:
                    result.append(sentence)
            else:
                the_count = 0
                result.append(sentence)
        
        return ' '.join(result)
    
    def add_human_imperfections(self, text: str) -> str:
        """NUOVO: Aggiunge costruzioni leggermente awkward ma umane"""
        patterns = {
            r'to achieve (\w+) performance': r'in their efforts to maximize \1',
            r'to achieve optimal': r'working towards best',
            r'while maintaining (\w+) standards': r'amidst keeping \1 standards intact',
            r'(\w+) numerous industries': r'\1 world of various industries',
            r'for automated decisions': r'for decisions made independently',
            r'throughout the (\w+) process': r'during \1',
        }
        
        for pattern, replacement in patterns.items():
            if random.random() < 0.6:  # 60% probabilità
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        return text
    
    def replace_synonyms_contextual(self, text: str, config: ModificationConfig, formality_level: str) -> str:
        """Sostituisce parole con sinonimi contestuali"""
        words = text.split()
        synonyms_dict = self.lang.get_synonyms()
        
        for i, word in enumerate(words):
            word_clean = word.lower().strip('.,!?;:()[]{}')
            
            if word_clean in synonyms_dict and random.random() < config.synonym_replacement:
                if word_clean in list(self.recently_used)[-5:]:
                    continue
                
                synonym = self._choose_best_synonym(
                    word_clean, 
                    synonyms_dict[word_clean],
                    formality_level
                )
                
                if word[0].isupper():
                    synonym = synonym.capitalize()
                
                punctuation = ''.join(c for c in word if c in '.,!?;:')
                words[i] = synonym + punctuation
                self.recently_used.append(word_clean)
        
        return ' '.join(words)
    
    def _choose_best_synonym(self, word: str, synonyms: List[str], formality: str) -> str:
        """Sceglie il sinonimo migliore"""
        scored = []
        
        for syn in synonyms:
            score = 0
            
            # Preferisci sinonimi più corti e naturali
            score += (15 - len(syn) * 0.5)
            
            # Evita ripetizioni recenti
            if syn not in self.recently_used:
                score += 10
            
            # Preferisci sinonimi nel mezzo della lista
            middle_idx = len(synonyms) // 2
            distance_from_middle = abs(synonyms.index(syn) - middle_idx)
            score += (10 - distance_from_middle)
            
            scored.append((syn, score))
        
        top_syns = sorted(scored, key=lambda x: x[1], reverse=True)[:3]
        return random.choice(top_syns)[0]
    
    def _split_sentences_advanced(self, text: str) -> List[str]:
        """Split avanzato delle frasi"""
        if not isinstance(text, str) or not text.strip():
            return []
        sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s+', text)
        return [s.strip() for s in sentences if s and s.strip()]

class Humanizer:
    """Humanizer principale - Ottimizzato per ZeroGPT 0%"""
    
    def __init__(self, language: str = 'en'):
        self.language = language
        self.lang_processor = EnglishProcessor()
        self.analyzer = TextAnalyzer()
        self.modifier = ModificationEngine(self.lang_processor)
        
    def humanize(self, text: str, intensity: float = 0.6, preserve_formatting: bool = True) -> Dict:
        """
        Umanizza il testo - Ottimizzato per ZeroGPT
        
        Args:
            text: Testo da umanizzare
            intensity: Livello di modifiche (0.0-1.0) - DEFAULT 0.6
            preserve_formatting: Mantiene formattazione originale
            
        Returns:
            Dict con testo umanizzato e metriche
        """
        if not text or len(text.strip()) < 10:
            return {
                'original': text,
                'humanized': text,
                'analysis': None,
                'modifications_applied': 0
            }
        
        self.modifier.reset_current_text_tracking()
        analysis = self.analyzer.analyze(text)
        base_config = self.modifier.get_config_for_tone(analysis.target_tone, analysis.is_already_human)
        
        if analysis.is_already_human:
            intensity = min(intensity * 0.15, 0.1)
        
        scaled_config = self._scale_config(base_config, intensity)
        modified_text = text
        modifications_count = 0
        
        try:
            # Step 1: Rimuovi frasi AI
            modified_text = self.modifier.replace_ai_phrases(modified_text)
            modifications_count += 1
            
            if not analysis.is_already_human:
                # Step 2: Trasforma strutture nominali
                modified_text = self.modifier.restructure_nominal_phrases(modified_text)
                modifications_count += 1
                
                # Step 3: Sostituisci sinonimi
                modified_text = self.modifier.replace_synonyms_contextual(
                    modified_text, scaled_config, analysis.target_tone
                )
                modifications_count += 1
                
                # Step 4: Riduci "The" ripetitivo
                modified_text = self.modifier.reduce_the_repetition(modified_text)
                modifications_count += 1
                
                # Step 5: Aggiungi imperfezioni umane
                modified_text = self.modifier.add_human_imperfections(modified_text)
                modifications_count += 1
            
            # Step 6: Pulizia finale
            modified_text = self._intelligent_cleanup(modified_text)
            
        except Exception as e:
            print(f"Error during humanization: {e}")
            modified_text = text
        
        quality_metrics = self._calculate_quality_metrics(text, modified_text)
        
        return {
            'original': text,
            'humanized': modified_text,
            'analysis': analysis,
            'config_used': scaled_config,
            'modifications_applied': modifications_count,
            'quality_metrics': quality_metrics,
            'was_already_human': analysis.is_already_human
        }
    
    def _scale_config(self, config: ModificationConfig, intensity: float) -> ModificationConfig:
        """Scala la configurazione in base all'intensità"""
        return ModificationConfig(
            uncertainty_probability=config.uncertainty_probability * intensity,
            colloquial_probability=config.colloquial_probability * intensity,
            sentence_variation=config.sentence_variation * intensity,
            personal_touches=config.personal_touches * intensity,
            synonym_replacement=config.synonym_replacement * intensity,
            structure_modification=config.structure_modification * intensity,
            max_modifications_per_sentence=config.max_modifications_per_sentence
        )
    
    def _intelligent_cleanup(self, text: str) -> str:
        """Pulizia intelligente del testo"""
        # Fix spazi
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        
        # Rimuovi em-dash
        text = re.sub(r'[\s\xa0\u00A0]*[\u2014\u2013\u2012\u2015—–-]{1,3}[\s\xa0\u00A0]*', ', ', text)
        
        # Ripristina parole composte con trattino
        compound_words = [
            'decision-making', 'well-being', 'long-term', 'real-time',
            'short-term', 'high-quality', 'low-cost', 'full-time',
            'part-time', 'state-of-the-art', 'up-to-date'
        ]
        
        for compound in compound_words:
            broken = compound.replace('-', ',\s*')
            text = re.sub(r'\b' + broken + r'\b', compound, text, flags=re.IGNORECASE)
        
        # Rimuovi connettori doppi
        text = re.sub(r'\b(So|But|Well|Now|Also|Plus),\s+(So|But|Well|Now|Also|Plus)\b', 
                     r'\1', text, flags=re.IGNORECASE)
        
        # Fix capitalizzazione random in mezzo alle frasi
        words = text.split()
        for i in range(1, len(words)):
            word = words[i]
            if word and len(word) > 2 and word[0].isupper():
                if not words[i-1].endswith(('.', '!', '?')):
                    if word.lower() not in ['ai', 'api', 'http', 'sql', 'xml', 'html', 'css', 'json', 'url']:
                        words[i] = word[0].lower() + word[1:]
        text = ' '.join(words)
        
        # Rimuovi pattern AI residui
        text = re.sub(r'\bSubsequently,?\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bFurthermore,?\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bMoreover,?\s+', '', text, flags=re.IGNORECASE)
        
        # Fix punteggiatura
        text = re.sub(r'\.\s*,\s*', '. ', text)
        text = re.sub(r',\s+\.', '.', text)
        text = re.sub(r',\s*,+', ',', text)
        text = re.sub(r'\.\.+', '.', text)
        
        # Rimuovi spazi doppi
        text = re.sub(r'\s+', ' ', text)
        
        # Fix capitalizzazione inizio frasi
        sentences = re.split(r'([.!?]\s+)', text)
        for i in range(len(sentences)):
            if sentences[i] and len(sentences[i]) > 0 and sentences[i][0].isalpha():
                sentences[i] = sentences[i][0].upper() + sentences[i][1:]
        text = ''.join(sentences)
        
        # Fix prima lettera del testo
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        
        return text.strip()
    
    def _calculate_quality_metrics(self, original: str, modified: str) -> Dict:
        """Calcola metriche di qualità dell'umanizzazione"""
        if not isinstance(original, str):
            original = str(original) if original else ""
        if not isinstance(modified, str):
            modified = str(modified) if modified else ""
        
        if not original or not modified:
            return {
                'vocabulary_change_ratio': 0.0,
                'burstiness_increase': 0.0,
                'tone_preserved': True,
                'original_tone': 'neutral',
                'length_change_percent': 0.0,
                'formality_shift': 0.0,
                'readability_maintained': True
            }

        orig_analysis = self.analyzer.analyze(original)
        mod_analysis = self.analyzer.analyze(modified)
        
        orig_words = set(original.lower().split())
        mod_words = set(modified.lower().split())
        vocabulary_change = len(mod_words - orig_words) / len(orig_words) if orig_words else 0
        
        orig_sentences = self.analyzer._split_sentences(original)
        mod_sentences = self.analyzer._split_sentences(modified)
        
        orig_lengths = [len(s.split()) for s in orig_sentences]
        mod_lengths = [len(s.split()) for s in mod_sentences]
        
        orig_variance = self._calculate_variance(orig_lengths)
        mod_variance = self._calculate_variance(mod_lengths)
        burstiness_increase = (mod_variance - orig_variance) / (orig_variance + 1)
        
        tone_preserved = orig_analysis.target_tone == mod_analysis.target_tone
        length_change = (len(modified) - len(original)) / len(original) * 100 if original else 0
        
        return {
            'vocabulary_change_ratio': round(vocabulary_change, 3),
            'burstiness_increase': round(burstiness_increase, 3),
            'tone_preserved': tone_preserved,
            'original_tone': orig_analysis.target_tone,
            'length_change_percent': round(length_change, 2),
            'formality_shift': round(mod_analysis.formality_score - orig_analysis.formality_score, 2),
            'readability_maintained': abs(length_change) < 10
        }
    
    def _calculate_variance(self, numbers: List[int]) -> float:
        """Calcola la varianza"""
        if not numbers:
            return 0
        mean = sum(numbers) / len(numbers)
        variance = sum((x - mean) ** 2 for x in numbers) / len(numbers)
        return variance
    
    def batch_humanize(self, texts: List[str], intensity: float = 0.6) -> List[Dict]:
        """Umanizza batch di testi"""
        results = []
        for text in texts:
            result = self.humanize(text, intensity)
            results.append(result)
        return results
    
    def get_analysis_only(self, text: str) -> TextAnalysis:
        """Restituisce solo l'analisi"""
        return self.analyzer.analyze(text)


class HumanizerEvaluator:
    """Valuta la qualità dell'umanizzazione"""
    
    @staticmethod
    def evaluate_ai_detection_evasion(text: str) -> Dict:
        """Simula detection AI"""
        score = 100.0
        issues = []
        
        ai_patterns = [
            (r'\b(furthermore|moreover|additionally|consequently|subsequently)\b', -4, "Formal transitions"),
            (r'\bIt is important to note that\b', -5, "AI opening phrase"),
            (r'\b(comprehensive|robust|leverage|utilize|facilitate)\b', -2, "AI vocabulary"),
            (r'\.\s+The\s+', -1, "Monotonous sentence starts"),
            (r',\s+(making|being|term)\b', -3, "Broken compound words"),
            (r'\b(So|But|Also),\s+(So|But|Also)\b', -4, "Double connectors"),
            (r'The \w+ of', -0.5, "Nominal phrase pattern"),
        ]
        
        for pattern, penalty, description in ai_patterns:
            matches = len(re.findall(pattern, text, re.IGNORECASE))
            if matches > 0:
                score += penalty * matches
                issues.append(f"{description}: {matches} occurrences")
        
        score = max(0, min(100, score))
        
        return {
            'evasion_score': round(score, 2),
            'detection_risk': 'low' if score > 85 else 'medium' if score > 70 else 'high',
            'issues_found': issues,
            'recommendation': 'Excellent' if score > 85 else 'Good' if score > 70 else 'Needs improvement'
        }
    
    @staticmethod
    def compare_versions(original: str, humanized: str) -> Dict:
        """Confronta versione originale e umanizzata"""
        orig_detection = HumanizerEvaluator.evaluate_ai_detection_evasion(original)
        human_detection = HumanizerEvaluator.evaluate_ai_detection_evasion(humanized)
        improvement = human_detection['evasion_score'] - orig_detection['evasion_score']
        
        return {
            'original_score': orig_detection['evasion_score'],
            'humanized_score': human_detection['evasion_score'],
            'improvement': round(improvement, 2),
            'original_risk': orig_detection['detection_risk'],
            'humanized_risk': human_detection['detection_risk'],
            'original_issues': len(orig_detection['issues_found']),
            'humanized_issues': len(human_detection['issues_found']),
            'recommendation': 'Excellent humanization' if improvement > 15 else 'Good humanization' if improvement > 5 else 'Minimal improvement'
        }


def humanize_text(text: str, intensity: float = 0.6, language: str = 'en') -> str:
    """Funzione rapida per umanizzare testo"""
    humanizer = Humanizer(language=language)
    result = humanizer.humanize(text, intensity=intensity)
    return result['humanized']

def analyze_text(text: str, language: str = 'en') -> TextAnalysis:
    """Funzione rapida per analizzare testo"""
    humanizer = Humanizer(language=language)
    return humanizer.get_analysis_only(text)

def evaluate_humanization(original: str, humanized: str) -> Dict:
    """Funzione rapida per valutare qualità umanizzazione"""
    return HumanizerEvaluator.compare_versions(original, humanized)