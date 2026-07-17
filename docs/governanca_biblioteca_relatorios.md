# Governanca da Biblioteca Oficial de Relatorios

## Papel da Biblioteca

A Biblioteca Oficial de Relatorios e o catalogo unico de descoberta, governanca e backlog dos relatorios gerenciais do PRUMO. Ela nao substitui telas operacionais, cadastros, importadores ou fluxos de trabalho; ela organiza apenas relatorios de consulta, auditoria e gestao.

## Relatorio x Tela Operacional

Relatorio oficial:
- consolida dados para leitura, auditoria ou decisao;
- possui item no catalogo de 38 relatorios oficiais;
- informa dominio, status, prioridade, permissao, dependencias e formatos;
- so anuncia Excel quando existe rota de exportacao;
- so anuncia PDF quando existe geracao real de PDF.

Tela operacional:
- cria, altera, exclui, importa, liquida, transfere ou aponta dados;
- permanece fora do catalogo, mesmo quando mostra listas ou saldos;
- nao deve ser removida por existir um relatorio semelhante.

## Campos obrigatorios do catalogo

Cada item em `modules/relatorios/catalogo.py` deve declarar:
- `id`
- `titulo`
- `descricao`
- `dominio`
- `grupo`
- `prioridade`
- `onda`
- `status`
- `dependencias`
- `formatos`
- `permissao`
- `endpoint` e `route_args`, quando disponivel para uso operacional.

## Status oficiais

- `Disponivel`: relatorio publicado e navegavel.
- `Disponivel - requer evolucao`: navegavel, mas com evolucao funcional conhecida.
- `Em estruturacao`: catalogado, ainda sem rota publica.
- `Dependencia funcional`: depende de dado, modulo ou integracao ainda nao disponivel.
- `Futuro`: previsto, mas fora do escopo atual.
- `Congelado`: documentado para preservar decisao, sem operacao ativa.

Itens em estruturacao, futuros ou congelados nao devem possuir endpoint operacional e devem usar formato `Catalogo`.

## Regras de rota e formato

- A Biblioteca fica em `/relatorios`.
- Relatorios oficiais usam `/relatorios/<dominio>/<slug>`.
- Exportacoes oficiais usam `/relatorios/<dominio>/<slug>/exportar`.
- DRE Gerencial permanece em `/dre-gerencial` e `/dre-gerencial/exportar-excel`.
- Fluxo de Caixa permanece em `/fluxo-caixa`.
- Impressao pelo navegador deve ser anunciada como `Impressao`, nao como `PDF`.
- Rotas futuras bloqueadas nao devem existir ate a sprint propria: Sankhya/NF, vendas, rastreabilidade comercial, giro, FIFO, CMV e OEE.

## Descontinuacao de legados

Uma rota legada pode ser descontinuada apenas quando existir substituto 1:1 validado. O tratamento permitido e:
- remover links de navegacao para o legado;
- redirecionar a rota legada para o relatorio oficial equivalente;
- retornar 410 apenas quando a descontinuidade for deliberada e sem necessidade de compatibilidade;
- preservar a implementacao antiga sem rota quando houver valor historico para consulta tecnica.

## Compatibilidade temporaria

Rotas preservadas temporariamente por ausencia de substituto 1:1:
- `/relatorio-custos`: requisito gerencial legado baseado em custos mensais cadastrados, fora dos 38 ate decisao humana.
- `/relatorio-viabilidade`: ferramenta operacional da Qualidade, fora dos 38 ate decisao humana.

Rota redirecionada por equivalencia validada:
- `/relatorio-rendimento` -> `/relatorios/producao/rendimento`

## Validacao automatizada

O teste `tests/test_governanca_biblioteca_relatorios.py` protege:
- total de 38 itens no catalogo;
- unicidade dos IDs;
- campos obrigatorios e vocabulario oficial;
- endpoints existentes para itens disponiveis;
- ausencia de rotas futuras bloqueadas;
- coerencia entre formatos anunciados e rotas reais;
- allowlist explicita para relatorios legados preservados.

Qualquer nova onda de relatorios deve atualizar o catalogo, a documentacao e esse teste no mesmo commit.
