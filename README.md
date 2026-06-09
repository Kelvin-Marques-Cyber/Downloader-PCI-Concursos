# PCI Downloader (foco em `PCI.py`)

Aplicação desktop em Tkinter para download de provas do PCI Concursos por cargo ou banca, com filtros e execução paralela.

## Funcionalidades

- Download de provas em PDF por cargo ou organizadora.
- Filtro por ano, limite de páginas e controle de simultaneidade.
- Salvamento em pasta de destino configurável.
- Exibição de pop-up com os concursos mais recentes e identificação de novos concursos desde a última checagem.

## Estrutura do projeto

- `PCI.py`: aplicação principal (interface gráfica, downloader e checador integrado).
- `data/`: cache local do checador (`concursos_cache_<filtro>.json`).
- `downloads/`: pasta sugerida para os arquivos baixados.

## Requisitos

- Python 3.10 ou superior
- `requests`
- `beautifulsoup4`

Instalação rápida:

```bash
pip install requests beautifulsoup4
```

## Execução

```bash
python PCI.py
```

## Checador integrado

O pop-up de concursos:

- é executado automaticamente na inicialização;
- pode ser acionado manualmente no botão `Pop-up últimos concursos`;
- utiliza o filtro selecionado (`TODOS`, `NACIONAL` ou qualquer UF do Brasil);
- compara os dados atuais com o cache local para destacar novos concursos;
- apresenta o link direto de cada concurso novo.

## Créditos e direitos autorais

### Crédito específico (checador de últimos concursos)

A funcionalidade de aviso de novos concursos por região foi inspirada no projeto:

- https://github.com/luiseduardobr1/PCIConcursos

### Copyright principal do projeto

Todo o restante deste projeto (download de provas, interface gráfica, integração, organização do código, ajustes e evolução) é de autoria de:

Kelvin e Silva Marques

LinkedIn:
https://www.linkedin.com/in/kelvin-e-silva-marques/

## Observações

- O cache do checador é armazenado em `data/concursos_cache_<filtro>.json`.
- A pasta padrão de download na interface é `downloads/provas_pci`.

