# Auditoria Final Pos-Refatoracao

Projeto: FrigoDatta Abatedouro Indicadores  
Data da auditoria: 2026-07-04  
Commit base auditado: `5f0647b`  
Objetivo: validar a arquitetura apos a modularizacao e identificar residuos perigosos antes das proximas sprints.

## Resumo executivo

A aplicacao inicializa, compila e os principais fluxos funcionais continuam operando com banco temporario. O `app.py` ficou sem rotas diretas e atualmente concentra criacao/configuracao da aplicacao, filtros Jinja, registro dos modulos e inicializacao controlada do schema.

Nao foram encontradas rotas duplicadas nem endpoints duplicados. Os testes obrigatorios executados nesta auditoria passaram.

Ainda existem residuos arquiteturais importantes que devem ser tratados em sprints futuras, principalmente SQL fora de `repositories`, regras de negocio ainda misturadas em alguns `routes.py`/`services.py`, endpoints referenciados por templates antigos de romaneio e arquivos de repository vazios/import-only.

## Estado atual do roteamento

Total de regras Flask registradas: 67.

Resultado da verificacao:

- Rotas duplicadas: nenhuma encontrada.
- Endpoints duplicados: nenhum encontrado.
- `app.py` com rotas diretas: nenhuma rota `@app.route` encontrada.
- Registro modular ativo:
  - `auth`
  - `usuarios`
  - `cadastros`
  - `dashboard`
  - `custos`
  - `dre`
  - `relatorios`
  - `producao`
  - `qualidade`
  - `almoxarifado`
  - `expedicao`
  - `movimentacoes`
  - `manutencao`
  - `importacao_oficial`

Observacao: o projeto usa funcoes `register_*_routes(app)` em vez de Flask Blueprints nativos. O registro esta funcional, mas ainda nao e uma arquitetura Blueprint plena.

## Templates e endpoints

Foram auditadas chamadas `url_for(...)` em templates HTML.

Achado critico medio:

Os seguintes templates apontam para endpoints inexistentes no mapa atual:

| Template | Endpoint inexistente |
|---|---|
| `templates/destinatarios_expedicao.html` | `historico_romaneios_expedicao` |
| `templates/historico_romaneios.html` | `destinatarios_expedicao` |
| `templates/historico_romaneios.html` | `visualizar_romaneio_expedicao` |
| `templates/romaneio_expedicao.html` | `historico_romaneios_expedicao` |
| `templates/romaneio_expedicao.html` | `destinatarios_expedicao` |
| `templates/romaneio_visualizar.html` | `historico_romaneios_expedicao` |

Impacto: se essas telas forem acessadas/renderizadas em algum fluxo futuro, o Flask pode gerar erro de `BuildError`. Na bateria atual, as telas principais acessadas nao renderizaram esses endpoints ausentes.

Recomendacao: em sprint especifica de expedicao/romaneios, decidir se esses templates sao legados a remover ou se os endpoints devem ser restaurados/compatibilizados.

## Imports nao utilizados

Auditoria estatica simples indicou imports potencialmente nao utilizados:

- `modules/dre/services.py`: `get_column_letter`
- `modules/almoxarifado/repositories.py`: `conectar`, `q`
- `modules/expedicao/repositories.py`: `conectar`, `q`
- `modules/movimentacoes/repositories.py`: `conectar`, `q`
- `modules/producao/repositories.py`: `conectar`, `q`
- `modules/qualidade/repositories.py`: `conectar`, `q`
- arquivos `__init__.py` de modulos exportam simbolos que a analise estatica marca como nao usados, mas esses exports podem ser intencionais.

Impacto: baixo para runtime, medio para manutencao.

Recomendacao: remover imports realmente ociosos em uma sprint de limpeza tecnica, com `compileall` e importacao completa apos a remocao.

## Funcoes duplicadas ou sobrepostas

Foram encontrados nomes duplicados em locais diferentes. Parte e esperada por padrao repository/service/route, mas alguns casos merecem revisao:

