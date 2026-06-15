"""
Parser de Notas de Corretagem — Padrao SINACOR (B3)
====================================================
Le PDFs de notas de corretagem de qualquer corretora que siga o padrao
SINACOR (Toro, XP, Inter, NuInvest, Clear, etc.).

Retorna resumo de taxas por ticker para ser mesclado ao calculo de CMPA.
"""

import re
import unicodedata
from typing import List, Dict, Any, Union, BinaryIO
from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# Utilitarios
# ─────────────────────────────────────────────────────────────────────────────

def _parse_br(value: str) -> float:
    """Converte numero BR (1.234,56 ou 1234,56) para float."""
    s = str(value or '').strip()
    # Remove pontos de milhar e converte virgula decimal
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _norm_text(s: str) -> str:
    """Normaliza texto: minusculo, sem acento, trata encoding corrompido."""
    result = str(s or '')
    # Remove acentos via NFD
    result = unicodedata.normalize('NFD', result)
    result = ''.join(c for c in result if not unicodedata.combining(c))
    return result.lower()


def _extract_ticker_from_spec(spec: str, name_to_ticker: Dict[str, str] = None) -> str:
    """
    Extrai o ticker B3 de uma especificacao de ativo da nota SINACOR.

    Estrategia:
    1. Busca padrao direto de ticker (ex: ROXO34, KLBN11) na spec
    2. Usa mapa nome->ticker das planilhas B3 (se fornecido)
    3. Usa dicionario embutido de nomes comuns de acoes brasileiras
    """
    spec_upper = spec.upper().strip()

    # 1. Padrao direto: 4-5 letras + 1-2 digitos
    m = re.search(r'\b([A-Z]{4,5}\d{1,2}[FT]?)\b', spec_upper)
    if m:
        t = m.group(1)
        if t.endswith('F') and len(t) > 5:
            t = t[:-1]
        return t

    # 2. Mapa fornecido via planilhas B3
    if name_to_ticker:
        if spec_upper in name_to_ticker:
            return name_to_ticker[spec_upper]
        for nome, ticker in name_to_ticker.items():
            nome_words = nome.upper().split()
            if len(nome_words) >= 2 and all(w in spec_upper for w in nome_words[:2]):
                return ticker

    # 3. Dicionario embutido de nomes frequentes em notas de corretagem
    _KNOWN = {
        'PETROBRAS PN':    'PETR4',
        'PETROBRAS ON':    'PETR3',
        'VALE ON':         'VALE3',
        'ITAU UNIBANCO PN': 'ITUB4',
        'ITAU UNIBANCO ON': 'ITUB3',
        'BRADESCO PN':     'BBDC4',
        'BRADESCO ON':     'BBDC3',
        'BANCO DO BRASIL ON': 'BBAS3',
        'AMBEV ON':        'ABEV3',
        'WEG ON':          'WEGE3',
        'TAESA UNT':       'TAEE11',
        'ENGIE BRASIL ON': 'EGIE3',
        'ITAUSA PN':       'ITSA4',
        'ITAUSA ON':       'ITSA3',
        'SANEPAR UNT':     'SAPR11',
        'KLABIN UNT':      'KLBN11',
        'GERDAU PN':       'GGBR4',
        'GERDAU ON':       'GGBR3',
        'HAPVIDA ON':      'HAPV3',
        'MAGAZINE LUIZA ON': 'MGLU3',
        'LOJAS RENNER ON': 'LREN3',
        'LOCALIZA ON':     'RENT3',
        'TOTVS ON':        'TOTS3',
        'FLEURY ON':       'FLRY3',
        'TEGMA ON':        'TGMA3',
        'USIMINAS PNA':    'USIM5',
        'SUZANO ON':       'SUZB3',
        'COPEL UNT':       'CPLE11',
        'ENERGIAS BR ON':  'ENBR3',
        'B3 SA ON':        'B3SA3',
        'CEMIG PN':        'CMIG4',
        'CEMIG ON':        'CMIG3',
        'TELEFONICA BRASIL ON': 'VIVT3',
        'EMBRAER ON':      'EMBR3',
        'JBS ON':          'JBSS3',
        'MARFRIG ON':      'MRFG3',
        'CSN ON':          'CSNA3',
        'TRANSMISSAO PAULISTA ON': 'TRPL4',
        'COSAN ON':        'CSAN3',
    }

    # Busca por substring nos nomes conhecidos
    spec_norm = spec_upper.replace(' ON ', ' ').replace(' PN ', ' ').replace(' UNT ', ' ')
    for nome, ticker in _KNOWN.items():
        nome_key = nome.upper().split()[0]  # primeira palavra
        if nome_key in spec_upper and len(nome_key) > 3:
            # Verifica se o tipo (ON/PN) bate
            nome_tipo = ''
            if ' PN' in nome.upper(): nome_tipo = 'PN'
            elif ' ON' in nome.upper(): nome_tipo = 'ON'
            elif ' UNT' in nome.upper(): nome_tipo = 'UNT'

            if not nome_tipo or nome_tipo in spec_upper:
                return ticker

    return ''


