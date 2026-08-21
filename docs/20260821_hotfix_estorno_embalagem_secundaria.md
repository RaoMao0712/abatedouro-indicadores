# Hotfix de estorno da Embalagem Secundária

## Diagnóstico

O reset legado validava a OP em uma conexão separada e, depois, apagava
fisicamente `pa_caixa_composicao`, `pa_caixas`, todo o ledger de PI da OP e os
apontamentos da Embalagem Primária. Além de perder rastreabilidade, a rotina
recusava OP encerrada e possuía uma janela de concorrência entre validação e
mutação. O endpoint destrutivo foi removido da interface e o serviço legado
passou a recusar chamadas.

Uma caixa criada na Embalagem Secundária gera:

- `pa_caixas`, com bruto, tara, líquido, datas e situação de PA;
- uma ou mais linhas em `pa_caixa_composicao` com o consumo exato por OP;
- uma `SAIDA_EMBALAGEM_SECUNDARIA` no ledger de PI por composição;
- estado `PENDENTE_OP` até o encerramento;
- no encerramento, evento `FORMACAO_ESTOQUE`, disponibilidade operacional e
  totais automáticos de produção.

Romaneios, reservas, movimentações de estoque, eventos sucessores e Produto
Não Conforme podem consumir ou alterar a caixa e, portanto, bloqueiam estorno.

## Solução

`modules.expedicao.estornos_embalagem` concentra estorno individual e integral.
Os dois fluxos usam o mesmo núcleo transacional e a mesma validação de vínculos.

- A caixa recebe status `Estornada`; não existe hard delete.
- Cada saída original de PI recebe uma `ENTRADA_ESTORNO_CAIXA` compensatória,
  vinculada por `movimento_origem_id`.
- O PA fica fora do estoque operacional e com disponibilidade `ESTORNADO`.
- OP encerrada volta para `Aberta` no estorno individual e aguarda a caixa
  correta. Totais automáticos obsoletos do encerramento são retirados.
- O estorno integral executa preflight de todas as caixas antes da primeira
  mutação e termina com a OP em `Estornada`.
- Chaves únicas, row locks no PostgreSQL, revalidação na transação e versão da
  caixa protegem idempotência e concorrência.
- A trilha imutável preserva snapshot, usuário, perfil, IP, justificativa,
  movimentos, totais anteriores e posteriores.
- A ação requer perfil `admin` ou `pcp`, CSRF de sessão e a flag
  `SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED=true`.

## Implantação futura — não executada

1. Confirmar encerramento da pesagem e ausência de lançamento ativo.
2. Criar snapshot/backup do PostgreSQL.
3. Conferir o commit atualmente implantado.
4. Integrar a branch somente após autorização.
5. Aplicar `database/20260821_estorno_caixa_embalagem_secundaria.sql`.
6. Fazer deploy com a flag em `false` e confirmar HTTP 200/logs.
7. Executar smoke test somente leitura.
8. Habilitar a flag em janela controlada.
9. Homologar com uma caixa indicada, conferindo PI/PA antes e depois.
10. Em anomalia, desligar a flag imediatamente; para rollback de versão, manter
    os dados de auditoria até avaliação e só usar o downgrade se autorizado.

Nenhuma migration, escrita, estorno ou teste foi executado em produção durante
esta etapa. A integração Zebra permaneceu intocada.

## Complemento urgente — conferência e estorno múltiplo

A tela da Embalagem Secundária agora contém a **Conferência de Caixas da OP**,
com caixas ativas e estornadas, filtros, seleção múltipla, totais recalculados
no navegador e confirmação transacional no servidor. O alerta de possível
duplicidade compara pesos, bandejas, datas, lote e usuário dentro de uma janela
centralizada de 120 segundos. O alerta nunca seleciona ou estorna sozinho.

O endpoint `POST /embalagem-secundaria/<op_id>/caixas/estornar-lote` recebe
somente IDs internos, faz preflight de todas as caixas e executa o conjunto em
uma única transação. Uma falha bloqueia integralmente o lote. A chave de
idempotência do lote impede novos movimentos em reenvios.

As inclusões individual e em lote também possuem identidade de requisição e
registram o usuário da pesagem. O botão é bloqueado após o primeiro envio e a
mesma chave retorna o resultado já concluído.

Antes de encerrar, o usuário deve registrar a conferência. O snapshot persiste
IDs ativos, totais, usuário, perfil, duplicidades e hash. Inclusão, estorno ou
qualquer alteração relevante muda o hash e bloqueia o encerramento até nova
conferência.

### Homologação

- testes focados: 88 aprovados;
- suíte ampla: 415 aprovados, 1 falha e 56 erros preexistentes de isolamento;
- cenário: 5 caixas / 58 bandejas / 61,780 kg brutos / 59,280 kg líquidos;
- após estornar 2 selecionadas: 3 caixas / 34 bandejas / 36,260 kg brutos /
  34,760 kg líquidos;
- PostgreSQL 16.15 descartável: upgrade, serviço em lote, idempotência,
  downgrade e novo upgrade aprovados;
- tempos observados: upgrade 122 ms, downgrade 75 ms e reupgrade entre 88 e
  191 ms;
- registro histórico preservado em todos os ciclos;
- Zebra ZD220 e NiceLabel permaneceram fora do escopo.
