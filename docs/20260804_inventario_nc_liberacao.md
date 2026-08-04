# Inventario nao conforme e liberacao em dois niveis

## Arquitetura reutilizada

- `pa_nao_conformes` continua sendo o cadastro oficial do PA bloqueado. O tipo
  `INVENTARIO_LEGADO_AGREGADO` usa o mesmo registro, com saldos em gramas inteiras.
- `pa_nao_conforme_eventos` continua sendo a trilha permanente de auditoria.
- `pa_nao_conforme_solicitacoes` guarda a reserva e a decisao do segundo nivel;
  nao e uma tabela paralela de estoque.
- `pa_caixas` permanece como fonte exclusiva para produtos futuros rastreados.
- `expedicao_itens` recebeu uma referencia opcional ao saldo agregado para a
  adaptacao minima dos romaneios por kg.

## Regras de integridade

- A medida oficial do legado e `saldo_*_g` (inteiro); a interface converte kg
  com no maximo tres casas decimais.
- A solicitacao reserva peso em `saldo_pendente_g`, sem libera-lo.
- Aprovar move, na mesma transacao, bloqueado para operacional. Rejeitar apenas
  desfaz a reserva.
- Caixa rastreada exige o peso integral; fracionamento e recusado no backend.
- Chaves unicas impedem repeticao da carga e da solicitacao.
- OP, lote e validade do legado permanecem nulos.

## Carga oficial

Simulacao (somente leitura/reconciliacao):

```powershell
$env:FLASK_APP='app.py'
flask carga-inventario-nc-20260730
```

Resultado esperado:

```json
{"bandejas": 10398, "caixas": 867, "existentes": 0, "inseridos": 0, "modo": "SIMULACAO", "peso_g": 10472060, "registros": 3}
```

Execucao mutavel, somente depois de autorizacao explicita e backup validado:

```powershell
$env:FLASK_APP='app.py'
flask carga-inventario-nc-20260730 --confirmar
```

Executar novamente e seguro: o retorno deve informar `inseridos=0` e
`existentes=3`. A carga nao e executada por migration nem pelo deploy.

## Reconciliacao inicial

- Fisico total: 10.472,060 kg; 867 caixas; 10.398 bandejas.
- Nao conforme bloqueado: 9.876,560 kg.
- Conforme aguardando liberacao: 595,500 kg.
- Operacional: 0 kg antes de qualquer aprovacao.

## Operacao

1. Qualidade abre Produtos Nao Conformes e solicita liberacao total ou parcial.
2. Gerencia ou Administrador abre Validar Liberacoes e aprova ou rejeita.
3. O saldo aprovado aparece separado no Estoque Operacional.
4. Romaneio normal pode reservar o legado por kg, exigindo caixas e bandejas.

## Risco residual

SQLite preexistente com `op_id`, `caixa_id` e `lote` definidos como `NOT NULL`
precisa de rebuild estrutural antes de executar a carga. O ambiente Render usa
PostgreSQL e recebe o `DROP NOT NULL` aditivo da migration/runtime. Nenhuma carga
de negocio e executada automaticamente.
