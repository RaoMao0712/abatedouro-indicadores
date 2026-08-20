# Relatório de Verificação de Produtos Não Conformes

## Objetivo

Disponibilizar, em **Expedição > Produtos Não Conformes**, uma seleção operacional e um PDF executivo para conferência física e decisão manual da Diretoria. A emissão não descarta, libera, reserva nem movimenta estoque.

## Fluxo

1. O usuário com perfil `pcp`, `qualidade` ou `gerencia` filtra os saldos elegíveis.
2. Seleciona um, vários ou todos os resultados e solicita a prévia.
3. O servidor recalcula os saldos e devolve um token SHA-256 da fotografia corrente.
4. Na emissão, o servidor recalcula novamente. Uma divergência invalida a geração.
5. Com a fotografia confirmada, o sistema grava o relatório, seu evento de auditoria e o hash de integridade.
6. A reimpressão usa exclusivamente o snapshot persistido e verifica sua integridade antes de produzir o PDF.

## Conteúdo persistido

- número único e data/hora com fuso `America/Manaus`;
- usuário e perfil emissor;
- filtros e referências internas selecionadas;
- quantidades originais e snapshot consolidado;
- totais por produto e apresentação;
- resultado da geração e hash SHA-256;
- evento de auditoria da emissão.

## Privacidade operacional do PDF

O PDF agrupa por característica, produto e apresentação. Referências usadas para consistência e auditoria permanecem no banco e não são exibidas: SKU, lote, validade, local, IDs e demais identificadores técnicos.

## Migração e reversão

Os artefatos `20260820_relatorio_verificacao_nc.sql` e sua variante SQLite criam as tabelas de relatório e eventos. Os arquivos `*_rollback.sql` removem somente essas tabelas e devem ser executados apenas quando os relatórios persistidos puderem ser descartados com autorização explícita.
