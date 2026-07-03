# Auditoria Arquitetural do Monolito FrigoDatta

Sprint 1 - Inventario tecnico do estado atual antes de modularizacao.

## Escopo e Premissas

- Projeto auditado: FrigoDatta Abatedouro Indicadores.
- Arquivo principal: `app.py`.
- Esta Sprint nao altera codigo, regras de negocio, templates ou calculos.
- Relatorio gerado por leitura estatica do codigo com AST e conferencia textual.
- Ponto seguro anterior existente: tag `PONTO_SEGURO_ANTES_REFATORACAO_ARQUITETURAL`.

## Resumo Executivo

- Linhas em `app.py`: 9241.
- Funcoes top-level em `app.py`: 223.
- Rotas Flask declaradas em `app.py`: 66.
- Templates renderizados diretamente por rotas: 44.
- Templates HTML existentes em `templates/`: 52.
- Funcoes com perfil de banco/persistencia: 99.
- Funcoes com perfil de calculo/normalizacao/preparacao: 34.
- Rotinas estruturais `criar_*`: 12.

## Lista Completa de Rotas

| # | Rota | Metodos | Funcao | Template(s) | Modulo provavel | Linha |
|---:|---|---|---|---|---|---:|
| 1 | `/almoxarifado` | GET, POST | `almoxarifado` | `almoxarifado.html` | Almoxarifado | 3867 |
| 2 | `/almoxarifado/editar/<int:insumo_id>` | GET, POST | `editar_insumo_almoxarifado` | `almoxarifado_editar.html` | Almoxarifado | 3899 |
| 3 | `/almoxarifado/entrada` | GET, POST | `entrada_estoque_almoxarifado` | `almoxarifado_entrada.html` | Almoxarifado | 3924 |
| 4 | `/almoxarifado/movimentacoes` | GET | `movimentacoes_almoxarifado` | `almoxarifado_movimentacoes.html` | Almoxarifado | 3977 |
| 5 | `/almoxarifado/rastreabilidade` | GET | `rastreabilidade_almoxarifado` | `almoxarifado_rastreabilidade.html` | Almoxarifado | 4019 |
| 6 | `/almoxarifado/saldo` | GET | `saldo_almoxarifado` | `almoxarifado_saldo.html` | Almoxarifado | 3956 |
| 7 | `/apontamento-descartes` | GET, POST | `apontamento_descartes` | `apontamento_descartes.html` | Apontamentos de Producao | 7429 |
| 8 | `/apontamento-mao-obra` | GET, POST | `apontamento_mao_obra` | `apontamento_mao_obra.html` | Apontamentos de Producao | 7235 |
| 9 | `/apontamento-paradas` | GET, POST | `apontamento_paradas` | `apontamento_paradas.html` | Apontamentos de Producao | 7367 |
| 10 | `/apontamento-setor` | GET, POST | `apontamento_setor` | `apontamento_setor.html` | Apontamentos de Producao | 7206 |
| 11 | `/descartes/lote/editar` | GET, POST | `editar_descartes_lote` | `editar_descartes_lote.html` | Apontamentos de Producao | 7973 |
| 12 | `/descartes/lote/excluir` | POST | `excluir_descartes_lote` | Sem template direto (redirect/acao) | Apontamentos de Producao | 8027 |
| 13 | `/mao-obra/<int:mao_obra_id>/editar` | GET, POST | `editar_mao_obra` | `editar_mao_obra.html` | Apontamentos de Producao | 7507 |
| 14 | `/mao-obra/lote/editar` | GET, POST | `editar_mao_obra_lote` | `editar_mao_obra_lote.html` | Apontamentos de Producao | 7743 |
| 15 | `/mao-obra/lote/excluir` | POST | `excluir_mao_obra_lote` | Sem template direto (redirect/acao) | Apontamentos de Producao | 7825 |
| 16 | `/parada/<int:parada_id>/editar` | GET, POST | `editar_parada` | `editar_parada.html` | Apontamentos de Producao | 7602 |
| 17 | `/paradas/lote/editar` | GET, POST | `editar_paradas_lote` | `editar_paradas_lote.html` | Apontamentos de Producao | 7862 |
| 18 | `/paradas/lote/excluir` | POST | `excluir_paradas_lote` | Sem template direto (redirect/acao) | Apontamentos de Producao | 7934 |
| 19 | `/tempos-setor` | GET, POST | `tempos_setor` | `tempos_setor.html` | Apontamentos de Producao | 7386 |
| 20 | `/` | GET, POST | `login` | `login.html` | Autenticacao e usuarios | 5529 |
| 21 | `/cadastrar-usuario` | GET, POST | `cadastrar_usuario` | `cadastrar_usuario.html` | Autenticacao e usuarios | 8270 |
| 22 | `/sair` | GET | `sair` | Sem template direto (redirect/acao) | Autenticacao e usuarios | 5565 |
| 23 | `/custos` | GET, POST | `custos` | `custos.html` | Custos | 6707 |
| 24 | `/custos/mensal/<int:custo_id>/editar` | GET, POST | `editar_custo_mensal` | `editar_custo_mensal.html` | Custos | 6787 |
| 25 | `/custos/mensal/<int:custo_id>/excluir` | POST | `excluir_custo_mensal` | Sem template direto (redirect/acao) | Custos | 6833 |
| 26 | `/relatorio-custos` | GET | `relatorio_custos` | `relatorio_custos.html` | Custos | 6650 |
| 27 | `/dre-gerencial` | GET | `dre_gerencial` | `dre_gerencial.html` | DRE Gerencial | 6619 |
| 28 | `/dre-gerencial/exportar-excel` | GET | `exportar_dre_gerencial_excel` | Sem template direto (redirect/acao) | DRE Gerencial | 6599 |
| 29 | `/dashboard` | GET | `dashboard` | `dashboard.html` | Dashboard | 5572 |
| 30 | `/embalagem-primaria` | GET, POST | `embalagem_primaria` | `embalagem_primaria.html` | Embalagem Primaria | 6139 |
| 31 | `/embalagem-secundaria` | GET, POST | `embalagem_secundaria` | `embalagem_secundaria.html` | Estoque PI/PA e Embalagem Secundaria | 6247 |
| 32 | `/embalagem-secundaria/<int:op_id>/finalizar` | POST | `finalizar_embalagem_secundaria` | Sem template direto (redirect/acao) | Estoque PI/PA e Embalagem Secundaria | 6213 |
| 33 | `/embalagem-secundaria/<int:op_id>/resetar` | POST | `resetar_embalagem_secundaria_op` | Sem template direto (redirect/acao) | Estoque PI/PA e Embalagem Secundaria | 6230 |
| 34 | `/estoque-produtos` | GET | `estoque_produtos` | `estoque_produtos.html` | Estoque PI/PA e Embalagem Secundaria | 6196 |
| 35 | `/expedicao` | GET | `expedicao` | `expedicao.html` | Expedicao | 6327 |
| 36 | `/expedicao/<int:expedicao_id>` | GET, POST | `detalhe_romaneio_expedicao` | `romaneio_detalhe.html` | Expedicao | 6569 |
| 37 | `/expedicao/novo` | GET, POST | `novo_romaneio_expedicao` | `novo_romaneio.html` | Expedicao | 6441 |
| 38 | `/financeiro` | GET | `financeiro` | Sem template direto (redirect/acao) | Financeiro / Movimentacoes | 7031 |
| 39 | `/financeiro/editar/<int:movimentacao_id>` | GET, POST | `editar_movimentacao_financeira` | `financeiro_editar.html` | Financeiro / Movimentacoes | 7076 |
| 40 | `/financeiro/excluir/<int:movimentacao_id>` | POST | `excluir_movimentacao_financeira_rota` | Sem template direto (redirect/acao) | Financeiro / Movimentacoes | 7104 |
| 41 | `/movimentacoes` | GET | `movimentacoes` | Sem template direto (redirect/acao) | Financeiro / Movimentacoes | 7037 |
| 42 | `/movimentacoes/despesas` | GET, POST | `movimentacoes_despesas` | `financeiro.html` | Financeiro / Movimentacoes | 7055 |
| 43 | `/movimentacoes/entradas` | GET, POST | `movimentacoes_entradas` | `financeiro.html` | Financeiro / Movimentacoes | 7043 |
| 44 | `/movimentacoes/estoque` | GET | `movimentacoes_estoque` | `financeiro.html` | Financeiro / Movimentacoes | 7067 |
| 45 | `/fornecedores` | GET, POST | `fornecedores` | `fornecedores.html` | Fornecedores | 7113 |
| 46 | `/importar-maio` | GET, POST | `importar_maio` | `importar_maio.html` | Importacao Maio/2026 | 9208 |
| 47 | `/cadastros/equipamentos` | GET, POST | `cadastro_equipamentos_manutencao` | `cadastro_equipamentos.html` | Manutencao | 7275 |
| 48 | `/cadastros/equipamentos/<int:equipamento_id>/editar` | POST | `editar_equipamento_manutencao` | Sem template direto (redirect/acao) | Manutencao | 7295 |
| 49 | `/cadastros/equipamentos/<int:equipamento_id>/excluir` | POST | `excluir_equipamento_manutencao` | Sem template direto (redirect/acao) | Manutencao | 7307 |
| 50 | `/manutencao` | GET, POST | `manutencao` | `manutencao.html` | Manutencao | 7319 |
| 51 | `/manutencao/ordem/<int:ordem_id>/atualizar` | POST | `atualizar_ordem_manutencao_rota` | Sem template direto (redirect/acao) | Manutencao | 7339 |
| 52 | `/manutencao/ordem/<int:ordem_id>/recursos` | POST | `salvar_recursos_ordem_manutencao_rota` | Sem template direto (redirect/acao) | Manutencao | 7351 |
| 53 | `/consultar-op` | GET | `consultar_op` | `consultar_op.html` | Ordem de Producao | 8177 |
| 54 | `/op/<int:op_id>/editar` | GET, POST | `editar_op` | `editar_op.html` | Ordem de Producao | 7449 |
| 55 | `/op/<int:op_id>/encerrar` | POST | `encerrar_op` | Sem template direto (redirect/acao) | Ordem de Producao | 8090 |
| 56 | `/op/<int:op_id>/excluir` | POST | `excluir_op` | Sem template direto (redirect/acao) | Ordem de Producao | 8065 |
| 57 | `/op/<int:op_id>/imprimir` | GET | `imprimir_op` | `op_impressao.html` | Ordem de Producao | 8234 |
| 58 | `/op/<int:op_id>/reabrir` | POST | `reabrir_op` | Sem template direto (redirect/acao) | Ordem de Producao | 8146 |
| 59 | `/ordem-producao` | GET, POST | `ordem_producao` | `ordem_producao.html` | Ordem de Producao | 7156 |
| 60 | `/receitas-sku` | GET, POST | `receitas_sku` | `receitas_sku.html` | Receitas / SKU | 4303 |
| 61 | `/receitas-sku/item/<int:item_id>/excluir` | POST | `excluir_item_receita_sku_rota` | Sem template direto (redirect/acao) | Receitas / SKU | 4346 |
| 62 | `/relatorio-rendimento` | GET | `relatorio_rendimento` | `relatorio_rendimento.html` | Relatorio de Rendimento | 8316 |
| 63 | `/relatorio-viabilidade` | GET | `relatorio_viabilidade` | `relatorio_viabilidade.html` | Relatorio de Viabilidade | 8878 |
| 64 | `/vendas` | GET, POST | `vendas` | `vendas.html` | Vendas | 6762 |
| 65 | `/vendas/<int:venda_id>/editar` | GET, POST | `editar_venda_diaria` | `editar_venda_diaria.html` | Vendas | 6856 |
| 66 | `/vendas/<int:venda_id>/excluir` | POST | `excluir_venda_diaria` | Sem template direto (redirect/acao) | Vendas | 6949 |

