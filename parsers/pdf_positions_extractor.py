"""
Extrator de posições finais do PDF do relatório consolidado B3.
"""

import pdfplumber
from pathlib import Path
import re


def extract_positions_from_pdf_file(pdf_path: str) -> dict:
    """
    Extrai todas as posições do PDF do relatório consolidado.
    
    Retorna: {ticker: {quantidade: float, valor_atualizado: float, preco_atual: float}}
    """
    
    positions = {}
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() + "\n"
        
        lines = full_text.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Procura ticker no padrão TICKER - NOME
            if re.match(r'^[A-Z]{1,6}\d{1,2}\s*-', line):
                match = re.match(r'^([A-Z]{1,6}\d{1,2})\s*-\s*(.+)$', line)
                if match:
                    ticker = match.group(1)
                    
                    i += 1
                    if i < len(lines):
                        next_line = lines[i].strip()
                        # Procura: "TIPO QTD R$ PREÇO R$ VALOR"
                        qty_match = re.search(
                            r'(\d+[\.,]\d+|\d+)\s+R\$\s+([\d\.]+,\d+)\s+R\$\s+([\d\.]+,\d+)',
                            next_line
                        )
                        
                        if qty_match:
                            qty_str = qty_match.group(1).replace('.', '').replace(',', '.')
                            qty = float(qty_str)
                            
                            valor_str = qty_match.group(3).replace('.', '').replace(',', '.')
                            valor = float(valor_str)
                            
                            positions[ticker] = {
                                'quantidade': qty,
                                'valor_atualizado': valor,
                                'preco_atual': valor / qty if qty > 0 else 0
                            }
            i += 1
    
    except Exception as e:
        print(f"Erro ao extrair posições do PDF: {e}")
    
    return positions


if __name__ == '__main__':
    pdf_path = r'g:\Maryane\calculainvestimentoir\exemplos\relatorio-consolidado-anual-2025.pdf'
    
    positions = extract_positions_from_pdf_file(pdf_path)
    
    print(f"Posições extraídas: {len(positions)} ativos")
    print("="*80)
    
    for ticker, pos in sorted(positions.items()):
        print(f"{ticker:10} Qtd: {pos['quantidade']:10.2f}  Valor: R$ {pos['valor_atualizado']:12.2f}  Preço: R$ {pos['preco_atual']:8.2f}")
    
    print("="*80)
    print(f"Valor total: R$ {sum(p['valor_atualizado'] for p in positions.values()):,.2f}")
