#!/usr/bin/env python3
"""
build_epg_br.py

Baixa um EPG XML (URL ou arquivo local) e gera um novo EPG contendo somente
os canais "brasileiros" (heurística baseada em id / display-name / keywords).

Uso:
  python build_epg_br.py --epg-url "https://epg.brtwo.fyi/epg.xml" --out epg_br.xml

Opcoes:
  --epg-url URL_OR_PATH   URL (https://...) ou caminho local do EPG original.
  --out PATH              Arquivo de saida (padrao: epg_br.xml).
  --keywords k1,k2,...    Lista de palavras-chave separadas por virgula usadas para detectar canais BR.
  --min-kw-matches N      Minimo de keywords que devem aparecer para considerar o canal BR (default 1).
  --use-curl              Forca usar curl para baixar (em vez de requests).
  --preview N             Mostra N canais detectados e sai (sem gravar).
"""
import argparse
import sys
import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from urllib.parse import urlparse
import subprocess

try:
    import requests
except Exception:
    requests = None

# heuristica default: palavras que costumam aparecer em canais brasileiros
DEFAULT_KEYWORDS = [
    "globo", "record", "sbt", "band", "spor", "sportv", "cultura",
    "brasil", "tv", "globoep", "tvbrasil", "rede", "rtv", "canal",
    "minas", "sp", "rj", "ba", "pr", "mg", "rs", "pe", "ce", "pa", "ba", "go",
    "amazonas", "acre", "alagoas", "sergipe", "paraiba", "paraíba",
    "espirito", "espírito", "santa", "catarina", "campinas", "recife", "nordeste",
    "norte", "sul", "centro", "capitais"
]

TZ_STR = ""  # not used here, kept for compatibility


def pretty_xml(elem):
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")


def download_text(url, use_curl=False, ua=None):
    """Retorna o conteúdo (texto) de uma URL ou caminho local."""
    ua = ua or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0"
    # se for caminho local
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        path = url if parsed.scheme == "" else parsed.path
        if not os.path.exists(path):
            raise FileNotFoundError(f"Arquivo local nao encontrado: {path}")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    # URL
    if use_curl or requests is None:
        # usar curl
        cmd = ["curl", "-sSL", "-A", ua, url]
        try:
            out = subprocess.check_output(cmd)
            return out.decode("utf-8", errors="replace")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"curl falhou: {e}")
    else:
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": ua})
            r.raise_for_status()
            return r.text
        except Exception as e:
            # fallback para curl se requests falhar
            try:
                cmd = ["curl", "-sSL", "-A", ua, url]
                out = subprocess.check_output(cmd)
                return out.decode("utf-8", errors="replace")
            except Exception:
                raise RuntimeError(f"download falhou: {e}")


def extract_channels_and_programmes(xml_text):
    """Parseia XML e retorna root, channels(list), programmes(list)."""
    # parse
    root = ET.fromstring(xml_text.encode("utf-8"))
    channels = root.findall("channel")
    programmes = root.findall("programme")
    return root, channels, programmes


def normalize(s):
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\u00C0-\u017F\s]", " ", s)  # mantem letras e acentos e numeros e espacos
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_brazilian_channel(channel_el, keywords, min_kw_matches=1):
    """
    Decide se um <channel> Element é "brasileiro" por heurística:
    - olha o id (attribute "id")
    - olha display-name(s)
    - conta quantas keywords aparecem (normalizadas)
    """
    cid = channel_el.get("id") or ""
    displays = [d.text or "" for d in channel_el.findall("display-name")]
    concat = " ".join([cid] + displays)
    s = normalize(concat)

    matches = 0
    for kw in keywords:
        kwn = normalize(kw)
        if not kwn:
            continue
        # match word boundary or substring (some ids like 'globo.sp' or 'globosp' need substring)
        if re.search(r"\b" + re.escape(kwn) + r"\b", s) or kwn in s:
            matches += 1
    return matches >= max(1, min_kw_matches)