def _extract_date(line: str) -> str:
    """Extrai data DD/MM/YYYY de uma linha."""
    m = re.search(r'(\d{2}/\d{2}/\d{4})', line)
    return m.group(1) if m else ''


def _extract_lines_from_page(page) -> List[str]:
    """
    Reconstroi linhas completas usando as coordenadas das palavras.
    O extract_text do pdfplumber pode cortar linhas — extract_words nao corta.
    """
    try:
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
        if not words:
            return [l.strip() for l in (page.extract_text() or '').splitlines() if l.strip()]

        # Agrupa por top (posicao vertical) com granularidade de 2px
        bucket: dict = defaultdict(list)
        for w in words:
            y_key = int(float(w['top']) // 2) * 2
            bucket[y_key].append((float(w['x0']), w['text']))

        lines = []
        for y in sorted(bucket.keys()):
            row = sorted(bucket[y], key=lambda x: x[0])
            line = ' '.join(t for _, t in row).strip()
            if line:
                lines.append(line)
        return lines
    except Exception:
        return [l.strip() for l in (page.extract_text() or '').splitlines() if l.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Parser de linha de negocio SINACOR
# ─────────────────────────────────────────────────────────────────────────────

def _build_name_to_ticker(transactions: List[Dict]) -> Dict[str, str]:
    """
    Constroi um mapa {nome_descricao: ticker} a partir das transacoes da B3.
    Ex: {'PETROBRAS PN': 'PETR4', 'WEG ON': 'WEGE3'}
    """
    mapping: Dict[str, str] = {}
    for t in transactions:
        ticker    = t.get('normalized_ticker') or t.get('ticker', '')
        full_name = t.get('full_name') or t.get('spec', '')
        if ticker and full_name:
            # Normaliza o nome
            key = full_name.upper().strip()
            if key and ticker not in mapping.values():
                mapping[key] = ticker
            # Tambem adiciona o inicio do nome (ate 2-3 palavras)
            words = key.split()
            if len(words) >= 2:
                short_key = ' '.join(words[:2])
                if short_key not in mapping:
                    mapping[short_key] = ticker
    return mapping


def _parse_negocio(line: str, name_to_ticker: Dict[str, str] = None) -> Dict[str, Any]:
    """
    Extrai dados de uma linha de negocio no padrao SINACOR.
    Formato: B3 RV LISTADCO MERCADO ESPECIFICACAO QUANTIDADE PRECO VALOR DC
    Exemplo: B3 RV LISTADCO FRACIONARIO PETROBRAS PN N2 5 31,020000 155,10 D
    """
    # Ancoras fixas do padrao SINACOR:
    # - PRECO tem SEMPRE 6 casas decimais (ex: 31,020000)
    # - VALOR tem SEMPRE 2 casas decimais (ex: 155,10)
    # - D/C no final (D=debito=compra, C=credito=venda)

    p = re.compile(
        r'(FRACION\w+|VISTA|TERMO)\s+'    # tipo de mercado
        r'(.+?)\s+'                        # especificacao do ativo (lazy)
        r'(\d+(?:[.,]\d+)?)\s+'           # quantidade
        r'(\d+[,]\d{6})\s+'               # preco com 6 decimais
        r'(\d[\d.]*[,]\d{2})'             # valor com 2 decimais
        r'(?:\s+([DC]))?',                 # D/C opcional
        re.IGNORECASE
    )

    m = p.search(line)
    if not m:
        return {}

    mercado, spec, qty_s, preco_s, valor_s, dc = m.groups()

    ticker = _extract_ticker_from_spec(spec, name_to_ticker)
    if not ticker:
        return {}

    # Inferir D/C se nao capturado
    if not dc:
        last = line.rstrip()[-1].upper()
        dc = last if last in ('D', 'C') else 'D'

    # No SINACOR: D = debito = compra; C = credito = venda
    tipo = 'C' if dc.upper() == 'D' else 'V'

    return {
        'ticker':       ticker,
        'tipo':         tipo,
        'mercado':      mercado.upper(),
        'spec':         spec.strip(),
        'quantidade':   _parse_br(qty_s),
        'preco':        _parse_br(preco_s),
        'valor':        _parse_br(valor_s),
        'taxa_rateada': 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Parser de pagina de nota
# ─────────────────────────────────────────────────────────────────────────────

def _parse_page(lines: List[str], name_to_ticker: Dict[str, str] = None) -> Dict[str, Any]:
    """Parseia uma lista de linhas de uma pagina de nota SINACOR."""

    # Verificacao rapida: deve conter "nota de corretagem"
    head = ' '.join(lines[:6])
    if 'nota de corretagem' not in _norm_text(head):
        return {}

    nota: Dict[str, Any] = {
        'data_pregao':      '',
        'corretora':        '',
        'negocios':         [],
        'emolumentos':      0.0,
        'taxa_liquidacao':  0.0,
        'corretagem':       0.0,
        'taxas_total':      0.0,
    }

    in_negocios = False

    for line in lines:
        n = _norm_text(line)

        # Data do pregao: linha "NUMERO FOLHA DD/MM/YYYY"
        if not nota['data_pregao']:
            d = _extract_date(line)
            if d and re.match(r'^\d+\s+\d+\s+\d{2}/\d{2}/\d{4}', line):
                nota['data_pregao'] = d

        # Corretora: primeira linha longa com "corretora" ou "ccvm" ou "dtvm"
        if not nota['corretora']:
            if any(k in n for k in ('corretora', 'ccvm', 'dtvm', 'valores mobiliarios')):
                if len(line) > 15 and not any(k in n for k in ('cnpj', 'tel', 'internet', 'rua', 'ouvidoria')):
                    nota['corretora'] = line[:60].strip()

        # Inicio da secao de negocios
        if 'negocios realizados' in n or re.search(r'neg.cios\s+realizados', n):
            in_negocios = True
            continue

        # Fim da secao de negocios
        if in_negocios and ('resumo dos neg' in n or 'resumo financeiro' in n):
            in_negocios = False

        # Linhas de negocio comecam com "B3"
        if in_negocios and re.match(r'^B3\s+', line, re.IGNORECASE):
            neg = _parse_negocio(line, name_to_ticker)
            if neg:
                nota['negocios'].append(neg)

        # Emolumentos — linha: "Emolumentos 0,02 D"
        if re.match(r'^emolumento', n):
            m = re.search(r'(\d[\d.]*,\d{2})', line)
            if m:
                v = _parse_br(m.group(1))
                if v > 0:
                    nota['emolumentos'] = v

        # Taxa de liquidacao — linha: "Compras a vista 558,00 Taxa de liquidacao/CCP 0,13 D"
        # O valor da taxa e o ULTIMO numero da linha, nao o primeiro
        if re.search(r'taxa\s+de\s+liquid', n):
            # Pega TODOS os numeros da linha e usa o ultimo (que e a taxa)
            nums = re.findall(r'(\d[\d.]*,\d{2})', line)
            if nums:
                v = _parse_br(nums[-1])  # ultimo valor = taxa
                if v > 0 and nota['taxa_liquidacao'] == 0:
                    nota['taxa_liquidacao'] = v

        # Corretagem — linha: "Corretagem 0,00 D" ou "Total 0,00 D"
        # Aparece na secao "Corretagem / Despesas"
        if re.match(r'^corretagem', n) and not re.search(r'despesa', n):
            m = re.search(r'(\d[\d.]*,\d{2})', line)
            if m:
                v = _parse_br(m.group(1))
                if v > 0:
                    nota['corretagem'] = v

    nota['taxas_total'] = round(
        nota['emolumentos'] + nota['taxa_liquidacao'] + nota['corretagem'], 4
    )

    # Rateia taxas proporcionalmente entre compras
    compras = [n for n in nota['negocios'] if n['tipo'] == 'C']
    total_compras = sum(c['valor'] for c in compras)

    if total_compras > 0 and nota['taxas_total'] > 0:
        for neg in nota['negocios']:
            if neg['tipo'] == 'C':
                neg['taxa_rateada'] = round(nota['taxas_total'] * neg['valor'] / total_compras, 4)

    return nota if nota['negocios'] else {}


# ─────────────────────────────────────────────────────────────────────────────
# Funcao publica principal
# ─────────────────────────────────────────────────────────────────────────────

def parse_notas_corretagem(
    file_path: Union[str, BinaryIO],
    transactions: List[Dict] = None,
) -> Dict[str, Any]:
    """
    Le um PDF de notas de corretagem (SINACOR) e retorna resumo de taxas.

    transactions: lista de transacoes da B3 (opcional) — usada para resolver
                  nomes de ativos que nao tem ticker explicito na nota.
    """
    try:
        import pdfplumber
    except ImportError:
        return {'notas': [], 'resumo_por_ticker': {}, 'total_taxas': 0.0,
                'erros': ['pdfplumber nao instalado.']}

    # Constroi mapa nome→ticker se tiver planilha de negociacoes
    name_to_ticker = _build_name_to_ticker(transactions or [])

    notas: List[Dict] = []
    erros: List[str]  = []

    try:
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                lines = _extract_lines_from_page(page)
                if not lines:
                    continue
                head = ' '.join(lines[:6])
                if 'nota de corretagem' not in _norm_text(head):
                    continue
                nota = _parse_page(lines, name_to_ticker)
                if nota:
                    notas.append(nota)
                else:
                    erros.append(f'Pagina {i+1}: nota sem negocios reconhecidos.')
    except Exception as e:
        return {'notas': [], 'resumo_por_ticker': {}, 'total_taxas': 0.0,
                'erros': [f'Erro ao ler PDF: {e}']}

    # Consolida por ticker
    resumo: Dict[str, Any] = {}
    for nota in notas:
        for neg in nota['negocios']:
            t = neg['ticker']
            if t not in resumo:
                resumo[t] = {'compras': 0.0, 'vendas': 0.0, 'taxas': 0.0, 'operacoes': []}
            if neg['tipo'] == 'C':
                resumo[t]['compras'] = round(resumo[t]['compras'] + neg['valor'], 2)
            else:
                resumo[t]['vendas']  = round(resumo[t]['vendas']  + neg['valor'], 2)
            resumo[t]['taxas'] = round(resumo[t]['taxas'] + neg['taxa_rateada'], 4)
            resumo[t]['operacoes'].append({
                'data':         nota['data_pregao'],
                'tipo':         neg['tipo'],
                'quantidade':   neg['quantidade'],
                'preco':        neg['preco'],
                'valor':        neg['valor'],
                'taxa_rateada': neg['taxa_rateada'],
                'corretora':    nota['corretora'],
            })

    total_taxas = round(sum(n['taxas_total'] for n in notas), 2)

    return {
        'notas':             notas,
        'resumo_por_ticker': resumo,
        'total_taxas':       total_taxas,
        'erros':             erros,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Merge com posicoes calculadas pelo motor B3
# ─────────────────────────────────────────────────────────────────────────────

def merge_taxas_nas_posicoes(assets: List[Dict], resumo_notas: Dict) -> List[Dict]:
    """
    Adiciona as taxas das notas de corretagem ao custo de cada ativo.
    Nao altera a logica de calculo — apenas soma os centavos das taxas.
    """
    for asset in assets:
        dados = resumo_notas.get(asset['ticker'])
        if dados and dados['taxas'] > 0:
            taxas = round(dados['taxas'], 2)
            asset['taxas_corretagem']      = taxas
            asset['total_cost_ajustado']   = round(asset['total_cost'] + taxas, 2)
            asset['average_cost_ajustado'] = round(
                asset['total_cost_ajustado'] / asset['quantity'], 4
            ) if asset['quantity'] > 0 else 0.0
        else:
            asset['taxas_corretagem']      = 0.0
            asset['total_cost_ajustado']   = asset['total_cost']
            asset['average_cost_ajustado'] = asset['average_cost']
    return assets
