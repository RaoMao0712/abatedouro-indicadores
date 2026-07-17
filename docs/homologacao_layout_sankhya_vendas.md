# Homologacao do Layout Sankhya/NF para Vendas

## Controle

- Projeto: PRUMO / FRIGODATTA Abatedouro.
- Etapa: Fundacao Comercial - Homologacao do layout Sankhya/NF.
- Commit inicial obrigatorio: `f4f06202560d64ad4c6c2b310b105efe6f83b049`.
- Worktree: `C:\Users\g227716298.GRUPOSP-AD\.codex\worktrees\4ca3\abatedouro indicadores`.
- Branch: `codex/homologacao-layout-sankhya-vendas`.
- Pacote Excel: `docs/modelos/Pacote_Homologacao_Layout_Sankhya_Vendas_v1.xlsx`.

## Por que a integracao permanece bloqueada

A etapa anterior classificou a Fundacao Comercial como **Cenario C**: nao existe layout Sankhya/NF real e homologado suficiente para criar modelo definitivo, tabelas, migracao, importador, endpoints, evento oficial de venda, vinculo com estoque, financeiro, DRE, Fluxo de Caixa, CMV ou relatorios oficiais de Vendas e Rastreabilidade.

Nesta nova auditoria tambem nao foi encontrado arquivo comercial Sankhya/NF confiavel. As referencias existentes sao:

- `/vendas`: cadastro legado consolidado por data + SKU;
- `/movimentacoes/importar` e `/movimentacoes/importar-vendas`: importadores financeiros para Central de Movimentacoes;
- `/importar-maio`: importador operacional/produtivo de OPs e descartes;
- catalogo de relatorios com Vendas e Rastreabilidade em estruturacao, sem endpoint publico;
- documentacao anterior confirmando ausencia de NF, cliente, item comercial e romaneio de venda.

Portanto, esta etapa nao implementa funcionalidade. Ela cria o pacote formal de coleta para que o responsavel pelo Sankhya/processo comercial devolva informacoes suficientes para homologacao.

## Objetivo do pacote

O arquivo `Pacote_Homologacao_Layout_Sankhya_Vendas_v1.xlsx` deve ser enviado ao responsavel pelo Sankhya/processo comercial para preenchimento e validacao. Ele organiza:

- dicionario de dados proposto;
- matriz de obrigatoriedade;
- exemplos totalmente ficticios;
- campos de documento, item, cliente e produto;
- status e eventos;
- chaves de idempotencia;
- regras de valores;
- casos obrigatorios de homologacao;
- decisoes pendentes;
- criterios objetivos para liberar a Fase 2.

Todo o conteudo e marcado como **PROPOSTA - NAO HOMOLOGADA** ate resposta humana.

## Como preencher

1. Preencher a aba `DICIONARIO_CAMPOS` com o nome real da coluna Sankhya, tipo, tamanho, obrigatoriedade e observacoes.
2. Substituir os exemplos ficticios por referencias estruturais anonimizadas quando houver arquivo real.
3. Preencher `CHECKLIST_ENTREGA` com os arquivos/evidencias devolvidos.
4. Mapear produtos em `PRODUTOS_ALIASES`, sem usar aliases do Plano de Contas.
5. Mapear status em `STATUS_EVENTOS`, sem declarar equivalencia se o responsavel Sankhya nao validar.
6. Validar chaves em `CHAVES_IDEMPOTENCIA`.
7. Confirmar formulas e tolerancias em `REGRAS_VALORES`.
8. Entregar evidencias dos casos de `CASOS_HOMOLOGACAO`.
9. Responder `DECISOES_PENDENTES`.
10. Somente liberar desenvolvimento quando `ACEITE_FASE_2` estiver completo.

## Arquivos que devem ser devolvidos

- Planilha de homologacao preenchida.
- Arquivo real anonimizado do Sankhya/NF.
- Dicionario oficial das colunas.
- Exemplo de NF com um item.
- Exemplo de NF com varios itens.
- Exemplo de NF cancelada.
- Exemplo de devolucao, se existir.
- Exemplo com desconto, frete e impostos.
- Exemplo de unidade alternativa.
- Exemplo de produto sem mapeamento.
- Exemplo de reexportacao identica.
- Exemplo de mesma chave com conteudo divergente, se o processo permitir.
- Descricao oficial dos status.
- Regra de autorizacao e confirmacao.
- Regra transacional.
- Confirmacao da chave unica.

## Anonimizacao

Nao enviar dados pessoais desnecessarios.

Antes de devolver arquivos reais:

- trocar nomes reais por `CLIENTE EXEMPLO A`, `CLIENTE EXEMPLO B` etc.;
- mascarar documentos de cliente;
- mascarar chaves NF-e;
- remover enderecos, telefones e e-mails se nao forem essenciais;
- nao incluir credenciais, tokens, links privados ou identificadores sensiveis;
- manter a estrutura, tipos e cardinalidade reais mesmo com dados mascarados.

O PRUMO precisa homologar estrutura e comportamento, nao dados pessoais.

## Proposta de contrato canonico

### Documento comercial

Campos minimos propostos:

- `origem_sistema`;
- `empresa_codigo`;
- `filial_codigo`;
- `documento_modelo`;
- `documento_serie`;
- `documento_numero`;
- `chave_nfe`;
- `identificador_externo`;
- `cliente_codigo`;
- `cliente_nome`;
- `cliente_documento`;
- `data_emissao`;
- `data_saida`;
- `data_cancelamento`;
- `status_documento`;
- `moeda`;
- `valor_produtos`;
- `valor_desconto`;
- `valor_frete`;
- `valor_outras_despesas`;
- `valor_impostos`;
- `valor_total`;
- `motivo_cancelamento`;
- `atualizado_em_origem`.

