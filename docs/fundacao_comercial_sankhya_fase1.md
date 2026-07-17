# Fundacao Comercial Sankhya/NF - Fase 1

## Controle da sprint

- Projeto: PRUMO / FRIGODATTA Abatedouro.
- Sprint: Fundacao Comercial - Fase 1, contrato oficial de evento de venda e integracao Sankhya/NF.
- Worktree auditado: `C:\Users\g227716298.GRUPOSP-AD\.codex\worktrees\4ca3\abatedouro indicadores`.
- Commit inicial obrigatorio: `d165366f641c7e26f01eca5b22b6685fae9ec6c0`.
- Branch de trabalho: `codex/fundacao-comercial-sankhya-fase1`.
- Arquivos nao rastreados preservados fora do commit: `entregas/`, `tools/`, `reset_financeiro_producao_20260709_133850.zip`.

## Decisao arquitetural

Classificacao da sprint: **Cenario C - sem layout real suficiente**.

Nao foi encontrado no repositorio, nos anexos disponiveis ou na documentacao versionada um layout homologado do Sankhya/NF com campos, aliases, identificadores e semantica suficientes para implantar importador operacional. Portanto:

- nao foi criado importador ficticio;
- nao foi criada tela operacional com planilha inventada;
- nao foram criadas tabelas comerciais prematuras;
- nao foram criadas rotas de integracao Sankhya;
- os relatorios oficiais de Vendas e Rastreabilidade comercial permanecem sem endpoint publico;
- o resultado desta fase e um contrato canonico proposto, idempotente e auditavel, para validacao humana antes da Fase 2.

## Auditoria do estado atual

### Cadastro legado `/vendas`

O cadastro legado esta em `modules/cadastros/routes.py` e usa a tabela `vendas_diarias`.

Campos disponiveis:

| Campo | Uso atual |
| --- | --- |
| `id` | Identificador interno |
| `data` | Data consolidada da venda |
| `sku` | Produto/SKU informado |
| `quantidade` | Quantidade historica |
| `unidade` | Unidade informada |
| `quantidade_unidades` | Quantidade em unidades |
| `quantidade_kg` | Quantidade em kg |
| `receita` | Receita historica legado |
| `observacoes` | Observacoes livres |
| `criado_em` | Timestamp de criacao |

Fluxos de escrita:

- `GET/POST /vendas`;
- `GET/POST /vendas/<id>/editar`;
- `POST /vendas/<id>/excluir`.

Chave pratica de duplicidade: data + SKU.

Conclusao: `vendas_diarias` e um cadastro consolidado legado. Ele nao e evento comercial oficial porque nao possui NF, serie, chave NF-e, empresa, filial, cliente oficial, item comercial, identificador externo, status de documento, cancelamento, romaneio de venda, caixa PA, baixa fisica, conta a receber ou vinculo oficial com a Central de Movimentacoes.

### Sankhya, NF e cliente comercial

Nao foram encontrados:

- modulo oficial Sankhya;
- rota oficial de importacao Sankhya;
- template de importacao Sankhya;
- tabela de documento comercial/NF;
- tabela de itens comerciais;
- tabela de clientes comerciais oficiais;
- amostra CSV/XLSX homologada do Sankhya;
- documento com nomes reais de colunas do Sankhya;
- aliases comerciais oficiais;
- consulta ou API Sankhya versionada.

### Importadores existentes

Importador financeiro:

- rotas: `/movimentacoes/importar` e `/movimentacoes/importar-vendas`;
- funcao principal: `importar_movimentacoes_financeiras_excel`;
- dominio: Central de Movimentacoes e financeiro;
- possui upload, validacao, resolucao de Plano de Contas, idempotencia por `import_key`, insercoes/atualizacoes em lote, rollback em falha e resumo final;
- nao e importador comercial Sankhya/NF;
- nao cria documento comercial, item comercial, cliente comercial, romaneio de venda ou baixa PA.

Importador oficial de maio:

- rota: `/importar-maio`;
- dominio: importacao operacional de producao/OPs e descartes;
- nao e fonte comercial nem contrato Sankhya/NF.

### Expedicao, estoque PA e rastreabilidade fisica

Estruturas existentes:

- `expedicoes`;
- `expedicao_itens`;
- `pa_caixas`;
- `pa_caixa_composicao`;
- `pa_movimentacoes`;
- `locais_estoque`.

Uso atual:

