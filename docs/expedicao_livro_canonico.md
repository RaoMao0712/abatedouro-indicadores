# Livro canônico de movimentação da Expedição

`estoque_eventos` é a fonte operacional oficial da Expedição. A tabela
`pa_movimentacoes` permanece preservada exclusivamente para compatibilidade
histórica explícita. O fallback só inclui uma linha legada quando não existe
evento canônico equivalente para a mesma caixa e o mesmo romaneio.

| arquivo | função/uso | tabela | finalidade | decisão |
|---|---|---|---|---|
| `modules/expedicao/estoque_service.py` | `_inserir_evento()` e fluxos de estoque | `estoque_eventos` | formação, reserva, remoção, cancelamento, confirmação, venda, estorno, devolução, bloqueio e auditoria | manter canônico |
| `modules/retrabalho/services.py` | encerramento/reversão de retrabalho | `estoque_eventos` | consumo, formação, reserva e liberação | manter canônico |
| `modules/pedidos_venda/services.py` | análise de romaneio | `estoque_eventos` | validar evento operacional do item | manter canônico |
| `modules/expedicao/services.py` | consultas de item, histórico e estoque | ambos | leitura operacional e compatibilidade histórica | migrado para adaptador canônico |
| `modules/relatorios/expedicao.py` | transferências, histórico e resumo | ambos | relatório oficial | migrado para adaptador canônico |
| `modules/expedicao/estornos_embalagem.py` | `_buscar_bloqueios*()` | ambos | bloquear reversão após movimento | migrado; legado somente fallback |
| `modules/producao/operacoes_op.py` | `_dados_bloqueios_caixas()` | ambos | reabertura e estorno integral | migrado; legado somente fallback |
| `modules/expedicao/encerramento_op.py` | `_preflight_cursor()` | ambos | impedir encerramento com movimento posterior | migrado; legado somente fallback |
| `modules/expedicao/reconciliacao_marco_zero.py` | `_preflight_cursor()` | ambos | vínculo histórico da OP 71 | legado isolado como fallback |
| `modules/expedicao/services.py` | `confirmar_transferencia_romaneio()` | `pa_movimentacoes` | escrita do fluxo anterior | desativado e isolado |
| `modules/movimentacoes/reset_financeiro.py` | catálogo de tabelas | `pa_movimentacoes` | escopo administrativo de reset | manter metadado; não é consumidor operacional |
| migrations e testes | DDL/fixtures | ambos | compatibilidade de schema e regressão | manter |

O adaptador `modules.expedicao.movimentacoes_canonicas` normaliza a leitura e
expõe a origem (`estoque_eventos` ou `pa_movimentacoes_fallback`). A rotina
`reconciliar_movimentacoes_expedicao()` é estritamente somente leitura e compara
documento, posição física, evento esperado/encontrado e presença legada.