### Item comercial

Campos minimos propostos:

- `origem_sistema`;
- `documento_chave_canonica`;
- `item_sequencia`;
- `item_identificador_externo`;
- `produto_codigo_sankhya`;
- `produto_descricao_origem`;
- `sku_prumo`;
- `unidade_origem`;
- `unidade_prumo`;
- `fator_conversao`;
- `quantidade_origem`;
- `quantidade_prumo`;
- `peso_liquido`;
- `peso_bruto`;
- `valor_unitario`;
- `valor_bruto`;
- `valor_desconto`;
- `valor_liquido`;
- `status_item`;
- `atualizado_em_origem`.

### Cliente

Campos propostos:

- `cliente_codigo_sankhya`;
- `nome_razao_social`;
- `nome_fantasia`;
- `tipo_pessoa`;
- `documento`;
- `municipio`;
- `UF`;
- `pais`;
- `status`;
- `atualizado_em_origem`.

## Proposta de idempotencia

Documento:

1. Preferencial: `origem_sistema + chave_nfe`.
2. Alternativa: `origem + empresa + filial + modelo + serie + numero`.

Item:

1. `documento_chave_canonica + item_sequencia`.
2. Se existir ID de item estavel, validar tambem `documento_chave_canonica + item_identificador_externo`.

Arquivo:

- `origem_sistema + SHA-256(conteudo_do_arquivo)`.

Regras:

- reexportacao identica deve ser no-op;
- reexportacao nao pode duplicar documento nem item;
- mesma chave com conteudo divergente deve gerar conflito auditavel;
- conflito nao pode sobrescrever registro oficial silenciosamente;
- cancelamento e devolucao devem ser rastreaveis;
- data + SKU nao pode ser chave oficial de venda.

## Campos obrigatorios propostos

Obrigatorios ate validacao contraria:

- origem do sistema;
- empresa;
- filial;
- modelo;
- serie;
- numero;
- chave NF-e ou chave alternativa homologada;
- cliente;
- data de emissao;
- status;
- sequencia do item;
- codigo do produto;
- descricao do produto;
- unidade;
- quantidade;
- valor unitario;
- valor liquido;
- total do documento.

Pendentes de homologacao:

- SKU PRUMO;
- peso;
- fator de conversao;
- devolucao;
- cancelamento;
- frete;
- impostos;
- outras despesas;
- tolerancia de arredondamento.

## Decisoes pendentes principais

- Qual exportacao Sankhya sera oficial?
- Arquivo, API ou consulta?
- Qual empresa e filial entram no escopo?
- A chave NF-e esta sempre presente?
- Como identificar documento sem chave NF-e?
- A sequencia do item e estavel?
- Cancelamento substitui ou versiona o documento?
- Como funciona devolucao?
- Existe devolucao parcial por item?
- Qual data representa a venda?
- Qual unidade e oficial?
- Como tratar peso variavel?
- Como mapear SKU?
- Qual tolerancia financeira e aceita?
- Quem pode importar?
- Quem pode confirmar?
- Um arquivo pode misturar empresas?
- Qual volume diario/mensal?
- Como sera feito reprocessamento?
- Qual politica para conflito?
- Quais dados de cliente podem ser armazenados?

## Criterios para liberar a Fase 2

A Fase 2 so deve iniciar quando houver:

- layout real;
- exemplo anonimizado;
- dicionario de dados;
- chave do documento confirmada;
- chave do item confirmada;
- status/cancelamento confirmados;
- regra de devolucao confirmada;
- totais e arredondamento confirmados;
- mapeamento inicial de produtos;
- volume estimado;
- regra de reprocessamento;
- regra de conflito;
- permissoes definidas;
- responsavel funcional identificado;
- aceite formal registrado.

## Riscos de desenvolver sem homologacao

- Duplicar NF ou item por chave instavel.
- Consolidar indevidamente vendas por data + SKU.
- Criar cliente, produto ou documento ficticio.
- Gerar receita sem documento comercial confiavel.
- Baixar estoque PA sem rastreabilidade de caixa.
- Misturar status comercial com status logistico.
- Tratar cancelamento ou devolucao como venda ativa.
- Criar relatorio oficial com base incompleta.
- Impactar DRE, Fluxo ou CMV antes do contrato correto.

## Validacao do pacote

Validacoes executadas:

- XLSX gerado em `docs/modelos/Pacote_Homologacao_Layout_Sankhya_Vendas_v1.xlsx`;
- 13 abas obrigatorias presentes;
- tabelas com filtros nas abas tabulares;
- primeira linha congelada em todas as abas;
- validacoes de dados aplicadas em colunas de status, obrigatoriedade, homologacao e decisoes;
- exemplos sinteticos identificados;
- ausencia de macros;
- ausencia de links externos;
- ausencia de formulas quebradas;
- ausencia de marcadores de dados reais sensiveis;
- renderizacao visual inspecionada para `LEIA-ME`, `DICIONARIO_CAMPOS`, `DOCUMENTOS_NF` e `ITENS_NF`.

Limitacao registrada:

- A renderizacao visual foi feita por previews das abas principais. As demais abas foram validadas estruturalmente por biblioteca XLSX.

## Nao impacto

Esta etapa nao altera:

- `app.py`;
- rotas;
- services;
- repositories;
- templates;
- CSS;
- schema;
- migracoes;
- banco;
- importadores;
- estoque;
- expedicao;
- financeiro;
- DRE;
- Fluxo de Caixa;
- producao;
- almoxarifado;
- CMV;
- Biblioteca de Relatorios.

Nenhum endpoint foi criado. Vendas e Rastreabilidade comercial continuam bloqueadas ate homologacao.