## Modulos e Funcoes Auxiliares Usadas

### Almoxarifado

- Rotas: 6
- Templates: `almoxarifado.html`, `almoxarifado_editar.html`, `almoxarifado_entrada.html`, `almoxarifado_movimentacoes.html`, `almoxarifado_rastreabilidade.html`, `almoxarifado_saldo.html`
- Funcoes auxiliares chamadas por rotas: `atualizar_insumo_almoxarifado`, `buscar_insumo_almoxarifado_por_id`, `buscar_insumos_almoxarifado`, `buscar_lotes_almoxarifado`, `buscar_lotes_almoxarifado_filtrado`, `buscar_movimentacoes_almoxarifado`, `buscar_movimentacoes_almoxarifado_filtrado`, `buscar_saldos_almoxarifado`, `buscar_saldos_almoxarifado_filtrado`, `calcular_resumo_almoxarifado`, `calcular_resumo_estoque_almoxarifado`, `calcular_resumo_rastreabilidade`, `criar_tabelas_almoxarifado`, `criar_tabelas_estoque_almoxarifado`, `salvar_entrada_estoque_almoxarifado`, `salvar_insumo_almoxarifado`
- Funcoes de banco/persistencia do modulo: `atualizar_insumo_almoxarifado`, `buscar_insumo_almoxarifado_por_id`, `buscar_insumos_almoxarifado`, `buscar_lotes_almoxarifado`, `buscar_lotes_almoxarifado_filtrado`, `buscar_movimentacoes_almoxarifado`, `buscar_movimentacoes_almoxarifado_filtrado`, `buscar_saldos_almoxarifado`, `buscar_saldos_almoxarifado_filtrado`, `criar_tabelas_almoxarifado`, `criar_tabelas_estoque_almoxarifado`, `salvar_entrada_estoque_almoxarifado`, `salvar_insumo_almoxarifado`
- Funcoes de calculo/preparacao do modulo: `calcular_resumo_almoxarifado`, `calcular_resumo_estoque_almoxarifado`, `calcular_resumo_rastreabilidade`
- Dependencias detectadas com outros modulos: Infraestrutura / apresentacao

