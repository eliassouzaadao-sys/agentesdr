"""
Lógica de decisão: quando usar áudio vs texto
"""
import re
from typing import Tuple


def should_use_audio(
    message: str,
    is_first_contact: bool = False,
    is_follow_up: bool = False,
    has_audio_tag: bool = False,
) -> Tuple[bool, str]:
    """
    Decide se deve enviar como áudio ou texto

    Args:
        message: Mensagem a ser enviada
        is_first_contact: Se é o primeiro contato com o lead
        is_follow_up: Se é uma mensagem de follow-up
        has_audio_tag: Se a mensagem tem tag [ENVIAR_AUDIO]

    Returns:
        Tuple[use_audio: bool, reason: str]
    """
    # Se tem tag explícita de áudio
    if has_audio_tag or "[ENVIAR_AUDIO]" in message:
        return True, "tag_audio"

    # Se tem links, números de telefone, emails - usar texto
    if _has_technical_content(message):
        return False, "conteudo_tecnico"

    # Se é muito curta (menos de 50 caracteres) - usar texto
    if len(message) < 50:
        return False, "mensagem_curta"

    # Primeiro contato - SEMPRE áudio (mais pessoal)
    if is_first_contact:
        return True, "primeiro_contato"

    # Follow-up depois de um tempo - áudio
    if is_follow_up:
        return True, "follow_up"

    # Mensagens longas e pessoais (mais de 200 chars) - áudio
    if len(message) > 200 and _is_personal_message(message):
        return True, "mensagem_longa_pessoal"

    # Mensagens com empatia/conexão - áudio
    if _has_empathy_indicators(message):
        return True, "mensagem_empatica"

    # Por padrão, usa texto para perguntas do SPIN
    if _is_spin_question(message):
        return False, "pergunta_spin"

    # Default: texto para mensagens normais
    return False, "default"


def _has_technical_content(message: str) -> bool:
    """Verifica se tem conteúdo técnico que deve ser texto"""
    patterns = [
        r"https?://",  # URLs
        r"\d{2}[\s.-]?\d{4,5}[\s.-]?\d{4}",  # Telefones
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # Emails
        r"R\$\s?\d",  # Valores em reais
        r"\d{2}/\d{2}/\d{4}",  # Datas
        r"\d{2}:\d{2}",  # Horários
    ]
    for pattern in patterns:
        if re.search(pattern, message):
            return True
    return False


def _is_personal_message(message: str) -> bool:
    """Verifica se é uma mensagem pessoal/emocional"""
    personal_words = [
        "entendo", "compreendo", "imagino", "sei como",
        "parabéns", "incrível", "ótimo", "legal",
        "obrigad", "agradeço", "prazer",
        "conte comigo", "estou aqui", "pode contar",
    ]
    message_lower = message.lower()
    return any(word in message_lower for word in personal_words)


def _has_empathy_indicators(message: str) -> bool:
    """Verifica se tem indicadores de empatia"""
    empathy_phrases = [
        "sei que", "entendo que", "imagino que",
        "deve ser difícil", "complicado mesmo",
        "te entendo", "faz sentido",
        "você está certo", "concordo",
    ]
    message_lower = message.lower()
    return any(phrase in message_lower for phrase in empathy_phrases)


def _is_spin_question(message: str) -> bool:
    """Verifica se é uma pergunta do SPIN Selling"""
    # Perguntas geralmente terminam com ?
    if "?" not in message:
        return False

    # Indicadores de perguntas SPIN
    spin_indicators = [
        "como você", "qual é", "quais são",
        "me conta", "me fala", "o que",
        "quanto", "quando", "por que",
        "como funciona", "como está",
    ]
    message_lower = message.lower()
    return any(indicator in message_lower for indicator in spin_indicators)


def clean_audio_tags(message: str) -> str:
    """
    Remove todas as tags de áudio/emoção da mensagem para envio como texto
    Usa função do tts_service que conhece todas as tags
    """
    from services.tts_service import clean_text_tags
    return clean_text_tags(message)
