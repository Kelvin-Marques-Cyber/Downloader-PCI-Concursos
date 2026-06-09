# PCI Downloader — Release v1.0.0

**Versão:** v1.0.0
**Data:** 2026-06-09

## Resumo

Primeira versão pública do PCI Downloader — ferramenta desktop em Tkinter para localizar e baixar provas do PCI Concursos. Esta release integra um mecanismo de checagem de concursos, oferece filtragem por região/cargo/banca e inclui um binário gerado com PyInstaller para Windows.

## Principais novidades

- Integração do "checador" de concursos, com detecção de novos editais desde a última checagem.
- Suporte a filtros por região: `TODOS`, `NACIONAL` e todas as UFs do Brasil.
- Pop-up de alertas refeito para exibir lista completa com links diretos e rolagem.
- Cache por região em `data/concursos_cache_<filtro>.json` para comparação incremental.
- Downloads paralelos de provas em PDF com controle de simultaneidade e pasta de destino configurável.
- Build disponibilizado via PyInstaller: `dist/PCIDownloader/PCIDownloader.exe` (Windows, onedir).

## Detalhes técnicos

- Linguagem: Python 3.10+ (testado com Python 3.12.10 no ambiente de build).
- Principais dependências: `requests`, `beautifulsoup4`.
- Arquivo principal da aplicação: `PCI.py` — contém UI, downloader e checador integrados.

## Observações de uso

- Para executar localmente: `python PCI.py`.
- Para gerar o executável Windows a partir do ambiente virtual:

```bash
c:/path/to/venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name PCIDownloader PCI.py
```

- O cache de concursos é seguro de apagar (o aplicativo irá reconstituí-lo), mas apagar o cache fará com que todos os concursos apareçam como “novos” na próxima checagem.

## Créditos e licença

- Função de checador inspirada no projeto: https://github.com/luiseduardobr1/PCIConcursos — crédito restrito à lógica de verificação de novos concursos.
- Copyright principal: Kelvin e Silva Marques.
- Licença do projeto: ver arquivo `LICENSE` (Apache License 2.0).

---

_Pontos futuros (backlog):_

- Exportar lista de concursos recentes para CSV/JSON.
- Melhorar detecção de duplicatas por heurísticas mais robustas.
- Criar instaladores para outras plataformas.

## Checksums

Arquivo: `SHA256SUMS.txt`

Conteúdo (SHA256):

```
9b71a84341170e6d4d2a1f4503be94b5ca1e8203ada4dbb3a9bdd9fe47fe06c8  dist/PCIDownloader/PCIDownloader.exe
```

## Como verificar a integridade do binário (Windows)

1. Baixe o executável da Release e o arquivo `SHA256SUMS.txt`.
2. No PowerShell, execute:

```powershell
certutil -hashfile "<caminho>\PCIDownloader.exe" SHA256
```

3. Compare o hash retornado com o valor presente em `SHA256SUMS.txt`.

Se os hashes coincidirem, o arquivo baixado corresponde ao binário publicado.
