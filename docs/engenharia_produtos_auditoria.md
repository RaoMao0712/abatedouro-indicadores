# Auditoria e arquitetura — Engenharia de Produtos

## Estado anterior

- Rota: `GET|POST /receitas-sku`, endpoint `receitas_sku`, em
  `modules/cadastros/routes.py`.
- Interface: `templates/receitas_sku.html`, com cadastro de SKU e inclusão de
  insumo na mesma tela.
- Persistência: tabelas `skus` e `receitas_sku`, criadas no startup.
- Produto e processo: armazenados na mesma entidade `skus`; não existia campo
  discriminador confiável para identificar processos.
- Insumos: cadastro oficial `almoxarifado_insumos`, compartilhado com estoque,
  rastreabilidade e manutenção. A Engenharia continua usando essa base.
- OP: `ordens_producao.sku` é texto, sem FK para `skus`. Impressão, pesagem,
  expedição e relatórios dependem desse texto, não das tabelas de receita.
- Dependências das receitas: fora do módulo legado não foram encontradas
  consultas a `receitas_sku`. Custos, vendas e relatórios usam o nome textual do
  SKU e permanecem inalterados.
- Permissão anterior: PCP e administrador podiam ler e editar; Produção,
  Qualidade e Gerência não acessavam a rota.
- Testes anteriores: não havia suíte específica para receitas/SKUs.
- Visual: o módulo antigo usava o padrão amplo de Almoxarifado. A nova tela
  segue a linguagem compacta recente de navegação, SGI e Expedição.
- Dados de produção: o ambiente de trabalho não recebeu `DATABASE_URL` nem
  acesso ao painel Render. A migração foi desenhada para ser aditiva,
  idempotente e validada contra uma base legada local representativa.

## Decisões

1. `skus` foi evoluída **in-place** para catálogo de produtos, preservando IDs,
   nomes e referências textuais existentes.
2. `receitas_sku` foi evoluída **in-place** para itens da estrutura, preservando
   IDs e vínculos com os insumos oficiais.
3. Registros legados recebem código controlado `LEG-<id>`, tipo
   `PRODUTO_ACABADO`, unidade do insumo oficial e tipo de consumo normalizado.
4. Nenhum SKU legado é convertido automaticamente em processo: a ausência de
   discriminador torna qualquer heurística destrutiva. Novos processos usam
   `processos_produtivos`.
5. Alterações novas são registradas em
   `engenharia_produtos_historico`, com usuário, data e estados anterior/novo.
6. Não há rota de exclusão física de produto. Produto e item são inativados;
   colunas de remoção lógica deixam a evolução futura preparada.
7. `/receitas-sku` permanece como alias GET retrocompatível do catálogo.
8. Leitura: PCP, Gerência, Administrador, Produção e Qualidade. Escrita: PCP,
   Gerência e Administrador, sempre validada no backend.

## Migração e rollback

A migração é somente aditiva e também roda de modo idempotente no startup.
Os scripts de referência são:

- `database/20260727_engenharia_produtos.sql`
- `database/20260727_engenharia_produtos_sqlite.sql`

Não há rollback destrutivo: remover colunas/tabelas apagaria histórico e novos
cadastros. Em contingência, o código pode voltar à versão anterior porque as
colunas extras não alteram os contratos legados; a restauração de banco deve
usar backup transacional.

## Fora do escopo preservado

Não foram adicionados FIFO, CMV, custos, baixa automática, explosão de
materiais, roteiros, capacidade, tempos, rendimento, viabilidade ou workflow de
versões.
