# Análise Completa do Problema - Cálculo de CMPA

## O VERDADEIRO PROBLEMA

Você identificou perfeitamente a sequência correta:

1. **PDF** → quantidade final de cada ativo (posição em 31/12/2025)
2. **Negociação** → compras/vendas
3. **Movimentação** → eventos corporativos
4. **CMPA** = custo total / quantidade final

Porém, o arquivo de **Negociação está incompleto**:

### Dados Disponíveis Atual

```
PDF (31/12/2025): 8 ativos
├─ AGRO3: 100 ações
├─ ITSA4: 122,40 ações
├─ KLBN3: 222,2 ações
├─ KLBN4: 222,2 ações
├─ SOJA3: 209,72 ações
├─ TTEN3: 100 ações
├─ UNIP3: 33 ações
└─ ROXO34: 36 BDR

Negociação (13 transações):
├─ 8 compras (11 quantidade)
├─ 5 vendas (2 quantidade)
└─ Data: 08/2022 a 12/2025 APENAS

Movimentação (190 registros):
├─ Apenas dividendos, JCP, rendimento
├─ Sem eventos corporativos dos 8 ativos do PDF
└─ Mostra posição histórica, não eventos
```

## POR QUE FALTAM DADOS?

Comparando as quantidades acumuladas vs PDF:

```
Ticker    Acumulado  PDF        Diferença    Causa Provável
──────────────────────────────────────────────────────────
SOJA3     200        209,72     +9,72        Bonificação/Desdobro (falta registrar)
KLBN3     200        222,2      +22,2        Idem
KLBN4     200        222,2      +22,2        Idem
UNIP3     30         33         +3           Idem
ITSA4     100        122,4      +22,4        Idem
ROXO34    0          36         +36          Nenhuma compra registrada!
```

Além disso, faltam **compras anteriores a 08/2022** que explicariam as posições do AGRO3, TTEN3, etc.

## SOLUÇÕES DISPONÍVEIS

### Solução 1: USAR IRPF ANTERIOR (RECOMENDADA) ✅

Se você tem o IRPF de 2025 (referente a 2024), use como base:

**Dados do IRPF anterior que você tem:**
- CYRE3: 58 ações, Custo Médio R$ 23,23
- EMBJ3: 25 ações, Custo Médio R$ 46,58
- ITUB4: 37,08 ações, Custo Médio R$ 29,99
- VIVT3: 21 ações, Custo Médio R$ 50,07
- AXIA6: 27 ações, Custo Médio R$ 37,50
- AXIA7: 7,09 ações, Custo Médio R$ 33,07

**Processo:**
1. Carregue o IRPF 2025 (posição em 31/12/2024)
2. Aplique compras/vendas/eventos de 2025
3. Recalcule CMPA automaticamente

**Vantagem:** Dados já validados e corretos

### Solução 2: EXPORTAR NEGOCIAÇÃO COMPLETA

Exporte novo arquivo do portal B3/Santander com período **01/01/2019 até hoje**:

**Passos:**
1. Acesse portal da corretora/B3
2. Vá em Extrato → Negociações
3. Período: **01/01/2019 a 31/12/2025**
4. Exporte como Excel
5. Substitua arquivo `negociacao-2019 a 2025.xlsx`

**Problema:** Ainda pode faltar eventos corporativos

### Solução 3: DADOS MANUAIS (NÃO RECOMENDADO)

Integre os 6 ativos da análise que você fez + eventos corporativos

**Problema:** Não escala, trabalhoso, propenso a erros

---

## RECOMENDAÇÃO FINAL

**Opção 1 + Opção 2:**

1. **Agora:** Use IRPF anterior como base (Solução 1)
   - Carga CMPA correto para 2024
   - Aplica transações 2025
   - Resultado pronto

2. **Depois:** Exporte Negociação completa (Solução 2)
   - Valida dados históricos completos
   - Sirve como backup para futuro

---

## CÓDIGO CRIADO

### Novos Arquivos

1. **`parsers/cmpa_from_pdf.py`**
   - Calcula CMPA a partir de PDF + negociações + movimentação
   - Detecta discrepâncias

2. **`parsers/pdf_positions_extractor.py`**
   - Extrai posições do PDF consolidado

3. **`parsers/cmpa_with_irpf_base.py`** ← USE ESTE
   - Usa IRPF anterior como base
   - Aplica transações 2025
   - Mais confiável

### Próximos Passos (para você implementar)

```python
# No app.py, adicionar suporte para:

1. Upload de IRPF anterior (opcional)
2. Se IRPF anterior fornecido:
   - Ler posições iniciais
   - Aplicar transações do ano
   - Calcular novo CMPA
3. Senão:
   - Ler PDF
   - Calcular com dados disponíveis
   - Avisar sobre discrepâncias
```

---

## VERIFICAÇÃO NECESSÁRIA

Você tem os arquivos IRPF de 2024 ou 2023?

Se sim, mande localização para:
- Implementar suporte a upload de IRPF anterior
- Validar com dados que você já fez manualmente

Se não:
- Exporte Negociação completa (2019-2025) do portal
- Envie para atualizar os arquivos
