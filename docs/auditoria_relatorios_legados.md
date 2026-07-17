# Auditoria de Relatorios Legados e Consolidacao Final

## Contexto auditado

- Worktree: `4ca3`
- Commit inicial exigido: `2a58876b06adc2075a281aaca7e0d77957767578`
- Branch de trabalho: `codex/governanca-biblioteca-relatorios-final`
- Rotas de aplicacao auditadas: 92
- Rota estatica Flask: 1
- Templates HTML auditados: 67
- Rotas de arquivo/exportacao: 9
- Itens oficiais reconciliados no catalogo: 38

## Matriz de classificacao

| Classe | Decisao | Superficies |
| --- | --- | --- |
| Relatorio oficial | Mantido na Biblioteca | `/relatorios`, rotas oficiais por dominio, DRE, Fluxo de Caixa |
| Exportacao oficial | Mantida quando anunciada | Excel financeiro, producao, almoxarifado, expedicao, gerencial e DRE |
| Tela operacional | Preservada fora da Biblioteca | dashboard, movimentacoes, importadores, almoxarifado, producao, expedicao, cadastros |
| Legado com substituto 1:1 | Redirecionado | `/relatorio-rendimento` |
| Legado sem substituto 1:1 | Preservado temporariamente | `/relatorio-custos` |
| Ferramenta operacional fora da Biblioteca | Preservada fora dos 38 | `/relatorio-viabilidade` |
| Futuro/bloqueado | Sem rota publica | Sankhya/NF, vendas, rastreabilidade comercial, giro, FIFO, CMV, OEE |
| Artefato orfao | Preservar ate revisao | templates de romaneio/historico e detalhe antigo de custo |

## Rotas oficiais de relatorio

| Rota | Endpoint | Decisao |
| --- | --- | --- |
| `/relatorios` | `biblioteca_relatorios` | Catalogo oficial |
| `/relatorios/financeiro/<slug>` | `relatorio_financeiro_oficial` | Oficial |
| `/relatorios/financeiro/<slug>/exportar` | `relatorio_financeiro_oficial_exportar` | Exportacao Excel |
| `/relatorios/producao/<slug>` | `relatorio_producao_oficial` | Oficial |
| `/relatorios/producao/<slug>/exportar` | `relatorio_producao_oficial_exportar` | Exportacao Excel |
| `/relatorios/almoxarifado/<slug>` | `relatorio_almoxarifado_oficial` | Oficial |
| `/relatorios/almoxarifado/<slug>/exportar` | `relatorio_almoxarifado_oficial_exportar` | Exportacao Excel |
| `/relatorios/expedicao/<slug>` | `relatorio_expedicao_oficial` | Oficial |
| `/relatorios/expedicao/<slug>/exportar` | `relatorio_expedicao_oficial_exportar` | Exportacao Excel |
| `/relatorios/gerencial/<slug>` | `relatorio_gerencial_oficial` | Oficial |
| `/relatorios/gerencial/<slug>/exportar` | `relatorio_gerencial_oficial_exportar` | Exportacao Excel |
| `/dre-gerencial` | `dre_gerencial` | Oficial financeiro |
| `/dre-gerencial/exportar-excel` | `exportar_dre_gerencial_excel` | Exportacao Excel |
| `/fluxo-caixa` | `fluxo_caixa` | Oficial financeiro |

## Relatorios legados

| Rota | Situacao | Decisao |
| --- | --- | --- |
| `/relatorio-rendimento` | Equivalente ao relatorio oficial de rendimento | Redirecionar para `/relatorios/producao/rendimento` |
| `/relatorio-custos` | Usa base legada de custos mensais cadastrados | Preservar como requisito gerencial legado fora dos 38 ate decisao humana |
| `/relatorio-viabilidade` | Ferramenta operacional da Qualidade para viabilidade, perdas e fornecedores | Preservar fora da Biblioteca; nao possui equivalente 1:1 |

Nenhuma rota recebeu 410 nesta sprint, porque as remocoes definitivas dependem de decisao funcional ou substituto 1:1 comprovado.

## Exportacoes auditadas

| Rota | Decisao |
| --- | --- |
| `/dre-gerencial/exportar-excel` | Mantida |
| `/movimentacoes/auditoria/exportar` | Tela operacional/auditoria, fora da Biblioteca |
| `/movimentacoes/liquidacao/exportar` | Tela operacional, fora da Biblioteca |
| `/movimentacoes/modelo-importacao-oficial` | Modelo operacional, fora da Biblioteca |
| `/relatorios/financeiro/<slug>/exportar` | Mantida |
| `/relatorios/producao/<slug>/exportar` | Mantida |
| `/relatorios/almoxarifado/<slug>/exportar` | Mantida |
| `/relatorios/expedicao/<slug>/exportar` | Mantida |
| `/relatorios/gerencial/<slug>/exportar` | Mantida |

## Correcoes aplicadas

- O item `producao-rendimento` deixou de anunciar `PDF`, pois a aplicacao oferece impressao pelo navegador, nao geracao real de PDF.
- O formato oficial passou a ser `Impressao`.
- O link visual para `Rendimento legado` foi removido da tela oficial de rendimento.
- `/relatorio-rendimento` passou a redirecionar para `/relatorios/producao/rendimento`, preservando query string.

## Artefatos orfaos ou sem rota direta

Templates preservados para revisao posterior:
- `historico_romaneios.html`
- `romaneio_expedicao.html`
- `romaneio_visualizar.html`
- `destinatarios_expedicao.html`
- `dre_detalhe_custo.html`

Esses arquivos nao foram excluidos porque podem representar fluxo operacional antigo, impressao ou decisao funcional pendente.

## Pendencias funcionais

- Decidir destino definitivo de `/relatorio-custos` apos avaliar migracao dos custos mensais cadastrados.
- Decidir se `/relatorio-viabilidade` deve virar item oficial futuro ou permanecer como ferramenta operacional da Qualidade.
- Implementar somente em sprint propria os relatorios congelados/futuros de vendas, rastreabilidade comercial, giro, FIFO, CMV, Sankhya/NF e OEE.
- Avaliar os templates orfaos antes de qualquer remocao fisica.
