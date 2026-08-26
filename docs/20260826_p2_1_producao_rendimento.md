# P2.1 — Produção e Rendimento

Data da sprint: 26/08/2026

Commit inicial: `fb5f11c474b338b2733f46867dafbf40b26d0006`

Branch: `codex/p2-1-producao-rendimento`

## Escopo e decisão arquitetural

A P2.1 estabiliza exclusivamente a leitura gerencial de Produção e Rendimento. Nenhuma rotina de lançamento, fechamento, retomada, reabertura, estorno, estoque, expedição ou PNC foi alterada. O serviço oficial continua em `modules/relatorios/producao.py`, agora como fonte única da tela, dos consolidados gerenciais e do Excel.

O card de rendimento do dashboard foi alinhado à mesma fonte física: peso líquido rateado das caixas PA ativas de OPs encerradas. O dashboard deixou de usar `apontamentos_producao` como numerador desse card.

Na homologação autenticada, a tela legada **Consultar OP** ainda apresentou o resumo baseado em `apontamentos_producao`. O fechamento da sprint alinhou também esses cards à mesma linha oficial da OP (aves consideradas, peso líquido de PA ativo, aproveitamento em aves e rendimento auditável), mantendo intactos os apontamentos e fluxos operacionais.

Não houve migration. As estruturas de auditoria de reabertura/estorno e as fontes físicas de PI/PA já estavam disponíveis pelas entregas P0/P1.

## Mapa oficial das grandezas

| Grandeza | Fonte atual | Unidade | Momento de consolidação | Fonte oficial P2.1 |
|---|---|---:|---|---|
| OP | `ordens_producao.id` | OP | abertura | Sim |
| Data de produção | `ordens_producao.data` | data | criação da OP | Sim; rege dia e mês produtivos |
| Fornecedor/origem | `ordens_producao.fornecedor` | texto | abertura | Sim |
| Aves recebidas | `ordens_producao.quantidade_aves` | aves | recebimento | Sim |
| Mortes pré-pendura | `ordens_producao.mortes_antes_pendura` + descartes com motivo `Morte na gaiola` | aves | recebimento/qualidade | Sim; fontes não são sobrepostas no fechamento atual |
| Aves consideradas | recebidas menos mortes pré-pendura | aves | cálculo de leitura | Sim |
| Aves efetivamente penduradas | não há evento dedicado | aves | — | Não calculável; não inferir além de “aves consideradas” |
| Aves abatidas/processadas | não há contagem industrial oficial independente | aves | — | Não calculável nesta sprint |
| Condenações | `apontamentos_descartes`, categoria ou motivo contendo condenação | aves ou kg | apontamento | Sim, mantendo unidades separadas |
| Descartes operacionais | `apontamentos_descartes`, excluídas morte na gaiola e condenação | aves ou kg | apontamento | Sim, mantendo unidades separadas |
| PI produzido | `embalagem_primaria_apontamentos.quantidade_bandejas` | aves/bandejas conforme SKU | Embalagem Primária | Sim |
| PI consumido | composição das caixas PA ativas | bandejas | Embalagem Secundária | Sim |
| Retorno de PI | `estoque_produto_intermediario`, `ENTRADA_ESTORNO_CAIXA` | bandejas | estorno de caixa | Sim |
| Estorno integral de PI | `estoque_produto_intermediario`, `SAIDA_ESTORNO_OP` | bandejas | estorno integral | Sim |
| Saldo PI | somatório assinado do ledger de PI | bandejas | consulta | Sim |
| Caixas válidas | `pa_caixas` fora de Cancelada/Estornada, via `pa_caixa_composicao` | caixas | Embalagem Secundária | Sim |
| Bandejas válidas | composição de caixas PA ativas | bandejas | Embalagem Secundária | Sim |
| Peso bruto | `pa_caixas.peso_bruto` ativo | kg | pesagem | Apenas informativo |
| Tara | diferença persistida/validada no fluxo de caixas | kg | pesagem | Apenas informativa; não é produção |
| Peso líquido de PA | `pa_caixas.peso_liquido` ativo | kg | pesagem | Numerador oficial de produção em peso |
| Produto Acabado produzido | caixas PA ativas vinculadas à OP | caixa/bandeja/kg | fechamento físico | Sim; independe do estoque atual e da venda posterior |
| Reabertura/retomada | `op_operacoes_auditoria` | evento | operação auditada | Sim; apenas marcador, sem nova produção |
| Estorno integral | status da OP + auditoria | evento | estorno | Sim; exclui da produção válida e preserva histórico |
| PNC originado na produção | `pa_nao_conformes.op_id` | registro/quantidade/kg | qualidade | Sim; não reduz retroativamente a produção histórica |
| Reprocessamento PNC | eventos próprios de PNC | evento | qualidade | Auditável, mas não cria produção adicional no relatório P2.1 |

## Definições e fórmulas

### Produção válida

