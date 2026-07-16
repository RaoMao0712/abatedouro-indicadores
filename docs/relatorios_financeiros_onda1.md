# Relatorios Financeiros - Onda 1

Sprint: Biblioteca Oficial de Relatorios - Onda 1 / Bloco Financeiro  
Data: 2026-07-16

## Objetivo

Implantar telas oficiais e exportacao Excel para os relatorios financeiros derivados da Biblioteca Oficial, preservando os calculos ja existentes de Fluxo de Caixa e DRE Gerencial.

## Escopo Implantado

Relatorios financeiros oficiais da Onda 1:

| Relatorio | Rota | Fonte | Criterio temporal principal | Impacto |
|---|---|---|---|---|
| Fluxo de Caixa | `/fluxo-caixa` | Servico existente | Vencimento / realizacao | Mantido sem reescrita |
| Entradas de Caixa | `/relatorios/financeiro/entradas-caixa` | Central de Movimentacoes | `data_vencimento` | `impacta_fluxo_caixa = 1` |
| Saidas de Caixa | `/relatorios/financeiro/saidas-caixa` | Central de Movimentacoes | `data_vencimento` | `impacta_fluxo_caixa = 1` |
| Contas a Pagar | `/relatorios/financeiro/contas-pagar` | Central de Movimentacoes | `data_vencimento` | Saidas por vencimento/status |
| Contas a Receber | `/relatorios/financeiro/contas-receber` | Central de Movimentacoes | `data_vencimento` | Entradas por vencimento/status |
| DRE Gerencial | `/dre-gerencial` | Servico existente | Competencia | Mantido sem reescrita |
| Despesas por Categoria | `/relatorios/financeiro/despesas-categoria` | Central de Movimentacoes | `data_documento` | `linha_dre` nao neutra |
| Despesas por Subcategoria | `/relatorios/financeiro/despesas-subcategoria` | Central de Movimentacoes | `data_documento` | `linha_dre` nao neutra |
| Receitas | `/relatorios/financeiro/receitas` | Central de Movimentacoes | `data_documento` | Linhas oficiais de receita da DRE |
| Aportes | `/relatorios/financeiro/aportes` | Central de Movimentacoes | `data_vencimento` | Caixa sim, DRE nao |
| Evolucao Financeira | `/relatorios/financeiro/evolucao-financeira` | Central de Movimentacoes | `data_documento` | Fluxo + aportes destacados |
| Competencia x Realizacao | `/relatorios/financeiro/competencia-realizacao` | Central de Movimentacoes | `data_documento` | Competencia comparada com realizacao |

## Diretrizes Preservadas

- A Central de Movimentacoes permanece como fonte unica dos relatorios derivados.
- Nao foi criada base paralela.
- Nao houve alteracao de Plano de Contas, Matriz de Impacto, DRE, Fluxo de Caixa, CMV, importadores, estoque, producao, romaneios ou expedicao.
- Fluxo de Caixa e DRE Gerencial continuam usando suas rotas e servicos existentes.
- Os novos relatorios nao executam DDL, backfill ou gravacao em chamadas GET.
- Os filtros sao aplicados nas consultas ao banco, nao no template nem em JavaScript.

## Regras Tecnicas

- Relatorios de caixa usam `impacta_fluxo_caixa`.
- Relatorios economicos usam `linha_dre` e excluem linhas neutras.
- Aportes sao tratados como eventos de caixa que nao compoem DRE.
- Transferencias entre contas proprias ficam fora do fluxo consolidado quando `impacta_fluxo_caixa = 0`.
- Valores nao sao inferidos por texto livre ou sinal; o tipo, a linha da DRE e a matriz de impacto orientam a leitura.

## Validacao Controlada

Banco temporario com quatro eventos:

| Evento | Tipo | Valor | Linha DRE | Impacta Caixa | Resultado esperado |
|---|---:|---:|---|---:|---|
| Venda teste | Entrada | 1000,00 | Receita Bruta | 1 | Caixa e DRE |
| Energia teste | Saida | 300,00 | Despesas Operacionais | 1 | Caixa e DRE |
| Aporte teste | Entrada | 500,00 | Neutro | 1 | Caixa, fora da DRE |
| Transferencia teste | Neutro | 200,00 | Neutro | 0 | Fora do fluxo consolidado e da DRE |

Resultado validado:

- Entradas de Caixa: previsto 1500,00; realizado 1500,00.
- Saidas de Caixa: previsto 300,00; aberto/vencido 300,00.
- Aportes: previsto e realizado 500,00.
- Receitas: 1000,00.
- Despesas por Categoria/Subcategoria: 300,00.
- Evolucao Financeira: entradas 1500,00; saidas 300,00; saldo 1200,00; aportes destacados 500,00.
- Competencia x Realizacao: competencia 1200,00; realizado 1500,00; diferenca em aberto -300,00.
- Transferencia neutra nao entrou nos relatorios de caixa/DRE.

## Validacoes Locais Executadas

- `python -m compileall app.py modules\relatorios`
- Registro das rotas:
  - `/relatorios`
  - `/relatorios/financeiro/<slug>`
  - `/relatorios/financeiro/<slug>/exportar`
  - `/fluxo-caixa`
  - `/dre-gerencial`
- Test client Flask autenticado:
  - biblioteca filtrada por Financeiro: 200
  - Fluxo de Caixa: 200
  - DRE Gerencial: 200
  - 10 relatorios derivados: 200
  - 10 exportacoes Excel: 200, XLSX gerado
- Validacao visual no navegador local:
  - `/relatorios?dominio=Financeiro` sem overflow horizontal.
  - `/relatorios/financeiro/entradas-caixa` sem overflow horizontal em desktop.
  - `/relatorios/financeiro/entradas-caixa` sem overflow horizontal em viewport mobile.

## Arquivos Alterados

- `modules/relatorios/catalogo.py`
- `modules/relatorios/routes.py`
- `modules/relatorios/financeiro.py`
- `templates/relatorio_financeiro_oficial.html`
- `templates/base.html`
- `static/style.css`
- `docs/relatorios_financeiros_onda1.md`