### Apontamentos de Producao

- Rotas: 13
- Templates: `apontamento_descartes.html`, `apontamento_mao_obra.html`, `apontamento_paradas.html`, `apontamento_setor.html`, `editar_descartes_lote.html`, `editar_mao_obra.html`, `editar_mao_obra_lote.html`, `editar_parada.html`, `editar_paradas_lote.html`, `tempos_setor.html`
- Funcoes auxiliares chamadas por rotas: `buscar_op_por_id`, `buscar_ordens`, `buscar_ordens_abertas`, `buscar_tempos_setor_por_op`, `conectar`, `contexto_apontamento`, `copiar_mao_obra_de_op`, `criar_banco`, `criar_tabela_tempos_setor`, `edicao_bloqueada_por_status`, `ids_do_request`, `obter_registros_por_ids`, `primeiro_op_id`, `q`, `salvar_apontamento_descarte`, `salvar_apontamento_mao_obra`, `salvar_apontamento_parada`, `salvar_apontamentos_descartes_lote`, `salvar_tempos_setor`, `setores_por_sku`
- Funcoes de banco/persistencia do modulo: `buscar_apontamento_embalagem_primaria_por_op`, `buscar_apontamentos_embalagem_primaria`, `buscar_tempos_setor_por_op`, `copiar_mao_obra_de_op`, `criar_tabela_tempos_setor`, `excluir_descartes_lote`, `excluir_mao_obra_lote`, `excluir_paradas_lote`, `registrar_apontamento_embalagem_primaria`, `salvar_apontamento_descarte`, `salvar_apontamento_mao_obra`, `salvar_apontamento_parada`, `salvar_apontamentos_descartes_lote`, `salvar_tempos_setor`
- Dependencias detectadas com outros modulos: Custos e Vendas, Estoque PI/PA e Embalagem Secundaria, Financeiro / Movimentacoes, Infraestrutura / apresentacao, Ordem de Producao, Producao - auxiliares, Producao / Manutencao, Receitas / SKU

### Autenticacao e usuarios

- Rotas: 3
- Templates: `cadastrar_usuario.html`, `login.html`
- Funcoes auxiliares chamadas por rotas: `conectar`, `criar_banco`, `q`
- Dependencias detectadas com outros modulos: Custos e Vendas, Infraestrutura / apresentacao

### Custos

- Rotas: 4
- Templates: `custos.html`, `editar_custo_mensal.html`, `relatorio_custos.html`
- Funcoes auxiliares chamadas por rotas: `buscar_custo_mensal_por_id`, `buscar_custos_mensais`, `buscar_dados_relatorio_custos`, `buscar_parametros_custos`, `conectar`, `criar_banco`, `criar_tabelas_custos`, `q`, `salvar_custo_mensal`, `salvar_custos_mensais_lote`, `salvar_parametros_custos`
- Funcoes de banco/persistencia do modulo: `buscar_custo_mensal_por_id`, `buscar_custos_mensais`, `buscar_dados_relatorio_custos`, `buscar_parametros_custos`, `criar_tabelas_custos`, `excluir_custo_mensal`, `salvar_custo_mensal`, `salvar_custos_mensais_lote`, `salvar_parametros_custos`
- Funcoes de calculo/preparacao do modulo: `preparar_linhas_custos_executivas`
- Dependencias detectadas com outros modulos: Custos e Vendas, Infraestrutura / apresentacao, Receitas / SKU, Relatorios gerenciais

