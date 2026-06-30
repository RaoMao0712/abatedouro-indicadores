# FrigoDatta Pesagem

Aplicativo independente para pesagem, etiquetagem e posterior integracao controlada com o FrigoDatta.

## Principios

- Operar localmente no computador da producao.
- Comunicar diretamente com balanca e impressora.
- Manter banco de dados proprio.
- Tratar Weightech WT1000 e Zebra ZD220 como primeiros adaptadores, nao como dependencias do nucleo.
- Permitir novos modelos e marcas por meio de novos adaptadores.
- Integrar com o FrigoDatta somente apos validacao operacional.

## Estrutura

```text
pesagem_app/
  src/pesagem_app/
    core/          Regras de pesagem, tara e registro
    ports/         Contratos para balanca, impressora e armazenamento
    adapters/      Implementacoes especificas por tecnologia/fabricante
    config/        Carregamento de configuracao local
  tests/           Testes automatizados do nucleo e adaptadores
```

## Etapa atual

STEP 1 - Integracao com balanca.

O primeiro objetivo tecnico e validar captura de peso bruto, calculo de peso liquido e registro local de cada caixa pesada.
