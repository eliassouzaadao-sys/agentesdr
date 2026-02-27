"""
Processador de Tags do SDR
Processa tags especiais nas respostas do agente e sincroniza com Supabase
"""
import re
import logging
from typing import Dict, Any, Optional, Tuple, List

from services.redis_service import redis_service
from services.supabase_service import supabase_service

logger = logging.getLogger(__name__)

# Mapeamento de tags para atualizações de estado
TAG_MAPPING = {
    "[QUALIFICADO]": {"qualificacao": "quente", "etapa_spin": "completo"},
    "[NAO_QUALIFICADO]": {"qualificacao": "frio", "etapa_spin": "completo"},
    "[FOLLOW_UP_24H]": {"follow_up": True},
    "[TRANSFERIR_VENDEDOR]": {"transferir": True, "qualificacao": "quente"},
    "[ENVIAR_AUDIO]": {"audio": True},
}

# Keywords para inferir etapa SPIN
ETAPA_KEYWORDS = {
    "situacao": ["o que vocês fazem", "me conta", "qual é o", "como funciona"],
    "problema": ["dor de cabeça", "dificuldade", "problema", "gargalo", "incomoda"],
    "implicacao": ["continuar assim", "impacto", "perder", "consequência"],
    "necessidade": ["se existisse", "ideal", "conectar", "vendedor", "solução"],
}


async def process_tags(
    response: str,
    current_state: Dict[str, Any],
    sender: str,
    get_summary_fn=None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Processa tags especiais na resposta, atualiza estado e sincroniza com Supabase.

    Args:
        response: Resposta do agente com possíveis tags
        current_state: Estado atual do lead
        sender: ID do remetente (remote_jid)
        get_summary_fn: Função async para gerar resumo da conversa

    Returns:
        Tupla (resposta_limpa, novo_estado ou None se não mudou)
    """
    new_state = current_state.copy()
    tags_found = []

    # Processa cada tag de qualificação
    for tag, updates in TAG_MAPPING.items():
        if tag in response:
            tags_found.append(tag)
            new_state.update(updates)
            response = response.replace(tag, "").strip()

    # Processa tags de objeção: [OBJECAO: descrição]
    objecao_pattern = r'\[OBJECAO:\s*([^\]]+)\]'
    objecoes_encontradas = re.findall(objecao_pattern, response, re.IGNORECASE)

    if objecoes_encontradas:
        response = re.sub(objecao_pattern, '', response, flags=re.IGNORECASE).strip()
        for objecao in objecoes_encontradas:
            objecao_limpa = objecao.strip()
            if objecao_limpa:
                await supabase_service.add_objecao(sender, objecao_limpa)
                logger.info(f"[Supabase] Objeção identificada para {sender}: {objecao_limpa}")

    # Infere etapa SPIN se não houver tags
    if not tags_found:
        response_lower = response.lower()
        for etapa, keywords in ETAPA_KEYWORDS.items():
            if any(kw in response_lower for kw in keywords):
                new_state["etapa_spin"] = etapa
                break

    # Atualiza Redis se houver mudanças
    if new_state != current_state:
        await redis_service.set_lead_state(sender, new_state)

    # Processa tags no Supabase (CRM)
    if "[QUALIFICADO]" in tags_found or "[NAO_QUALIFICADO]" in tags_found:
        resumo = await get_summary_fn(sender) if get_summary_fn else None
        qualificacao = "quente" if "[QUALIFICADO]" in tags_found else "frio"

        await supabase_service.update_lead_qualification(
            remote_jid=sender,
            qualificacao=qualificacao,
            resumo=resumo
        )
        logger.info(f"[Supabase] Lead {sender} qualificado como {qualificacao}")

    if "[TRANSFERIR_VENDEDOR]" in tags_found:
        resumo = await get_summary_fn(sender) if get_summary_fn else None

        contato = await supabase_service.convert_lead_to_contact(
            remote_jid=sender,
            resumo=resumo
        )
        if contato:
            logger.info(f"[Supabase] Lead {sender} convertido para contato")

    return response, new_state if new_state != current_state else None