### Custos e Vendas

- Rotas: 0
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Funcoes de banco/persistencia do modulo: `criar_banco`
- Dependencias detectadas com outros modulos: Infraestrutura / apresentacao

### DRE Gerencial

- Rotas: 2
- Templates: `dre_gerencial.html`
- Funcoes auxiliares chamadas por rotas: `buscar_dados_dre_gerencial`, `criar_banco`, `criar_tabela_vendas`, `criar_tabelas_custos`, `gerar_excel_dre_gerencial`
- Funcoes de banco/persistencia do modulo: `buscar_dados_dre_gerencial`
- Dependencias detectadas com outros modulos: Custos, Custos e Vendas, Infraestrutura / apresentacao, Vendas

### Dashboard

- Rotas: 1
- Templates: `dashboard.html`
- Funcoes auxiliares chamadas por rotas: `conectar`, `q`
- Dependencias detectadas com outros modulos: Custos e Vendas, Infraestrutura / apresentacao

### Embalagem Primaria

- Rotas: 1
- Templates: `embalagem_primaria.html`
- Funcoes auxiliares chamadas por rotas: `buscar_apontamento_embalagem_primaria_por_op`, `buscar_apontamentos_embalagem_primaria`, `buscar_caixas_pa`, `buscar_op_por_id`, `buscar_ops_para_embalagem_primaria`, `buscar_saldos_estoque_pi`, `calcular_resumo_estoques_pi_pa`, `registrar_apontamento_embalagem_primaria`
- Funcoes de banco/persistencia do modulo: `buscar_ops_para_embalagem_primaria`
- Dependencias detectadas com outros modulos: Apontamentos de Producao, Custos e Vendas, Estoque PI/PA e Embalagem Secundaria, Infraestrutura / apresentacao, Ordem de Producao

### Estoque PI/PA e Embalagem Secundaria

- Rotas: 4
- Templates: `embalagem_secundaria.html`, `estoque_produtos.html`
- Funcoes auxiliares chamadas por rotas: `buscar_caixas_pa`, `buscar_movimentacoes_estoque_pi`, `buscar_ops_com_saldo_pi`, `buscar_saldos_estoque_pi`, `calcular_fechamento_industrial_op`, `calcular_resumo_estoques_pi_pa`, `conectar`, `finalizar_embalagem_secundaria_op`, `q`, `registrar_caixa_pa_manual`, `registrar_caixas_pa_lote`, `resetar_processamento_op`
- Funcoes de banco/persistencia do modulo: `buscar_caixas_pa`, `buscar_expedicoes`, `buscar_ops_com_saldo_pi`, `buscar_resumo_pa_completo`, `buscar_saldos_estoque_pa`, `buscar_saldos_estoque_pi`, `criar_tabela_estoque_produto_acabado`, `criar_tabelas_estoque_pi_pa`, `inserir_caixa_pa`, `registrar_caixa_pa_manual`, `registrar_caixas_pa_lote`, `registrar_entrada_estoque_pa_op`, `registrar_entrada_estoque_pi_op`, `registrar_lote_pa_galinha_inteira`, `registrar_saida_pi_por_caixa`
- Funcoes de calculo/preparacao do modulo: `buscar_resumo_pa_completo`, `calcular_fechamento_industrial_op`, `calcular_perdas_aves_op`, `calcular_resumo_estoque_pa`, `calcular_resumo_estoques_pi_pa`, `calcular_validade_padrao`, `preparar_composicao_caixa`, `validar_balanco_aves_op`, `validar_reset_processamento_op`, `validar_saldo_pi_para_composicoes`
- Dependencias detectadas com outros modulos: Custos e Vendas, Expedicao, Financeiro / Movimentacoes, Infraestrutura / apresentacao, Ordem de Producao, Producao - auxiliares, Receitas / SKU

### Expedicao

- Rotas: 3
- Templates: `expedicao.html`, `novo_romaneio.html`, `romaneio_detalhe.html`
- Funcoes auxiliares chamadas por rotas: `buscar_expedicao_por_id`, `buscar_expedicoes`, `buscar_itens_expedicao`, `calcular_resumo_expedicao`, `calcular_resumo_itens_expedicao`, `criar_tabelas_expedicao`, `salvar_item_expedicao`, `salvar_romaneio_expedicao`
- Funcoes de banco/persistencia do modulo: `buscar_expedicao_por_id`, `buscar_itens_expedicao`, `criar_tabelas_expedicao`, `salvar_item_expedicao`, `salvar_romaneio_expedicao`
- Funcoes de calculo/preparacao do modulo: `calcular_resumo_expedicao`, `calcular_resumo_itens_expedicao`
- Dependencias detectadas com outros modulos: Estoque PI/PA e Embalagem Secundaria, Infraestrutura / apresentacao

### Expedicao / Estoque / Embalagens

- Rotas: 0
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Dependencias detectadas com outros modulos: Estoque PI/PA e Embalagem Secundaria, Financeiro / Movimentacoes

### Financeiro / Movimentacoes

- Rotas: 7
- Templates: `financeiro.html`, `financeiro_editar.html`
- Funcoes auxiliares chamadas por rotas: `atualizar_movimentacao_financeira`, `buscar_movimentacao_financeira_por_id`, `contexto_movimentacoes`, `destino_movimentacao_por_tipo`, `excluir_movimentacao_financeira`, `salvar_movimentacao_por_visao`
- Funcoes de banco/persistencia do modulo: `atualizar_movimentacao_financeira`, `buscar_movimentacao_financeira_por_id`, `buscar_movimentacoes_estoque_pa`, `buscar_movimentacoes_estoque_pi`, `buscar_movimentacoes_financeiras`, `criar_tabela_movimentacoes_financeiras`, `excluir_movimentacao_financeira`, `excluir_movimentacao_financeira_rota`, `remover_movimentacoes_estoque_pa_por_op`, `remover_movimentacoes_estoque_pi_por_op`, `salvar_movimentacao_financeira`, `salvar_movimentacao_por_visao`
- Funcoes de calculo/preparacao do modulo: `agrupar_fluxo_por_dia`, `calcular_resumo_financeiro`, `calcular_status_financeiro_visual`, `preparar_movimentacoes_financeiras_para_tela`
- Dependencias detectadas com outros modulos: Estoque PI/PA e Embalagem Secundaria, Infraestrutura / apresentacao