- transferencias sao exclusivamente logisticas;
- a transferencia move `pa_caixas.local_estoque_id`;
- o evento fisico e registrado em `pa_movimentacoes` com tipo `TRANSFERENCIA`;
- nao ha venda, receita, conta a receber, DRE, Fluxo, CMV ou baixa comercial acoplada a transferencia.

### Banco e migracoes

Padroes observados:

- schema principal inicializado no startup por rotinas estruturais da aplicacao;
- uso de `CREATE TABLE IF NOT EXISTS` em services e app;
- alteracoes idempotentes com `ALTER TABLE ... ADD COLUMN` e helpers de migracao;
- compatibilidade tratada por ramificacoes SQLite/PostgreSQL;
- indices criados com `CREATE INDEX IF NOT EXISTS`;
- datas armazenadas majoritariamente como texto ISO ou timestamps;
- valores monetarios historicamente usam `REAL` em SQLite e tipos numericos no PostgreSQL quando aplicavel;
- status usam texto controlado por dominio;
- DDL deve permanecer fora de GETs e navegacao oportunista.

Nesta fase nao foi introduzido DDL novo.

## Contrato canonico proposto - nao homologado

Este contrato e uma proposta tecnica para validacao humana. Ele nao representa layout real Sankhya homologado.

### Documento comercial

| Campo canonico | Obrigatorio | Observacao |
| --- | --- | --- |
| `origem_sistema` | Sim | Ex.: `SANKHYA` |
| `empresa` | Sim | Empresa emissora/origem |
| `filial` | Sim | Filial emissora/origem |
| `modelo_documento` | Sim | Modelo fiscal/comercial |
| `numero_documento` | Sim, salvo se houver chave unica superior | Numero da NF/documento |
| `serie_documento` | Sim, salvo se houver chave unica superior | Serie da NF/documento |
| `chave_nfe` | Recomendado | Preferencia maxima de idempotencia quando existir |
| `identificador_externo` | Recomendado | ID interno Sankhya ou equivalente |
| `cliente_codigo_externo` | Sim | Identificador do cliente na origem |
| `data_emissao` | Sim | Data oficial de emissao |
| `data_saida` | Recomendado | Data de saida/operacao se existir |
| `status_documento` | Sim | Ex.: emitido, cancelado, denegado, inutilizado |
| `valor_bruto_documento` | Sim | Total bruto do documento |
| `valor_desconto_documento` | Recomendado | Desconto total |
| `valor_liquido_documento` | Sim | Total liquido do documento |
| `observacoes` | Opcional | Texto limitado e sanitizado |

### Item comercial

| Campo canonico | Obrigatorio | Observacao |
| --- | --- | --- |
| `documento_chave_canonica` | Sim | Referencia ao documento oficial |
| `item_identificador_externo` | Recomendado | ID do item na origem |
| `item_sequencia` | Sim | Sequencia oficial dentro do documento |
| `produto_codigo_externo` | Sim | Codigo do produto na origem |
| `sku_prumo` | Pendente de homologacao | Mapeamento comercial/produto, nao financeiro |
| `produto_descricao_original` | Sim | Descricao como veio da origem |
| `unidade` | Sim | Unidade do item |
| `quantidade` | Sim | Quantidade fiscal/comercial |
| `peso_liquido` | Quando oficial | Nao inferir se ausente |
| `peso_bruto` | Quando oficial | Nao inferir se ausente |
| `valor_unitario` | Sim | Valor unitario oficial |
| `valor_bruto_item` | Sim | Valor bruto do item |
| `valor_desconto_item` | Recomendado | Desconto do item |
| `valor_liquido_item` | Sim | Valor liquido do item |

### Cliente comercial

| Campo canonico | Obrigatorio | Observacao |
| --- | --- | --- |
| `origem_sistema` | Sim | Ex.: `SANKHYA` |
| `cliente_codigo_externo` | Sim | Chave externa |
| `razao_social_nome` | Sim | Nome oficial exibivel |
| `documento_cliente` | Recomendado | Mascara e exposicao restrita |
| `situacao_cliente` | Recomendado | Ativo/inativo/outro |
| `atualizado_em_origem` | Opcional | Se o layout trouxer |

### Lote/importacao comercial