- `criar_tabela_tempos_setor`: `app.py` e `modules/producao/services.py`
- `formatar_numero_br`, `formatar_moeda_br`, `formatar_percentual_br`: `app.py`, `filters.py`, `modules/dre/services.py`, `modules/qualidade/routes.py`
- `buscar_fornecedores`: `modules/cadastros/routes.py` e `modules/producao/services.py`
- helpers repetidos entre `modules/producao/routes.py` e `modules/qualidade/routes.py`: `ids_do_request`, `obter_registros_por_ids`, `primeiro_op_id`, `edicao_bloqueada_por_status`
- `executar_rotina_estrutural_uma_vez`: `app.py`, `modules/cadastros/routes.py`, `repositories/manutencao_repository.py`

Impacto: medio. Nao quebra a execucao atual, mas aumenta risco de divergencia futura.

Recomendacao: consolidar formatadores e guards estruturais em helpers compartilhados, e mover helpers duplicados para services comuns somente apos testes de regressao.

## Funcoes potencialmente nao utilizadas

A analise estatica por nomes encontrou muitos falsos positivos porque rotas Flask sao referenciadas dinamicamente por endpoint/template e muitos services sao usados via imports indiretos. Itens mais relevantes para revisao futura:

- `adicionar_meses` em `modules/movimentacoes/services.py`
- funcoes de estoque PA em `modules/expedicao/services.py` relacionadas a estrutura futura
- `registrar_filtros_jinja` em `filters.py`
- `login_obrigatorio` em `modules/auth/decorators.py`

Impacto: baixo imediato.

Recomendacao: nao remover nesta etapa. Confirmar por busca de referencias e teste funcional antes de qualquer exclusao.

## Banco de dados e camadas

Achado alto para arquitetura:

Ainda existem chamadas diretas a banco fora de repositories. Contagem aproximada por arquivo fora de `repositories`/`database`:

| Arquivo | Ocorrencias aproximadas |
|---|---:|
| `app.py` | 85 |
| `modules/expedicao/services.py` | 95 |
| `modules/cadastros/routes.py` | 52 |
| `modules/producao/routes.py` | 41 |
| `modules/producao/services.py` | 41 |
| `modules/almoxarifado/services.py` | 38 |
| `modules/qualidade/routes.py` | 21 |
| `modules/movimentacoes/services.py` | 20 |
| `modules/importacao_oficial/routes.py` | 9 |
| `modules/qualidade/services.py` | 4 |
| `modules/expedicao/routes.py` | 2 |

Impacto: medio/alto para manutencao e consistencia de arquitetura. A refatoracao reduziu o monolito, mas ainda nao isolou completamente SQL em repositories.

Observacao importante: `app.py` ainda contem rotinas estruturais de schema (`criar_banco`, `criar_tabela_tempos_setor`) e inicializacao controlada. Elas rodam no bootstrap via `inicializar_schema_aplicacao()` e tambem sao chamadas por login/importacao como integracao legada protegida por guarda em memoria.

Recomendacao: proxima fase deve centralizar schema remanescente em `database/schema.py` e migrar SQL operacional de `routes.py`/`services.py` para repositories por modulo, uma familia de telas por sprint.

## Regras de negocio fora dos services

Achado medio:

Ainda ha regras de negocio em:

- `modules/cadastros/routes.py`: vendas, receitas SKU e fornecedores ainda estao majoritariamente no arquivo de rotas.
- `modules/producao/routes.py`: edicoes, encerramento, exclusoes e algumas consultas ainda possuem SQL/regra diretamente na rota.
- `modules/qualidade/routes.py`: relatorios e edicoes ainda possuem SQL/regra diretamente na rota.
- `modules/importacao_oficial/routes.py`: parser, validacao e importacao estao no arquivo de rotas.

Impacto: medio. A aplicacao funciona, mas o desenho ainda nao esta totalmente route/service/repository.

Recomendacao: tratar como divida tecnica planejada, sem mudanca funcional ampla.

## Codigo estrutural de banco em requests

Achado medio:

As rotinas estruturais possuem guarda em memoria, mas algumas funcoes chamadas em fluxo normal ainda acionam criacao/verificacao estrutural:

- `criar_banco()` em login e integracoes legadas.
- `criar_tabelas_receitas_sku()` dentro de cadastros/receitas.
- `criar_tabela_vendas()` dentro de vendas/DRE.
- rotinas de estoque/almoxarifado/producao ainda chamadas por services antes de operacoes.

