# Consolidado de estoque da Câmara

## Auditoria anterior à implementação

A tela oficial é `GET /expedicao/estoque`. O estoque individualizado posterior ao marco zero está em `pa_caixas`; o inventário agregado anterior ao marco está em `pa_nao_conformes`, com `tipo_registro = INVENTARIO_LEGADO_AGREGADO`. `expedicao_itens` é apenas a reconciliação de reservas e destinações do legado e não constitui uma terceira fonte física.

O cadastro `skus` é a fonte oficial da identidade do produto. `LEG-1` representa Galinha Cortada. `LEG-2`, combinado com `unidade_estoque = PACOTE` e `galinhas_por_pacote`, identifica Galinha Inteira V1 e V2. O fator é aplicado uma única vez; `quantidade_galinhas` é preservada como quantidade oficial e a divergência com o fator gera alerta técnico.

Os estados terminais (`TRANSFERIDO`, `EXPEDIDO`, `DESCARTADO`, `DEVOLVIDO`, `CANCELADO` e `ESTORNADO`) não compõem a posição. Os estados físicos apresentados são: disponível, reservado, não conforme bloqueado, em reprocessamento e aguardando liberação.

## Regra central

`modules/expedicao/consolidado_estoque.py` é o único motor de consolidação. A tela e o PDF consomem a mesma fotografia retornada por `consolidar_estoque_camara`. O serviço executa agregações no banco, mantém pesos em `Decimal` até a apresentação e não cria eventos nem movimentações.

Para pacotes parcialmente reservados, a posição é repartida entre disponível e reservado por `quantidade_pacotes_reservados`. Solicitações pendentes ligadas a caixas rastreadas são exibidas como aguardando liberação. Para o legado, pesos disponíveis e reservados vêm dos respectivos saldos; caixas e bandejas são reconciliadas pelas liberações aprovadas e pelos itens abertos ou concluídos, sem somar novamente o físico.

## Relatório

O PDF reutiliza o cabeçalho, rodapé, logomarca, cores e paginação do relatório oficial de expedição. Por padrão ele contém apenas o estoque conforme. A opção “Incluir estoque não conforme” adiciona uma seção separada com bloqueado, reprocessamento e aguardando liberação. Data, hora, fuso e usuário emissor ficam explícitos.
