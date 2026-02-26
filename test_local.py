"""
Script de teste local - simula webhooks sem precisar expor externamente
"""
import asyncio
import httpx

BASE_URL = "http://localhost:8000"


async def test_captura():
    """Testa webhook de captura de lead"""
    print("\n" + "=" * 50)
    print("TESTE 1: Captura de Lead")
    print("=" * 50)

    payload = {
        "nome": "João Silva",
        "whatsapp": "11999998888",
        "segmento": "Contabilidade",
        "origem": "formulario_teste",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_URL}/webhook/captura", json=payload)
        print(f"Status: {response.status_code}")
        print(f"Resposta: {response.json()}")


async def test_mensagem_whatsapp():
    """Testa webhook de mensagem WhatsApp"""
    print("\n" + "=" * 50)
    print("TESTE 2: Mensagem WhatsApp")
    print("=" * 50)

    # Simula payload da Evolution API
    payload = {
        "event": "messages.upsert",
        "instance": "teste",
        "server_url": "http://localhost",
        "apikey": "teste",
        "data": {
            "key": {
                "id": "msg123",
                "remoteJid": "5511999998888@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "Olá, tudo bem?"},
            "messageType": "conversation",
            "pushName": "João",
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/webhook/whatsapp", json=payload, timeout=60.0
        )
        print(f"Status: {response.status_code}")
        print(f"Resposta: {response.json()}")


async def test_health():
    """Testa health check"""
    print("\n" + "=" * 50)
    print("TESTE 0: Health Check")
    print("=" * 50)

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Resposta: {response.json()}")


async def test_conversa_interativa():
    """Teste interativo - você digita, o agente responde"""
    print("\n" + "=" * 50)
    print("TESTE INTERATIVO: Conversa com o Agente SDR")
    print("=" * 50)
    print("Digite suas mensagens (ou 'sair' para encerrar)")
    print("-" * 50)

    sender = "5511999998888@s.whatsapp.net"

    while True:
        msg = input("\nVocê: ").strip()
        if msg.lower() == "sair":
            break

        payload = {
            "event": "messages.upsert",
            "instance": "teste",
            "server_url": "http://localhost",
            "apikey": "teste",
            "data": {
                "key": {
                    "id": f"msg_{hash(msg)}",
                    "remoteJid": sender,
                    "fromMe": False,
                },
                "message": {"conversation": msg},
                "messageType": "conversation",
                "pushName": "Teste",
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/webhook/whatsapp", json=payload, timeout=60.0
            )

            if response.status_code == 200:
                # Aguarda o debounce processar
                print("\n(Aguardando resposta do agente...)")
                await asyncio.sleep(25)  # Debounce é 20s
                print("Luana: [Verifique o terminal do servidor para ver a resposta]")
            else:
                print(f"Erro: {response.text}")


async def main():
    print("\n" + "=" * 50)
    print("  TESTES DO AGENTE SDR")
    print("  Certifique-se que o servidor está rodando!")
    print("  (python main.py)")
    print("=" * 50)

    print("\nEscolha um teste:")
    print("1. Health Check")
    print("2. Captura de Lead")
    print("3. Mensagem WhatsApp")
    print("4. Conversa Interativa")
    print("5. Todos os testes")

    escolha = input("\nOpção: ").strip()

    if escolha == "1":
        await test_health()
    elif escolha == "2":
        await test_captura()
    elif escolha == "3":
        await test_mensagem_whatsapp()
    elif escolha == "4":
        await test_conversa_interativa()
    elif escolha == "5":
        await test_health()
        await test_captura()
        await asyncio.sleep(2)
        await test_mensagem_whatsapp()
    else:
        print("Opção inválida")


if __name__ == "__main__":
    asyncio.run(main())
