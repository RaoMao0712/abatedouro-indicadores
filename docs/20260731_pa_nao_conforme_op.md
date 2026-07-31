# Produto Acabado Não Conforme no encerramento da OP

## Auditoria do fluxo anterior

- Galinha Cortada: a Embalagem Primária gera PI; a Embalagem Secundária cria `pa_caixas` e `pa_caixa_composicao`; `finalizar_embalagem_secundaria_op` concilia aves e PI, soma o peso líquido das caixas, gera uma única produção automática, encerra a OP e ativa as caixas.
- Galinha Inteira: a Embalagem Primária cria uma posição de PA para cada apresentação V1/V2, gera a produção automática, encerra a OP e ativa as posições na mesma transação.
- O lote físico já é o `codigo_caixa`; a composição liga caixa/posição à OP. O local vem de `locais_estoque`.
- Uma caixa só se torna comercialmente elegível após a OP encerrada, com `estoque_operacional=1`, `condicao=CONFORME` e `disponibilidade=DISPONIVEL`.
- Transferência e romaneio regular já filtravam e validavam `CONFORME + DISPONIVEL` no backend. Romaneios específicos tratavam itens não conformes bloqueados.
- Já existiam `condicao=NAO_CONFORME`, `disponibilidade=BLOQUEADO`, zona segregada e eventos de estoque, mas o bloqueio era posterior e individual: faltavam captura no fechamento, registro oficial, estados de Qualidade, decisão, filtros e auditoria própria.
- Produção, rendimento e Dashboard usam `apontamentos_producao`. No encerramento, o apontamento em kg nasce da soma das caixas físicas. Portanto, criar outro saldo ou outro apontamento para a não conformidade duplicaria massa e rendimento.
- Descartes e condenações ficam em `apontamentos_descartes` e participam da conciliação de aves; Produto Acabado Não Conforme não usa essa estrutura.
- O módulo de vendas não seleciona caixas físicas. A proteção comercial efetiva está na disponibilidade oficial do estoque e nos seletores/validações de transferência e expedição.

## Arquitetura adotada

`pa_nao_conformes` governa a não conformidade e possui relação única com uma caixa/posição real de `pa_caixas`. Não há saldo paralelo. `pa_nao_conforme_eventos` mantém a trilha imutável de criação, bloqueio, avaliação, decisão e tentativas negadas.

No encerramento, zero ou várias posições existentes podem ser classificadas. Produto, lote, quantidade, peso e unidade são conferidos no backend contra a posição física; campos adulterados são recusados. A criação do registro, o bloqueio da posição, a produção automática, o encerramento da OP e a formação do estoque usam a mesma transação.

Equações preservadas:

- peso produzido total = soma única das caixas/posições, conformes e não conformes;
- estoque comercial disponível = somente `CONFORME + DISPONIVEL`;
- estoque físico = disponível + reservado + bloqueado + reprocessamento e demais estados explicitados.

Ao liberar, a mesma caixa muda para `CONFORME + DISPONIVEL`; nenhuma caixa ou produção é recriada. Retrabalho e manutenção do bloqueio continuam bloqueados. Reprocesso usa a situação já existente `REPROCESSAMENTO`. Descarte marca a posição como `DESCARTADO`, sem apagar o registro oficial nem gerar movimento financeiro.

## Compatibilidade e evolução

- O bloqueio legado da Expedição continua disponível para registros anteriores e não é migrado automaticamente para evitar inferência de dados gerenciais inexistentes.
- A consulta oficial fica em Qualidade e também é alcançável pelos domínios de Produção e Expedição conforme o perfil.
- A exportação CSV cobre o relatório do MVP; eventual catálogo parametrizado na Biblioteca de Relatórios permanece uma evolução isolada.
- Não foram implementados causa raiz, 5 Porquês, plano de ação, eficácia, nova OP automática, custos, CMV ou integração financeira.
