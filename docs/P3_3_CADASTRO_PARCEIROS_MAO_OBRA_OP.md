# P3.3 — Cadastro Mestre de Parceiros + Mão de Obra da OP

## Arquitetura

O cadastro mestre é aditivo e tem `parceiros` como raiz. Os papéis atuais ficam em
`parceiro_papeis`, permitindo zero, um ou vários papéis simultâneos. Toda mudança
gera eventos imutáveis em `parceiro_eventos`. Clientes e fornecedores legados não
foram convertidos nem vinculados automaticamente.

O apontamento existente de Mão de Obra continua em `apontamentos_mao_obra`. Foram
acrescentados `parceiro_id`, `parceiro_nome_snapshot` e `natureza_vinculo`. Os
campos legados permanecem; `colaborador` recebe o mesmo nome do snapshot para
compatibilidade com consultas, impressão e Dashboard já existentes.

## Auditoria inicial de cadastros

| Entidade atual | Tabela/model | Uso | Dependências | Decisão P3.3 |
| --- | --- | --- | --- | --- |
| Clientes | `clientes`, `cliente_eventos`; `modules/clientes` | Venda Direta e Expedição | `pedidos_venda`, `expedicoes`, snapshots de cliente | Preservar integralmente; futura reconciliação explícita |
| Fornecedores | `fornecedores`; `modules/cadastros` | seleção textual da entrada da OP | OP, cadastros e telas de fornecedor | Preservar integralmente; não migrar |
| Colaboradores | não existe cadastro | nome digitado em Mão de Obra | `apontamentos_mao_obra.colaborador` | Passar novos apontamentos para Parceiros |
| Prestadores | não existe cadastro | textos livres pontuais em manutenção/financeiro | sem vínculo cadastral seguro | Criar papel em Parceiros, sem migrar textos |
| Pessoas | não existe entidade central | — | — | Atendida por Parceiros PF/PJ |
| Contatos | campos dispersos em Clientes | telefone/endereço | Clientes | Não alterar; Parceiros recebe seus próprios contatos |
| Usuários | `usuarios`; `modules/auth`, `modules/usuarios` | autenticação e autorização | sessão/perfis | Manter separado; não criar parceiro automaticamente |

Não há correspondência inequívoca suficiente para backfill. A repetição eventual
entre Parceiros e um cadastro legado deve ser reconciliada numa sprint futura,
com relatório de candidatos, confirmação humana e vínculo explícito — nunca por
nome aproximado.

## Auditoria da Mão de Obra existente

| Item | Estado encontrado e decisão |
| --- | --- |
| Rota | `/apontamento-mao-obra`, endpoint `apontamento_mao_obra`, mantido |
| Template | `templates/apontamento_mao_obra.html`, preservado e integrado |
| Model/tabela | SQL direto em `apontamentos_mao_obra`; não há ORM |
| Service | `modules/producao/services.py`, `salvar_apontamento_mao_obra` e `copiar_mao_obra_de_op` |
| Origem anterior | texto livre `colaborador`; substituído, apenas em novas inclusões, pela lista de Parceiros elegíveis |
| Campos | OP, data, colaborador, função, setor, turno e observações; todos preservados |
| Inclusão | somente OP aberta; rota para `admin`/`producao`; validação de elegibilidade acrescentada no backend |
| Edição | individual permite identidade/função/setor/turno/observação; lote preserva nomes e altera os demais dados |
| Remoção/estorno | exclusão em lote existente, bloqueada em OP encerrada salvo admin; não foi redesenhada |
| Horas/intervalos | Mão de Obra não guarda início/fim/intervalo. Dashboard calcula HH por quantidade única de nomes × jornada padrão, descontando paradas por setor; lógica preservada |
| Função/atividade | lista fixa de funções e setor; preservada |
| Custo | não existe no apontamento; nada criado |
| Auditoria | não havia trilha própria do apontamento; snapshots cadastrais foram adicionados, sem ampliar para auditoria operacional completa |
| Permissões | `perfil_permitido("producao")`, com admin implícito; mantidas |
| Relatórios | consulta/impressão da OP e Dashboard usam `colaborador`; compatibilidade preservada pelo snapshot nesse campo |
| Fechamento/reabertura/estorno | edição/exclusão bloqueadas quando encerrada, exceto admin; reabertura volta a liberar; rotinas de estorno incluem a tabela. Sem alteração |

## Entidade Parceiro e documento

`parceiros` contém UUID, PF/PJ, nome/razão social, fantasia, CPF/CNPJ,
telefone, e-mail, endereço, observações, status e metadados de criação/edição.
CPF/CNPJ é opcional porque os cadastros atuais aceitam documento ausente. Quando
presente, é normalizado para dígitos, validado por dígitos verificadores e protegido
por índice único parcial, fazendo valores mascarados e não mascarados equivalentes.

Parceiro sem papel é permitido para cadastro prévio. Não existe hard delete na
interface: inativação preserva o histórico e retira o parceiro das novas seleções.

## Papéis e histórico

Papéis suportados: `CLIENTE`, `FORNECEDOR`, `PRESTADOR_SERVICOS` e
`COLABORADOR_CLT`. A relação única `(parceiro_id, papel)` é ativada/inativada,
preservando autor e datas de adição/remoção. Os eventos registram estado anterior,
posterior, usuário, perfil e data/hora em `America/Manaus` para criação, edição,
papel, documento e status.

Alterações cadastrais não atualizam apontamentos. Cada apontamento preserva o ID,
nome e natureza usados. Assim, remover CLT, adicionar Prestador ou inativar uma
pessoa só altera a elegibilidade futura.

## Integração e regra de elegibilidade

Uma única consulta, sem N+1, oferece parceiros distintos que satisfaçam:

`status = 'Ativo' AND papel ativo IN ('COLABORADOR_CLT','PRESTADOR_SERVICOS')`

Cliente/Fornecedor sem papel trabalhista não aparece. Parceiro CLT + Prestador
aparece uma vez e exige natureza explícita. Com apenas um papel, o backend pode
inferir a natureza; em ambos os casos valida que o papel ainda está ativo. A cópia
de equipe preserva os snapshots de origem e o fluxo anterior.

## Permissões

- Visualizar: admin, gerência, PCP e produção.
- Cadastrar/editar: admin, gerência e PCP.
- Ativar/inativar: admin e gerência.
- Mão de Obra: permissões existentes de produção/admin, sem ampliação.

Os decorators protegem rotas e os services repetem as validações críticas de
edição, status, documento, papel e elegibilidade.

## Migration

As migrations PostgreSQL e SQLite são aditivas e possuem rollback correspondente.
Não fazem hard delete, não preenchem parceiro fictício e deixam registros antigos
com os três novos campos nulos. O bootstrap da aplicação é idempotente.

## Limitações e plano futuro

- A substituição de Clientes/Fornecedores por Parceiros está fora da P3.3.
- A eventual reconciliação deve criar tabelas de vínculo com IDs legados, relatório
  de conflitos e aprovação humana antes de trocar dependências.
- Custo/hora, folha, encargos, rateio e custo por OP permanecem fora do escopo.
- A exclusão/estorno e auditoria operacional da própria Mão de Obra mantêm o
  comportamento legado; esta sprint protege a identidade histórica por snapshot.
