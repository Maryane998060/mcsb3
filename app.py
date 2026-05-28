"""
IRPF Renda Variável B3 — versão Flask com SQLAlchemy
"""

import os
import uuid
import json
import tempfile
from datetime import date
from io import BytesIO
from decimal import Decimal
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_file, send_from_directory, jsonify,
)

from parsers.excel_parser import parse_negociacao_sheet, parse_movimentacao_sheet
from parsers.pdf_parser import parse_informe_pdf
from parsers.cmpa_calculator import calculate_positions
from parsers.income_calculator import calculate_income, aggregate_by_ir_type, detect_year_from_movements
from parsers.cmpa_advanced import CalculadoraCMPA
from parsers.tax_calculator import CalculadoraIR

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'irpf-b3-flask-secret-dev')

# Armazenamento em memória dos relatórios processados (chaveado por UUID)
_report_store: dict = {}

ALLOWED_EXCEL = {'xlsx', 'xls'}
ALLOWED_PDF   = {'pdf'}


def _allowed(filename: str, extensions: set) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in extensions


# ── Rotas ──────────────────────────────────────────────────────────────────────

@app.route('/templates/css/<path:filename>')
def serve_template_css(filename):
    css_dir = os.path.join(os.path.dirname(__file__), 'templates', 'css')
    return send_from_directory(css_dir, filename, mimetype='text/css')


@app.route('/', methods=['GET'])
def upload():
    current_year = date.today().year
    return render_template('upload.html', current_year=current_year)


