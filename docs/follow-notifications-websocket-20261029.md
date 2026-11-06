# AltAmino — seguir, alertas por comunidade e WebSocket

Data: 29/10/2026. Implementação em FastAPI/MongoDB/Redis, preservando os contratos e o provedor Agora do AltAmino. O backend Kioraa foi consultado como referência; não foi alterado. Nenhuma alteração no APK ou no telefone.

## Seguir com estado persistente

A lista de membros utilizava `OwnNonSensetiveProfile`, que fixa `followingStatus=0`. Outras respostas omitiam o usuário que estava consultando, e respostas autenticadas podiam passar pelo cache HTTP. O estado persistido existia, mas a interface recebia “não segue”.

`Users.following` continua sendo a origem da relação em cada banco/comunidade. A projeção consulta os dados persistidos e retorna os mesmos bits em `followingStatus` e `membershipStatus`: 0 nenhum, 1 segue, 2 é seguido, 3 mútuo. Aplica-se a membros, líderes, curadores, favoritos, busca, perfis e listas de relações. A lista de seguidores e suas contagens consultam as relações de saída reais, evitando confiar exclusivamente no espelho legado `whoFollows`.

Seguir usa `$addToSet`; uma repetição não duplica a relação nem gera outro alerta da mesma transição. Deixar de seguir usa `$pull` e autoriza somente um dos participantes daquela relação. Os espelhos existentes continuam sendo atualizados. Respostas autenticadas deixam de usar o cache de rota; cache público permanece. Não há migração ou recriação das contas.

Fontes alteradas: `api/helpers/follow_state.py`, `api/routers/profile.py`, `api/routers/communities.py`, `api/objects/user.py`, `api/helpers/routers/cachable.py`.

## Alertas globais e de comunidades

As consultas já usam coleções separadas (`x{ndcId}/Notifications`; o helper de banco resolve o escopo global). O campo de navegação nativo `contextNdcId` faltava em alertas antigos e em criações sem contexto explícito. O Android interpreta a ausência como zero e abre o perfil global.

Agora o DTO comunitário informa o ID da comunidade em `contextNdcId`, e o operador recebe `ndcId` e `isGlobal` coerentes. Alertas de seguir globais usam zero. Contextos explícitos de outros tipos de alertas globais são preservados. Novos registros recebem contexto por padrão; registros antigos são corrigidos durante a leitura, sem reescrever o histórico. Pushes incluem o contexto. Alertas e estados de leitura continuam separados por comunidade.

Fontes: `api/helpers/notification_contract.py`, `api/helpers/notification.py`, `websocket/objects/ws_events.py`. Contrato nativo: `decoded-c/smali/com/narvii/notice/Notice.smali` e `decoded-c/smali_classes3/com/narvii/notice/NoticeListFragment$Adapter.smali` (campo `contextNdcId` usado ao montar o destino).

## Eventos nativos do WebSocket

| Entrada | Comportamento |
| --- | --- |
| 20 | Registra telemetria sanitizada, limitada e com expiração; não registra credenciais em campos de autenticação. |
| 100 / 103 | Preserva entrada/saída de tela; adiciona assinaturas de sala compartilhadas com leases no Redis. |
| 105 / 108 / 112 / 200 | Preserva os handlers RTC existentes; acrescenta ACL, estado compartilhado e controle de papel antes de credenciais. |
| 116 | Heartbeat retorna papéis reais e renova atividade/participação válida; não inventa canais no Pong. |
| 120 / 122 | Atualiza/consulta playlist persistida da sala de projeção ativa (tipo 5); alteração exige organizador. |
| 126 | Organizador rebaixa um apresentador real; notifica o alvo e atualiza/encerra o canal conforme participantes restantes. |
| 132 / 134 / 136 / 138 | Limpa, aprova, cancela/recusa e registra pedidos reais para falar, com fila persistida e expiração. |
| 300 / 302 | Assina/cancela tópicos nativos; respostas 301/303. |
| 304 / 306 | Atividades compostas: Browsing, Chatting, Typing, Recording, Playing, Polling, Commenting, Voting; respostas 305/307. |
| 1001 | Mantém a marcação de leitura legada do AltAmino. Não se aplica cegamente a rejeição de eventos de servidor usada no Kioraa. |

As notificações de atividade 400/401 descrevem entradas/saídas reais, com perfis e contagem atual. Tópicos privados verificam participação; um observador não recebe a lista de pessoas em DMs alheias. Assinar um tópico não cria uma entrada fictícia. Atividades de quiz/enquete/comentário/voto têm leitura REST complementar.