Mitigacao atual: guards `executar_rotina_estrutural_uma_vez` e `inicializar_schema_uma_vez` reduzem repeticao por processo.

Risco residual: em Render, cada novo processo ainda executa verificacoes estruturais no startup, o que e aceitavel agora; o risco maior e manter CREATE/ALTER espalhado.

## Inicializacao e performance

Teste de inicializacao local com banco temporario:

- Importacao da aplicacao e registro das 67 rotas: aproximadamente 1,652 segundos.
- Warnings Python em importacao com `warnings.simplefilter('default')`: nenhum warning reportado.

Conclusao: inicializacao local esta aceitavel para o estado atual. A lentidao anterior por repeticao estrutural em requests foi mitigada, mas a arquitetura ainda tem schema espalhado.

## Logs, erros e warnings

Durante os testes automatizados desta auditoria:

- Erros de runtime: nenhum nos testes aprovados.
- Warnings Python: nenhum reportado no teste de importacao.
- Warnings de Git/CRLF: podem aparecer ao stagear arquivos no Windows; nao sao warnings da aplicacao.

## Testes executados

### Compilacao

Comando:

```powershell
python -B -m compileall -q app.py modules services repositories database
```

Resultado: OK.

### Inicializacao local

Comando de importacao com banco temporario:

```powershell
$env:DB_NAME='test_auditoria_init.db'
python -B -c "import app; print('rules', len(list(app.app.url_map.iter_rules())))"
```

Resultado: OK, 67 rotas registradas.

### Login e logout

Resultado:

- `GET /`: OK
- `POST /` com `admin@app.com`: OK
- `GET /sair`: OK

### Fluxo completo de OP

Fluxo validado com banco temporario:

- Criar fornecedor: OK
- Criar OP: OK
- Confirmar OP aberta no banco: OK
- Consultar OP: OK
- Encerrar OP: OK
- Confirmar status `Encerrada`: OK
- Confirmar apontamentos automaticos gerados: OK

### Modulos principais

Telas validadas via test client com sessao admin:

- Dashboard: OK
- Producao: OK
- Qualidade: OK
- Almoxarifado: OK
- Expedicao: OK
- Movimentacoes: OK
- DRE: OK
- Relatorio de custos: OK
- Relatorio de rendimento: OK
- Relatorio de viabilidade: OK
- Usuarios/perfis: OK
- Equipamentos/manutencao: OK
- Manutencao: OK

### Usuarios e perfis

Perfis testados:

- `pcp`: cadastro OK, login OK, bloqueio em cadastro de usuario OK
- `producao`: cadastro OK, login OK, bloqueio em cadastro de usuario OK
- `qualidade`: cadastro OK, login OK, bloqueio em cadastro de usuario OK

Observacao: a tela atual de cadastro possui `admin`, `pcp`, `producao` e `qualidade`. Nao ha perfil financeiro separado na interface atual.

## Riscos residuais

1. Endpoints de romaneio historico ausentes em templates legados.
2. SQL e regras ainda espalhados em routes/services, especialmente Producao, Qualidade, Expedicao, Almoxarifado e Cadastros.
3. Schema estrutural ainda parcialmente em `app.py` e services.
4. Repositories vazios/import-only em alguns modulos criam falsa sensacao de separacao completa.
5. Funcoes duplicadas de formatacao/guard podem divergir em futuras manutencoes.

## Conclusao

A refatoracao foi validada funcionalmente e o sistema esta apto para seguir para deploy no Render a partir do estado auditado. Nao ha bloqueio imediato de runtime identificado nos fluxos obrigatorios.

A arquitetura modular esta funcional, mas ainda nao esta totalmente limpa. O principal proximo trabalho recomendado e uma sprint de endurecimento arquitetural, sem mudar regra de negocio, para:

1. Corrigir ou remover referencias a endpoints legados de romaneio.
2. Migrar SQL remanescente para repositories.
3. Mover regras ainda presentes em routes para services.
4. Centralizar schema estrutural remanescente em `database/schema.py`.
5. Remover imports/funcoes realmente ociosos apos validacao.
