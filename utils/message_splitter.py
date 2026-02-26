"""
Utilitário para dividir mensagens longas em partes menores
Similar ao código JavaScript do n8n
"""
import re
from typing import List


def split_message(text: str, preserve_paragraphs: bool = True) -> List[str]:
    """
    Divide uma mensagem longa em partes menores para envio natural via WhatsApp

    Args:
        text: Texto original
        preserve_paragraphs: Se True, divide primeiro por parágrafos

    Returns:
        Lista de mensagens menores
    """
    if not text or not isinstance(text, str):
        return []

    # Remove aspas extras
    text = text.strip().strip('"').strip("'")

    # Converte **texto** para *texto*
    text = re.sub(r"\*\*(.*?)\*\*", r"*\1*", text)

    # Remove emojis (baseado no regex do n8n)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002600-\U000026FF"  # misc symbols
        "\U00002700-\U000027BF"  # dingbats
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)

    # Remove travessões (baseado nas regras do prompt)
    text = text.replace(" — ", " ")
    text = text.replace("—", "")
    text = text.replace(" – ", " ")
    text = text.replace("–", "")

    if preserve_paragraphs:
        # Divide por quebras de linha primeiro
        parts = text.split("\n")
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) > 1:
            return parts

    # Se não dividiu por parágrafos, divide por pontuação
    # Regex similar ao do n8n para dividir em sentenças
    sentences = _split_by_punctuation(text)

    return sentences


def _split_by_punctuation(text: str) -> List[str]:
    """
    Divide texto por pontuação final (. ! ?)
    Preserva URLs, emails e números com ponto
    """
    # Padrão para identificar URLs e emails (não dividir nesses casos)
    url_email_pattern = r"(https?://[^\s]+|www\.[^\s]+|\b[\w.-]+@[a-zA-Z.-]+\.[a-zA-Z]{2,6}\b)"

    # Protege URLs e emails
    protected = {}
    counter = 0

    def protect(match):
        nonlocal counter
        key = f"__PROTECTED_{counter}__"
        protected[key] = match.group(0)
        counter += 1
        return key

    text = re.sub(url_email_pattern, protect, text)

    # Divide por . ! ? seguidos de espaço ou fim de string
    # Mas não divide números decimais (1.5, 3.14, etc)
    sentences = []
    current = ""

    i = 0
    while i < len(text):
        char = text[i]
        current += char

        # Verifica se é final de sentença
        if char in ".!?":
            # Verifica se não é número decimal
            is_decimal = False
            if char == "." and i > 0 and i < len(text) - 1:
                prev_char = text[i - 1]
                next_char = text[i + 1]
                if prev_char.isdigit() and next_char.isdigit():
                    is_decimal = True

            # Se não é decimal e é seguido de espaço ou fim
            if not is_decimal:
                if i == len(text) - 1 or (i < len(text) - 1 and text[i + 1] == " "):
                    sentence = current.strip()
                    if sentence:
                        sentences.append(sentence)
                    current = ""
                    # Pula espaço após pontuação
                    if i < len(text) - 1 and text[i + 1] == " ":
                        i += 1

        i += 1

    # Adiciona resto se houver
    if current.strip():
        sentences.append(current.strip())

    # Restaura URLs e emails
    result = []
    for sentence in sentences:
        for key, value in protected.items():
            sentence = sentence.replace(key, value)
        result.append(sentence)

    return result if result else [text]


def merge_short_sentences(sentences: List[str], min_length: int = 20) -> List[str]:
    """
    Mescla sentenças muito curtas com a próxima

    Args:
        sentences: Lista de sentenças
        min_length: Tamanho mínimo para não mesclar

    Returns:
        Lista de sentenças mescladas
    """
    if len(sentences) <= 1:
        return sentences

    result = []
    i = 0

    while i < len(sentences):
        current = sentences[i]

        # Se a sentença é muito curta e não é a última
        if len(current) < min_length and i < len(sentences) - 1:
            # Mescla com a próxima
            current = f"{current} {sentences[i + 1]}"
            i += 1

        result.append(current)
        i += 1

    return result
