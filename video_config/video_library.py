"""
Biblioteca de Vídeos Demo por Segmento
Mapeia segmentos para vídeos de demonstração do Fyness
"""
from typing import Optional, Dict

# ============================================================
# CONFIGURAÇÃO DOS VÍDEOS POR SEGMENTO
# ============================================================

# Estrutura: segmento -> { url, caption }
# URL pode ser link direto do vídeo ou mediaKey da Evolution API

VIDEO_LIBRARY: Dict[str, Dict[str, str]] = {
    # Exemplo de estrutura - PREENCHER COM URLS REAIS
    "logistica": {
        "url": "https://drive.google.com/uc?export=download&id=1i4V4nNRgbSC2IdtVvT0SmxdmWuVEfAEO",
        "caption": "Olha só como funciona o Fyness para empresas de logística!"
    },
    "restaurante": {
        "url": "",
        "caption": "Veja como o Fyness ajuda restaurantes a controlar as finanças! 👆"
    },
    "salao": {
        "url": "",
        "caption": "Confira como funciona o Fyness para salões de beleza! 👆"
    },
    "loja": {
        "url": "",
        "caption": "Veja o Fyness em ação para lojas e comércios! 👆"
    },
    "servicos": {
        "url": "",
        "caption": "Olha como o Fyness funciona para prestadores de serviço! 👆"
    },
    "ecommerce": {
        "url": "",
        "caption": "Confira o Fyness para e-commerces! 👆"
    },
    # Vídeo genérico para segmentos não mapeados
    "default": {
        "url": "",  # URL do vídeo genérico
        "caption": "Olha só como funciona o Fyness! 👆"
    }
}


def get_video_for_segment(segmento: str) -> Optional[Dict[str, str]]:
    """
    Retorna o vídeo e legenda para um segmento específico.

    Args:
        segmento: Segmento do lead (ex: "logística", "restaurante")

    Returns:
        Dict com 'url' e 'caption', ou None se não houver vídeo configurado
    """
    if not segmento:
        return VIDEO_LIBRARY.get("default")

    segmento_lower = segmento.lower().strip()

    # Busca exata
    if segmento_lower in VIDEO_LIBRARY:
        video = VIDEO_LIBRARY[segmento_lower]
        if video.get("url"):  # Só retorna se tiver URL configurada
            return video

    # Busca parcial (ex: "salão de beleza" -> "salao")
    for key, video in VIDEO_LIBRARY.items():
        if key != "default" and key in segmento_lower:
            if video.get("url"):
                return video

    # Mapeamentos comuns
    segment_mappings = {
        "beleza": "salao",
        "cabelo": "salao",
        "barbearia": "salao",
        "comida": "restaurante",
        "bar": "restaurante",
        "lanchonete": "restaurante",
        "comercio": "loja",
        "varejo": "loja",
        "transporte": "logistica",
        "frete": "logistica",
        "entrega": "logistica",
        "online": "ecommerce",
        "digital": "ecommerce",
    }

    for term, mapped_segment in segment_mappings.items():
        if term in segmento_lower:
            video = VIDEO_LIBRARY.get(mapped_segment)
            if video and video.get("url"):
                return video

    # Fallback para vídeo default
    default_video = VIDEO_LIBRARY.get("default")
    if default_video and default_video.get("url"):
        return default_video

    return None


def is_video_library_configured() -> bool:
    """Verifica se há pelo menos um vídeo configurado na biblioteca"""
    for key, video in VIDEO_LIBRARY.items():
        if video.get("url"):
            return True
    return False


def list_configured_segments() -> list:
    """Lista os segmentos que têm vídeo configurado"""
    return [key for key, video in VIDEO_LIBRARY.items() if video.get("url")]
