# Global separado de Recente — 29/10/2026

Correção publicada: API `altamino-api:global-scope-20261029-ba2afc8fd8b1`. WebSocket permanece `altamino-websocket:follow-ws-20261029-3136900233bd`, sem recriação nesta correção. API importou e respondeu health 200. Nenhuma suite ou ação no telefone foi executada.

## Causa e contrato

`GET /g/s/chat/thread?type=joined-me` e a variante `/x{ndcId}/s/chat/thread` entravam na mesma consulta agregada dos recentes. O helper tratava `ndcId=0` como “procurar em todas as comunidades acessíveis”, misturando o feed Global com Recente.

O cliente `CommunityChatFragment$Adapter.createRequest` usa `joined-me` e `communityId(ndcId)` para cada aba. `GlobalChatService` usa `exist-multi` com IDs explícitos para resolver os recentes. Fontes nativas: `H:/ca/work/altamino-play-20261028/decoded-c/smali_classes2/com/narvii/chat/global/chat/CommunityChatFragment$Adapter.smali:173` e `.../chat/util/GlobalChatService.smali:679`.

Agora `joined-me` passa `all_scopes=False`: global consulta somente chats de `g`, e cada comunidade consulta somente seu `xN`. `exist-multi`, `recent` e `recent-chats` conservam agregação autorizada, escopo real de cada thread, ordem de atividade e fixações pessoais. Comunidades abandonadas e salas sem participação continuam excluídas pelo helper existente. Nenhum chat foi movido, apagado ou recadastrado.

Arquivos: `api/routers/chats.py` (seletor `if_chat_exists`) e `api/helpers/chat_preferences.py` (`accessible_scopes`, `recent_rows`). Backups de checkout/runtime e override anterior estão em `/root/other/altamino/.codex-global-chat-scope-20261029-ba2afc8fd8b1/backup`.

Confiança alta na causa e na correção estática; comportamento renderizado no APK ainda depende do teste do usuário. Recarregar a lista da aba Global e comparar com Recente, depois abrir uma comunidade. Cache local antigo pode permanecer até a lista ser atualizada; não limpar dados do aplicativo.

## Regressão preparada, não executada

`H:/ca/work/altamino-global-chat-scope-20261029/tests/test_chat_scope.py`: três casos com Mongo isolado para garantir separação Global/comunidades, preservação da agregação e ordem dos recentes, exclusão de chat sem acesso e ausência de vazamento de fixação comunitária na aba Global. Não foram rodados por solicitação de o usuário fazer a validação. Não confundir verificação de import/health com teste funcional.

## Pendência separada: push Firebase

Os logs da versão de API anterior a este ajuste mostraram rejeições FCM `SENDER_ID_MISMATCH`/`PERMISSION_DENIED` (e registros `INVALID_ARGUMENT`). Isso é separado dos alertas internos, seu contexto comunitário e do transporte WebSocket. O projeto/sender que emite o token do cliente precisa corresponder ao projeto usado pelas credenciais do servidor. A compatibilidade das credenciais não foi alterada nem foi lido/exportado segredo. Entrega de push em segundo plano permanece pendente; não declarar resolvida pela saúde da API ou pelas correções de navegação dos alertas.
