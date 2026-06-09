#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCI Concursos - Downloader com interface grafica (Tkinter)

Permite baixar provas filtrando por CARGO ou por BANCA (organizadora),
com filtro opcional de ANO, escolha de pasta, delay e limite de paginas.

Estrutura do site usada:
  - Indice de cargos:        /provas/
  - Indice de organizadoras: /organizadoras/  (perfil em /organizadoras/{slug})
  - Listagem (cargo/banca):  /provas/{slug}  e  /provas/{slug}/{pagina}
  - Pagina de download:      /provas/download/{slug}  -> contem os links .pdf
  - Arquivo final:           /provas/{id}/{hash}/arquivo.pdf

DEPENDENCIAS:
    pip install requests beautifulsoup4
  (tkinter ja vem com o Python no Windows)

EXECUTAR:
    python PCI.py
"""

import os
import re
import time
import json
import unicodedata
import queue
import random
import threading
import concurrent.futures as cf
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

BASE = "https://www.pciconcursos.com.br"
CONCURSOS_URL = BASE + "/concursos/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

UFS_BRASIL = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

NOME_ESTADO_PARA_UF = {
    "NACIONAL": "NACIONAL",
    "ACRE": "AC",
    "ALAGOAS": "AL",
    "AMAPA": "AP",
    "AMAZONAS": "AM",
    "BAHIA": "BA",
    "CEARA": "CE",
    "DISTRITO FEDERAL": "DF",
    "ESPIRITO SANTO": "ES",
    "GOIAS": "GO",
    "MARANHAO": "MA",
    "MATO GROSSO": "MT",
    "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG",
    "PARA": "PA",
    "PARAIBA": "PB",
    "PARANA": "PR",
    "PERNAMBUCO": "PE",
    "PIAUI": "PI",
    "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN",
    "RIO GRANDE DO SUL": "RS",
    "RONDONIA": "RO",
    "RORAIMA": "RR",
    "SANTA CATARINA": "SC",
    "SAO PAULO": "SP",
    "SERGIPE": "SE",
    "TOCANTINS": "TO",
}

OPCOES_REGIAO_CONCURSOS = ["TODOS", "NACIONAL", *UFS_BRASIL]


# ----------------------------------------------------------------------------
# MOTOR DE SCRAPING / DOWNLOAD  (sem dependencia da interface)
# ----------------------------------------------------------------------------

def criar_sessao():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


_thread_local = threading.local()


def sessao_thread():
    """Cada thread usa sua propria Session (requests.Session nao garante thread-safety)."""
    s = getattr(_thread_local, "sess", None)
    if s is None:
        s = criar_sessao()
        _thread_local.sess = s
    return s


def pausa(delay):
    time.sleep(delay + random.uniform(0, delay * 0.5))


def get_soup(sess, url, delay, log=print):
    for tentativa in range(3):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            if r.status_code == 404:
                return None
            log(f"  [!] HTTP {r.status_code} em {url} (tentativa {tentativa+1})")
        except requests.RequestException as e:
            log(f"  [!] Erro de rede: {e} (tentativa {tentativa+1})")
        pausa(delay * 2)
    return None


def listar_cargos(sess, delay, log=print):
    soup = get_soup(sess, BASE + "/provas/", delay, log)
    if not soup:
        return {}
    cargos = {}
    for a in soup.select('a[href*="/provas/"]'):
        path = urlparse(urljoin(BASE, a.get("href", ""))).path
        m = re.fullmatch(r"/provas/([a-z0-9\-]+)", path)
        if m and m.group(1) not in {"download", "top"}:
            cargos[m.group(1)] = a.get_text(strip=True)
    return cargos


def listar_organizadoras(sess, delay, log=print):
    soup = get_soup(sess, BASE + "/organizadoras/", delay, log)
    if not soup:
        return {}
    orgs = {}
    for a in soup.select('a[href*="/organizadoras/"]'):
        path = urlparse(urljoin(BASE, a.get("href", ""))).path
        m = re.fullmatch(r"/organizadoras/([a-z0-9\-]+)", path)
        if m:
            orgs[m.group(1)] = a.get_text(strip=True)
    return orgs


def resolver_slug_provas_da_banca(sess, profile_slug, delay, log=print):
    """A partir de /organizadoras/{slug}, acha o link 'Provas realizadas...' -> /provas/{slug}."""
    soup = get_soup(sess, f"{BASE}/organizadoras/{profile_slug}", delay, log)
    if not soup:
        return None
    for a in soup.find_all("a"):
        if "provas realizadas" in a.get_text(strip=True).lower():
            path = urlparse(urljoin(BASE, a.get("href", ""))).path
            m = re.fullmatch(r"/provas/([a-z0-9\-]+)", path)
            if m:
                return m.group(1)
    # fallback: primeiro /provas/{slug} que nao seja o indice
    for a in soup.select('a[href*="/provas/"]'):
        path = urlparse(urljoin(BASE, a.get("href", ""))).path
        m = re.fullmatch(r"/provas/([a-z0-9\-]+)", path)
        if m:
            return m.group(1)
    return None


def total_paginas(soup):
    maior = 1
    for a in soup.select('a[href]'):
        m = re.search(r"/provas/[a-z0-9\-]+/(\d+)$", a.get("href", ""))
        if m:
            maior = max(maior, int(m.group(1)))
    return maior


def provas_na_pagina(soup):
    """Lista de (download_url, ano, cargo) extraida da tabela de listagem.
    O 'cargo' vem do texto do proprio link da prova (1a coluna da tabela)."""
    out, vistos = [], set()
    for a in soup.select('a[href*="/provas/download/"]'):
        href = urljoin(BASE, a.get("href"))
        if href in vistos:
            continue
        vistos.add(href)
        cargo = a.get_text(strip=True) or "outros"
        ano = None
        tr = a.find_parent("tr")
        if tr:
            m = re.search(r"\b(?:19|20)\d{2}\b", tr.get_text(" ", strip=True))
            if m:
                ano = int(m.group(0))
        out.append((href, ano, cargo))
    return out


def pdfs_na_pagina_de_download(soup):
    pdfs = set()
    for a in soup.select('a[href$=".pdf"]'):
        pdfs.add(urljoin(BASE, a.get("href")))
    return sorted(pdfs)


def nome_seguro(s):
    s = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE)
    return s.strip("_") or "arquivo"


def baixar_pdf(sess, url, pasta_destino, delay, log=print):
    parsed = urlparse(url)
    partes = [p for p in parsed.path.split("/") if p]
    nome = nome_seguro("_".join(partes[-3:])) if len(partes) >= 3 else nome_seguro(partes[-1])
    if not nome.lower().endswith(".pdf"):
        nome += ".pdf"
    destino = os.path.join(pasta_destino, nome)
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        log(f"      = ja existe: {nome}")
        return False
    try:
        with sess.get(url, timeout=60, stream=True) as r:
            ct = r.headers.get("Content-Type", "")
            if r.status_code != 200 or "pdf" not in ct.lower():
                log(f"      [!] nao parece PDF ({r.status_code}, {ct})")
                return False
            os.makedirs(pasta_destino, exist_ok=True)
            tmp = destino + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp, destino)
            log(f"      + baixado: {nome}")
            return True
    except requests.RequestException as e:
        log(f"      [!] erro ao baixar: {e}")
        return False


def _processar_prova(href, destino_pasta, delay, stop_event, log):
    """Abre uma pagina /provas/download/{slug} e baixa seus PDFs. Roda em thread."""
    if stop_event.is_set():
        return 0
    sess = sessao_thread()
    soup_dl = get_soup(sess, href, delay, log)
    if delay:
        pausa(delay)
    if not soup_dl:
        return 0
    n = 0
    for pdf in pdfs_na_pagina_de_download(soup_dl):
        if stop_event.is_set():
            break
        if baixar_pdf(sess, pdf, destino_pasta, delay, log):
            n += 1
        if delay:
            pausa(delay)
    return n


def baixar_slug(sess, slug, nome_amigavel, pasta_base, delay,
                ano_min, ano_max, max_paginas, stop_event, log=print,
                por_cargo=False, workers=8):
    """Percorre /provas/{slug} e baixa os PDFs em PARALELO (com filtro de ano).
    Se por_cargo=True, cria subpastas com o nome do cargo dentro da pasta do slug."""
    log(f"\n=== {nome_amigavel} ({slug}) ===")
    primeira = get_soup(sess, f"{BASE}/provas/{slug}", delay, log)
    if not primeira:
        log("  [!] nao consegui abrir a listagem; pulando.")
        return 0
    tp = total_paginas(primeira)
    if max_paginas:
        tp = min(tp, max_paginas)
    log(f"  Paginas: {tp} | downloads simultaneos: {workers}")
    pasta = os.path.join(pasta_base, nome_seguro(slug))

    # ---- Fase 1: coletar todas as provas (paginas em paralelo) ----
    entradas = list(provas_na_pagina(primeira))  # pagina 1

    def baixar_pagina(p):
        if stop_event.is_set():
            return []
        s = sessao_thread()
        soup = get_soup(s, f"{BASE}/provas/{slug}/{p}", delay, log)
        if delay:
            pausa(delay)
        return list(provas_na_pagina(soup)) if soup else []

    if tp > 1:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(baixar_pagina, range(2, tp + 1)):
                entradas.extend(res)

    # filtro de ano
    if ano_min or ano_max:
        filtradas = []
        for href, ano, cargo in entradas:
            if ano is None:
                continue
            if ano_min and ano < ano_min:
                continue
            if ano_max and ano > ano_max:
                continue
            filtradas.append((href, ano, cargo))
        entradas = filtradas

    log(f"  Total de provas a baixar: {len(entradas)}")
    if not entradas:
        return 0

    # ---- Fase 2: baixar PDFs de cada prova em paralelo ----
    baixados = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = []
        for href, ano, cargo in entradas:
            if stop_event.is_set():
                break
            destino = os.path.join(pasta, nome_seguro(cargo)) if por_cargo else pasta
            futuros.append(ex.submit(_processar_prova, href, destino, delay, stop_event, log))
        for fut in cf.as_completed(futuros):
            try:
                baixados += fut.result()
            except Exception as e:
                log(f"  [!] erro em uma prova: {e}")

    log(f"  >> {baixados} arquivos novos em '{slug}'")
    return baixados


def extrair_concursos_regiao(soup, regiao):
    """Extrai concursos por estado (UF), NACIONAL ou TODOS da pagina /concursos/."""
    regiao = regiao.strip().upper()
    if regiao not in OPCOES_REGIAO_CONCURSOS:
        raise ValueError(f"Regiao nao suportada: {regiao}")

    source_code_str = str(soup)
    blocos_uf = list(re.finditer(r'<div class="uf">\s*([^<]+?)\s*</div>', source_code_str, flags=re.IGNORECASE))
    if not blocos_uf:
        return []

    def normalizar_estado(nome_estado):
        nome = unicodedata.normalize("NFD", nome_estado)
        nome = "".join(ch for ch in nome if unicodedata.category(ch) != "Mn")
        return re.sub(r"\s+", " ", nome).strip().upper()

    concursos = []
    for i, match in enumerate(blocos_uf):
        nome_estado = normalizar_estado(match.group(1))
        uf = NOME_ESTADO_PARA_UF.get(nome_estado)
        if not uf:
            continue

        if regiao == "TODOS" and uf not in UFS_BRASIL:
            continue
        if regiao == "NACIONAL" and uf != "NACIONAL":
            continue
        if regiao in UFS_BRASIL and uf != regiao:
            continue

        inicio_idx = match.end()
        fim_idx = blocos_uf[i + 1].start() if i + 1 < len(blocos_uf) else len(source_code_str)
        trecho_html = source_code_str[inicio_idx:fim_idx]
        linhas = BeautifulSoup(trecho_html, "html.parser").find_all(class_="ca")

        for line in linhas:
            a = line.select_one('a[href*="/noticias/"]') or line.find("a")
            if not a:
                continue

            nome = a.get_text(strip=True)
            href = a.get("href", "")
            link = urljoin(BASE, href) if href else "-"
            cd = str(line.find(class_="cd") or "")
            ce = str(line.find(class_="ce") or "")

            vagas = "".join(re.findall(r"(\d+)\s*vaga", cd, flags=re.IGNORECASE))
            nivel = "/".join(re.findall(r"Superior|Médio|Fundamental|Técnico", cd, flags=re.IGNORECASE))
            salario = "".join(re.findall(r"R\$ *[\d\.,]+", cd))
            inscricao = "".join(re.findall(r"\d{2}/\d{2}/\d{4}", ce))

            concursos.append(
                {
                    "concurso": nome,
                    "vagas": vagas or "-",
                    "nivel": nivel or "-",
                    "salario": salario or "-",
                    "inscricao": inscricao or "-",
                    "link": link,
                    "uf": uf,
                }
            )

    return concursos


# Credito especifico: a ideia de checagem de ultimos/novos concursos por regiao
# foi inspirada em https://github.com/luiseduardobr1/PCIConcursos.
# Todo o restante do projeto e de autoria de Kelvin e Silva Marques.
def carregar_cache_concursos(cache_path):
    if not os.path.exists(cache_path):
        return []
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, list):
            return dados
    except (OSError, json.JSONDecodeError):
        pass
    return []


def salvar_cache_concursos(cache_path, concursos):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(concursos, f, ensure_ascii=False, indent=2)


def detectar_novos_concursos(anteriores, atuais):
    def link_normalizado(item):
        return urljoin(BASE, item.get("link", ""))

    chaves_anteriores = {
        (item.get("concurso", ""), link_normalizado(item))
        for item in anteriores
    }
    return [
        item for item in atuais
        if (item.get("concurso", ""), link_normalizado(item)) not in chaves_anteriores
    ]


def montar_texto_popup_concursos(regiao, ultimos, novos):
    if regiao == "TODOS":
        escopo = "todos os estados"
    elif regiao == "NACIONAL":
        escopo = "nacional"
    else:
        escopo = regiao

    linhas = [f"Ultimos concursos ({escopo})", ""]
    for item in ultimos:
        uf = item.get("uf", "-")
        prefixo = f"[{uf}] " if uf and uf != "-" else ""
        linhas.append(f"- {prefixo}{item.get('concurso', '-')}")

    if novos:
        linhas.extend(["", f"Novos desde a ultima checagem: {len(novos)}", ""])
        for item in novos:
            uf = item.get("uf", "-")
            prefixo = f"[{uf}] " if uf and uf != "-" else ""
            linhas.append(f"+ {prefixo}{item.get('concurso', '-')}")
            linhas.append(f"  Link: {item.get('link', '-')}")

    return "\n".join(linhas)


def checar_concursos(sess, regiao, cache_path, log=print):
    soup = get_soup(sess, CONCURSOS_URL, delay=0, log=log)
    if not soup:
        raise RuntimeError("Nao foi possivel acessar a pagina de concursos.")

    atuais = extrair_concursos_regiao(soup, regiao)
    if not atuais:
        raise RuntimeError(f"Nenhum concurso encontrado para a regiao {regiao}.")

    anteriores = carregar_cache_concursos(cache_path)
    novos = detectar_novos_concursos(anteriores, atuais)
    salvar_cache_concursos(cache_path, atuais)

    return {
        "ultimos": atuais,
        "novos": novos,
    }


# ----------------------------------------------------------------------------
# INTERFACE GRAFICA
# ----------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PCI Concursos - Downloader de Provas")
        self.geometry("820x620")
        self.minsize(740, 560)

        self.sess = criar_sessao()
        self.fila = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.itens = {}          # slug -> nome amigavel (do modo atual)
        self.lista_filtrada = [] # [(slug, nome)]
        self.checker_worker = None
        self.regiao_checker = tk.StringVar(value="TODOS")
        self.cache_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
        )

        self._montar_ui()
        self.after(100, self._consumir_fila)
        self.after(1500, self._checar_concursos_popup)

    # --- construcao da interface ---
    def _montar_ui(self):
        topo = ttk.Frame(self, padding=10)
        topo.pack(fill="x")

        ttk.Label(topo, text="Buscar por:").grid(row=0, column=0, sticky="w")
        self.modo = tk.StringVar(value="cargo")
        ttk.Radiobutton(topo, text="Cargo", variable=self.modo, value="cargo",
                        command=self._carregar_lista).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(topo, text="Banca (organizadora)", variable=self.modo, value="banca",
                        command=self._carregar_lista).grid(row=0, column=2, sticky="w")
        self.btn_carregar = ttk.Button(topo, text="Carregar lista do site", command=self._carregar_lista)
        self.btn_carregar.grid(row=0, column=3, padx=10)

        ttk.Label(topo, text="Filtrar:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.busca = tk.StringVar()
        self.busca.trace_add("write", lambda *_: self._aplicar_filtro())
        ttk.Entry(topo, textvariable=self.busca, width=40).grid(
            row=1, column=1, columnspan=3, sticky="we", pady=(8, 0))
        topo.columnconfigure(3, weight=1)

        # lista com multipla selecao
        meio = ttk.Frame(self, padding=(10, 0))
        meio.pack(fill="both", expand=True)
        ttk.Label(meio, text="Selecione um ou mais (Ctrl/Shift para multiplos):").pack(anchor="w")
        quadro = ttk.Frame(meio)
        quadro.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(quadro, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(quadro, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)

        # opcoes
        opc = ttk.LabelFrame(self, text="Opcoes", padding=10)
        opc.pack(fill="x", padx=10, pady=8)

        ttk.Label(opc, text="Ano de:").grid(row=0, column=0, sticky="e")
        self.ano_min = tk.StringVar()
        ttk.Entry(opc, textvariable=self.ano_min, width=8).grid(row=0, column=1, sticky="w", padx=(2, 12))
        ttk.Label(opc, text="ate:").grid(row=0, column=2, sticky="e")
        self.ano_max = tk.StringVar()
        ttk.Entry(opc, textvariable=self.ano_max, width=8).grid(row=0, column=3, sticky="w", padx=(2, 12))

        ttk.Label(opc, text="Delay (s):").grid(row=0, column=4, sticky="e")
        self.delay = tk.StringVar(value="0")
        ttk.Entry(opc, textvariable=self.delay, width=6).grid(row=0, column=5, sticky="w", padx=(2, 12))

        ttk.Label(opc, text="Simultaneos:").grid(row=0, column=6, sticky="e")
        self.workers = tk.StringVar(value="12")
        ttk.Entry(opc, textvariable=self.workers, width=6).grid(row=0, column=7, sticky="w", padx=(2, 12))

        ttk.Label(opc, text="Max paginas (0=todas):").grid(row=2, column=4, columnspan=2, sticky="e", pady=(8, 0))
        self.max_pag = tk.StringVar(value="0")
        ttk.Entry(opc, textvariable=self.max_pag, width=6).grid(row=2, column=6, sticky="w", padx=(2, 12), pady=(8, 0))

        ttk.Label(opc, text="Pasta de destino:").grid(row=1, column=0, sticky="e", pady=(8, 0))
        self.pasta = tk.StringVar(value=os.path.abspath("./downloads/provas_pci"))
        ttk.Entry(opc, textvariable=self.pasta, width=58).grid(
            row=1, column=1, columnspan=6, sticky="we", pady=(8, 0))
        ttk.Button(opc, text="Escolher...", command=self._escolher_pasta).grid(
            row=1, column=7, sticky="w", pady=(8, 0))

        self.por_cargo = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opc, text="No modo banca, separar em subpastas por cargo",
            variable=self.por_cargo,
        ).grid(row=2, column=0, columnspan=8, sticky="w", pady=(8, 0))

        # botoes de acao
        acoes = ttk.Frame(self, padding=(10, 0))
        acoes.pack(fill="x")
        self.btn_baixar = ttk.Button(acoes, text="Baixar selecionados", command=self._iniciar)
        self.btn_baixar.pack(side="left")
        self.btn_parar = ttk.Button(acoes, text="Parar", command=self._parar, state="disabled")
        self.btn_parar.pack(side="left", padx=8)
        ttk.Label(acoes, text="Regiao: ").pack(side="left", padx=(14, 2))
        self.cmb_regiao = ttk.Combobox(
            acoes,
            width=9,
            textvariable=self.regiao_checker,
            values=OPCOES_REGIAO_CONCURSOS,
            state="readonly",
        )
        self.cmb_regiao.pack(side="left")
        self.btn_checador = ttk.Button(
            acoes,
            text="Pop-up ultimos concursos",
            command=self._checar_concursos_popup,
        )
        self.btn_checador.pack(side="left", padx=8)
        self.lbl_status = ttk.Label(acoes, text="Pronto.")
        self.lbl_status.pack(side="left", padx=12)

        # log
        logf = ttk.LabelFrame(self, text="Progresso", padding=6)
        logf.pack(fill="both", expand=True, padx=10, pady=8)
        self.txt = tk.Text(logf, height=10, wrap="word", state="disabled")
        self.txt.pack(side="left", fill="both", expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.txt.yview)
        sb2.pack(side="right", fill="y")
        self.txt.config(yscrollcommand=sb2.set)

    # --- helpers de log/fila (thread-safe) ---
    def log(self, msg):
        self.fila.put(("log", str(msg)))

    def status(self, msg):
        self.fila.put(("status", str(msg)))

    def _consumir_fila(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    self.txt.config(state="normal")
                    self.txt.insert("end", dado + "\n")
                    self.txt.see("end")
                    self.txt.config(state="disabled")
                elif tipo == "status":
                    self.lbl_status.config(text=dado)
                elif tipo == "popup_concursos":
                    self._mostrar_popup_concursos(dado)
                elif tipo == "erro_popup":
                    messagebox.showwarning("PCI Concursos", dado)
                elif tipo == "fim":
                    self.btn_baixar.config(state="normal")
                    self.btn_parar.config(state="disabled")
                    self.btn_carregar.config(state="normal")
                elif tipo == "fim_popup":
                    self.btn_checador.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._consumir_fila)

    def _mostrar_popup_concursos(self, texto):
        popup = tk.Toplevel(self)
        popup.title("PCI Concursos - Ultimos concursos")
        popup.geometry("900x620")
        popup.minsize(720, 420)
        popup.transient(self)

        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill="both", expand=True)

        txt = tk.Text(frame, wrap="word", state="normal")
        sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)

        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        txt.insert("1.0", texto)
        txt.configure(state="disabled")

        rodape = ttk.Frame(popup, padding=(10, 0, 10, 10))
        rodape.pack(fill="x")
        ttk.Button(rodape, text="Fechar", command=popup.destroy).pack(side="right")

        popup.grab_set()
        popup.focus_force()

    # --- acoes ---
    def _escolher_pasta(self):
        d = filedialog.askdirectory(initialdir=self.pasta.get() or ".")
        if d:
            self.pasta.set(d)

    def _carregar_lista(self):
        self.btn_carregar.config(state="disabled")
        self.status("Carregando lista do site...")
        modo = self.modo.get()
        delay = self._ler_float(self.delay.get(), 2.0)

        def tarefa():
            try:
                if modo == "cargo":
                    itens = listar_cargos(self.sess, delay, self.log)
                else:
                    itens = listar_organizadoras(self.sess, delay, self.log)
                self.itens = itens
                self.status(f"{len(itens)} itens carregados ({modo}).")
            except Exception as e:
                self.log(f"[!] erro ao carregar lista: {e}")
                self.status("Falha ao carregar.")
            finally:
                self.fila.put(("recarregar_listbox", None))
                self.fila.put(("fim", None))

        threading.Thread(target=tarefa, daemon=True).start()
        # gambiarra simples: trata o evento de recarregar no consumidor
        self.after(150, self._talvez_recarregar_listbox)

    def _talvez_recarregar_listbox(self):
        # processa qualquer pedido de recarga pendente
        recarregar = False
        novos = []
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "recarregar_listbox":
                    recarregar = True
                else:
                    novos.append((tipo, dado))
        except queue.Empty:
            pass
        for item in novos:
            self.fila.put(item)
        if recarregar:
            self._aplicar_filtro()
        else:
            self.after(150, self._talvez_recarregar_listbox)

    def _aplicar_filtro(self):
        termo = self.busca.get().strip().lower()
        self.lista_filtrada = []
        self.listbox.delete(0, "end")
        for slug, nome in sorted(self.itens.items(), key=lambda kv: kv[1].lower()):
            if termo in nome.lower() or termo in slug.lower():
                self.lista_filtrada.append((slug, nome))
                self.listbox.insert("end", f"{nome}   [{slug}]")

    def _ler_int(self, s, padrao=0):
        try:
            return int(str(s).strip())
        except ValueError:
            return padrao

    def _ler_float(self, s, padrao=2.0):
        try:
            return float(str(s).strip().replace(",", "."))
        except ValueError:
            return padrao

    def _iniciar(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("Atencao", "Selecione pelo menos um item na lista.")
            return
        escolhidos = [self.lista_filtrada[i] for i in sel]
        modo = self.modo.get()
        delay = self._ler_float(self.delay.get(), 2.0)
        ano_min = self._ler_int(self.ano_min.get(), 0)
        ano_max = self._ler_int(self.ano_max.get(), 0)
        max_pag = self._ler_int(self.max_pag.get(), 0)
        pasta = self.pasta.get().strip() or "./provas_pci"
        os.makedirs(pasta, exist_ok=True)
        separar_por_cargo = self.por_cargo.get()
        workers = max(1, self._ler_int(self.workers.get(), 12))

        self.stop_event.clear()
        self.btn_baixar.config(state="disabled")
        self.btn_parar.config(state="normal")
        self.btn_carregar.config(state="disabled")
        self.status("Baixando...")

        def tarefa():
            total = 0
            try:
                for slug, nome in escolhidos:
                    if self.stop_event.is_set():
                        break
                    slug_provas = slug
                    if modo == "banca":
                        self.log(f"\nResolvendo provas da banca '{nome}'...")
                        slug_provas = resolver_slug_provas_da_banca(self.sess, slug, delay, self.log)
                        if not slug_provas:
                            self.log(f"  [!] nao achei a listagem de provas de {nome}; pulando.")
                            continue
                    total += baixar_slug(
                        self.sess, slug_provas, nome, pasta, delay,
                        ano_min or None, ano_max or None, max_pag or None,
                        self.stop_event, self.log,
                        por_cargo=(modo == "banca" and separar_por_cargo),
                        workers=workers,
                    )
                self.log(f"\nConcluido. Arquivos novos: {total}")
                self.status(f"Concluido. {total} arquivos novos. Pasta: {pasta}")
            except Exception as e:
                self.log(f"[!] erro inesperado: {e}")
                self.status("Erro.")
            finally:
                self.fila.put(("fim", None))

        self.worker = threading.Thread(target=tarefa, daemon=True)
        self.worker.start()

    def _parar(self):
        self.stop_event.set()
        self.status("Parando apos a requisicao atual...")

    def _checar_concursos_popup(self):
        if self.checker_worker and self.checker_worker.is_alive():
            return

        regiao = self.regiao_checker.get().strip().upper()
        self.btn_checador.config(state="disabled")
        self.status(f"Checando concursos ({regiao})...")

        def tarefa_popup():
            try:
                cache_path = os.path.join(self.cache_dir, f"concursos_cache_{regiao.lower()}.json")
                dados = checar_concursos(self.sess, regiao, cache_path, self.log)
                ultimos = dados["ultimos"]
                novos = dados["novos"]
                texto = montar_texto_popup_concursos(regiao, ultimos, novos)
                self.fila.put(("popup_concursos", texto))
                self.status(
                    f"Concluido: {len(ultimos)} concursos lidos ({len(novos)} novos)."
                )
            except Exception as e:
                self.log(f"[!] erro no checador: {e}")
                self.fila.put(("erro_popup", f"Falha ao checar concursos: {e}"))
                self.status("Falha ao checar concursos.")
            finally:
                self.fila.put(("fim_popup", None))

        self.checker_worker = threading.Thread(target=tarefa_popup, daemon=True)
        self.checker_worker.start()


if __name__ == "__main__":
    App().mainloop()