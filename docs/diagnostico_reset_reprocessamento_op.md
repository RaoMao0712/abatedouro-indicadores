# Diagnóstico do reset administrativo de Ordens de Produção na base auditada

Base auditada `7632c00efffa3ed6968d987f10cc787cb0eafefe`, confirmada em `origin/main`. Os dados de produção foram consultados em transações somente leitura.

## Implementação de reprocessamento

O reset administrativo registra uma prévia com hash, revalida o plano na transação e cria um novo ciclo da mesma OP. O histórico distingue o ciclo invalidado dos apontamentos, posições e caixas vigentes. A operação registra compensações ligadas às origens de PI, PA, itens de romaneio e eventos de CMV, conforme a rastreabilidade disponível. Documentos compartilhados preservam as parcelas de outras OPs. Composições mistas e baixas sem origem rastreável permanecem impedimentos identificados na prévia.

Os cenários sintéticos usam um PostgreSQL descartável. As seções abaixo registram o estado observado antes da implementação.

## Fluxo atual

- `encerramento_op.encerrar_op_oficial` concentra a formação do PA e a validação final. Galinha Inteira monta on-line a Embalagem Primária e as posições V1/V2 dentro da transação do encerramento. Galinha Cortada usa os lançamentos e caixas já existentes, valida a conferência e então ativa o PA. A aprovação gerencial usa o mesmo serviço para divergências quantitativas elegíveis.
- `operacoes_op.reabrir_op` muda a etapa e a versão, preservando apontamentos, PI, PA e caixas. O estorno integral compensa efeitos e termina em `Estornada`. A reversão desse estorno restaura PI e reabre a OP, preservando caixas estornadas como histórico.
- O reset destrutivo antigo foi desativado. O estorno atual de caixa exige uma saída de PI íntegra e uma formação de estoque inequivocamente identificada. Esse contrato exclui caixas pendentes sem formação e não cobre o consumo `SAIDA_FORMACAO_PA_PRIMARIA` de Galinha Inteira.
- A Embalagem Primária de Galinha Inteira rejeita qualquer composição já vinculada, inclusive histórica. O caminho atual também apaga PI e apontamentos primários antes de gravar uma primeira formação e gera códigos V1/V2 fixos por OP. Liberar o guard sem mudar esse caminho apagaria o histórico ou colidiria com os códigos.
- A produção e a Embalagem Primária têm mecanismos de vigência. Descartes, mão de obra, paradas e tempos por setor não têm `vigente` nem `ciclo_operacional` no PostgreSQL atual. Os consumidores desses registros incluem o detalhe da OP, os balanços produtivos e os indicadores. A disponibilidade, a performance e o OEE têm seus próprios snapshots e trilhas de auditoria.

## Dependências e ordem de recuperação

| Origem | Efeitos e dependências que o reset deve tratar |
| --- | --- |
| Dados cadastrais | Identidade, SKU, fornecedor, entrada e programação. Conservar o cadastro atual e auditar separadamente as alterações cadastrais. |
| Lançamentos | Produção, mão de obra, paradas, tempos de setor, descartes e condenações. Conservar as linhas e separar vigência dos ciclos nos leitores, inclusive no balanço e nos relatórios. |
| Embalagem e pesagem | Apontamento primário gera entradas no livro PI. Pesagem e embalagem secundária geram caixas e saídas PI. Galinha Inteira gera posições V1/V2 na própria transação de encerramento. Etiquetas e conferências referenciam caixas e versões. |
| Formação de PA e logística | A composição liga caixas à OP. Formação, palletização, reservas, movimentações, romaneios, expedições, vendas, PNC e retrabalho dependem das caixas. Identificar sucessores externos antes da mutação. Zerar vínculos internos somente por operações auditadas. |
| Financeiro | Verificar vínculo com camadas e consumo do CMV e documentos de venda/faturamento antes de autorizar. A ausência de um vínculo direto por OP não elimina vínculos indiretos por caixa/romaneio. |
| Histórico | Tentativas, fechamentos, aprovações, reaberturas, estornos e auditorias devem sobreviver à operação, com referências originais e fronteira explícita entre ciclos. |

Contrato proposto. Travar a OP e revalidar a versão e os vínculos. Bloquear expedição, venda, consumo externo, composição compartilhada e referências não conciliadas. Desvincular pallets internos, compensar formação de PA registrada, inativar caixas pendentes sem inventar formação, compensar PI por movimento original e invalidar lançamentos apenas para as visões operacionais. Invalidar conferências e derivados ativos, reabrir a mesma OP e auditar origem e destino na mesma transação. A chave da operação deve identificar a OP e o ciclo. Revalidação, compensação e gravação devem compartilhar o lock com os demais escritores.

