# QUAL-SGI-01 — Central de Verificações PLM 01 a 05

## Entrega funcional

A Central de Verificações está disponível em `/sgi/qualidade` para os perfis
`qualidade`, `pcp` e `gerencia` (além do administrador global). Ela reúne seis
fichas fixas: as duas versões documentais do PLM 01, PLM 02, PLM 03, PLM 04 e
PLM 05. Os códigos regulatórios foram preservados; as variantes do PLM 01 são
distinguidas apenas por `formulario_tipo` interno.

Cada verificação exige vínculo com ambiente, estrutura ou equipamento. Ambientes
e estruturas são uma extensão mínima da Central de Configuração na tabela
`cadastros_locais`; equipamentos reutilizam `manutencao_equipamentos`.

## Arquitetura e migration

- Configuração fixa das fichas: `modules/qualidade/plm_config.py`.
- Regras: `modules/qualidade/services.py`.
- Persistência e consultas: `modules/qualidade/repositories.py`.
- Rotas: `modules/qualidade/routes.py`.
- Migration PostgreSQL auditável: `database/20260720_qual_sgi_01.sql`.
- Inicialização aditiva e idempotente: `criar_tabelas_sgi()` no startup.

Entidades: `cadastros_locais`, `sgi_verificacoes`, `sgi_verificacao_itens`,
`sgi_nao_conformidades`, `sgi_acoes_imediatas` e `sgi_eventos`. A OS continua em
`manutencao_ordens`, acrescida apenas de `sgi_nc_id`. Não existe hard delete nas
entidades SGI e o formulário não é persistido como JSON opaco.

## Regras implantadas

- PLM 02: reposição simples gera ação imediata, permanece pendente e exige
  segunda verificação exclusiva da Qualidade. Não abre OS automaticamente.
- PLM 03: limite automático pela classificação do ambiente (110, 220 ou 540 lux).
- PLM 04: aceita `Não se aplica` por equipamento inexistente.
- Toda marcação NC gera registro estruturado, criticidade e histórico.
- NC crítica cria pendência interna de decisão da Gerência, com justificativa.
- OS é facultativa, usa o domínio real de Manutenção e mantém vínculo navegável
  nos dois sentidos.
- A conclusão da OS muda a NC para `Aguardando validacao da Qualidade`; não a
  encerra. Eficácia e encerramento definitivo são exclusivos da Qualidade.
- O consolidado mensal oferece filtros e impressão com campos de assinatura.

## Itens conscientemente adiados

- Fotografias/anexos: não há armazenamento durável compatível com o Render.
- Requisição de compra: não há módulo transacional; a OS pode usar o status
  `Aguardando material` e seus recursos existentes até a sprint específica.
- Gráficos, Pareto, reincidência, tendências e relatório de efetividade.
- Correção da permissão do relatório legado de viabilidade.

## Operação paralela por três dias

1. Dia 1: cadastrar ambientes/estruturas, conferir equipamentos e executar um
   registro digital ao lado de cada formulário em papel, sem abandonar o papel.
2. Dia 2: comparar item a item, conferir NCs, ações imediatas, OS e responsáveis;
   registrar divergências sem editar o histórico já concluído.
3. Dia 3: repetir o paralelo, imprimir o consolidado da competência e obter aceite
   da Qualidade, PCP e Gerência antes de descontinuar o preenchimento em papel.