| Campo canonico | Obrigatorio | Observacao |
| --- | --- | --- |
| `arquivo_nome_seguro` | Sim | Nome sanitizado |
| `arquivo_hash_sha256` | Sim | Idempotencia do arquivo |
| `origem_sistema` | Sim | Ex.: `SANKHYA` |
| `usuario` | Sim | Usuario autenticado |
| `status_importacao` | Sim | preview, confirmado, rejeitado, conflito, erro |
| `total_linhas` | Sim | Total lido |
| `total_documentos` | Sim | Documentos identificados |
| `total_itens` | Sim | Itens identificados |
| `total_aceitos` | Sim | Linhas/documentos aceitos |
| `total_rejeitados` | Sim | Rejeicoes |
| `total_conflitos` | Sim | Conflitos |
| `criado_em` | Sim | Timestamp do processamento |

## Idempotencia proposta

Chave natural do documento:

1. Preferencial: `origem_sistema + chave_nfe`.
2. Alternativa: `origem_sistema + empresa + filial + modelo_documento + serie_documento + numero_documento`.

Chave natural do item:

1. `documento_chave_canonica + item_sequencia`.
2. Se a origem fornecer ID de item estavel, validar tambem `documento_chave_canonica + item_identificador_externo`.

Chave do arquivo:

- `origem_sistema + sha256(conteudo_do_arquivo)`.

Regras:

- reimportacao identica deve ser no-op;
- reimportacao nao pode duplicar documento nem itens;
- documento com mesma chave e conteudo divergente deve virar conflito auditavel;
- conflito nao pode sobrescrever registro oficial silenciosamente;
- cancelamento deve ser evento/status rastreavel;
- falha parcial deve provocar rollback da unidade transacional;
- nenhuma linha pode ser parcialmente oficializada sem registro do resultado;
- data + SKU e proibido como chave oficial de venda.

## Layout proposto para validacao humana - nao homologado

Este modelo e apenas uma proposta para solicitar ou validar o layout real do Sankhya. Ele nao deve ser aceito como contrato produtivo sem homologacao.

| Coluna proposta | Obrigatoria | Entidade | Observacao |
| --- | --- | --- | --- |
| `origem_sistema` | Sim | Documento | Valor esperado: `SANKHYA` |
| `empresa` | Sim | Documento | Empresa emissora |
| `filial` | Sim | Documento | Filial emissora |
| `modelo_documento` | Sim | Documento | Modelo NF/documento |
| `numero_documento` | Sim | Documento | Numero oficial |
| `serie_documento` | Sim | Documento | Serie oficial |
| `chave_nfe` | Recomendado | Documento | Chave de acesso quando houver |
| `identificador_externo` | Recomendado | Documento | ID origem |
| `data_emissao` | Sim | Documento | Data oficial |
| `data_saida` | Recomendado | Documento | Data de saida/operacao |
| `status_documento` | Sim | Documento | Emitido/cancelado/etc. |
| `cliente_codigo_externo` | Sim | Cliente | Codigo origem |
| `cliente_nome` | Sim | Cliente | Razao social/nome |
| `cliente_documento` | Recomendado | Cliente | Exibicao controlada |
| `item_sequencia` | Sim | Item | Sequencia dentro do documento |
| `item_identificador_externo` | Recomendado | Item | ID origem do item |
| `produto_codigo_externo` | Sim | Item | Codigo Sankhya/produto |
| `produto_descricao` | Sim | Item | Descricao original |
| `sku_prumo` | Pendente | Item | Mapeamento depende de homologacao |
| `unidade` | Sim | Item | Unidade comercial/fiscal |
| `quantidade` | Sim | Item | Quantidade oficial |
| `peso_liquido` | Quando existir | Item | Nao inferir |
| `peso_bruto` | Quando existir | Item | Nao inferir |
| `valor_unitario` | Sim | Item | Valor unitario |
| `valor_bruto_item` | Sim | Item | Valor bruto do item |
| `valor_desconto_item` | Recomendado | Item | Desconto do item |
| `valor_liquido_item` | Sim | Item | Valor liquido do item |
| `valor_bruto_documento` | Sim | Documento | Total bruto |
| `valor_desconto_documento` | Recomendado | Documento | Desconto total |
| `valor_liquido_documento` | Sim | Documento | Total liquido |
| `cfop` | Opcional | Item/Documento | Se houver no layout |
| `natureza_operacao` | Opcional | Documento | Se houver no layout |
| `vendedor` | Opcional | Documento | Se houver no layout |
| `pedido_origem` | Opcional | Documento | Se houver no layout |
| `cancelado_em` | Quando cancelado | Documento | Data/hora de cancelamento |
| `substitui_chave_nfe` | Quando aplicavel | Documento | Somente se origem suportar |
| `observacoes` | Opcional | Documento | Texto limitado |

