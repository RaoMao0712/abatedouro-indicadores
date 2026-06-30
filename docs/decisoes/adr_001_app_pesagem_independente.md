# ADR 001 - Aplicativo de pesagem independente

## Status

Aprovado.

## Contexto

O ecossistema FrigoDatta ira controlar a operacao do frigorifico, mas nao deve se conectar diretamente aos equipamentos industriais de chao de fabrica.

Os primeiros equipamentos disponiveis para desenvolvimento sao:

- Balanca Weightech WT1000
- Impressora Zebra ZD220

Mesmo assim, o projeto deve nascer preparado para trocar ou adicionar outros modelos e marcas no futuro.

## Decisao

O aplicativo de pesagem sera um sistema independente do FrigoDatta.

Ele tera um nucleo de dominio livre de detalhes de fabricante e usara adaptadores para cada equipamento fisico.

O nucleo do aplicativo dependera apenas de contratos genericos:

- `Balanca`: captura leituras de peso.
- `ImpressoraEtiqueta`: imprime etiquetas.
- `RepositorioPesagens`: persiste caixas, pallets e eventos operacionais.

Os equipamentos especificos, como Weightech WT1000 e Zebra ZD220, serao implementados como adaptadores externos ao nucleo.

## Consequencias

- A troca de balanca ou impressora nao deve exigir reescrita do fluxo operacional.
- O aplicativo pode ser validado localmente com simuladores antes do uso em producao.
- A integracao com o FrigoDatta sera feita somente depois da validacao completa da pesagem e da etiquetagem.
- O FrigoDatta recebera informacoes consolidadas no encerramento do pallet, nao uma comunicacao por caixa.

## Regra operacional

O desenvolvimento seguira uma etapa por vez:

1. Integracao e validacao da balanca.
2. Integracao e validacao da impressora.
3. Integracao controlada com o FrigoDatta.

Nenhuma etapa posterior deve bloquear ou contaminar a estabilidade da etapa atual.