### Fornecedores

- Rotas: 1
- Templates: `fornecedores.html`
- Funcoes auxiliares chamadas por rotas: `conectar`, `criar_banco`, `criar_tabela_fornecedores`, `q`
- Funcoes de banco/persistencia do modulo: `buscar_fornecedores`, `criar_tabela_fornecedores`
- Dependencias detectadas com outros modulos: Custos e Vendas, Infraestrutura / apresentacao

### Importacao Maio/2026

- Rotas: 1
- Templates: `importar_maio.html`
- Funcoes auxiliares chamadas por rotas: `importar_dados_oficiais_maio`, `ler_planilha_importacao_maio`, `resumir_importacao_maio`
- Funcoes de banco/persistencia do modulo: `excluir_historico_maio_2026`, `importar_dados_oficiais_maio`, `importar_maio`
- Funcoes de calculo/preparacao do modulo: `normalizar_cabecalho_importacao`, `resumir_importacao_maio`
- Dependencias detectadas com outros modulos: Apontamentos de Producao, Custos e Vendas, Infraestrutura / apresentacao, Relatorios e Importacao

### Infraestrutura / apresentacao

- Rotas: 0
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Funcoes de calculo/preparacao do modulo: `formatar_moeda_br`, `formatar_numero_br`, `formatar_percentual_br`, `preparar_grafico_despesas_operacionais`

### Manutencao

- Rotas: 6
- Templates: `cadastro_equipamentos.html`, `manutencao.html`
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Funcoes de banco/persistencia do modulo: `excluir_equipamento_manutencao`

### Ordem de Producao

- Rotas: 7
- Templates: `consultar_op.html`, `editar_op.html`, `op_impressao.html`, `ordem_producao.html`
- Funcoes auxiliares chamadas por rotas: `buscar_fornecedores`, `buscar_op_por_id`, `buscar_ordens`, `calcular_resumo_op`, `conectar`, `criar_banco`, `criar_tabela_tempos_setor`, `gerar_producao_automatica_setores`, `op_possui_caixa_pa`, `q`, `remover_movimentacoes_estoque_pi_por_op`
- Funcoes de banco/persistencia do modulo: `atualizar_ordem_manutencao_rota`, `buscar_op_por_id`, `salvar_recursos_ordem_manutencao_rota`
- Funcoes de calculo/preparacao do modulo: `validar_op_aberta`
- Dependencias detectadas com outros modulos: Apontamentos de Producao, Custos e Vendas, Estoque PI/PA e Embalagem Secundaria, Financeiro / Movimentacoes, Fornecedores, Infraestrutura / apresentacao, Producao - auxiliares

### Producao - auxiliares

- Rotas: 0
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Funcoes de banco/persistencia do modulo: `buscar_ordens`, `buscar_ordens_abertas`
- Funcoes de calculo/preparacao do modulo: `calcular_resumo_op`
- Dependencias detectadas com outros modulos: Infraestrutura / apresentacao

### Producao / Manutencao

- Rotas: 0
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Funcoes de banco/persistencia do modulo: `excluir_op`
- Dependencias detectadas com outros modulos: Apontamentos de Producao, Custos e Vendas, Financeiro / Movimentacoes, Fornecedores, Infraestrutura / apresentacao, Ordem de Producao, Producao - auxiliares

### Receitas / SKU

- Rotas: 2
- Templates: `receitas_sku.html`
- Funcoes auxiliares chamadas por rotas: `buscar_insumos_almoxarifado`, `buscar_receitas_sku`, `buscar_skus`, `calcular_resumo_receitas_sku`, `criar_tabelas_receitas_sku`, `excluir_item_receita_sku`, `salvar_item_receita_sku`, `salvar_sku`
- Funcoes de banco/persistencia do modulo: `buscar_receitas_sku`, `buscar_skus`, `buscar_venda_diaria_por_data_sku`, `criar_tabelas_receitas_sku`, `excluir_item_receita_sku`, `excluir_item_receita_sku_rota`, `salvar_item_receita_sku`, `salvar_sku`
- Funcoes de calculo/preparacao do modulo: `calcular_resumo_receitas_sku`
- Dependencias detectadas com outros modulos: Almoxarifado, Infraestrutura / apresentacao, Ordem de Producao, Vendas

### Relatorio de Rendimento

- Rotas: 1
- Templates: `relatorio_rendimento.html`
- Funcoes auxiliares chamadas por rotas: `buscar_fornecedores`, `conectar`, `criar_banco`, `formatar_percentual_br`, `q`
- Dependencias detectadas com outros modulos: Custos e Vendas, Fornecedores, Infraestrutura / apresentacao

### Relatorio de Viabilidade

- Rotas: 1
- Templates: `relatorio_viabilidade.html`
- Funcoes auxiliares chamadas por rotas: `buscar_dados_relatorio_viabilidade`, `buscar_opcoes_relatorio_viabilidade`, `normalizar_data_relatorio_viabilidade`
- Funcoes de banco/persistencia do modulo: `buscar_dados_relatorio_viabilidade`, `buscar_opcoes_relatorio_viabilidade`
- Funcoes de calculo/preparacao do modulo: `normalizar_data_relatorio_viabilidade`
- Dependencias detectadas com outros modulos: Custos e Vendas, Infraestrutura / apresentacao

