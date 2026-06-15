{% extends "base.html" %}

{% block title %}Relatório de IRPF - B3{% endblock %}

{% block nav_extra %}
<a href="{{ url_for('export_excel') }}" class="btn btn-sm btn-success me-2">
    <i class="bi bi-file-earmark-excel me-1"></i>Exportar Excel
</a>
<button class="btn btn-sm btn-outline-light" onclick="window.print()">
    <i class="bi bi-printer me-1"></i>Imprimir / PDF
</button>
<a href="{{ url_for('upload') }}" class="btn btn-sm btn-outline-light">
    <i class="bi bi-arrow-left me-1"></i>Novo
</a>
{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="card shadow-sm mb-4">
        <div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">
            <h4 class="mb-0">Relatório de Renda Variável — Ano Calendário {{ r.year }}</h4>
            <span class="badge bg-light text-dark">Contribuinte: {{ r.client_name }} (CPF: {{ r.cpf }})</span>
        </div>
        <div class="card-body">
            <div class="row text-center">
                <div class="col-md-3 border-end">
                    <h6 class="text-muted">Custo Total em Posição</h6>
                    <h3 class="text-primary">R$ {{ r.summary.total_assets_cost }}</h3>
                </div>
                <div class="col-md-3 border-end">
                    <h6 class="text-muted">Total de Proventos</h6>
                    <h3 class="text-success">R$ {{ r.summary.total_income }}</h3>
                </div>
                <div class="col-md-3 border-end">
                    <h6 class="text-muted">Lucro Líquido no Ano</h6>
                    <h3 class="{% if r.summary.net_gain >= 0 %}text-success{% else %}text-danger{% endif %}">
                        R$ {{ r.summary.net_gain }}
                    </h3>
                </div>
                <div class="col-md-3">
                    <h6 class="text-muted">Ano Detectado (B3)</h6>
                    <h3 class="text-secondary">{{ r.detected_year }}</h3>
                </div>
            </div>
        </div>
    </div>

    {% if r.validation_issues %}
    <div class="alert alert-warning shadow-sm" role="alert">
        <h5 class="alert-heading"><i class="bi bi-exclamation-triangle-fill me-2"></i>Avisos e Inconsistências Detectadas:</h5>
        <ul class="mb-0">
            {% for issue in r.validation_issues %}
                <li>{{ issue.message }}</li>
            {% endfor %}
        </ul>
    </div>
    {% endif %}

    <div class="card shadow-sm mb-4">
        <div class="card-header bg-dark text-white">
            <h5 class="mb-0"><i class="bi bi-portfolio me-2"></i>Bens e Direitos (Posições em 31/12)</h5>
        </div>
        <div class="table-responsive">
            <table class="table table-hover table-striped mb-0 alignment-middle">
                <thead>
                    <tr>
                        <th>Ativo</th>
                        <th>Tipo</th>
                        <th>Qtd</th>
                        <th>CMPA</th>
                        <th>Custo Total</th>
                        <th>Discriminação para o Programa da Receita Federal</th>
                    </tr>
                </thead>
                <tbody>
                    {% for asset in r.assets %}
                    <tr>
                        <td><strong>{{ asset.ticker }}</strong><br><small class="text-muted">{{ asset.full_name }}</small></td>
                        <td><span class="badge bg-secondary">{{ asset.type }}</span></td>
                        <td>{{ asset.quantity }}</td>
                        <td>R$ {{ asset.average_cost }}</td>
                        <td>R$ {{ asset.total_cost }}</td>
                        <td><small class="text-dark bg-light p-1 d-block border rounded">{{ asset.discriminacao }}</small></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}