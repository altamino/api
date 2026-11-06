# AltAmino — alertas, chats recentes, fixação e recuperação WebSocket

Publicado em 29/10/2026, preservando FastAPI, MongoDB, Redis e o protocolo do APK 3.4.33618. Nenhum APK foi alterado, recompilado ou instalado.

## Correções publicadas

- **Alertas:** o modelo nativo `Notice` lê `operator`, não `author`. A API agora fornece `operator` com o perfil real e mantém `author` como alias. Datas são convertidas para ISO UTC. Se o autor saiu da comunidade, usa sua identidade global existente; uma identidade inexistente continua ausente, sem inventar nome/foto. Paginação e filtro pelo destinatário são preservados.
- **Conversas recentes:** `GET /api/v1/g/s/chat/thread?type=exist-multi&q=id1,id2` deixou de retornar vazio fixo. Resolve os IDs no global e nas comunidades efetivamente acessíveis à conta, respeitando a ordem pedida e a participação no chat. `joined-me`, `recent` e `recent-chats` também usam dados persistentes, com paginação e ordenação por atividade/fixação. Consultas comunitárias continuam limitadas ao seu escopo.
- **Fixação:** `POST /api/v1/{g|xN}/s/chat/thread/{id}/pin|unpin` salva uma preferência exclusiva do usuário. Retorna o `thread` completo esperado pelo APK; `Chat.Info` projeta `isPinned` por leitor. Conversas antigas fixadas não desaparecem apenas por falta de atividade recente.
- **Cache:** chat, notificações, avisos e lembretes consultam o estado atual e revalidam a autenticação. Operações que alteram estado não reutilizam respostas em cache. Esses fluxos usam `Cache-Control: no-store`.
- **WebSocket:** eventos selecionados são persistidos no Mongo antes do aviso pelo Redis. O worker recupera pendências após reconexão, reinício e perda do aviso Redis. Cursores são independentes por usuário/sessão; somente um hash da identificação da sessão é persistido. Antes da entrega, verifica novamente a conta, comunidade, participação no chat e a existência/versão do conteúdo. Sockets que falham são removidos e fechados para permitir reconexão.
- **Entrada do WebSocket:** o `main.py` do checkout continha dois comandos de terminal. Foi preservado em backup e substituído pela versão Python válida de 60 linhas que já estava no container em execução.

## Persistência: limites explícitos

A fila conserva até **128 eventos por usuário**, com retenção de **3 dias** e limite de **64 KiB por payload**. Comandos de chamada, presença e digitação continuam transitórios; não são reexecutados na reconexão. Payloads maiores continuam no transporte anterior e no histórico REST correspondente, sem entrar nesta fila.

O APK não fornece ACK de aplicação para esse mecanismo. O cursor avança após a escrita no socket: isso não comprova que a interface processou o evento e não garante entrega exatamente uma vez. Mensagens e notificações existentes continuam sendo a fonte de recuperação via REST. Não houve backfill artificial de eventos anteriores à publicação nem alteração das coleções existentes para simular entrega.

Coleções novas: `ChatPreferences`, `WsOutbox` e `WsDeliveryCursors`. As duas últimas possuem índices TTL; preferências de fixação não expiram.

## Validação e teste manual

Antes da publicação passaram **23 testes**: 20 de compatibilidade/API/persistência, com MongoDB real em bancos temporários isolados, e 3 de transporte no runtime próprio do WebSocket. Cobrem DTOs nativos, isolamento entre contas/comunidades, concorrência da fila, expiração e recriação, duas sessões, socket com falha, Redis indisponível e revogação de acesso. As dependências de cosméticos e alguns transportes são isoladas nas fixtures dos testes; não há mocks nas implementações publicadas.

Após o reinício, `/health` da API e do WebSocket retornaram 200. A verificação de logs realizada não encontrou novas exceções nos serviços.

**Teste funcional no APK: pendente com o usuário, por solicitação dele.** Não considerar a apresentação visual e o ciclo real entre duas contas comprovados pelos testes de servidor.

Roteiro manual:

1. Reabrir os alertas e atualizar a lista: conferir nomes, fotos, datas e abertura do perfil correto.
2. Abrir chats de comunidades diferentes e voltar à lista de recentes; conferir escopo e mensagens.
3. Fixar/desfixar um chat, fechar/reabrir o app e confirmar a preferência. Outra conta não deve herdar a fixação.
4. Desconectar/reconectar a rede com outra conta enviando uma mensagem; conferir recuperação e ausência de repetição visual indevida.

## Implantação e continuidade

- Workspace local: `H:/ca/work/altamino-api-fixes-20261029`.
- Fontes anteriores: `checkout/` e `runtime/`; mudanças: `patched/`; testes: `tests/`.
- Backup remoto: `/root/other/altamino/.codex-compat-20261029-4332ec92235f/backup`.
- Imagens locais: `altamino-api:compat-20261029-4332ec92235f` e `altamino-websocket:compat-20261029-4332ec92235f`.
- Override: `/root/other/altamino/docker-compose/docker-compose.override.yml`, verificado pelo Compose. Mantém as imagens corrigidas na próxima recriação normal dos serviços.
- Somente API e WebSocket foram reiniciados. MongoDB e Redis não foram reiniciados; contas, sessões, moedas, mensagens e notificações existentes não foram apagadas.
- Nenhum commit/push ou publicação de imagem em registry foi realizado. Alterações anteriores em `objects/communities.py` e `routers/altteam.py` foram preservadas.

Próximo passo: receber o resultado dos testes manuais. Investigar apenas o fluxo que falhar, sem refazer a comparação geral ou reconstruir o APK. O deploy atual está registrado em `deployment-result.json` no workspace; a implantação conferiu hashes dos arquivos anteriores e manteve backups para reversão seletiva.