### Relatorios e Importacao

- Rotas: 0
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Dependencias detectadas com outros modulos: Custos e Vendas, Importacao Maio/2026, Infraestrutura / apresentacao, Producao - auxiliares

### Relatorios gerenciais

- Rotas: 0
- Funcoes auxiliares chamadas por rotas: nenhuma chamada local direta identificada.
- Funcoes de calculo/preparacao do modulo: `listar_competencias_periodo`, `normalizar_competencia`

### Vendas

- Rotas: 3
- Templates: `editar_venda_diaria.html`, `vendas.html`
- Funcoes auxiliares chamadas por rotas: `buscar_venda_diaria_por_data_sku`, `buscar_venda_diaria_por_id`, `buscar_vendas_diarias`, `conectar`, `criar_banco`, `criar_tabela_vendas`, `preparar_quantidades_venda`, `q`, `salvar_venda_diaria`
- Funcoes de banco/persistencia do modulo: `buscar_venda_diaria_por_id`, `buscar_vendas_diarias`, `criar_tabela_vendas`, `excluir_venda_diaria`, `salvar_venda_diaria`
- Funcoes de calculo/preparacao do modulo: `normalizar_venda_para_dre`, `preparar_quantidades_venda`
- Dependencias detectadas com outros modulos: Custos e Vendas, Infraestrutura / apresentacao, Receitas / SKU

## Funcoes de Banco de Dados e Persistencia

Inclui funcoes cujo nome indica criacao estrutural, busca, salvamento, atualizacao, exclusao, registro, remocao, copia ou importacao.

### Almoxarifado
- `criar_tabelas_almoxarifado` - linha 3298
- `salvar_insumo_almoxarifado` - linha 3331
- `buscar_insumos_almoxarifado` - linha 3368
- `buscar_insumo_almoxarifado_por_id` - linha 3403
- `atualizar_insumo_almoxarifado` - linha 3419
- `criar_tabelas_estoque_almoxarifado` - linha 3448
- `salvar_entrada_estoque_almoxarifado` - linha 3533
- `buscar_saldos_almoxarifado` - linha 3632
- `buscar_lotes_almoxarifado` - linha 3658
- `buscar_movimentacoes_almoxarifado` - linha 3681
- `buscar_saldos_almoxarifado_filtrado` - linha 3718
- `buscar_movimentacoes_almoxarifado_filtrado` - linha 3758
- `buscar_lotes_almoxarifado_filtrado` - linha 3795

### Apontamentos de Producao
- `criar_tabela_tempos_setor` - linha 644
- `registrar_apontamento_embalagem_primaria` - linha 1595
- `buscar_apontamentos_embalagem_primaria` - linha 1755
- `buscar_apontamento_embalagem_primaria_por_op` - linha 1774
- `salvar_apontamento_mao_obra` - linha 4998
- `copiar_mao_obra_de_op` - linha 5024
- `salvar_apontamento_parada` - linha 5076
- `salvar_apontamento_descarte` - linha 5212
- `salvar_apontamentos_descartes_lote` - linha 5238
- `salvar_tempos_setor` - linha 5429
- `buscar_tempos_setor_por_op` - linha 5482
- `excluir_mao_obra_lote` - linha 7825
- `excluir_paradas_lote` - linha 7934
- `excluir_descartes_lote` - linha 8027

### Custos
- `criar_tabelas_custos` - linha 683
- `buscar_parametros_custos` - linha 759
- `buscar_custos_mensais` - linha 777
- `salvar_parametros_custos` - linha 821
- `salvar_custo_mensal` - linha 861
- `salvar_custos_mensais_lote` - linha 885
- `buscar_custo_mensal_por_id` - linha 1156
- `buscar_dados_relatorio_custos` - linha 2653
- `excluir_custo_mensal` - linha 6833

### Custos e Vendas
- `criar_banco` - linha 280

### DRE Gerencial
- `buscar_dados_dre_gerencial` - linha 2893

### Embalagem Primaria
- `buscar_ops_para_embalagem_primaria` - linha 1794

### Estoque PI/PA e Embalagem Secundaria
- `criar_tabelas_estoque_pi_pa` - linha 1273
- `registrar_entrada_estoque_pi_op` - linha 1441
- `registrar_lote_pa_galinha_inteira` - linha 1522
- `buscar_saldos_estoque_pi` - linha 1812
- `buscar_caixas_pa` - linha 1866
- `buscar_ops_com_saldo_pi` - linha 1884
- `registrar_saida_pi_por_caixa` - linha 1926
- `inserir_caixa_pa` - linha 2036
- `registrar_caixa_pa_manual` - linha 2107
- `registrar_caixas_pa_lote` - linha 2151
- `buscar_resumo_pa_completo` - linha 2489
- `criar_tabela_estoque_produto_acabado` - linha 2535
- `registrar_entrada_estoque_pa_op` - linha 2543
- `buscar_saldos_estoque_pa` - linha 2547
- `buscar_expedicoes` - linha 2560

### Expedicao
- `criar_tabelas_expedicao` - linha 1190
- `salvar_romaneio_expedicao` - linha 6385
- `buscar_expedicao_por_id` - linha 6462
- `buscar_itens_expedicao` - linha 6480
- `salvar_item_expedicao` - linha 6511

### Financeiro / Movimentacoes
- `remover_movimentacoes_estoque_pi_por_op` - linha 1402
- `buscar_movimentacoes_estoque_pi` - linha 1848
- `remover_movimentacoes_estoque_pa_por_op` - linha 2539
- `buscar_movimentacoes_estoque_pa` - linha 2551
- `criar_tabela_movimentacoes_financeiras` - linha 4477
- `salvar_movimentacao_financeira` - linha 4556
- `buscar_movimentacao_financeira_por_id` - linha 4669
- `atualizar_movimentacao_financeira` - linha 4687
- `excluir_movimentacao_financeira` - linha 4724
- `buscar_movimentacoes_financeiras` - linha 4739
- `salvar_movimentacao_por_visao` - linha 7016
- `excluir_movimentacao_financeira_rota` - linha 7104