Ponto de aceite ainda aberto. A contabilidade de Galinha Inteira precisa aceitar um novo ciclo sem somar ou excluir o livro do ciclo anterior. Os lançamentos sem vigência precisam de modelo e filtragem coerentes. O checkpoint de publicação exige executar o ciclo completo em PostgreSQL isolado, incluindo pallet, saldos e teste concorrente.

## OPs investigadas

| OP | Diagnóstico de produção | Elegibilidade para reset |
| --- | --- | --- |
| 93 | Aberta, Galinha Cortada. A entrada PI #2139, de 03/09/2026, registra 1.468 bandejas. Há 1.500 aves e 44 descartes em aves, o que implica 1.456 no balanço observado. Não há segunda entrada de Primária. As 279 saídas de 3.342 bandejas brutas foram parcialmente compensadas por 166 estornos de 1.988 bandejas. Restam 1.354 bandejas consumidas e 114 em PI. As 113 caixas ativas estão pendentes e não têm evento de formação. | Nenhum item de expedição, vínculo ativo de pallet ou PNC encontrado. O estorno canônico atual não oferece uma anulação dessas caixas pendentes sem formação. A trilha consultada não comprova quando o lançamento inicial e os descartes passaram a divergir. |
| 123 | Aberta após reabertura para ajustar fornecedor. Uma posição histórica de Galinha Inteira está expedida, com nove itens de expedição e oito eventos de venda direta. PI líquido zero. | Bloqueada por expedição e vendas. |
| 124 | Aberta após reabertura para ajustar fornecedor. Uma posição histórica de Galinha Inteira está expedida, com oito itens de expedição e sete eventos de venda direta. PI líquido zero. | Bloqueada por expedição e vendas. |
| 129 | Aberta após reabertura por equívoco no fornecedor. Uma posição de Galinha Inteira está disponível, com formação de estoque. Entrada e consumo primário de 2.270 aves, PI líquido zero. | Nenhum item de expedição, vínculo ativo de pallet ou PNC encontrado. Exige compensação da formação e consumo primário com preservação da posição original e dos códigos do ciclo anterior. |

As auditorias das OPs 123, 124 e 129 registram alteração de estado por reabertura. A operação preservou PA e PI. A edição comum não altera o status diretamente, mas regravava a mortalidade de pré-pendura como zero mesmo sem campo correspondente no formulário. Os registros dessas OPs não demonstram que essa gravação isolada causou o bloqueio. O ajuste local oferece uma correção de fornecedor exclusivamente cadastral com auditoria, sem reabrir a ordem nem alterar a versão operacional.

## Revisão da reversibilidade de expedição e venda

A presença de venda ou expedição é uma consequência a planejar. O estorno canônico de romaneio concluído hoje restaura estoque, inativa itens, reverte atendimento de pedido e registra auditoria na transação do documento. Ele opera sobre todos os itens ativos do documento. O CMV possui um serviço separado que restaura consumo referenciado ao evento original. A integração do reset precisa comprovar essa referência e incluir a reversão aplicável na mesma transação.

- OP 123: oito itens ativos em documentos de venda concluídos e um vínculo histórico inativo no documento 100. Os documentos 95, 98 e 104 também têm itens ativos de outras OPs.
- OP 124: sete itens ativos em documentos de venda concluídos, mais um item histórico inativo no documento 92. Os documentos 92, 98, 111, 113 e 114 também têm itens ativos de outras OPs.
- Para documentos compartilhados, a prévia deve mostrar a abrangência da reversão integral. Reverter o documento inteiro é uma opção a validar e autorizar quando o gestor aceitar o alcance; reverter apenas os itens da OP não é uma capacidade comprovada no serviço atual.
- A investigação não comprova irreversibilidade econômica dos documentos. Confirma uma limitação técnica do reset atual: falta compor estornos de estoque, expedição, pedido e CMV com fronteira de ciclo, dentro de uma transação e com validação dos efeitos em outras OPs.

A versão local do planejador distingue histórico, caixas pendentes, formação existente e documentos que merecem avaliação de estorno ou cancelamento. Ela informa itens ativos fora da OP e devolve uma prévia não executável. A mudança local na Embalagem Primária desativa a exclusão física de PI e a substituição destrutiva. A aceitação de um novo ciclo com identificadores distintos ainda depende do modelo de ciclo e dos leitores de vigência.