## Estados comerciais propostos

| Estado | Significado |
| --- | --- |
| `importado` | Arquivo lido e estruturado tecnicamente |
| `validado` | Documento/item passou nas validacoes obrigatorias |
| `pendente` | Falta mapeamento ou decisao semantica |
| `rejeitado` | Registro invalido com motivo rastreavel |
| `conflito` | Mesma chave natural com conteudo divergente |
| `cancelado` | Cancelamento oficial da origem |
| `substituido` | Somente se a origem trouxer relacao oficial de substituicao |
| `processado_logistica` | Estado futuro, separado do evento comercial |
| `processado_financeiro` | Estado futuro, separado do evento comercial |

O estado comercial nao deve ser confundido com status logistico, baixa de estoque, recebimento financeiro, Fluxo de Caixa, DRE ou CMV.

## Validacoes obrigatorias futuras

Quando houver layout homologado, validar:

- soma dos itens versus total do documento;
- valores brutos, descontos e liquidos;
- quantidade e unidade;
- documento com cliente;
- item com SKU reconhecido ou pendente formal;
- duplicidade de sequencia dentro do documento;
- datas validas;
- status conhecido;
- cancelamento;
- documento sem itens;
- item sem documento;
- valores negativos inesperados;
- divergencia de chave;
- arquivo repetido;
- conflito entre versoes do mesmo documento.

Toda rejeicao deve possuir motivo legivel e rastreavel. Nada deve ser rejeitado silenciosamente.

## Produtos e aliases

O relacionamento entre codigo de produto Sankhya e SKU PRUMO nao esta homologado.

Diretrizes:

- nao criar produto automaticamente;
- nao usar aliases financeiros para produtos;
- tratar aliases de SKU como dominio comercial/produto separado;
- registrar codigo externo, SKU interno, origem, vigencia, status e ambiguidade;
- bloquear confirmacao quando o SKU for obrigatorio e nao puder ser resolvido com seguranca.

## Estrategia para o legado `/vendas`

Nesta sprint:

- o legado foi preservado;
- nenhum dado legado foi migrado;
- nenhum registro consolidado por data + SKU foi convertido em NF;
- nenhuma venda legada passou a alimentar relatorio oficial de Vendas;
- nenhuma transferencia foi tratada como venda.

Estrategia futura:

- manter `/vendas` como legado ate a homologacao do evento comercial oficial;
- descontinuar ou reduzir uso apenas depois de fonte documental confiavel;
- migrar somente se houver NF/cliente/item oficiais capazes de reconstruir a origem;
- impedir que o legado seja promovido a verdade comercial oficial.

## Rotas

Rotas operacionais criadas nesta sprint: nenhuma.

Rotas sugeridas para fase futura, mantidas inexistentes no Cenario C:

- `/integracoes/sankhya/vendas/importar`;
- `/integracoes/sankhya/vendas/importar/preview`;
- `/integracoes/sankhya/vendas/importar/confirmar`;
- `/integracoes/sankhya/vendas/importacoes/<id>`.

Relatorios que devem permanecer em 404:

- `/relatorios/expedicao/vendas`;
- `/relatorios/expedicao/vendas/exportar`;
- `/relatorios/expedicao/rastreabilidade`;
- `/relatorios/expedicao/rastreabilidade/exportar`.

Tambem permanecem fora desta fase:

- Giro;
- FIFO analitico;
- Romaneio de venda;
- Baixa PA por venda;
- Receita automatica;
- Conta a receber;
- DRE;
- Fluxo de Caixa;
- CMV.

## Prova de nao impacto

Como a sprint nao altera codigo funcional nem banco, o impacto esperado e zero em:

- Central de Movimentacoes;
- DRE;
- Fluxo de Caixa;
- Contas a Receber;
- estoque PA;
- caixas PA;
- historico de caixas;
- transferencias;
- CMV;
- importadores;
- Plano de Contas;
- Producao;
- Almoxarifado;
- Expedicao.

Validacoes locais e Render devem confirmar que as rotas existentes continuam respondendo e que as rotas comerciais futuras continuam bloqueadas.

## Testes executados

