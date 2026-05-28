# Projeto Original — IRPF Renda Variável B3 (React + TypeScript)

Aplicação web para apuração de imposto de renda sobre renda variável da B3 (bolsa de valores brasileira). O usuário faz upload das planilhas exportadas do portal **investor.b3.com.br** e recebe um relatório completo para preenchimento da Declaração de Ajuste Anual (DAA/IRPF).

---

## Stack

- **Frontend:** React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui
- **Backend:** Express (Node.js) — apenas health check; toda a lógica roda no browser
- **Parsing:** `xlsx` (Excel) e `pdfjs-dist` (PDF) — executados no cliente
- **Exportação:** `jsPDF` (PDF) e `xlsx` (Excel)
- **Monorepo:** pnpm workspaces

---

## Entradas aceitas

| Arquivo | Obrigatoriedade | Descrição |
|---|---|---|
| `Negociação.xlsx` | Opcional | Compras e vendas do home broker (investor.b3.com.br → Extratos → Negociação) |
| `Movimentação.xlsx` | Obrigatório | Todos os eventos: compras, vendas, proventos, eventos corporativos (investor.b3.com.br → Extratos → Movimentação) |
| `Informe.pdf` | Opcional | Informe de Rendimentos da corretora — usado apenas para validação cruzada |

---

## Lógica principal

### 1. Parsing Excel
- Detecção automática de cabeçalho (normaliza acentos para comparação)
- Suporte ao formato antigo (8 colunas) e novo (9 colunas) da B3
- Normalização de ticker (remove sufixo `F` de ações fracionárias, ex: `VALE3F` → `VALE3`)
- Extração de CNPJ embutido no nome do ativo/corretora

### 2. Cálculo de CMPA (Custo Médio Ponderado de Aquisição)
- Timeline cronológica unificando Negociação e Movimentação
- Deduplicação automática: entradas de compra/venda que aparecem nos dois arquivos são contabilizadas uma única vez
- Eventos corporativos alteram o CMPA sem gerar custo:
  - **Bonificação** — adiciona cotas a custo zero, dilui CMPA
  - **Desdobramento** — multiplica cotas, reduz CMPA proporcionalmente
  - **Agrupamento** — reduz cotas, aumenta CMPA proporcionalmente
  - **Leilão de Frações** — crédito com preço entra como compra; débito gera venda

### 3. Proventos
- Classifica por tipo fiscal:
  - **Tipo 9** — Dividendos
  - **Tipo 10** — JCP (Juros sobre Capital Próprio)
  - **Tipo 26** — Rendimento de FII (tickers terminados em `11` ou `12`)
- Detecta automaticamente o ano-base dos proventos nos dados (ignora o campo digitado pelo usuário se houver divergência)

### 4. Validação cruzada com PDF
- Compara totais extraídos do Informe de Rendimentos (PDF) com os calculados a partir da Movimentação
- Gera avisos (`ValidationIssue`) se houver divergência acima de R$ 0,50

---

## Saídas geradas

- **Bens & Direitos** — posições em carteira com ticker, tipo (Ação/FII/BDR/ETF), código IRPF (31/52/73/36), quantidade, CMPA e custo total
- **Proventos** — eventos de dividendo/JCP/rendimento por ticker e tipo IR
- **Lucro & Prejuízo** — vendas com base de custo, ganho/perda e resumo mensal para cálculo de DARF
- **Eventos Corporativos** — registro de bonificações, desdobramentos e agrupamentos
- **Log de Auditoria** — eventos suspeitos ou ignorados com justificativa

Exportação disponível em PDF (jsPDF) e Excel (xlsx).

---

## Fluxo da aplicação

```
/ (UploadPage)
  → formulário: nome, CPF, ano-base + 3 zonas de upload
  → POST → /processing (ProcessingPage)
  → pipeline assíncrono com barra de progresso
  → /report (ReportPage) — abas: Bens, Proventos, L&P, Corporativos
```

Estado global via React Context + sessionStorage (persiste entre navegações sem recarregar).
