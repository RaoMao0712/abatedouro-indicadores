# Pedido de Venda Direta — auditoria e arquitetura

## Fluxo anterior auditado

1. O cliente é ligado ao romaneio por `expedicoes.cliente_id`. Na conclusão de uma venda direta, o cadastro precisa continuar ativo e `cliente_snapshot` preserva os dados usados no documento.
2. Os itens físicos ficam em `expedicao_itens`, ligados a `pa_caixas` por `caixa_id`. Pacotes usam `quantidade_pacotes` e `quantidade_galinhas`; caixas usam quantidade de bandejas e peso líquido, além dos snapshots operacionais.
3. O estoque é reservado somente por `reservar_itens`/`reservar_operacional`. A baixa ocorre em `concluir_romaneio`; criar ou editar o cabeçalho não movimenta estoque.
4. O cancelamento de romaneio aberto libera reservas e restaura disponibilidade. O estorno de romaneio concluído recompõe pacotes/caixas, localização e condição anteriores.
5. O vínculo comercial necessário é item a item: `pedido_venda_itens` → `expedicao_itens.pedido_item_id` → `pedido_venda_atendimentos`. O atendimento registra quantidade, unidade e peso sem depender apenas do cabeçalho.

Também foram auditados a numeração `ROM-AAAAMMDD-NNN`, os perfis existentes (`admin`, `gerencia`, `pcp`, `qualidade`), a trilha `estoque_eventos`, as duas visões do relatório de entregas e o padrão de migrations PostgreSQL/SQLite.

## Arquitetura adotada

- `pedidos_venda`: cabeçalho comercial, pagamento, totais exatos em centavos, status, snapshots, versão otimista e autoria.
- `pedido_venda_itens`: SKU/produto, apresentação, quantidade em milésimos, unidade, preço/desconto em centavos e snapshots históricos.
- `pedido_venda_romaneio_itens`: plano de atendimento de cada item em cada romaneio.
- `pedido_venda_atendimentos`: entrega efetiva por item do romaneio, com quantidade, unidade, peso e estado reversível.
- `pedido_venda_eventos`: auditoria permanente com estados, usuário, perfil, justificativa, origem e chave idempotente.
- `pedido_venda_sequencias`: numeração concorrente `PV-AAAAMMDD-NNN`.
- `expedicoes.pedido_venda_id`: um único pedido por romaneio no MVP; nulo em documentos históricos.
- `expedicoes.pedido_destino_entrega`: destino comercial, separado do destino operacional controlado “Venda direta”.
- `expedicao_itens.pedido_item_id`: vínculo físico/comercial no nível do item.

## Regras de integridade

- Dinheiro nunca usa `float`: valores são convertidos com `Decimal` e persistidos em centavos.
- Quantidades são persistidas em milésimos e nunca somadas entre unidades diferentes.
- O backend recalcula bruto, líquido, subtotal, desconto geral e total, rejeitando divergência enviada pelo navegador.
- Somente rascunhos são editáveis. Confirmação não reserva nem baixa estoque.
- A geração de romaneio usa versão otimista contra duplo clique e bloqueio transacional do pedido; planos abertos também consomem o saldo disponível.
- A reserva oficial reutiliza o estoque existente e só aceita posição física que corresponda unicamente a SKU/nome, apresentação, unidade e saldo planejado.
- A conclusão bloqueia o pedido, valida sobre-entrega, grava atendimentos e recalcula o status na mesma transação da baixa.
- Cancelar romaneio aberto não entrega quantidade. Estornar romaneio concluído marca atendimentos como estornados e recalcula o pedido na mesma transação.
- Pedidos não são excluídos fisicamente. Cancelar pedido exige gestão, motivo e inexistência de romaneio aberto.
- Romaneios anteriores continuam sem pedido e são identificados como “Não vinculado — documento anterior ao novo fluxo”.

## Migrations

As migrations `20260810_pedidos_venda_romaneios` possuem versões PostgreSQL e SQLite, além dos dois rollbacks. São aditivas, não convertem nem criam registros históricos e o inicializador da aplicação aplica a mesma estrutura de forma idempotente.
