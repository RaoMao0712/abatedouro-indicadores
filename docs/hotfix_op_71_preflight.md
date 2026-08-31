# Preflight produtivo — Hotfix OP #71

Data da inspeção: 31/08/2026 (America/Manaus)
Modo: somente leitura
Commit servido antes do hotfix: `3dab21aac1730726a795b1a4e0d332e4c32e7f45`

## Conclusão

O banco produtivo não confirma a hipótese de que a OP #71 esteja marcada como
legada. A OP está persistida como `POS_MARCO`; as caixas estão em
`PENDENTE_OP`, mas a tela chama incorretamente todo PA não operacional de
“Registro histórico anterior ao marco zero”.

O Marco Zero persistido é 24/07/2026, ativado em 24/07/2026 10:23:38, com
`legacy_max_op_id = 69`. A OP #71 possui data operacional e fabricação em
01/08/2026. O schema não possui timestamp próprio de abertura da OP; portanto,
a relação temporal disponível é determinada pela fotografia persistida do
Marco Zero, pela classificação da OP e pelos eventos auditáveis.

Os totais físicos e lógicos fecham exatamente e permitem o caminho A:
reaproveitar o PA existente, concluir a OP e formar o estoque sem recriar ou
reconsumir dados.

## OP

- ID/número: 71
- Produto: Galinha Cortada
- Data operacional: 01/08/2026
- Situação: Aberta
- Classificação persistida: `POS_MARCO`
- Versão operacional: 0
- Quantidade de aves: 500
- Reaberturas auditadas: nenhuma
- Encerramento anterior: nenhum apontamento final encontrado

## Embalagem Primária e PI

- Um apontamento primário, ID 50, criado em 27/08/2026 18:17:10
- Quantidade original e atual: 314 bandejas
- Entrada de PI: 314 bandejas
- Saídas de PI: 314 bandejas em 27 movimentos vinculados às caixas
- Saldo disponível: zero
- Chaves idempotentes duplicadas: zero
- Estornos/alterações: nenhum encontrado

## Embalagem Secundária

- 27 caixas: `CX-20260827-001` a `CX-20260827-027`
- 26 caixas de 12 bandejas e uma caixa parcial de 2 bandejas
- Total: 314 bandejas
- Peso líquido: 366,59998 kg
- Peso bruto: 380,09998 kg
- Fabricação: 01/08/2026
- Validade: 01/08/2027
- Estado real: `PENDENTE_OP`
- Estoque operacional: não, antes da reconciliação
- Caixas legadas (`LEGADO`): zero
- Reservas: zero
- Expedições/romaneios: zero
- Estornos/cancelamentos: zero
- Movimentos de PA posteriores: zero
- Eventos de estoque anteriores: zero
- Códigos duplicados: zero
- Composições mistas: zero

## Balanço industrial

- Embaladas: 314 aves/bandejas
- Morte na gaiola: 78 aves
- Outros descartes: 84 + 24 aves
- Total conciliado: 500 aves
- Divergência: zero

## Controles de não impacto

- OP #83 fotografada antes da mutação: Aberta, `POS_MARCO`, versão operacional 1
- Financeiro: `FINANCEIRO_EM_RECONSTRUCAO`, ativo
- O hotfix não importa nem chama serviços do módulo Financeiro
- A reconciliação é restrita à OP #71 e bloqueia reserva, expedição, composição
  mista, duplicidade, divergência de PI, formação parcial e alteração concorrente

## Decisão do preflight

`A_RECONCILIAR_PA_EXISTENTE`

Não registrar PI novamente, não recriar caixas, não alterar códigos, pesos,
bandejas, fabricação ou validade e não oferecer nova pesagem com saldo zero.