def build_filtered_epg(xml_text, keywords, min_kw_matches=1):
    """
    Constrói um novo root XML apenas com canais/programas brasileiros.
    Retorna bytes (utf-8) do XML resultante.
    """
    root = ET.fromstring(xml_text.encode("utf-8"))
    # coletar canais BR
    channels = root.findall("channel")
    br_ids = []
    for ch in channels:
        if is_brazilian_channel(ch, keywords, min_kw_matches):
            cid = ch.get("id")
            if cid:
                br_ids.append(cid)

    print(f"Channels found in source: {len(channels)}. Brazilian channels matched: {len(br_ids)}")

    # criar novo tv root
    tv = ET.Element("tv", {
        "source-info-name": "epg-filter-br",
        "generator-info-name": "build_epg_br.py"
    })

    # adicionar apenas canais filtrados (com seus display-name)
    for ch in channels:
        cid = ch.get("id")
        if not cid or cid not in br_ids:
            continue
        newch = ET.SubElement(tv, "channel", {"id": cid})
        for dn in ch.findall("display-name"):
            dn_el = ET.SubElement(newch, "display-name")
            dn_el.text = dn.text

        # copiar icon/other tags if present
        for icon in ch.findall("icon"):
            ic = ET.SubElement(newch, "icon")
            for k,v in icon.attrib.items():
                ic.set(k, v)

    # adicionar programas com channel attr em br_ids
    progs = root.findall("programme")
    count_prog = 0
    for p in progs:
        ch = p.get("channel")
        if ch and ch in br_ids:
            # append programme (clone)
            prog = ET.SubElement(tv, "programme", dict(p.attrib))
            for child in list(p):
                # copiar elementos filhos (title, desc, category etc)
                el = ET.SubElement(prog, child.tag)
                el.text = child.text
                # se houver atributos em child, copie-os
                for k,v in child.attrib.items():
                    el.set(k, v)
            count_prog += 1

    print(f"Programmes copied: {count_prog}")

    return pretty_xml(tv)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epg-url", default="https://epg.brtwo.fyi/epg.xml",
                   help="URL ou caminho local do EPG fonte (default: https://epg.brtwo.fyi/epg.xml)")
    p.add_argument("--out", default="epg_br.xml", help="Arquivo de saida")
    p.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS),
                   help="Lista de palavras-chave separadas por virgula para identificar canais BR")
    p.add_argument("--min-kw-matches", type=int, default=1,
                   help="Numero minimo de keywords que devem aparecer para considerar canal BR (default 1)")
    p.add_argument("--use-curl", action="store_true", help="Forcar uso de curl para baixar")
    p.add_argument("--preview", type=int, default=0, help="Se >0, mostra N canais detectados e sai (nao grava)")
    args = p.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    print(f"Using keywords: {keywords[:10]}{'...' if len(keywords)>10 else ''}  min_matches={args.min_kw_matches}")

    try:
        text = download_text(args.epg_url, use_curl=args.use_curl)
    except Exception as e:
        print(f"Erro ao baixar/ler EPG fonte: {e}")
        sys.exit(2)

    # teste parse rápido
    try:
        root, channels, programmes = None, None, None
        root, channels, programmes = (None, None, None)
        parsed_root = ET.fromstring(text.encode("utf-8"))
        channels = parsed_root.findall("channel")
    except Exception as e:
        print("Erro ao parsear XML fonte:", e)
        # exibir inicio do arquivo para debug (limitado)
        print("Snippet (first 1000 chars):")
        print(text[:1000])
        sys.exit(2)

    # identificar quais canais o script considera BR
    br_list = []
    for ch in channels:
        if is_brazilian_channel(ch, keywords, args.min_kw_matches):
            br_list.append((ch.get("id"), " / ".join([dn.text or "" for dn in ch.findall("display-name")])))
    print(f"Detected {len(br_list)} Brazilian channels (heuristic).")

    if args.preview > 0:
        print("--- preview of matched channels ---")
        for cid, name in br_list[:args.preview]:
            print(f"{cid} -> {name}")
        sys.exit(0)

    # construir epg filtrado
    try:
        out_bytes = build_filtered_epg(text, keywords, args.min_kw_matches)
    except Exception as e:
        print("Erro ao construir EPG filtrado:", e)
        sys.exit(2)

    # gravar em disco
    try:
        with open(args.out, "wb") as f:
            f.write(out_bytes)
        print(f"EPG brasileiro gerado com sucesso: {args.out}")
    except Exception as e:
        print("Erro ao escrever arquivo de saida:", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