O estado de canais usa `WsChannelState`, locks com renovação em `WsChannelLocks`, versão do documento e leases de participantes de 90 segundos. A fila usa `WsVoiceWaiting` com pedidos temporários e aprovações temporárias. A playlist é persistida no canal real e limpa no ciclo de encerramento. Reiniciar o processo não transforma participantes antigos em conectados permanentemente; quem não renovar expira.

A sessão é revalidada antes de cada operação, durante manutenção e antes de recuperar eventos persistidos. Identidade vem do SID, não do UID enviado no corpo. As operações verificam comunidade, participação, bloqueios e papel de organizador. Autenticação/assinatura inicial existente foi mantida.

Limites do transporte: entrada 64 KiB, fila de entrada 32 frames, 120 operações/minuto por conexão, saída limitada a 32 frames pendentes/256 KiB com timeout, ping do transporte 60 s e timeout 20 s. A recuperação de eventos duráveis da etapa anterior permanece: outbox limitada e com expiração, cursor por sessão e revalidação do conteúdo/ACL. Push atrasado de um follow removido é descartado. RTC, digitação e presença transitória não são reproduzidos como se ainda estivessem ativos.

Fontes novas: `websocket/helpers/native_protocol.py`, `native_access.py`, `native_activities.py`, `channel_store.py`, `bounded_send.py`; integração em `handlers/__init__.py`, `handlers/chat.py`, `handlers/call.py`, `helpers/connection_manager.py`, `helpers/durable_delivery.py` e `main.py`.

## Referências e compatibilidade

Kioraa: `H:/ca/outputs/amino-backend/src/realtime.ts`, `realtime-contracts.ts`, `realtime-hub.ts`, `modules/follows/state.ts`, `modules/follows/index.ts`, `modules/voice-channels.ts`, `modules/live-layer.ts`.

A ordem RTC foi conferida nos callbacks `RtcService$10` / `RtcService$10$1` do cliente reconstruído: entrada, atualização de papel, configuração de canal quando necessária e solicitação de credenciais. A implementação não substitui Agora por LiveKit. Eventos privados do Kioraa sem o recurso correspondente no AltAmino, como suas reações customizadas 21000/21001, não são anunciados como implementados. Precisam primeiro de armazenamento/REST e de um consumidor compatível no cliente.

## O que foi verificado e o que continua pendente

Confiança alta: causas encontradas em código, separação das coleções, campo de navegação, handlers escritos e integração/importação do servidor. Verificações desta etapa: análise sintática, compilação estática Python, importação de `main` em ambos os serviços, guard de hashes, publicação e saúde operacional. Não foram executadas suites ou ações no telefone, conforme solicitado. Os 23 testes da etapa anterior pertencem àquela versão e não validam esta ampliação.

Confiança ainda desconhecida: renderização/reconexão no APK, interação efetiva da fila/playlist e áudio bidirecional. Saúde HTTP 200 não comprova esses recursos no aplicativo. O cliente e o projeto Agora existentes precisam ser compatíveis e estar configurados para mídia real; a ausência de configuração retorna erro, sem simular chamada bem-sucedida.

### Roteiro para o teste do usuário

1. Seguir um curador/membro, sair da tela e voltar; confirmar o estado. Reabrir o app e repetir. Deixar de seguir e confirmar novamente. Comparar a mesma conta em comunidades diferentes e no perfil global.
2. Abrir um alerta comunitário e tocar no autor: deve abrir o perfil daquela comunidade. Repetir com alerta global: deve abrir o perfil global. Conferir também alertas antigos após recarregar a lista.
3. Desconectar e reconectar a rede; verificar mensagens/alertas pendentes e conversas recentes/fixadas da etapa anterior.
4. Com duas contas, confirmar atividade, desaparecimento após inatividade, pedidos/aprovações para falar, lista de participantes, playlist e áudio. Sem duas contas/dispositivos, não declarar áudio bidirecional validado.

Dados e sessões existentes preservados. Somente API e WebSocket foram recriados para aplicar o código e limites; Mongo e Redis não foram reiniciados. Backups seletivos e imagens da versão anterior estão preservados no stage descrito em `deployment.json`.

## Publicação atual

Release `3136900233bd`. API e WebSocket foram recriados usando as imagens registradas em `deployment.json`. O stage remoto contém backup seletivo da versão imediatamente anterior e o override Compose anterior. Verificações funcionais no aplicativo continuam pendentes.