@app.route('/process', methods=['POST'])
def process():
    errors = []

    client_name = request.form.get('client_name', '').strip() or 'Contribuinte'
    cpf         = request.form.get('cpf', '').strip()         or '000.000.000-00'
    year_str    = request.form.get('year', '').strip()
    try:
        year = int(year_str)
    except ValueError:
        year = date.today().year - 1

    negociacao_file  = request.files.get('negociacao')
    movimentacao_file = request.files.get('movimentacao')
    informe_file     = request.files.get('informe')

    if not movimentacao_file or not movimentacao_file.filename:
        return render_template('upload.html', error='O arquivo de Movimentação é obrigatório.')

    # Salva arquivos em diretório temporário
    tmpdir = tempfile.mkdtemp()

    transactions = []
    movements    = []
    pdf_summary  = None

    try:
        # Movimentação (obrigatório)
        mov_path = os.path.join(tmpdir, 'movimentacao.xlsx')
        movimentacao_file.save(mov_path)
        movements = parse_movimentacao_sheet(mov_path)

        # Negociação (opcional)
        if negociacao_file and negociacao_file.filename and _allowed(negociacao_file.filename, ALLOWED_EXCEL):
            neg_path = os.path.join(tmpdir, 'negociacao.xlsx')
            negociacao_file.save(neg_path)
            transactions = parse_negociacao_sheet(neg_path)

        # Informe de Rendimentos PDF (opcional)
        if informe_file and informe_file.filename and _allowed(informe_file.filename, ALLOWED_PDF):
            pdf_path = os.path.join(tmpdir, 'informe.pdf')
            informe_file.save(pdf_path)
            pdf_summary = parse_informe_pdf(pdf_path)

    except Exception as e:
        return render_template('upload.html', error=f'Erro ao processar arquivos: {e}')
    finally:
        # Limpa arquivos temporários
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Calcula posições e CMPA
    result = calculate_positions(transactions, movements)
    assets           = result['assets']
    sales            = result['sales']
    corporate_events = result['corporate_events']
    operations       = result['operations']
    audit_log        = result['audit_log']
    validation_issues = result['validation_issues']

    # Detecta ano dos proventos e calcula renda
    detected_year = detect_year_from_movements(movements, year)
    income_events = calculate_income(movements, detected_year)
    aggregated    = aggregate_by_ir_type(income_events)

    # Distribui proventos nos ativos
    income_map: dict = {}
    for ev in income_events:
        bucket = income_map.setdefault(ev['ticker'], {'dividends': 0.0, 'jcp': 0.0, 'fii_income': 0.0})
        if ev['ir_type'] == 9:
            bucket['dividends']  += ev['value']
        elif ev['ir_type'] == 10:
            bucket['jcp']        += ev['value']
        elif ev['ir_type'] == 26:
            bucket['fii_income'] += ev['value']

    for asset in assets:
        bucket = income_map.get(asset['ticker'])
        if bucket:
            asset['dividends']  = round(bucket['dividends'],  2)
            asset['jcp']        = round(bucket['jcp'],        2)
            asset['fii_income'] = round(bucket['fii_income'], 2)
        asset['discriminacao'] = _build_discriminacao(asset)

    # Validações cruzadas com PDF
    if pdf_summary:
        tax9  = aggregated['tax9']
        tax10 = aggregated['tax10']
        tax26 = aggregated['tax26']
        if pdf_summary.get('dividendos') and abs(pdf_summary['dividendos'] - tax9) > 0.5:
            validation_issues.append({
                'level':   'warning',
                'message': f"Total de dividendos do PDF (R${pdf_summary['dividendos']:.2f}) difere do calculado (R${tax9:.2f}).",
            })
        if pdf_summary.get('jcp') and abs(pdf_summary['jcp'] - tax10) > 0.5:
            validation_issues.append({
                'level':   'warning',
                'message': f"Total de JCP do PDF (R${pdf_summary['jcp']:.2f}) difere do calculado (R${tax10:.2f}).",
            })
        if pdf_summary.get('rendimento_fii') and abs(pdf_summary['rendimento_fii'] - tax26) > 0.5:
            validation_issues.append({
                'level':   'warning',
                'message': f"Total de rendimento FII do PDF (R${pdf_summary['rendimento_fii']:.2f}) difere do calculado (R${tax26:.2f}).",
            })
        for note in pdf_summary.get('notes', []):
            validation_issues.append({'level': 'warning', 'message': note})

    total_assets_cost = sum(a['total_cost'] for a in assets)
    total_gain  = sum(s['gain'] for s in sales if s['gain'] > 0)
    total_loss  = sum(s['gain'] for s in sales if s['gain'] < 0)

    # Agrupa vendas por mês para o relatório
    monthly_sales: dict = {}
    for s in sales:
        parts = s['date'].split('/')
        if len(parts) == 3:
            key = f"{parts[1]}/{parts[2]}"
            bucket = monthly_sales.setdefault(key, {'gain': 0.0, 'loss': 0.0, 'net': 0.0, 'count': 0})
            if s['gain'] >= 0:
                bucket['gain'] += s['gain']
            else:
                bucket['loss'] += s['gain']
            bucket['net']   += s['gain']
            bucket['count'] += 1

    report = {
        'client_name':       client_name,
        'cpf':               cpf,
        'year':              year,
        'detected_year':     detected_year,
        'assets':            assets,
        'income_events':     income_events,
        'sales':             sales,
        'monthly_sales':     monthly_sales,
        'corporate_events':  corporate_events,
        'operations':        operations,
        'audit_log':         audit_log,
        'validation_issues': validation_issues,
        'pdf_summary':       pdf_summary,
        'summary': {
            'total_assets_cost': round(total_assets_cost, 2),
            'total_income':      aggregated['total'],
            'tax9':              aggregated['tax9'],
            'tax10':             aggregated['tax10'],
            'tax26':             aggregated['tax26'],
            'total_gain':        round(total_gain, 2),
            'total_loss':        round(total_loss, 2),
            'net_gain':          round(total_gain + total_loss, 2),
        },
        'diagnostics': {
            'negociacao_rows':  len(transactions),
            'movimentacao_rows': len(movements),
            'assets_found':     len(assets),
            'income_found':     len(income_events),
        },
    }

    report_id = str(uuid.uuid4())
    _report_store[report_id] = report
    session['report_id'] = report_id
    return redirect(url_for('report'))


@app.route('/report')
def report():
    report_id = session.get('report_id')
    if not report_id or report_id not in _report_store:
        return redirect(url_for('upload'))
    return render_template('report.html', r=_report_store[report_id])