Somente OP com estado atual `Encerrada` compõe cards, consolidados e rendimento. OP aberta, aguardando Embalagem Secundária ou reaberta pode ser consultada no escopo **Em andamento**, sem efeito nos consolidados. OP estornada/cancelada aparece apenas em **Histórico sem efeito**.

Uma OP reaberta e encerrada novamente permanece uma única OP. O estado físico vigente das caixas prevalece; snapshots e apontamentos automáticos anteriores permanecem históricos com `vigente = 0`.

### Aves

`mortes pré-pendura = ordens_producao.mortes_antes_pendura + eventos “Morte na gaiola”`

`aves consideradas = max(0, aves recebidas - mortes pré-pendura)`

`aves aproveitadas = quantidade oficial da Embalagem Primária`

`aproveitamento em aves = soma das aves aproveitadas ÷ soma das aves consideradas × 100`

O percentual consolidado é ponderado pelos denominadores; não é média simples das OPs.

### Produto Intermediário

`PI produzido válido = PI da Embalagem Primária - compensação de estorno integral da OP`

`PI consumido válido = bandejas das caixas PA ativas`

`PI produzido válido = PI consumido válido + saldo PI remanescente`

Retorno de caixa estornada aumenta o saldo do ledger. O estorno integral neutraliza a entrada-base e deixa a OP apenas no histórico.

### Produto Acabado e peso

`caixas produzidas = caixas PA ativas, contadas uma vez pelo componente principal`

`bandejas produzidas = soma da composição ativa atribuída à OP`

`peso PA produzido = soma do peso líquido das caixas ativas`

Em caixa com composição de mais de uma OP, peso bruto e líquido são rateados proporcionalmente às bandejas da composição. A caixa física é contada uma vez, pelo primeiro componente persistido, impedindo duplicidade no consolidado.

Produção histórica não é estoque atual: venda, reserva, transferência, bloqueio ou descarte posterior de PNC não apagam o que foi produzido.

### Rendimento

`rendimento em peso = soma do peso líquido PA ativo ÷ soma do peso vivo oficial aplicável × 100`

O denominador inclui somente OPs que possuem simultaneamente peso vivo oficial e peso líquido PA. Produto sem peso líquido oficial é apresentado como **Não calculável**, sem estimativa por caixa, bandeja ou peso médio.

O antigo fallback para `apontamentos_producao` foi removido do relatório: esses apontamentos continuam históricos/auditáveis, mas o PA físico válido é a fonte oficial da P2.1.

## Perdas sem sobreposição

| Categoria | Regra |
|---|---|
| Mortes pré-pendura | campo da OP + eventos “Morte na gaiola” |
| Condenação sanitária | categoria ou motivo contendo “condenação” |
| Descarte operacional | eventos restantes, excluídas morte na gaiola e condenação |
| PNC de PA | indicador de qualidade separado; não subtrai a produção histórica |
| Perdas em kg | exibidas em kg; não convertidas para aves |
| Diferença de PI | divergência de reconciliação, não classificada automaticamente como perda física |

## Casos controlados

| Grandeza | Fonte | Resultado do cenário principal |
|---|---|---:|
| Aves recebidas | OP | 100 aves |
| Mortes pré-pendura | OP + morte na gaiola | 7 aves |
| Aves consideradas | cálculo oficial | 93 aves |
| Condenações | descartes classificados | 3 aves |
| PI produzido | Embalagem Primária | 85 bandejas |
| PI consumido | caixas ativas | 85 bandejas |
| Saldo PI | ledger | 0 bandeja |
| Caixas | PA ativo | 2 caixas |
| Bandejas | composição ativa | 85 bandejas |
| Peso líquido | PA ativo | 105,000 kg |
| Rendimento em peso | 105 ÷ 200 | 52,50% |
| Aproveitamento em aves | 85 ÷ 93 | 91,40% |

Também foram cobertos: OP aberta/parcial, retomada, encerramento, reabertura e novo encerramento, estorno integral, caixa estornada/substituta, apontamento tardio mantendo a data original, PNC posterior sem redução da produção, composição mista, agregação ponderada e Excel com datas/números nativos.

## Limitações reais e P2.2

- Não existe contagem oficial dedicada de aves efetivamente penduradas, abatidas ou processadas; “aves consideradas” não recebeu outro nome.
- Galinha Inteira não possui peso líquido oficial em seus lotes/pacotes atuais; rendimento em peso fica não calculável.
- A data de encerramento não possui campo próprio; a competência produtiva permanece `ordens_producao.data`.
- Disponibilidade, Performance e OEE não foram alterados e permanecem para a P2.2.
- A meta legada de 63% foi preservada como referência visual, sem alterar a fórmula física da P2.1.

## Integridade e segurança

- Consultas de indicador são exclusivamente `SELECT`.
- Tela e Excel usam o mesmo contexto e os mesmos filtros.
- Datas do Excel são células de data e grandezas permanecem numéricas.
- Nenhum dado histórico é recalculado ou atualizado pelo relatório.
- Não houve backfill, hard delete, migration ou alteração de permissões.