| Teste | Resultado |
| --- | --- |
| `python -m compileall app.py modules` | OK |
| `git diff --check` | OK |
| Smoke local autenticado das rotas publicadas | OK |
| Confirmacao local de 404 para rotas futuras | OK |
| Smoke Render autenticado das rotas publicadas | Pendente de execucao |
| Confirmacao Render de 404 para rotas futuras | Pendente de execucao |

Detalhes do smoke local:

- acesso anonimo a `/dashboard`: `302` para `/`;
- login admin local: `302` para `/dashboard`;
- rotas existentes com `200`: `/relatorios`, `/relatorios?dominio=Expedicao`, `/dashboard`, `/relatorios/gerencial/dashboard-executivo`, `/relatorios/gerencial/indicadores`, `/relatorios/gerencial/comparativos`, `/relatorios/gerencial/tendencias`, `/dre-gerencial?competencia=2026-07`, `/fluxo-caixa`, `/movimentacoes/importar`, `/estoque-produtos`, `/expedicao`, `/relatorios/expedicao/transferencias`, `/relatorios/expedicao/estoque-camara-fria`, `/relatorios/expedicao/historico-por-caixa`, `/relatorios/producao/producao-por-op`, `/relatorios/almoxarifado/estoque-atual`, `/relatorios/financeiro/receitas`;
- `/movimentacoes`: `302` esperado para `/movimentacoes/entradas`;
- rotas futuras/comerciais com `404`: `/integracoes/sankhya/vendas/importar`, `/integracoes/sankhya/vendas/importar/preview`, `/integracoes/sankhya/vendas/importar/confirmar`, `/relatorios/expedicao/vendas`, `/relatorios/expedicao/vendas/exportar`, `/relatorios/expedicao/rastreabilidade`, `/relatorios/expedicao/rastreabilidade/exportar`, `/relatorios/almoxarifado/giro`, `/relatorios/almoxarifado/fifo`.

## Validacao no Render

Pendente nesta revisao documental. Apos o merge e push para `origin/main`, validar:

- `/relatorios`;
- `/relatorios?dominio=Expedicao`;
- `/dashboard`;
- `/relatorios/gerencial/dashboard-executivo`;
- `/relatorios/gerencial/indicadores`;
- `/relatorios/gerencial/comparativos`;
- `/relatorios/gerencial/tendencias`;
- `/dre-gerencial`;
- `/fluxo-caixa`;
- `/movimentacoes`;
- `/movimentacoes/importar`;
- `/estoque-produtos`;
- `/expedicao`;
- relatorios existentes de Expedicao, Producao, Almoxarifado e Financeiro.

Confirmar 404 para:

- `/integracoes/sankhya/vendas/importar`;
- `/relatorios/expedicao/vendas`;
- `/relatorios/expedicao/vendas/exportar`;
- `/relatorios/expedicao/rastreabilidade`;
- `/relatorios/expedicao/rastreabilidade/exportar`;
- `/relatorios/almoxarifado/giro`;
- `/relatorios/almoxarifado/fifo`.

## Pendencias exatas para a Fase 2

Para sair do Cenario C, e necessario receber/homologar:

1. Layout real Sankhya/NF com nomes de colunas e tipos.
2. Regra oficial de chave do documento: chave NF-e ou composicao empresa/filial/modelo/serie/numero.
3. Regra oficial de sequencia/identidade do item.
4. Lista de status possiveis e semantica de cancelamento/substituicao.
5. Mapeamento oficial produto Sankhya -> SKU PRUMO.
6. Regra de cliente: codigo externo, documento e exibicao.
7. Exemplo de arquivo com documento de um item, varios itens, cancelamento e reimportacao.
8. Definicao da unidade transacional: arquivo, documento ou lote confirmado.
9. Permissao operacional para preview/confirmacao.
10. Regra futura de acoplamento com romaneio de venda, baixa PA, financeiro, DRE, Fluxo e CMV.

## Conclusao

A base atual nao permite criar importador Sankhya/NF oficial sem inventar contrato operacional. O caminho correto e homologar primeiro o layout e a chave natural do evento comercial. Ate la, o PRUMO deve manter Vendas e Rastreabilidade comercial bloqueadas como relatorios oficiais, preservando o legado `/vendas` apenas como cadastro historico e evitando qualquer impacto em estoque, financeiro, DRE, Fluxo de Caixa e CMV.