### Fornecedores
- `criar_tabela_fornecedores` - linha 4857
- `buscar_fornecedores` - linha 4880

### Importacao Maio/2026
- `excluir_historico_maio_2026` - linha 9139
- `importar_dados_oficiais_maio` - linha 9155
- `importar_maio` - linha 9208

### Manutencao
- `excluir_equipamento_manutencao` - linha 7307

### Ordem de Producao
- `buscar_op_por_id` - linha 5393
- `buscar_op_por_id` - linha 5500
- `atualizar_ordem_manutencao_rota` - linha 7339
- `salvar_recursos_ordem_manutencao_rota` - linha 7351

### Producao - auxiliares
- `buscar_ordens` - linha 4898
- `buscar_ordens_abertas` - linha 4911

### Producao / Manutencao
- `excluir_op` - linha 8065

### Receitas / SKU
- `buscar_venda_diaria_por_data_sku` - linha 1048
- `criar_tabelas_receitas_sku` - linha 4060
- `buscar_skus` - linha 4133
- `salvar_sku` - linha 4160
- `salvar_item_receita_sku` - linha 4186
- `excluir_item_receita_sku` - linha 4234
- `buscar_receitas_sku` - linha 4246
- `excluir_item_receita_sku_rota` - linha 4346

### Relatorio de Viabilidade
- `buscar_opcoes_relatorio_viabilidade` - linha 8502
- `buscar_dados_relatorio_viabilidade` - linha 8558

### Vendas
- `criar_tabela_vendas` - linha 948
- `salvar_venda_diaria` - linha 1088
- `buscar_vendas_diarias` - linha 1137
- `buscar_venda_diaria_por_id` - linha 1170
- `excluir_venda_diaria` - linha 6949

## Funcoes de Calculo, Normalizacao e Preparacao

### Almoxarifado
- `calcular_resumo_estoque_almoxarifado` - linha 3704
- `calcular_resumo_rastreabilidade` - linha 3836
- `calcular_resumo_almoxarifado` - linha 3851

### Custos
- `preparar_linhas_custos_executivas` - linha 172

### Estoque PI/PA e Embalagem Secundaria
- `calcular_perdas_aves_op` - linha 1478
- `validar_balanco_aves_op` - linha 1507
- `calcular_validade_padrao` - linha 1968
- `preparar_composicao_caixa` - linha 1983
- `validar_saldo_pi_para_composicoes` - linha 2020
- `calcular_fechamento_industrial_op` - linha 2221
- `validar_reset_processamento_op` - linha 2379
- `buscar_resumo_pa_completo` - linha 2489
- `calcular_resumo_estoques_pi_pa` - linha 2520
- `calcular_resumo_estoque_pa` - linha 2555

### Expedicao
- `calcular_resumo_expedicao` - linha 2602
- `calcular_resumo_itens_expedicao` - linha 6499

### Financeiro / Movimentacoes
- `calcular_status_financeiro_visual` - linha 4408
- `preparar_movimentacoes_financeiras_para_tela` - linha 4448
- `calcular_resumo_financeiro` - linha 4776
- `agrupar_fluxo_por_dia` - linha 4816

### Importacao Maio/2026
- `normalizar_cabecalho_importacao` - linha 8944
- `resumir_importacao_maio` - linha 9110

### Infraestrutura / apresentacao
- `formatar_numero_br` - linha 29
- `formatar_moeda_br` - linha 39
- `formatar_percentual_br` - linha 43
- `preparar_grafico_despesas_operacionais` - linha 62

### Ordem de Producao
- `validar_op_aberta` - linha 4944

### Producao - auxiliares
- `calcular_resumo_op` - linha 4949

### Receitas / SKU
- `calcular_resumo_receitas_sku` - linha 4287

### Relatorio de Viabilidade
- `normalizar_data_relatorio_viabilidade` - linha 8491

### Relatorios gerenciais
- `normalizar_competencia` - linha 2623
- `listar_competencias_periodo` - linha 2635

### Vendas
- `preparar_quantidades_venda` - linha 991
- `normalizar_venda_para_dre` - linha 2862

## Imports Possivelmente Nao Utilizados

- Linha 16: `from openpyxl.utils import get_column_letter` - nome auditado: `get_column_letter`.
- Linha 17: `from auth import login_obrigatorio, destino_por_perfil, perfil_permitido` - nome auditado: `login_obrigatorio`.
- Linha 19: `from utils import calcular_horas_programadas, calcular_produtividade, setores_padrao, normalizar_chave_setor` - nome auditado: `calcular_produtividade`.

Observacao: a remocao de imports deve ser validada em Sprint propria, pois esta auditoria nao altera codigo.

## Duplicidades Evidentes

- `buscar_op_por_id` definido em: linha 5393, linha 5500.
- Existem aliases/wrappers legados de Estoque PA que delegam para PI/PA, mantendo compatibilidade temporaria.
- Ha rotas alias/redirecionadoras (`/financeiro`, `/movimentacoes`) que devem ser preservadas ate decisao de compatibilidade.

## Funcoes Candidatas a Remocao Futura

Nao remover nesta Sprint. Candidatas dependem de validacao funcional, historico de links externos e deploy.