@app.route('/export/excel')
def export_excel():
    report_id = session.get('report_id')
    if not report_id or report_id not in _report_store:
        return redirect(url_for('upload'))

    r = _report_store[report_id]
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    header_font  = Font(bold=True, color='FFFFFF')
    header_fill  = PatternFill('solid', fgColor='1e3a5f')
    center_align = Alignment(horizontal='center')

    def write_sheet(ws, title, headers, rows):
        ws.title = title
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font   = header_font
            cell.fill   = header_fill
            cell.alignment = center_align
        for row_idx, row in enumerate(rows, 2):
            for col_idx, val in enumerate(row, 1):
                ws.cell(row=row_idx, column=col_idx, value=val)
        for col in ws.columns:
            max_len = max((len(str(c.value or '')) for c in col), default=10)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 40)

    # Aba 1 — Bens & Direitos
    ws1 = wb.active
    write_sheet(ws1, 'Bens e Direitos', [
        'Ticker', 'Nome', 'Tipo', 'Código IRPF', 'Quantidade',
        'CMPA (R$)', 'Custo Total (R$)', 'Dividendos (R$)', 'JCP (R$)',
        'Rendimento FII (R$)', 'CNPJ Ativo', 'Corretora',
    ], [
        [
            a['ticker'], a['full_name'], a['type'], a['irpf_code'],
            a['quantity'], a['average_cost'], a['total_cost'],
            a['dividends'], a['jcp'], a['fii_income'],
            a.get('asset_cnpj', ''), a['institution'],
        ]
        for a in r['assets']
    ])

    # Aba 2 — Proventos
    ws2 = wb.create_sheet()
    write_sheet(ws2, 'Proventos', [
        'Data', 'Ticker', 'Tipo', 'Tipo IR', 'Quantidade', 'Preço Unit.', 'Valor (R$)',
    ], [
        [e['date'], e['ticker'], e['type'], e['ir_type'], e['quantity'], e['unit_price'], e['value']]
        for e in r['income_events']
    ])

    # Aba 3 — Vendas
    ws3 = wb.create_sheet()
    write_sheet(ws3, 'Lucro e Prejuízo', [
        'Data', 'Ticker', 'Quantidade', 'Preço Venda (R$)',
        'CMPA (R$)', 'Base de Custo (R$)', 'Ganho/Perda (R$)',
    ], [
        [s['date'], s['ticker'], s['quantity'], s['sale_price'],
         s['cmpa_at_sale'], s['cost_basis'], s['gain']]
        for s in r['sales']
    ])

    # Aba 4 — Eventos Corporativos
    ws4 = wb.create_sheet()
    write_sheet(ws4, 'Eventos Corporativos', [
        'Data', 'Ticker', 'Tipo', 'Descrição', 'Δ Quantidade',
    ], [
        [e['date'], e['ticker'], e['type'], e['details'], e['quantity_change']]
        for e in r['corporate_events']
    ])

    # Aba 5 — Operações
    ws5 = wb.create_sheet()
    write_sheet(ws5, 'Operações', [
        'Data', 'Ticker', 'Nome', 'Tipo', 'Quantidade',
        'Preço Unit.', 'Valor (R$)', 'Corretora', 'Nota',
    ], [
        [
            o['date'], o['ticker'], o.get('full_name', ''), o['type'],
            o['quantity'], o.get('unit_price', 0), o.get('value', 0),
            o.get('institution', ''), o.get('note', ''),
        ]
        for o in r['operations']
    ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"IRPF_B3_{r['client_name'].replace(' ', '_')}_{r['year']}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


# ─── Helper functions for reports ────────────────────────────────────────────────

def _fmt_qty(n: float) -> str:
    """Formata quantidade no padrão BR (vírgula decimal, sem zeros desnecessários)."""
    if n == int(n):
        return str(int(n))
    s = f"{n:.4f}".rstrip('0')
    return s.replace('.', ',')


def _fmt_brl(n: float) -> str:
    """Formata valor monetário no padrão BR: 1.234,56."""
    return f"{n:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _build_discriminacao(a: dict) -> str:
    """Monta discriminação no padrão Bens e Direitos IRPF."""
    unidade_map = {'FII': 'COTAS', 'ETF': 'COTAS', 'BDR': 'BDRs'}
    unidade     = unidade_map.get(a['type'], 'AÇÕES')
    ticker      = a['ticker']
    qty_str     = _fmt_qty(a['quantity'])
    cmpa_br     = _fmt_brl(a['average_cost'])
    total_br    = _fmt_brl(a['total_cost'])

    buy_events   = a.get('buy_events', [])
    bonus_events = a.get('bonus_events', [])

    # Monta parte da custódia
    custodia = ''
    if a.get('institution'):
        custodia = f"CUSTÓDIA NA {a['institution'].upper()}"
        if a.get('broker_cnpj'):
            custodia += f", CNPJ {a['broker_cnpj']}"

    if not bonus_events:
        # ── Caso simples: só compras, sem bonificação ──
        if not buy_events:
            datas_str = a.get('first_purchase_date', '')
        elif len(buy_events) == 1:
            datas_str = buy_events[0]['date']
        else:
            datas = list(dict.fromkeys(b['date'] for b in buy_events))
            datas_str = ', '.join(datas[:-1]) + ' E ' + datas[-1]

        texto = (
            f"{qty_str} {unidade} {ticker}, "
            f"ADQUIRIDAS EM {datas_str}, "
            f"COM O CUSTO MÉDIO DE R$ {cmpa_br}"
        )
        if custodia:
            texto += f", {custodia}"
        return texto + '.'

    # ── Caso complexo: compras + bonificações ──
    total_buy_qty  = sum(b['quantity']   for b in buy_events)
    total_buy_cost = sum(b['total_cost'] for b in buy_events)

    if len(buy_events) == 1:
        b = buy_events[0]
        compra_part = (
            f"SENDO {_fmt_qty(b['quantity'])} ADQUIRIDAS EM {b['date']} "
            f"PELO CUSTO TOTAL DE R$ {_fmt_brl(b['total_cost'])}"
        )
    else:
        datas = list(dict.fromkeys(b['date'] for b in buy_events))
        datas_str = ', '.join(datas[:-1]) + ' E ' + datas[-1]
        compra_part = (
            f"SENDO {_fmt_qty(total_buy_qty)} ADQUIRIDAS EM {datas_str} "
            f"PELO CUSTO TOTAL DE R$ {_fmt_brl(total_buy_cost)}"
        )

    bonus_parts = []
    for bns in bonus_events:
        ano = bns['date'].split('/')[-1] if '/' in bns['date'] else bns['date']
        bonus_parts.append(
            f"E {_fmt_qty(bns['quantity'])} RECEBIDAS EM BONIFICAÇÃO EM {ano} "
            f"AO CUSTO UNITÁRIO DE R$ {_fmt_brl(bns['unit_price'])} "
            f"(TOTAL R$ {_fmt_brl(bns['total_cost'])})"
        )

    texto = (
        f"{qty_str} {unidade} {ticker}, "
        f"{compra_part} "
        f"{' '.join(bonus_parts)}. "
        f"NOVO CUSTO MÉDIO UNITÁRIO: R$ {cmpa_br}. "
        f"CUSTO TOTAL DE AQUISIÇÃO: R$ {total_br}."
    )
    if custodia:
        texto += f" {custodia}."
    return texto


def _parse_date_to_datetime(date_str: str):
    """Converte string DD/MM/YYYY para date"""
    if not date_str:
        return None
    try:
        d, m, y = date_str.strip().split('/')
        return date(int(y), int(m), int(d))
    except:
        return None


@app.route('/new')
def new_report():
    session.pop('report_id', None)
    return redirect(url_for('upload'))


# ─── Rotas de Relatórios JSON ─────────────────────────────────────────────

@app.route('/api/client/report')
def api_relatorio_bens():
    """Relatório de Bens e Direitos (JSON)"""
    report_id = session.get('report_id')
    if not report_id or report_id not in _report_store:
        return jsonify({'error': 'Nenhum relatório encontrado'}), 404
    
    r = _report_store[report_id]
    
    ativos_formatados = []
    for a in r['assets']:
        ativos_formatados.append({
            'irpf_grupo':     a.get('irpf_grupo', '03'),
            'irpf_codigo':    a.get('irpf_codigo', '01'),
            'ticker':         a['ticker'],
            'cnpj_ativo':     a.get('asset_cnpj'),
            'cnpj_corretora': a.get('broker_cnpj'),
            'corretora':      a.get('institution'),
            'discriminacao':  _build_discriminacao(a),
            'negociado_bolsa': True,
            'data_aquisicao': a.get('first_purchase_date'),
            'quantidade':     a['quantity'],
            'cmpa':           a['average_cost'],
            'custo_total':    a['total_cost'],
        })
    
    return jsonify({
        'cliente': {'nome': r['client_name'], 'cpf': r['cpf'], 'ano_fiscal': r['year']},
        'data_geracao': date.today().isoformat(),
        'ativos': ativos_formatados,
        'total_custo': r['summary']['total_assets_cost'],
    })


@app.route('/api/client/report/proventos')
def api_relatorio_proventos():
    """Relatório de Proventos (JSON)"""
    report_id = session.get('report_id')
    if not report_id or report_id not in _report_store:
        return jsonify({'error': 'Nenhum relatório encontrado'}), 404
    
    r = _report_store[report_id]
    
    return jsonify({
        'cliente': {'nome': r['client_name'], 'cpf': r['cpf'], 'ano_fiscal': r['year']},
        'data_geracao': date.today().isoformat(),
        'dividendos_tipo9': r['summary']['tax9'],
        'jcp_tipo10': r['summary']['tax10'],
        'rendimento_fii_tipo26': r['summary']['tax26'],
        'total_proventos': r['summary']['total_income'],
    })


@app.route('/api/client/report/lucro-prejuizo')
def api_relatorio_lucro_prejuizo():
    """Relatório de Lucro/Prejuízo com cálculo de imposto"""
    report_id = session.get('report_id')
    if not report_id or report_id not in _report_store:
        return jsonify({'error': 'Nenhum relatório encontrado'}), 404
    
    r = _report_store[report_id]
    
    calc_ir = CalculadoraIR()
    
    for s in r['sales']:
        calc_ir.adicionar_venda(
            data=_parse_date_to_datetime(s['date']),
            ticker=s['ticker'],
            quantidade=Decimal(str(s['quantity'])),
            preco_compra=Decimal(str(s.get('cmpa_at_sale', 0))),
            preco_venda=Decimal(str(s['sale_price'])),
            custo_medio_aquisicao=Decimal(str(s.get('cmpa_at_sale', 0))),
            custos_operacionais=Decimal('0'),
        )
    
    resumo_anual = calc_ir.gerar_resumo_anual(r['year'])
    
    return jsonify({
        'cliente': {'nome': r['client_name'], 'cpf': r['cpf'], 'ano_fiscal': r['year']},
        'data_geracao': date.today().isoformat(),
        'total_lucro_bruto': float(resumo_anual['total_lucro_bruto']),
        'total_lucro_liquido': float(resumo_anual['total_lucro_liquido']),
        'total_imposto': float(resumo_anual['total_imposto']),
        'darf_necessario': resumo_anual['total_imposto'] > 0,
        'vendas_count': len(r['sales']),
    })


@app.route('/api/client/report/darf')
def api_relatorio_darf():
    """Relatório DARF (imposto de renda)"""
    report_id = session.get('report_id')
    if not report_id or report_id not in _report_store:
        return jsonify({'error': 'Nenhum relatório encontrado'}), 404
    
    r = _report_store[report_id]
    
    calc_ir = CalculadoraIR()
    
    for s in r['sales']:
        calc_ir.adicionar_venda(
            data=_parse_date_to_datetime(s['date']),
            ticker=s['ticker'],
            quantidade=Decimal(str(s['quantity'])),
            preco_compra=Decimal(str(s.get('cmpa_at_sale', 0))),
            preco_venda=Decimal(str(s['sale_price'])),
            custo_medio_aquisicao=Decimal(str(s.get('cmpa_at_sale', 0))),
            custos_operacionais=Decimal('0'),
        )
    
    darfs_gerados = calc_ir.gerar_darf_completo(r['year'])
    
    total_imposto = sum(Decimal(str(d['valor_imposto'])) for d in darfs_gerados)
    total_lucro = sum(Decimal(str(d['valor_lucro'])) for d in darfs_gerados)
    
    return jsonify({
        'cliente': {'nome': r['client_name'], 'cpf': r['cpf'], 'ano_fiscal': r['year']},
        'data_geracao': date.today().isoformat(),
        'ano': r['year'],
        'darfs': darfs_gerados,
        'total_imposto': float(total_imposto.quantize(Decimal('0.01'))),
        'total_lucro_tributavel': float(total_lucro.quantize(Decimal('0.01'))),
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port)
