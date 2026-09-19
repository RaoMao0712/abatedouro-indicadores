# FRIGODATTA — REQUISIÇÃO DE COMPRA
## Etapa B — Relatório de implementação do MVP

**SHA base:** `8e1b94db1eb8af07dc9dd9960de7bfe2fa6d8a8b`  
**Branch:** `codex/melhoria-romaneio-multiplas-ops`  
**Data:** 19/09/2026

## Resultado

Foi implementado localmente um módulo próprio de Requisições de Compra, documental e separado da Requisição de Almoxarifado. A RC não cria lote, reserva, movimento de estoque, lançamento financeiro, CMV, conta a pagar, Pedido, Cotação ou Recebimento.

## Arquitetura, schema e migrations

- módulo `modules/requisicoes_compra/`: registry de origens, serviço transacional, rotas e PDF;
- migrations PostgreSQL e SQLite, com rollbacks, para `requisicoes_compra`, `requisicao_compra_itens` e `requisicao_compra_eventos`;
- índices por origem/status, status/data, solicitante e material; uniques de número, chave de criação e evento idempotente;
- bootstrap idempotente somente na inicialização da aplicação, nunca em request;
- numeração por ID transacional no formato `RC-000001`, sem `MAX`;
- estados preparados: `RASCUNHO`, `ABERTA`, `APROVADA`, `REJEITADA`, `CANCELADA`, `ATENDIDA` e `PARCIALMENTE_ATENDIDA`; os dois últimos não possuem fluxo físico no MVP.

## Origens e snapshots

Registry central suporta `REPOSICAO_ESTOQUE`, `ORDEM_SERVICO`, `ORDEM_PRODUCAO`, `NAO_CONFORMIDADE_SGI`, `QUALIDADE`, `ADMINISTRATIVO`, `PROJETO` e `OUTRO`. Cada origem formal valida existência e permissão e produz snapshot imutável. Origens documentais exigem setor, descrição e justificativa; Projeto também exige código/nome.

O link reverso consulta `tipo_origem + origem_id`, sem gravar `rc_id` nas entidades de origem. A situação atual é acessada por URL separada do contexto original.

## Itens

- material cadastrado: existência/atividade, unidade e descrição vindas do cadastro;
- item provisório: descrição, unidade válida e quantidade; marcado `pendente_cadastro=1`;
- vinculação posterior por `admin/pcp`, com compatibilidade de unidade e snapshot original preservado;
- duplicidade do mesmo material ou descrição/unidade provisória na RC é bloqueada;
- duplicidade em outra RC não terminal da mesma origem gera alerta, sem bloqueio;
- custo é exclusivamente estimado e informativo.

## Fluxo, idempotência e concorrência

- criação em rascunho; origem imutável;
- edição somente em rascunho, com eventos `EDICAO` e `ALTERACAO_QUANTIDADE`;
- envio, aprovação, rejeição e cancelamento conforme máquina de estados;
- eventos idempotentes com chave única;
- versão otimista, transação, lock PostgreSQL e guarda `UPDATE ... WHERE versao=?`;
- retries devolvem o estado persistido, sem duplicar RC/evento;
- autoaprovação bloqueada inclusive para admin/gerência e tentativa auditada;
- rejeição e cancelamento exigem motivo nas condições especificadas.

## Permissões

- reposição: admin/PCP;
- OS: admin/manutenção/PCP/gerência; Qualidade apenas para OS com vínculo SGI;
- OP: admin/produção/PCP/gerência;
- NC/Qualidade: admin/qualidade/gerência;
- administrativo/projeto/outro: admin/gerência;
- aprovar/rejeitar: admin/gerência;
- todas as ações mutantes validam permissão no serviço, além das rotas.

## Integrações

- **OS:** botão “Solicitar compra”, formulário pré-preenchido e bloco separado de RCs; Requisições de Almoxarifado continuam no bloco de materiais de estoque;
- **Requisição de Almoxarifado:** nenhuma tabela/regra foi reutilizada ou misturada;
- **Reposição:** ação no saldo abre RC pré-preenchida; snapshot inclui saldo físico e data, sem inventar estoque mínimo;
- **Qualidade:** NC SGI formal cria RC e mostra links reversos em consulta em lote, evitando N+1; Qualidade livre permanece documental;
- **Administrativo/Projeto/Outro:** origem manual obrigatória e restrita à gestão;
- **Navegação:** novo domínio Compras → Requisições de Compra;
- **PDF:** identidade institucional, origem, prioridade, itens, custos estimados, pendência cadastral e aprovação, sem dados fictícios de compra.

## Invariantes

Testes comparam antes/depois de criação, envio e aprovação:

- lotes, movimentos e saldos/reservas: delta zero;
- movimentações financeiras: delta zero;
- OS de origem: inalterada;
- snapshots permanecem imutáveis.

## Testes e regressão

Executados em processos separados devido ao isolamento documentado de `DB_NAME` nas suítes legadas:

| Suíte | Resultado |
|---|---:|
| `test_requisicoes_compra.py` | 8 aprovados |
| `test_p3_6_os_rastreabilidade.py` | 15 aprovados |
| `test_p3_5_requisicoes_almoxarifado.py` | 9 aprovados |
| `test_hotfix_correcao_entrada_estoque.py` | 20 aprovados |
| `test_p3_6_etapa_c_complementar.py` | 13 aprovados |
| `test_manutencao_objetos_os.py` | 20 aprovados |
| `test_qual_sgi_01.py` | 12 aprovados |
| `test_nova_navegacao_inicio.py` | 18 aprovados |
| **Total** | **115 aprovados** |

Validações adicionais: compilação Python; compilação de sete templates afetados; migration e rollback SQLite em banco descartável; `git diff --check` sem erro.

### Falhas classificadas

- `REGRESSAO_REAL_DA_SPRINT`: uma quebra textual do contrato “Desdobramentos” no detalhe da OS foi encontrada, corrigida e revalidada.
- `FIXTURE_ISOLAMENTO`: ao agrupar a nova suíte e P3.6 no mesmo processo, 11 testes reutilizaram `DB_NAME` importado e encontraram locks/duplicatas. O próprio arquivo P3.6 exige processo independente; separados, todos os 15 passaram.
- `ERRO_COLETA_FORA_ESCOPO`: o comando `pytest` não estava no PATH; `python -m pytest` funcionou normalmente.
- `INCONCLUSIVO`: 4 testes de DDL PostgreSQL foram pulados porque não há PostgreSQL configurado neste ambiente. A migration PostgreSQL foi revisada estaticamente; nenhuma migration foi executada em produção.
- `FALHA_PREEXISTENTE`: nenhuma falha preexistente relevante encontrada.

## Limitações restantes

- não há edição de origem: cancelar o rascunho e criar outro;
- não há atendimento, Pedido, Cotação, Recebimento, reserva física ou custo real;
- `ATENDIDA/PARCIALMENTE_ATENDIDA` estão apenas preparados;
- validação executável de PostgreSQL requer instância descartável na Etapa C;
- aprovação por valor, perfil Compras e estoque mínimo permanecem fora do MVP.

## Commit final

Preenchido após a criação do commit desta etapa.

**REQUISIÇÃO DE COMPRA — ETAPA B CONCLUÍDA: MVP IMPLEMENTADO LOCALMENTE, ORIGENS/OS/ALMOXARIFADO/QUALIDADE INTEGRADOS E TESTES EXECUTADOS — AGUARDANDO REVISÃO PARA ETAPA C**