| Funcao/Rota | Motivo |
|---|---|
| `criar_tabela_estoque_produto_acabado` | Wrapper temporario de compatibilidade que apenas chama criar_tabelas_estoque_pi_pa. |
| `remover_movimentacoes_estoque_pa_por_op` | Wrapper legado que delega para remover_movimentacoes_estoque_pi_por_op. |
| `registrar_entrada_estoque_pa_op` | Wrapper legado que delega para registrar_entrada_estoque_pi_op. |
| `buscar_saldos_estoque_pa` | Wrapper legado que delega para buscar_saldos_estoque_pi. |
| `buscar_movimentacoes_estoque_pa` | Wrapper legado que delega para buscar_movimentacoes_estoque_pi. |
| `calcular_resumo_estoque_pa` | Wrapper legado que delega para calcular_resumo_estoques_pi_pa. |
| `buscar_op_por_id` | Definida duas vezes no app.py; manter apenas uma apos validacao. |
| `financeiro` | Rota antiga que hoje redireciona para movimentacoes_entradas; candidata a alias permanente ou remocao futura com plano de compatibilidade. |
| `movimentacoes` | Rota agregadora que redireciona para entradas; candidata a alias simples. |

## Dependencias Entre Modulos

- Almoxarifado depende de: Infraestrutura / apresentacao.
- Apontamentos de Producao depende de: Custos e Vendas, Estoque PI/PA e Embalagem Secundaria, Financeiro / Movimentacoes, Infraestrutura / apresentacao, Ordem de Producao, Producao - auxiliares, Producao / Manutencao, Receitas / SKU.
- Autenticacao e usuarios depende de: Custos e Vendas, Infraestrutura / apresentacao.
- Custos depende de: Custos e Vendas, Infraestrutura / apresentacao, Receitas / SKU, Relatorios gerenciais.
- Custos e Vendas depende de: Infraestrutura / apresentacao.
- DRE Gerencial depende de: Custos, Custos e Vendas, Infraestrutura / apresentacao, Vendas.
- Dashboard depende de: Custos e Vendas, Infraestrutura / apresentacao.
- Embalagem Primaria depende de: Apontamentos de Producao, Custos e Vendas, Estoque PI/PA e Embalagem Secundaria, Infraestrutura / apresentacao, Ordem de Producao.
- Estoque PI/PA e Embalagem Secundaria depende de: Custos e Vendas, Expedicao, Financeiro / Movimentacoes, Infraestrutura / apresentacao, Ordem de Producao, Producao - auxiliares, Receitas / SKU.
- Expedicao depende de: Estoque PI/PA e Embalagem Secundaria, Infraestrutura / apresentacao.
- Expedicao / Estoque / Embalagens depende de: Estoque PI/PA e Embalagem Secundaria, Financeiro / Movimentacoes.
- Financeiro / Movimentacoes depende de: Estoque PI/PA e Embalagem Secundaria, Infraestrutura / apresentacao.
- Fornecedores depende de: Custos e Vendas, Infraestrutura / apresentacao.
- Importacao Maio/2026 depende de: Apontamentos de Producao, Custos e Vendas, Infraestrutura / apresentacao, Relatorios e Importacao.
- Ordem de Producao depende de: Apontamentos de Producao, Custos e Vendas, Estoque PI/PA e Embalagem Secundaria, Financeiro / Movimentacoes, Fornecedores, Infraestrutura / apresentacao, Producao - auxiliares.
- Producao - auxiliares depende de: Infraestrutura / apresentacao.
- Producao / Manutencao depende de: Apontamentos de Producao, Custos e Vendas, Financeiro / Movimentacoes, Fornecedores, Infraestrutura / apresentacao, Ordem de Producao, Producao - auxiliares.
- Receitas / SKU depende de: Almoxarifado, Infraestrutura / apresentacao, Ordem de Producao, Vendas.
- Relatorio de Rendimento depende de: Custos e Vendas, Fornecedores, Infraestrutura / apresentacao.
- Relatorio de Viabilidade depende de: Custos e Vendas, Infraestrutura / apresentacao.
- Relatorios e Importacao depende de: Custos e Vendas, Importacao Maio/2026, Infraestrutura / apresentacao, Producao - auxiliares.
- Vendas depende de: Custos e Vendas, Infraestrutura / apresentacao, Receitas / SKU.

## Riscos Para Modularizacao

- `app.py` mistura camadas de rota, regra de negocio, SQL, importacao, exportacao Excel e formatacao de apresentacao.
- Varias funcoes de consulta chamam rotinas `criar_*`; a guarda recente reduz custo, mas a responsabilidade estrutural ainda esta espalhada.
- DRE, custos e vendas compartilham dados e regras de CMV; devem ser extraidos juntos ou por contrato muito claro.
- Estoque PI/PA, embalagem primaria/secundaria e expedicao tem acoplamento operacional por OP, SKU, caixa e saldo.
- Manutencao ja possui `services/` e `repositories/`, mas ainda e acionada por rotas no `app.py`; pode servir de modelo para extrair outros modulos.
- Importacao Maio/2026 executa carga historica sensivel; nao deve ser movida antes de testes de regressao e backup.
- Rotas de edicao/exclusao em lote compartilham helpers genericos (`obter_registros_por_ids`, `ids_do_request`, `primeiro_op_id`, `edicao_bloqueada_por_status`).

## Proposta de Ordem Segura Para Futura Modularizacao

1. Extrair apenas infraestrutura compartilhada pequena: conexao, `q`, filtros Jinja e helpers de formatacao.
2. Consolidar Manutencao, pois ja tem service/repository e menor dependencia da DRE.
3. Extrair Almoxarifado e Receitas/SKU juntos, mantendo contratos de estoque e insumos.
4. Extrair Financeiro/Movimentacoes sem tocar DRE, custos ou CMV.
5. Extrair Estoque PI/PA, Embalagens e Expedicao em uma etapa coordenada.
6. Deixar DRE/Custos/Vendas para uma etapa posterior com testes de regressao de indicadores.

## Validacoes Desta Sprint

- Nenhum arquivo de codigo foi alterado para produzir este inventario.
- O relatorio e documental e nao muda comportamento do sistema.
- Validacoes finais devem incluir compilacao Python e importacao da aplicacao antes do commit.

