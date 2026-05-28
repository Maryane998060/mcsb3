# IRPF Renda Variável B3 — Flask

Versão Flask do sistema de apuração de imposto de renda sobre renda variável (B3).  
Processa as planilhas exportadas do portal **investor.b3.com.br** e gera um relatório completo para preenchimento da Declaração de Ajuste Anual.

---

## Funcionalidades

- **Parsing de Negociação** — suporta os formatos antigo (8 colunas) e novo (9 colunas) da B3
- **Parsing de Movimentação** — classifica automaticamente compras, vendas, bonificações, desdobramentos, agrupamentos, leilões de frações, dividendos, JCP e rendimentos FII
- **Cálculo de CMPA** — custo médio ponderado por ativo com timeline cronológica completa
- **Deduplicação** — elimina entradas duplicadas entre Negociação e Movimentação
- **Proventos** — classifica por tipo fiscal (Tipo 9 / Tipo 10 / Tipo 26) e distribui por ativo
- **Parsing de PDF** — extrai totais de dividendos, JCP e rendimento FII do Informe de Rendimentos
- **Validação cruzada** — compara dados do PDF com os calculados e gera avisos de divergência
- **Exportação Excel** — planilha multi-abas com todas as seções do relatório
- **Impressão / PDF** — layout otimizado para impressão via `Ctrl+P` do navegador

---

## Estrutura

```
flaskversion/
├── app.py                    # Aplicação Flask (rotas e orquestração)
├── requirements.txt
├── README.md
├── parsers/
│   ├── excel_parser.py       # Leitura das planilhas Negociação e Movimentação
│   ├── pdf_parser.py         # Extração de texto do Informe de Rendimentos (PDF)
│   ├── cmpa_calculator.py    # Cálculo de CMPA, posições, vendas e eventos corporativos
│   └── income_calculator.py  # Classificação e agregação de proventos por tipo IR
└── templates/
    ├── base.html             # Layout base com navbar e tema claro/escuro
    ├── upload.html           # Página de upload com drag-and-drop
    └── report.html           # Relatório completo com abas e exportação
```

---

## Instalação e uso

```bash
# 1. Entre na pasta
cd flaskversion

# 2. Crie e ative um ambiente virtual (recomendado)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Inicie o servidor
python app.py
```

Acesse `http://localhost:5000` no navegador.

---

## Como obter os arquivos da B3

1. Acesse **investor.b3.com.br** e faça login com sua conta Gov.br.
2. Vá em **Extratos e Informativos → Movimentação** → selecione o período → exporte em Excel *(obrigatório)*.
3. Vá em **Extratos e Informativos → Negociação** → exporte em Excel *(opcional, melhora a precisão)*.
4. Baixe o **Informe de Rendimentos** em PDF da sua corretora *(opcional, usado para validação cruzada)*.

---

## Rotas

| Método | Rota             | Descrição                                  |
|--------|------------------|--------------------------------------------|
| GET    | `/`              | Página de upload                           |
| POST   | `/process`       | Processa arquivos e redireciona ao relatório |
| GET    | `/report`        | Exibe o relatório gerado                   |
| GET    | `/export/excel`  | Baixa o relatório em `.xlsx`               |
| GET    | `/new`           | Limpa a sessão e volta ao upload           |

---

## Dependências

| Pacote       | Uso                                      |
|--------------|------------------------------------------|
| `flask`      | Framework web                            |
| `openpyxl`   | Leitura e exportação de arquivos Excel   |
| `pdfplumber` | Extração de texto de PDFs                |
