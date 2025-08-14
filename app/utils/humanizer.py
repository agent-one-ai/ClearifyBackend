import random
import re
from collections import Counter

class Humanizer:
    def __init__(self):
        # Dizionario sinonimi molto più esteso e contestuale
        self.contextual_synonyms = {
            # Verbi comuni AI
            "analyze": ["examine", "look at", "check out", "dig into", "study", "review", "assess", "evaluate"],
            "demonstrate": ["show", "prove", "illustrate", "make clear", "exhibit", "reveal", "display"],
            "indicate": ["suggest", "point to", "hint at", "show", "reveal", "imply", "signal"],
            "establish": ["set up", "create", "build", "form", "develop", "put in place", "institute"],
            "facilitate": ["help", "make easier", "assist", "enable", "support", "aid", "smooth the way"],
            "implement": ["put into action", "carry out", "execute", "apply", "use", "deploy", "roll out"],
            "optimize": ["improve", "enhance", "perfect", "fine-tune", "make better", "streamline"],
            
            # Aggettivi formali tipici AI
            "comprehensive": ["complete", "thorough", "extensive", "full", "detailed", "all-encompassing"],
            "significant": ["important", "major", "big", "notable", "considerable", "meaningful"],
            "substantial": ["large", "considerable", "major", "significant", "hefty", "sizable"],
            "efficient": ["effective", "productive", "streamlined", "smooth", "well-organized"],
            "robust": ["strong", "solid", "reliable", "sturdy", "durable", "stable"],
            "innovative": ["creative", "new", "fresh", "original", "cutting-edge", "groundbreaking"],
            
            # Sostantivi formali
            "methodology": ["method", "approach", "way", "system", "process", "technique"],
            "framework": ["structure", "system", "model", "setup", "foundation", "base"],
            "implementation": ["execution", "application", "use", "deployment", "rollout"],
            "utilization": ["use", "usage", "application", "employment", "exploitation"]
        }

        # Pattern AI molto specifici da sostituire
        self.ai_phrase_patterns = {
            # Frasi di apertura tipiche AI
            r"\bIt is important to note that\b": [
                "Keep in mind that", "Worth mentioning", "Here's the thing", "What's interesting is",
                "You should know", "Actually", "The reality is", "Honestly"
            ],
            r"\bIt should be noted that\b": [
                "Also", "Plus", "What's worth noting", "By the way", "Another thing"
            ],
            r"\bIt is worth noting that\b": [
                "Interestingly", "What's cool is", "Here's something", "Actually", "Get this"
            ],
            
            # Transizioni robotiche
            r"\bIn conclusion\b": [
                "So basically", "Bottom line", "To wrap this up", "Long story short", 
                "All in all", "When you boil it down", "At the end of the day"
            ],
            r"\bIn summary\b": [
                "So", "Basically", "To sum it up", "In short", "All told"
            ],
            r"\bFurthermore\b": [
                "Also", "Plus", "On top of that", "What's more", "And another thing",
                "Not only that, but", "Beyond that"
            ],
            r"\bMoreover\b": [
                "Also", "Plus", "And", "What's more", "On top of that", "Besides"
            ],
            r"\bAdditionally\b": [
                "Also", "Plus", "And", "On top of that", "What's more", "Besides that"
            ],
            r"\bConsequently\b": [
                "So", "As a result", "Because of this", "This means", "Therefore"
            ],
            
            # Frasi di chiusura AI
            r"\bOverall\b": [
                "All in all", "Generally speaking", "For the most part", "By and large",
                "On the whole", "Taking everything together"
            ],
            
            # Pattern di certezza eccessiva
            r"\bClearly\b": [
                "Obviously", "It seems like", "Apparently", "From what I can tell", "Looks like"
            ],
            r"\bUndoubtedly\b": [
                "Probably", "Most likely", "I'd say", "Seems like", "Pretty sure"
            ],
            r"\bCertainly\b": [
                "Definitely", "For sure", "Absolutely", "No doubt", "Of course"
            ]
        }

        # Marcatori di incertezza e soggettività umana
        self.uncertainty_markers = [
            "I think", "I believe", "It seems to me", "In my opinion", "From my perspective",
            "I'd say", "I reckon", "My guess is", "I suspect", "It appears", "Probably",
            "Maybe", "Perhaps", "Possibly", "Likely", "I'm not entirely sure, but"
        ]

        # Espressioni colloquiali e informali
        self.colloquial_expressions = [
            "you know", "I mean", "like", "sort of", "kind of", "basically", "actually",
            "honestly", "frankly", "to be honest", "if you ask me", "the way I see it"
        ]

        # Connettori più naturali e vari
        self.natural_connectors = [
            "But here's the thing", "Now", "So", "Well", "Actually", "You see",
            "The thing is", "What's interesting is", "Here's what happened", "Turns out"
        ]

        # Pattern di ripetizione e ridondanza (tipici umani)
        self.redundancy_patterns = [
            " - I mean, ", " - or rather, ", " - well, ", " - you know, ",
            " (if that makes sense)", " (you get the idea)", " (or something like that)"
        ]

        # Errori grammaticali minori intenzionali
        self.intentional_errors = {
            " who ": [" who ", " that "],  # 70% who, 30% that per variazione
            " which ": [" which ", " that "],
            " different ": [" different ", " various ", " varying "],
        }

    def add_perplexity_variation(self, text):
        """Aggiunge variazione nella scelta delle parole per aumentare la perplexity"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        modified_sentences = []
        
        for sentence in sentences:
            words = sentence.split()
            if len(words) > 5:  # Solo per frasi sufficientemente lunghe
                # Cambia casualmente alcune parole con sinonimi meno ovvi
                for i in range(len(words)):
                    word = words[i].lower().strip('.,!?;:')
                    if word in self.contextual_synonyms and random.random() < 0.3:
                        # Sceglie sinonimo meno comune (non il primo della lista)
                        synonyms = self.contextual_synonyms[word]
                        if len(synonyms) > 1:
                            # Preferisce sinonimi dalla metà della lista in poi
                            preferred_syns = synonyms[len(synonyms)//2:]
                            words[i] = words[i].replace(word, random.choice(preferred_syns))
            
            modified_sentences.append(' '.join(words))
        
        return ' '.join(modified_sentences)

    def add_human_uncertainty(self, text):
        """Aggiunge marcatori di incertezza tipicamente umani"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        for i in range(len(sentences)):
            if random.random() < 0.2:  # 20% delle frasi
                uncertainty = random.choice(self.uncertainty_markers)
                # Inserisce l'incertezza in posizioni naturali
                if sentences[i].startswith(('The ', 'This ', 'That ')):
                    sentences[i] = uncertainty + ", " + sentences[i].lower()
                else:
                    sentences[i] = uncertainty + " " + sentences[i].lower()
        
        return ' '.join(sentences)

    def add_conversational_flow(self, text):
        """Aggiunge elementi di conversazione naturale"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        for i in range(len(sentences)):
            # Aggiunge espressioni colloquiali
            if random.random() < 0.15:
                colloquial = random.choice(self.colloquial_expressions)
                # Inserisce in posizioni strategiche
                words = sentences[i].split()
                if len(words) > 4:
                    insert_pos = random.randint(2, len(words)-2)
                    words.insert(insert_pos, f"({colloquial})")
                    sentences[i] = ' '.join(words)
            
            # Aggiunge connettori naturali all'inizio di alcune frasi
            if i > 0 and random.random() < 0.1:
                connector = random.choice(self.natural_connectors)
                sentences[i] = connector + ", " + sentences[i].lower()
        
        return ' '.join(sentences)

    def vary_sentence_structure(self, text):
        """Varia la struttura delle frasi per sembrare più umano"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        modified = []
        
        for sentence in sentences:
            words = sentence.split()
            
            # Occasionalmente divide frasi lunghe
            if len(words) > 20 and random.random() < 0.4:
                mid_point = len(words) // 2
                # Trova una buona posizione per dividere
                for j in range(mid_point-3, mid_point+3):
                    if j < len(words) and words[j].endswith((',', ';')):
                        first_part = ' '.join(words[:j+1])
                        second_part = ' '.join(words[j+1:])
                        modified.append(first_part)
                        modified.append(second_part)
                        break
                else:
                    # Se non trova virgole, divide comunque
                    first_part = ' '.join(words[:mid_point]) + ","
                    second_part = ' '.join(words[mid_point:])
                    modified.append(first_part)
                    modified.append(second_part)
            else:
                # Occasionalmente inizia con congiunzioni
                if random.random() < 0.1 and len(modified) > 0:
                    conjunctions = ["But", "And", "So", "Yet", "Still"]
                    sentence = random.choice(conjunctions) + " " + sentence.lower()
                
                modified.append(sentence)
        
        return ' '.join(modified)

    def add_personal_touches(self, text):
        """Aggiunge tocchi personali e soggettivi"""
        personal_intros = [
            "In my experience, ", "What I've noticed is ", "From what I've seen, ",
            "I've found that ", "What strikes me is ", "Personally, I think "
        ]
        
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        # Aggiunge introduzioni personali ad alcune frasi
        for i in range(len(sentences)):
            if i == 0 or (random.random() < 0.1 and i > 2):
                intro = random.choice(personal_intros)
                sentences[i] = intro + sentences[i].lower()
        
        return ' '.join(sentences)

    def add_hesitation_and_correction(self, text):
        """Aggiunge esitazioni e auto-correzioni tipiche del linguaggio umano"""
        correction_patterns = [
            " - well, actually, ", " - or should I say, ", " - I mean, ",
            " - at least, that's what I think", " - though I could be wrong"
        ]
        
        sentences = text.split('. ')
        
        for i in range(len(sentences)):
            if random.random() < 0.08:  # 8% delle frasi
                words = sentences[i].split()
                if len(words) > 6:
                    insert_pos = random.randint(3, len(words)-2)
                    correction = random.choice(correction_patterns)
                    words.insert(insert_pos, correction)
                    sentences[i] = ' '.join(words)
        
        return '. '.join(sentences)

    def reduce_ai_vocabulary(self, text):
        """Sostituisce parole tipicamente AI con alternative più umane"""
        # Sostituzioni specifiche per vocabolario AI
        ai_vocab_replacements = {
            "utilize": "use",
            "facilitate": "help",
            "demonstrate": "show",
            "indicate": "suggest",
            "substantial": "big",
            "comprehensive": "complete",
            "methodology": "method",
            "implementation": "use",
            "optimization": "improvement",
            "enhancement": "improvement",
            "parameter": "setting",
            "paradigm": "approach",
            "infrastructure": "system",
            "instantiate": "create",
            "aggregation": "combination",
            "preliminary": "initial",
        }
        
        for ai_word, human_word in ai_vocab_replacements.items():
            text = re.sub(r'\b' + ai_word + r'\b', human_word, text, flags=re.IGNORECASE)
        
        return text

    def vary_sentence_length_naturally(self, text):
        """Crea variazione naturale nella lunghezza delle frasi"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        
        i = 0
        while i < len(sentences):
            current = sentences[i]
            words = current.split()
            
            # Se la frase è molto lunga, prova a spezzarla
            if len(words) > 25:
                # Cerca punti naturali di divisione
                for j in range(10, len(words)-5):
                    if words[j] in ['and', 'but', 'or', 'because', 'since', 'while', 'when']:
                        part1 = ' '.join(words[:j]) + '.'
                        part2 = ' '.join(words[j:])
                        result.append(part1)
                        result.append(part2)
                        break
                else:
                    result.append(current)
            
            # Se la frase è molto corta, occasionalmente combinala con la successiva
            elif len(words) < 5 and i < len(sentences) - 1 and random.random() < 0.3:
                next_sentence = sentences[i + 1]
                combined = current.rstrip('.!?') + ', and ' + next_sentence.lower()
                result.append(combined)
                i += 1  # Salta la prossima frase
            else:
                result.append(current)
            
            i += 1
        
        return ' '.join(result)

    def humanize(self, text):
        """Processo completo di umanizzazione"""
        # Fase 1: Rimozione pattern AI evidenti
        for pattern, replacements in self.ai_phrase_patterns.items():
            text = re.sub(pattern, lambda _: random.choice(replacements), text)
        
        # Fase 2: Riduzione vocabolario AI
        text = self.reduce_ai_vocabulary(text)
        
        # Fase 3: Aggiunta variazione perplexity
        text = self.add_perplexity_variation(text)
        
        # Fase 4: Aggiunta incertezza umana
        text = self.add_human_uncertainty(text)
        
        # Fase 5: Flusso conversazionale
        text = self.add_conversational_flow(text)
        
        # Fase 6: Variazione struttura frasi
        text = self.vary_sentence_structure(text)
        
        # Fase 7: Tocchi personali
        text = self.add_personal_touches(text)
        
        # Fase 8: Esitazioni e correzioni
        text = self.add_hesitation_and_correction(text)
        
        # Fase 9: Variazione lunghezza frasi
        text = self.vary_sentence_length_naturally(text)
        
        # Fase 10: Pulizia finale
        text = re.sub(r'\s+', ' ', text)  # Rimuove spazi multipli
        text = re.sub(r' ,', ',', text)   # Corregge spazi prima delle virgole
        text = text.strip()
        
        return text