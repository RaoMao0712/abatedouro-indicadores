# P3.2 — Integração com Zebra ZD220

## Estado e limite da homologação

A integração web, a fila e o agente são seguros para homologação simulada. A homologação física está bloqueada até a auditoria em uma estação que possua a Zebra ZD220 e o NiceLabel licenciado. Nenhum dado de produção e nenhuma configuração de impressora devem ser alterados para superar esse bloqueio.

Auditoria somente leitura realizada em 26/08/2026 (America/Manaus), estação `NB-ABT-LSM-001`:

- nenhuma Zebra/ZD220 encontrada em `Win32_Printer`, `Get-Printer` ou drivers instalados;
- nenhum produto, serviço ou processo NiceLabel/Loftware encontrado no inventário instalado;
- pacote original localizado em `Desktop\ETIQUETA CAIXA.zip`, SHA-256 `CFFBBB6FCA43694743E689DB6D83F6E650FFE7B94627C3AD975664F8860931ED`;
- `ETIQUETA CAIXA.nlbl` interno, 4.747 bytes, SHA-256 `b33439f24aa3fc37c2ebab78b5cc2ff3f8f2d0f8e8c0ec05cecf417c3b851ea4`;
- o NLBL é um contêiner protegido. Variáveis, pré-visualização e vínculo de impressora não puderam ser auditados sem NiceLabel. O original não foi extraído, alterado nem sobrescrito.

Fingerprint final somente leitura, em 26/08/2026 16:17:44 -04:00: zero Zebra, zero NiceLabel, mesmo usuário/estação, mesmo conjunto de 10 impressoras e mesmo SHA-256 do ZIP. Não houve mudança de driver, porta, nome, impressora padrão, spooler, firmware, calibração ou preferência.

## Arquitetura segura

A persistência da caixa e a criação opcional do job compartilham a mesma transação. A impressão é assíncrona e nunca desfaz a caixa. A API entrega jobs somente a agente pareado, com token armazenado no servidor apenas como hash e, no Windows, protegido por DPAPI.

Estados: `PENDENTE`, `EM_PROCESSAMENTO`, `FALHA_TEMPORARIA`, `ENVIADA_IMPRESSORA`, `CONFERENCIA_NECESSARIA`, `FALHA_PERMANENTE` e `INVALIDADA`. **Enviada à impressora** significa somente que o spool aceitou a solicitação; não afirma que a etiqueta saiu fisicamente. Resposta ambígua após o spool vai a `CONFERENCIA_NECESSARIA` e não é reenviada automaticamente.

Cada job possui snapshot JSON imutável e idempotência por caixa, tipo e geração. Reimpressão exige perfil autorizado e justificativa, cria nova geração ligada ao job anterior e não movimenta estoque. O estorno invalida jobs ainda pendentes; jobs já enviados permanecem no histórico e recebem o marcador de caixa estornada.

## Fonte e mapa central de variáveis

Somente valores já persistidos em `pa_caixas` são usados:

| Variável lógica | Fonte persistida | Regra |
|---|---|---|
| fabricação | `data_fabricacao` | data original da OP preservada pelo fluxo |
| validade | `data_validade` | regra vigente já validada antes da caixa |
| lote | `codigo_caixa` | lote físico oficial documentado; nunca OP/id/data inventados |
| peças | `quantidade_bandejas` | somente em modelo com equivalência explicitamente validada; caixa parcial usa quantidade real |
| bruto | `peso_bruto` | string decimal do snapshot |
| tara | `peso_tara` | diferença persistida exata; 0,500 kg é apenas o padrão de entrada atual |
| líquido | `peso_liquido` | string decimal do snapshot |

O job é recusado se `bruto != líquido + tara`, se peças não forem inteiras/positivas ou se faltar lote. No fluxo atual, SKU e apresentação operacional da caixa coincidem; qualquer nova apresentação exige configuração distinta.

## Modelos e impressora

`label_model_configs` relaciona SKU + apresentação + tipo a caminho, SHA-256, mapa de variáveis e allowlist exata de impressoras. Não existe configuração ativa por padrão. O agente verifica o hash imediatamente antes de enviar. O adaptador `NiceLabelAutomationAdapter` permanece fail-closed até confirmar edição, versão, licença, componentes e API Automation na estação real. Não há fallback para ZPL bruto; WT1000 e `pesagem_app` estão fora do escopo.

O agente fica no código em `local_print_agent/` e sua instalação operacional recomendada é `%LOCALAPPDATA%\FrigoDatta\PrintAgent`. Ele roda como processo do usuário, sem serviço e sem inicialização automática. `start_agent.bat`, `stop_agent.bat` e `diagnostic.bat` não alteram driver, porta, nome, padrão, firmware, calibração ou spooler.

## Flags e ativação controlada

Todas têm padrão de produção `false`:

- `LABEL_PRINTING_ENABLED`;
- `BOX_LABEL_AUTO_PRINT_ENABLED`;
- `LOCAL_PRINT_AGENT_ENABLED`.

Antes de ativar: auditar a estação real; duplicar o NLBL somente se variáveis fixas exigirem isso; nunca sobrescrever o original; registrar o hash da cópia; cadastrar allowlist com o nome exato da Zebra; validar pré-visualização controlada; parear por código temporário; executar diagnóstico; obter autorização do usuário para **uma** etiqueta física; usar uma caixa real indicada pelo usuário, sem criar caixa fictícia. Só depois do aceite visual considerar a homologação física concluída.

## Migração e rollback

As migrations `20260826_p3_2_integracao_zebra*` são aditivas, sem backfill e compatíveis com PostgreSQL/SQLite. O rollback remove apenas as quatro tabelas novas. Antes de produção, realizar backup, aplicar migration com as três flags desligadas, publicar e validar raiz, login, embalagem secundária e APIs desabilitadas.
