# P3.4 — Migração de Clientes e Fornecedores para Parceiros

## Inventário real pré-migração

Auditoria autenticada e somente leitura em produção em 09/09/2026, antes da alteração de dados:

| Tipo | ID legado | Nome | Documento | Dependências | Parceiro existente | Ação |
|---|---:|---|---|---|---|---|
| Cliente | 1 | Liberaci Silva e Silva | CNPJ final 0187 | 6 pedidos; 34 expedições | Não | Criar Parceiro + CLIENTE |
| Cliente | 2 | 46.489.562 JOAO CARLOS DA SILVA LIMA | CNPJ final 0141 | 1 expedição | Não | Criar Parceiro + CLIENTE |
| Cliente | 3 | Miranildo Castro Guimarães | CPF final 6215 | 1 pedido; 2 expedições | Não | Criar Parceiro + CLIENTE |
| Fornecedor | 1 | São Pedro Km 30 | Sem documento | 82 OPs; 82 GTAs textuais | Não | Criar Parceiro + FORNECEDOR |
| Fornecedor | 2 | São Pedro Km 03 | Sem documento | 6 OPs; 6 GTAs textuais | Não | Criar Parceiro + FORNECEDOR |

Totais: 3 clientes, 2 fornecedores, 3 documentos, 2 sem documento, 0 Parceiros prévios, 5 criações inequívocas. O universo auditado contém 7 pedidos, 44 expedições e 88 OPs. Não havia pedido, expedição ou OP órfão antes da migração.

## Dependências auditadas

- Clientes: `clientes`, eventos cadastrais, `pedidos_venda.cliente_id`, snapshots de pedido, `expedicoes.cliente_id`, snapshots de romaneio, filtros e relatórios comerciais/logísticos.
- Fornecedores: `fornecedores`, `ordens_producao.fornecedor`, GTA e nota fiscal textuais na OP, filtros de produção, rendimento e viabilidade.
- Vendas diárias, financeiro, DRE, CMV e almoxarifado não possuem FK cadastral segura para Cliente/Fornecedor; seus valores, datas, textos e documentos permanecem intocados.
- Não existe tabela GTA independente: a referência histórica está em `ordens_producao.gta` e não é reescrita.

## Estratégia e idempotência

O backfill `migrar_clientes_fornecedores_legados` aplica documento normalizado, vínculo explícito e nome exato normalizado; nunca usa fuzzy matching. Ambiguidades e conflito de status ficam auditados e o registro não é alterado. A unicidade `(tipo_legado,id_legado)`, a unicidade de `(parceiro_id,papel)` e `parceiros.documento` tornam reexecuções idempotentes.

As tabelas legadas são preservadas. `clientes.parceiro_id` e `fornecedores.parceiro_id` mantêm a rastreabilidade. Pedidos, expedições e OPs recebem chaves canônicas aditivas, enquanto IDs, snapshots, nomes, GTAs, valores, datas e quantidades históricos não são reescritos.

## Fluxos centralizados

- Pedidos e Venda Direta listam e validam somente Parceiros ativos com papel `CLIENTE`.
- Nova OP lista e valida somente Parceiros ativos com papel `FORNECEDOR`; o nome gravado na OP continua sendo snapshot textual.
- `/cadastros/clientes`, sua criação e edição redirecionam para Parceiros.
- `/fornecedores` redireciona para Parceiros e não aceita novo write legado.
- A navegação mantém somente `Cadastros → Parceiros`; o atalho de Fornecedores em equipamentos foi removido.
- Helpers oficiais ficam em `modules/parceiros/services.py`.

## Migration, backfill e rollback

- PostgreSQL: `database/20260909_p3_4_migracao_clientes_fornecedores_parceiros.sql`.
- SQLite: `database/20260909_p3_4_migracao_clientes_fornecedores_parceiros_sqlite.sql`.
- Rollbacks correspondentes são conservadores: removem apenas vínculos e papéis de migração sem uso operacional posterior. Parceiros criados e a trilha de auditoria são preservados como evidência; sua exclusão exige revisão humana. Os cadastros legados nunca são apagados.
- O bootstrap da aplicação executa primeiro as estruturas e depois o backfill transacional. Isso adapta a sequência ao deploy do Render: a versão entra no ar, cria colunas e migra no mesmo startup.

## Integridade e testes

Os testes P3.4 cobrem os 32 cenários requeridos: criação/reuso, mesmo documento e múltiplos papéis, ausência de documento, idempotência, rollback, status, listas elegíveis, snapshots, GTA/OP, menu, rotas e bloqueio de writes legados. As regressões dirigidas abrangem Parceiros, Mão de Obra, Pedidos, Expedição, Romaneios, Produção, financeiro e relatórios.

Consultas pós-deploy devem confirmar: 5/5 vínculos legados, 5 Parceiros, 5 papéis, 0 documentos duplicados, 0 vínculos/papéis duplicados e 0 órfãos introduzidos.

## Pendências técnicas legadas

As tabelas `clientes` e `fornecedores`, a coluna histórica `pedidos_venda.cliente_id` e os textos históricos de OP permanecem por compatibilidade. Sua remoção física exige sprint futura e prova de ausência de dependências. Almoxarifado e lançamentos financeiros textuais não foram redesenhados por estarem fora do escopo.
