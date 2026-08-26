# P2.2 — Disponibilidade, Performance e OEE

Data da auditoria: 2026-08-26 (America/Manaus)  
Baseline: `86d240a6df23e86a00d507237194a6b2343a89c6`  
Branch: `codex/p2-2-disponibilidade-performance-oee`

## Auditoria anterior à alteração

| Indicador | Implementação encontrada | Fonte | Fórmula | Situação no baseline |
| --- | --- | --- | --- | --- |
| Disponibilidade | `modules/producao/disponibilidade.py` | programação versionada, pausas estruturadas e paradas com impacto na linha | tempo operacional / tempo planejado líquido | Motor já existente e preservado; faltava consolidação por período e ajuste explícito de OP aberta |
| Performance | `modules/producao/performance.py` | aves recebidas menos mortes pré-pendura, snapshot da velocidade e tempo operacional | aves consideradas / capacidade teórica | Motor já existente e preservado; faltava consolidação por período e integração de OEE |
| Qualidade | inexistente como base OEE oficial | não há contagem independente de unidades processadas e unidades boas | não aplicável | `NAO_CALCULAVEL` |
| OEE | item futuro no catálogo, sem motor oficial | dependente de D, P e Q | D × P × Q | não implementado |
| Ganchos | nenhuma configuração persistida | estimativa operacional externa de 80% | não aplicável | ausente; proibido inferir histórico |

O dashboard possuía uma jornada fixa de 8,8 h usada em métricas legadas de produtividade e mão de obra. Ela foi mantida somente nessa seção e não participa de Disponibilidade, Performance, Qualidade ou OEE.

## Regras oficiais consolidadas

### Disponibilidade

`D = tempo operacional / tempo planejado líquido × 100`

- O tempo planejado vem exclusivamente da programação da Linha de Abate.
- Pausas programadas por natureza estruturada são removidas do denominador e não reduzem D.
- Somente paradas com `afeta_linha_abate = 1` e natureza válida reduzem o tempo operacional.
- Intervalos são recortados pela janela programada e unidos antes da subtração; sobreposições não contam duas vezes.
- Programações que atravessam meia-noite e registros com offset de Manaus são aceitos.
- Dia sem programação encerrado resulta em `NAO_CALCULAVEL`; OP aberta ou parada aberta durante OP aberta resulta em `EM_ANDAMENTO`.
- Resultado fora de 0–100% é `INCONSISTENTE`, sem truncamento.

### Performance

`P = aves consideradas / (velocidade ideal × horas operacionais) × 100`

`aves consideradas = aves recebidas − mortes antes da pendura`

A velocidade é configurada, aprovada, versionada por vigência e preservada em snapshot por OP. Não é deduzida da produção real e não sofre backfill com a velocidade atual. O cálculo usa `Decimal` e não arredonda componentes antecipadamente. Performance acima de 100% permanece calculável e visível, acompanhada de alerta.

A expressão “aves consideradas” é deliberada: não existe medição independente de aves efetivamente penduradas/processadas. PI, caixas, peso, condenações e nória não substituem essa base.

### Qualidade e OEE

Não existe numerador oficial de unidades boas nem denominador independente de unidades processadas. Rendimento em peso, PNC, condenações e descartes não foram convertidos em Qualidade por conveniência, evitando dupla contagem e alteração sem regra operacional formal.

Assim, no estado atual:

- Qualidade = `NAO_CALCULAVEL` / N/A;
- OEE = `NAO_CALCULAVEL` / N/A;
- D e P continuam visíveis quando calculáveis;
- OEE parcial (`D × P`) é proibido.

Quando houver base oficial futura, a fórmula preparada é:

`Q = soma de unidades boas / soma de unidades processadas × 100`

`OEE = (D / 100) × (P / 100) × (Q / 100) × 100`

Os estados seguem a precedência: `INCONSISTENTE`, `EM_ANDAMENTO`, `NAO_CALCULAVEL`, `CALCULAVEL`.

## Consolidação por período

- D consolidada = soma do tempo operacional / soma do tempo planejado × 100.
- P consolidada = soma das aves consideradas / soma das capacidades teóricas por OP × 100.
- Q consolidada, quando existir = soma das unidades boas / soma das unidades processadas × 100.
- OEE consolidado, quando D/P/Q forem calculáveis, é o produto dos componentes consolidados.

Não há média simples de percentuais ou OEEs individuais. OP aberta/reaberta fica em andamento e não entra no filtro final padrão. OP estornada/cancelada permanece disponível no filtro histórico, sem indicador vigente.

## Configuração física da linha

Foi criada a tabela aditiva `linha_abate_configuracoes_fisicas`, PostgreSQL-safe, para registrar por vigência:

- ganchos instalados e operacionais das nórias 1 e 2;
- justificativa técnica;
- usuário e data do registro;
- versão e estado lógico.

Somente Administrador registra configurações; vigências sobrepostas são rejeitadas. Nenhum valor de 500 ganchos ou 80% foi semeado, inferido ou aplicado retroativamente. Ganchos não multiplicam Performance.

## Rastreabilidade e interface

- Dashboard e relatórios chamam o mesmo serviço consolidado.
- Os cards exibem tempo planejado, tempo operacional, D, aves consideradas, capacidade teórica, P, Q e OEE.
- A visão por OP expõe numeradores, denominadores, velocidade/snapshot, estados, alertas e motivos.
- Exportação Excel mantém datas e números como tipos nativos.
- O histórico de paradas exibe início, fim, duração, setor, equipamento, motivo, natureza, impacto na linha, situação e usuário registrador.
- Novos apontamentos armazenam `registrado_por` e `registrado_por_id`; registros históricos não são preenchidos automaticamente.

## Homologação controlada local

| Componente | Numerador | Denominador | Resultado manual | Resultado do sistema |
| --- | ---: | ---: | ---: | ---: |
| Disponibilidade | 450 min operacionais | 480 min planejados líquidos | 93,75% | 93,75% |
| Performance | 900 aves consideradas | 7.500 aves de capacidade teórica | 12,00% | 12,00% |
| Qualidade | N/A | N/A | N/A | N/A |
| OEE | N/A | N/A | N/A | N/A |

Cenário de D: programação 08:00–17:00, pausa 12:00–13:00 e paradas 09:00–09:20/09:10–09:30. A união das paradas é 30 minutos.  
Cenário de P: 900 aves, velocidade de 1.000 aves/h e 7,5 h operacionais.  
Cenário >100%: 900 aves, velocidade de 100 aves/h e 7,5 h resultam em 120%, preservado com alerta.

## Limitações preservadas

- Qualidade e OEE permanecem N/A até existir base oficial de unidades boas/processadas.
- OPs antigas sem programação, snapshot ou contagens oficiais permanecem N/A; não há backfill.
- A configuração física é informativa e auditável, sem fórmula técnica que a associe à velocidade.
- A OP 83 deve ser consultada somente em produção e, enquanto aberta, aparecer como `EM_ANDAMENTO`, sem OEE final.

