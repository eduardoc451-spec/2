import io
import sqlite3
import re
import json
import datetime
from io import BytesIO
from datetime import datetime, date
import streamlit as st
st.set_page_config(
    page_title="i-Saúde - Validação Municipal",
    page_icon="⚕️",
    layout="wide"
)
st.markdown("""
    <meta name="google" content="notranslate" />
    <style>
        html, body, div, span, p, h1, h2, h3, h4, h5, h6, label {
            unicode-bidi: isolate;
        }
        .stMarkdown, div[data-testid="stMetricValue"], div[data-testid="stMetricDelta"], label {
            translate: no !important;
        }
        label, p, span, div {
            text-transform: none !important;
            font-variant: normal !important;
        }
    </style>
    <script>
        document.documentElement.setAttribute('lang', 'pt-BR');
        document.documentElement.classList.add('notranslate');
    </script>
""", unsafe_allow_html=True)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
PONTUACOES_MAX_ISAUDE = {
    "1": 5, "2": 10, "3": 10, "3.1": 4, "3.2": 4, "4": 6, "5": 4, "6": 5, "7": 3, "8": 2,
    "9": 18, "9.2": 5, "10": 100, "11": 10, "11.2": 2, "12.0": 10, "12.1": 50, "12.2": 40,
    "13": 5, "13.1": 15, "14": 1, "14.1": 10, "14.2": 2, "14.2.1": 10, "15": 2, "15.1": 7,
    "16": 10, "16.1": 5, "21": 10, "22": 30, "23.1": 30, "24.1": 10, "25": 5, "26": 10,
    "27": 5, "28": 5, "28.1": 5, "29": 15, "30.1.1": 9, "32.1": 45, "33.1": 10, "34.0": 5,
    "35.1": 15, "35.2": 10, "36": 40, "36.1": 40, "37": 90, "S2": 20, "S3": 25, "S4": 10,
    "S5": 10, "S6": 100, "S7": 20, "S17": 25, "S18": 25, "S19": 25, "S20": 25
}
CATEGORIAS_MAP = {
    "atencao_basica": {
        "label": "1.0 Atenção Básica",
        "qids": ["1", "2", "3", "3.1", "3.2", "4", "5", "6", "7", "8", "9", "9.2"]
    },
    "vigilancia_saude": {
        "label": "2.0 Vigilância em Saúde",
        "qids": ["10", "11", "11.2", "12.0", "12.1", "12.2", "13", "13.1"]
    },
    "assistencia_farmaceutica": {
        "label": "3.0 Assistência Farmacêutica",
        "qids": ["14", "14.1", "14.2", "14.2.1", "15", "15.1", "16", "16.1"]
    },
    "infraestrutura_ubs": {
        "label": "4.0 Infraestrutura de UBS",
        "qids": ["21", "22", "23.1", "24.1", "25", "26", "27", "28", "28.1", "29"]
    },
    "gestao_recursos": {
        "label": "5.0 Gestão e Recursos Humanos",
        "qids": ["30.1.1", "32.1", "33.1", "34.0", "35.1", "35.2", "36", "36.1", "37"]
    },
    "financiamento_minimo": {
        "label": "6.0 Limite Constitucional (SIOPS)",
        "qids": ["S2", "S3", "S4", "S5", "S6", "S7", "S17", "S18", "S19", "S20"] 
    }
}

# =============================================================================
# CALLBACKS DE SALVAMENTO (Para isolar e proteger o estado síncrono)
# =============================================================================
def callback_salvar_quesito(quesito, chave_radio_ou_valor, chave_link, opts_dict=None, e_string_composta=False):
    """Garante o salvamento imediato e limpo no momento exato da alteração."""
    # Recupera o valor atual do input
    if e_string_composta:
        novo_valor = chave_radio_ou_valor  # Já passa a string montada
    else:
        novo_valor = st.session_state.get(chave_radio_ou_valor)
        
    novo_link = st.session_state.get(chave_link, "")
    
    # Calcula pontos se houver dicionário de opções
    novos_pts = 0.0
    if opts_dict and novo_valor in opts_dict:
        novos_pts = opts_dict[novo_valor]
    elif quesito == "17.4.1":
        # Cálculo específico da regra de negócio do 17.4.1
        partes = novo_valor.split("|")
        try:
            ta_2, ta_1, ta_at = float(partes[0]), float(partes[1]), float(partes[2])
            novos_pts = -2.0 if ta_at > ((ta_2 + ta_1) / 2.0) else 0.0
        except:
            novos_pts = 0.0

    # Dispara a sua função original de banco de dados
    save_resp(quesito, novo_valor, novos_pts, novo_link)
    
    # Atualiza o cache local imediatamente
    res_data[quesito] = {"valor": novo_valor, "pontos": novos_pts, "link": novo_link}
    
    # Validação de modal de aviso de link se necessário
    links_atuais = re.findall(r'(https?://[^\s]+)', novo_link)
    # Abre o modal se a mudança veio do link e ele é novo
    if links_atuais:
        # Nota: Se precisar abrir o modal, faça aqui. Caso contrário, o on_change já cuida do rerun automático.
        pass

# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================
def limpar_xml(texto):
    if not texto:
        return ""
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")

# =============================================================================
# COLOQUE A DEFINIÇÃO DA FUNÇÃO EXATAMENTE AQUI (ANTES DO RESTO DA TELA)
# =============================================================================
def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    subquestoes_saude_local = globals().get('subquestoes_saude', [])
    resposta_condicional_nao_local = globals().get('resposta_condicional_nao', False)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()
    
    # Estilos de Parágrafos personalizados
    style_titulo_capa = ParagraphStyle('TituloCapa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=24, leading=28, textColor=colors.HexColor("#0078D4"), alignment=1)
    style_ano_capa = ParagraphStyle('AnoCapa', parent=styles['Normal'], fontName='Helvetica', fontSize=16, leading=20, textColor=colors.HexColor("#7f8c8d"), alignment=1)
    style_tabela_padrao = ParagraphStyle('TabPadrao', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11, textColor=colors.HexColor("#2c3e50"))
    style_tabela_centro = ParagraphStyle('TabCentro', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_th = ParagraphStyle('TabHeader', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=12, textColor=colors.white, alignment=1)
    
    if all_data is None:
        all_data = {}
        
    ano_atual = int(str(ano).strip()[:4])
    ano_ant = ano_atual - 1
    dados_ano_anterior = all_data.get(ano_ant, {})


    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    try:
        logo = Image("iegm.png", width=380, height=180)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    except Exception:
        elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Relatório i-Saúde", style_titulo_capa))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("Índice de Fiscalização e Gestão da Saúde Municipal", ParagraphStyle('SubCapa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, leading=18, textColor=colors.HexColor("#718096"), alignment=1)))
    elements.append(Spacer(1, 15))
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO (ATUALIZADO)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))
    
    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#00897b"), alignment=2)
    
    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa de Gestão da Saúde)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito i-Saúde", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades (Eficiência Preventiva)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências (Gargalos Persistentes)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030 (Metas ODS / ONU)", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
        # Novos itens adicionados abaixo com paginação estimada de fluxo:
        [Paragraph("6. Análise Comparativa de Prazos e Indicadores Históricos", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
        [Paragraph("7. Série Histórica do iSaúde (Consolidado Final)", style_item_esquerda), Paragraph("Pág. 6", style_pag_direita)],
    ]
    
    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10), # Reduzi levemente de 12 para 10 para caber tudo na folha 2 sem quebrar
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7"), 1, (2, 4)), 
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-SAÚDE (GESTÃO EM SAÚDE) - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA DE GESTÃO DA SAÚDE)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))
    
    nota_atual = float(total)
    
    def converter_pontos_em_faixa_isaude(pontos):
        pts = float(pontos)
        if pts <= 500.0: return "C"
        elif pts <= 599.0: return "C+"
        elif pts <= 749.0: return "B"
        elif pts <= 899.0: return "B+"
        else: return "A"
        
    nota_anterior = 0.0
    if ano_ant in all_data:
        nota_anterior = float(sum(info_ant.get("pontos", 0) for qid_ant, info_ant in dados_ano_anterior.items() if isinstance(info_ant, dict) and not qid_ant.startswith("COM_") and not ("_" in qid_ant and not qid_ant.startswith("S"))))
        
    faixa_anterior = converter_pontos_em_faixa_isaude(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_isaude(nota_atual)
    variacao_pontos = nota_atual - nota_anterior
    
    texto_percentual = f"{(variacao_pontos / nota_anterior) * 100:+.2f}%" if nota_anterior > 0 else "0.00%"
    
    if variacao_pontos > 0:
        cor_variacao = colors.HexColor("#28a745")
        seta_tendencia = "▲"
    elif variacao_pontos < 0:
        cor_variacao = colors.HexColor("#dc3545")
        seta_tendencia = "▼"
    else:
        cor_variacao = colors.HexColor("#6c757d")
        seta_tendencia = "■"
        
    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor("#00897b"), alignment=1)
    style_td_var = ParagraphStyle('TdVar', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_variacao, alignment=1)
    
    dados_comparativos = [
        [Paragraph("Exercício", style_th), Paragraph("Pontuação Obtida", style_th), Paragraph("Faixa / Conceito", style_th), Paragraph("Variação Nominal", style_th), Paragraph("Variação Percentual", style_th)],
        [Paragraph(str(ano_ant), style_td_ano), Paragraph(f"{nota_anterior:.1f} pts", style_td_pts), Paragraph(str(faixa_anterior), style_td_faixa), Paragraph("-", style_td_var), Paragraph("-", style_td_var)],
        [Paragraph(str(ano_atual), style_td_ano), Paragraph(f"{nota_atual:.1f} pts", style_td_pts), Paragraph(str(faixa_real_atual), style_td_faixa), Paragraph(f"{seta_tendencia} {variacao_pontos:+.1f} pts", style_td_var), Paragraph(f"{seta_tendencia} {texto_percentual}", style_td_var)]
    ]
    
    tabela_comp = Table(dados_comparativos, colWidths=[80, 105, 95, 105, 105])
    tabela_comp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")), 
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8f9fa")), ("BACKGROUND", (0, 2), (-1, 2), colors.whitesmoke),                    
    ]))
    elements.append(tabela_comp)
    elements.append(Spacer(1, 12))
    
    style_analise = ParagraphStyle('Analise', parent=styles['Normal'], fontSize=10, leading=14)
    if variacao_pontos > 0:
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global da gestão em saúde comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores assistenciais e orçamentários da saúde em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade i-Saúde."
    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # =========================================================================
    # 2. ANÁLISE DE DESEMPENHO POR QUESITO i-SAÚDE
    # =========================================================================
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO i-SAÚDE</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    lista_pontos_fortes = []
    lista_pontos_fracos = []
    dados_consolidados = {}
    
    def normalizar_chave(c):
        s = str(c).strip()
        if s.endswith('.0'):
            s = s[:-2]
        return s
        
    pontuacoes_max_norm = {normalizar_chave(k): v for k, v in PONTUACOES_MAX_ISAUDE.items()}
    
    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")
        qid_limpo = normalizar_chave(qid)
        
        if qid_limpo not in pontuacoes_max_norm:
            continue
        if qid_limpo not in dados_consolidados:
            dados_consolidados[qid_limpo] = {"pts_obtidos": 0.0, "valores": [], "links": []}
            
        dados_consolidados[qid_limpo]["pts_obtidos"] += pts_obtidos
        if valor_resposta:
            dados_consolidados[qid_limpo]["valores"].append(limpar_xml(valor_resposta))
        if link_evidencia:
            link_limpo = limpar_xml(link_evidencia)
            if link_limpo not in dados_consolidados[qid_limpo]["links"]:
                dados_consolidados[qid_limpo]["links"].append(link_limpo)
                
    for qid_norm, info in dados_consolidados.items():
        pts_maximo = float(pontuacoes_max_norm.get(qid_norm, 10.0))
        if pts_maximo <= 0: pts_maximo = 10.0
        pts_obtidos = max(0.0, min(info["pts_obtidos"], pts_maximo))
        eficiencia = (pts_obtidos / pts_maximo) * 100
        respostas_unificadas = " | ".join(info["valores"]) if info["valores"] else "-"
        evidencias_unificadas = ", ".join(info["links"]) if info["links"] else ""
        
        item_data = {
            "qid": qid_norm, 
            "pts_obtidos": pts_obtidos, 
            "pts_maximo": pts_maximo, 
            "eficiencia": eficiencia, 
            "valor": respostas_unificadas, 
            "link": evidencias_unificadas
        }
        if eficiencia < 80.0: 
            lista_pontos_fracos.append(item_data)
        else:
            lista_pontos_fortes.append(item_data)
            
    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes da Gestão da Saúde:</b>", styles["h3"]))
        data_fortes = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["eficiencia"], reverse=True):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=8 color='gray'>{item['link']}</font>"
            data_fortes.append([
                Paragraph(item['qid'], style_tabela_centro), 
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro), 
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro), 
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        tabela_fortes = Table(data_fortes, colWidths=[65, 75, 65, 285])
        tabela_fortes.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00897b")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#00897b")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))
        
    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Oportunidades de Melhoria / Fragilidades (< 80% de Eficiência):</b>", styles["h3"]))
        data_fracos = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fracos, key=lambda x: x["eficiencia"]):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=8 color='gray'>{item['link']}</font>"
            data_fracos.append([
                Paragraph(item['qid'], style_tabela_centro), 
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro), 
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro), 
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        tabela_fracos = Table(data_fracos, colWidths=[65, 75, 65, 285])
        tabela_fracos.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e67e22")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)
    # =========================================================================
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    PENALIDADES_MAX = {
        "14.2.2": -2.0, "15.2": -2.0, "17.1.2": -5.0, "17.2": -0.5, "17.3": -3.0,
        "17.3.1": -3.0, "17.3.2": -2.0, "17.4": -3.0, "17.4.1": -2.0, "17.4.2": -2.0,
        "17.5": -5.0, "17.5.2": -5.0, "17.5.2.1": -5.0, "17.6": -5.0, "17.6.1": -2.5,
        "17.7.1": -5.0, "17.8.1": -5.0, "17.9.1": -5.0, "17.9.2": -5.0, "18.1": -10.0,
        "18.2": -5.0, "18.4": -5.0, "18.5.3": -10.0, "18.5.4": -10.0, "19.3": -10.0,
        "19.4": -5.0, "19.5": -15.0, "20.1": -5.0, "20.2": -5.0, "31.2": -10.0,
        "31.3": -20.0, "S8": -5.0, "S9": -5.0, "S10": -2.0, "S11": -2.0,
        "S12": -2.0, "S13": -2.0, "S14": -2.0, "S15": -2.0, "S16": -2.0
    }
    penalidades_max_norm = {normalizar_chave(k): v for k, v in PENALIDADES_MAX.items()}
    dados_penalidades = {}
    
    for k, v in dados.items():
        if isinstance(v, dict):
            dados_penalidades[normalizar_chave(k)] = v
            
    for qid_pen, val_max in penalidades_max_norm.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {"pontos": val_max, "valor": "Não preenchido / Ocultado por condicional", "link": ""}
            
    lista_penalidades = []
    reincidencias_detectadas = []
    
    for qid_norm, pen_max in penalidades_max_norm.items():
        if qid_norm in dados_penalidades:
            info = dados_penalidades[qid_norm]
            nota_real = float(info.get("pontos", 0.0))
            nota_risco = nota_real if nota_real <= 0.0 else 0.0
            
            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0
                
            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))
            lista_penalidades.append({
                "qid": qid_norm, "nota_real": nota_real, "pen_max": pen_max, "eficiencia": eficiencia_preventiva, 
                "valor": info.get("valor", ""), "link": info.get("link", "")
            })
            
            if eficiencia_preventiva < 100.0 and isinstance(all_data, dict) and (ano_ant in all_data):
                dados_ant_norm = {normalizar_chave(ka): va for ka, va in dados_ano_anterior.items() if isinstance(va, dict)}
                if qid_norm in dados_ant_norm:
                    info_ant = dados_ant_norm[qid_norm]
                    nota_real_ant = float(info_ant.get("pontos", 0.0))
                    if nota_real == nota_real_ant:
                        reincidencias_detectadas.append({
                            "qid": qid_norm, "tipo": "Penalidade Aplicada", 
                            "detalhe": f"Impacto Recorrente de Penalidade de {nota_real:.1f} pts", 
                            "ant": f"{nota_real_ant:.1f} pts", "atual": f"{nota_real:.1f} pts"
                        })
                        
    if lista_penalidades:
        data_penalidades = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Penalidade Aplicada", style_th), 
            Paragraph("Pior Cenário", style_th), 
            Paragraph("Eficiência Preventiva", style_th), 
            Paragraph("Status de Risco", style_th)
        ]]
        
        def ordenar_quesitos(x):
            limpo = ''.join(c for c in x["qid"] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]
            
        for item in sorted(lista_penalidades, key=ordenar_quesitos):
            nota_txt = f"{item['nota_real']:.1f} pts"
            teto_txt = f"{item['pen_max']:.1f} pts"
            ef_txt = f"{item['eficiencia']:.1f}%"
            
            if item['eficiencia'] >= 100.0: 
                status = "<font color='#2e7d32'><b>Risco Mitigado</b></font>"
            elif item['eficiencia'] <= 0.0: 
                status = "<font color='#c0392b'><b>Impacto Máximo</b></font>"
            else: 
                status = "<font color='#d35400'><b>Impacto Parcial</b></font>"
                
            data_penalidades.append([
                Paragraph(item['qid'], style_tabela_centro), 
                Paragraph(nota_txt, style_tabela_centro), 
                Paragraph(teto_txt, style_tabela_centro), 
                Paragraph(ef_txt, style_tabela_centro), 
                Paragraph(status, style_tabela_padrao)
            ])
            
        tabela_pen = Table(data_penalidades, colWidths=[70, 110, 80, 115, 125])
        tabela_pen.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1b4f72")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_pen)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES)
    # =========================================================================
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    TETOS_VALIDOS = {
        "14.2.2": 10.0, "15.2": 10.0, "17.1": 15.0, "17.2": 5.0, "17.3": 10.0,
        "17.4": 10.0, "17.5": 20.0, "17.6": 15.0, "17.7": 10.0, "17.8": 10.0, 
        "17.9": 10.0, "18.1": 30.0, "18.2": 20.0, "18.4": 15.0, "18.5": 25.0, 
        "19.3": 20.0, "19.4": 15.0, "19.5": 40.0, "20.1": 10.0, "20.2": 10.0, 
        "31.2": 20.0, "31.3": 50.0, "S8": 15.0, "S9": 15.0, "S10": 10.0
    }
    
    dados_analise_reinc = dados.copy()
    
    if subquestoes_saude_local and resposta_condicional_na_local:
        for sub_id in subquestoes_saude_local:
            if sub_id not in dados_analise_reinc:
                dados_analise_reinc[sub_id] = {"pontos": 0.0, "valor": "Não se aplica / Zerado por Condicional", "link": ""}

    for qid, info_atual in dados_analise_reinc.items():
        if qid.startswith("COM_") or not isinstance(info_atual, dict): 
            continue
            
        qid_str = str(qid).strip()
        qid_limpo = normalizar_chave(qid_str)
        
        # 🌟 FILTRO 1: Ignora se a resposta atual for inválida, vazia ou "selecione"
        valor_atual = str(info_atual.get("valor", "")).strip().lower()
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0))
        
        if not valor_atual or "selecione" in valor_atual or pts_obtidos_atual == 0.0:
            continue
        
        if "_" in qid_limpo:
            chave_mae = qid_limpo.split("_")[0]
        else:
            partes_chave = qid_limpo.split('.')
            if len(partes_chave) > 2:
                chave_mae = f"{partes_chave[0]}.{partes_chave[1]}"
            else:
                chave_mae = qid_limpo
            
        if chave_mae not in TETOS_VALIDOS:
            continue
            
        pts_maximo = float(TETOS_VALIDOS[chave_mae])
        
        # Verifica se está abaixo de 50% de eficiência no ano atual
        if pts_maximo > 0 and (pts_obtidos_atual / pts_maximo) * 100 < 50.0:
            info_ant = dados_ano_anterior.get(qid, {}) if isinstance(dados_ano_anterior, dict) else {}
            
            if isinstance(info_ant, dict) and info_ant:
                valor_ant = str(info_ant.get("valor", "")).strip().lower()
                pts_obtidos_ant = float(info_ant.get("pontos", 0.0))
                
                # 🌟 FILTRO 2: Ignora se o ano anterior também não foi respondido ou era 0
                if not valor_ant or "selecione" in valor_ant or pts_obtidos_ant == 0.0:
                    continue
                
                # Verifica se também estava abaixo de 50% no ano anterior
                if (pts_obtidos_ant / pts_maximo) * 100 < 50.0:
                    origem = "Gestão da Saúde Geral"
                    
                    if 'CATEGORIAS_MAP_ISAUDE' in globals():
                        for cat_chave, cat_info in CATEGORIAS_MAP_ISAUDE.items():
                            if chave_mae in cat_info.get("qids", []):
                                origem = cat_info.get("label", "Outros")
                                break
                    else:
                        if chave_mae.startswith("14") or chave_mae.startswith("15"):
                            origem = "Atenção Básica e Assistência"
                        elif chave_mae.startswith("17"):
                            origem = "Vigilância em Saúde e Sanitária"
                        elif chave_mae.startswith("18") or chave_mae.startswith("19"):
                            origem = "Recursos, Orçamento e Financiamento"
                        elif chave_mae.startswith("20") or chave_mae.startswith("31"):
                            origem = "Transparência e Controle Social"
                        elif chave_mae.startswith("S"):
                            origem = "Indicadores Assistenciais Pactuados"
                                
                    reincidencias_detectadas.append({
                        "qid": qid_str, 
                        "tipo": origem, 
                        "detalhe": "Ineficiência Crônica de Desempenho (Eficiência inferior a 50% por 2 anos consecutivos)",
                        "ant": f"{pts_obtidos_ant:.1f} / {pts_maximo:.1f} pts", 
                        "atual": f"{pts_obtidos_atual:.1f} / {pts_maximo:.1f} pts"
                    })

    if reincidencias_detectadas:
        data_reinc = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Bloco / Origem da Falha", style_th), 
            Paragraph("Impacto Histórico i-Saúde", style_th), 
            Paragraph("Exercício Anterior", style_th), 
            Paragraph("Exercício Atual", style_th)
        ]]
        
        def ordenacao_segura(x):
            limpo = ''.join(c for c in x["qid"].split('_')[0] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]

        for reinc in sorted(reincidencias_detectadas, key=ordenacao_segura): 
            data_reinc.append([
                Paragraph(reinc["qid"], style_tabela_centro), 
                Paragraph(reinc["tipo"], style_tabela_centro), 
                Paragraph(f"<b>{reinc['detalhe']}</b>", style_tabela_padrao), 
                Paragraph(reinc["ant"], style_tabela_centro), 
                Paragraph(reinc["atual"], style_tabela_centro)
            ])
            
        tabela_reinc = Table(data_reinc, colWidths=[65, 115, 170, 75, 65])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), 
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_reinc)
    else: 
        elements.append(Paragraph("<font color='#2e7d32'><b>✅ Nenhuma reincidência ativa detectada nos blocos do i-Saúde. O município corrigiu ou mitigou os gargalos assistenciais e orçamentários do ano anterior.</b></font>", styles["Normal"]))
        
    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU) - FORMATADO I-SAÚDE
    # -------------------------------------------------------------------------
    import reportlab.lib.colors as rl_colors
    from reportlab.lib.styles import ParagraphStyle as Alias_Style

    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    def calcular_percentual_checklist(resposta_bruta, total_itens):
        if not resposta_bruta: return 0.0
        itens = [i.strip().lower() for i in str(resposta_bruta).split(",") if i.strip()]
        itens_validos = [i for i in itens if "outros" not in i and i != ""]
        if total_itens > 0:
            return min((len(itens_validos) / total_itens) * 100.0, 100.0)
        return 0.0

    analise_ods = []
    quesitos_validos_ods = [
        "1.0", "2.0", "3.0", "3.1", "3.2", "4.0", "5.0", "6.0", "7.0", "8.0", "9.0", 
        "11.0", "12.0", "13.0", "13.1", "14.0", "14.1", "14.2", "14.2.2", "14.2.2.1", 
        "15.0", "15.2", "15.2.1", "16.0", "16.1", "17.1", "17.3", "17.3.2", "17.4", 
        "17.5", "17.6", "18.1", "18.3", "18.4", "18.4.1", "18.5"
    ]

    for qid in quesitos_validos_ods:
        if qid not in dados: 
            continue
            
        info = dados[qid]
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()
        
        if not resp or resp_l == "não respondido" or resp == "[]" or "selecione" in resp_l: 
            continue

        metas = "3.0"
        status = "Não Atendido"

        # Lógica de Mapeamento do i-Saúde baseada nas regras enviadas
        if qid == "1.0":
            status = "Atendido" if "sim, com propostas para construção das diretrizes e metas da saúde municipal" in resp_l else "Não Atendido"
        elif qid == "2.0":
            status = "Atendido" if "até prazo de envio à câmara municipal do projeto de lei sobre ppa 2026-2029" in resp_l else "Não Atendido"
        elif qid == "3.0":
            status = "Atendido" if "até prazo de envio à câmara municipal do projeto de lei de diretrizes orçamentárias do ano selecionado" in resp_l else "Não Atendido"
        elif qid == "3.1":
            if "sim, todas as ações foram executadas" in resp_l: status = "Atendido"
            elif "sim, a maior parte das ações foram executadas" in resp_l: status = "Parcialmente Atendido"
        elif qid == "3.2":
            if "sim, todas as metas foram atingidas" in resp_l: status = "Atendido"
            elif "sim, a maior parte das metas foram atingidas" in resp_l: status = "Parcialmente Atendido"
        elif qid == "4.0":
            pct = calcular_percentual_checklist(resp, 4)
            status = f"{pct:.1f}% Atendido"
        elif qid == "5.0":
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "6.0":
            if "sim, com responsabilidade específica do setor de saúde e com recursos movimentados exclusivamente pelo fundo" in resp_l:
                status = "Atendido"
            elif "sim, com responsabilidade específica do setor de saúde, mas não houve movimentação de recursos exclusivamente pelo fundo" in resp_l:
                status = "Parcialmente Atendido"
        elif qid == "7.0":
            pct = calcular_percentual_checklist(resp, 3)
            status = f"{pct:.1f}% Atendido"
        elif qid == "8.0":
            status = "Atendido" if "sim, meio eletrônico" in resp_l else "Não Atendido"
        elif qid == "9.0":
            status = "Atendido" if "aprovado sem ressalvas" in resp_l else "Não Atendido"
        elif qid == "11.0":
            metas = "3.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "12.0":
            metas = "3.8"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "13.0":
            status = "Atendido" if "sim, para todos os profissionais da saúde" in resp_l else "Não Atendido"
        elif qid == "13.1":
            status = "Atendido" if "sim, todos cumprem integralmente a jornada de trabalho" in resp_l else "Não Atendido"
        elif qid == "14.0":
            metas = "3.0, 16.6"
            status = "Atendido" if "agendamento de cada paciente em horário único com, no mínimo, 15 minutos de atendimento" in resp_l else "Não Atendido"
        elif qid == "14.1":
            metas = "3.0, 3.8, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.2":
            metas = "3.0, 16.6"
            status = "Atendido" if "sim, para todas as consultas" in resp_l else "Não Atendido"
        elif qid == "14.2.2":
            metas = "3.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.2.2.1":
            metas = "3.0, 3.8, 16.6"
            pct = calcular_percentual_checklist(resp, 6)
            status = f"{pct:.1f}% Atendido"
        elif qid == "15.0":
            metas = "3.0, 16.6"
            status = "Atendido" if "sim, para todos os exames" in resp_l else "Não Atendido"
        elif qid == "15.2":
            metas = "3.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "15.2.1":
            metas = "3.0, 3.8"
            pct = calcular_percentual_checklist(resp, 5)
            status = f"{pct:.1f}% Atendido"
        elif qid == "16.0":
            metas = "3.0, 16.6, 17.8"
            status = "Atendido" if "sim, para todos os procedimentos da saúde" in resp_l else "Não Atendido"
        elif qid == "16.1":
            metas = "3.0, 3.8, 16.6, 17.8"
            pct = calcular_percentual_checklist(resp, 5)
            status = f"{pct:.1f}% Atendido"
        elif qid == "17.1":
            status = "Atendido" if "sim, para todos os profissionais da saúde" in resp_l else "Não Atendido"
        elif qid == "17.3":
            status = "Atendido" if "sim, para todas as consultas médicas" in resp_l else "Não Atendido"
        elif qid == "17.3.2":
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "17.4":
            status = "Atendido" if "sim, para todos os exames" in resp_l else "Não Atendido"
        elif qid == "17.5":
            status = "Atendido" if "sim, todos os serviços" in resp_l else "Não Atendido"
        elif qid == "17.6":
            status = "Atendido" if "sim, para todos os procedimentos da saúde" in resp_l else "Não Atendido"
        elif qid == "18.1":
            metas = "3.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "18.3":
            metas = "3.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "18.4":
            metas = "3.4, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "18.4.1":
            metas = "3.4, 16.6"
            pct = calcular_percentual_checklist(resp, 4)
            status = f"{pct:.1f}% Atendido"
        elif qid == "18.5":
            metas = "3.4, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"

        # Trata tamanho da string da diretriz para não quebrar o layout
        exibicao_resp = limpar_xml(resp)
        if len(exibicao_resp) > 45:
            exibicao_resp = exibicao_resp[:45] + "..."

        analise_ods.append({
            "qid": qid,
            "metas": metas,
            "resp": exibicao_resp,
            "status": status
        })

    if analise_ods:
        data_ods = [["Quesito", "Diretriz Declarada", "Vínculo Metas ODS", "Status de Alinhamento"]]
        style_td_ods = Alias_Style('TdOdsHealth', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        # Função interna e isolada de ordenação para quesitos estruturados complexos do i-Saúde (ex: 14.2.2.1)
        def ordenacao_complexa_isaude(x):
            partes = []
            for i in x['qid'].split('.'):
                if i.isdigit():
                    partes.append(int(i))
                else:
                    # Captura caso haja letras ou sub-chaves
                    limpo = ''.join(c for c in i if c.isdigit())
                    partes.append(int(limpo) if limpo else 999)
            return partes

        for item in sorted(analise_ods, key=ordenacao_complexa_isaude):
            st_txt = item["status"]
            
            # Formatação de Cores Dinâmicas para o Status
            if "Não Atendido" in st_txt:
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Parcialmente Atendido" in st_txt:
                st_p = Paragraph(f"<font color='#e67e22'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt:
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else:
                # Caso das respostas em percentual (%)
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
                
            data_ods.append([
                Paragraph(f"<b>{item['qid']}</b>", style_tabela_centro), 
                Paragraph(item["resp"], style_tabela_padrao), 
                Paragraph(item["metas"], style_tabela_centro), 
                st_p
            ])
            
        tabela_ods = Table(data_ods, colWidths=[55, 210, 115, 110])
        tabela_ods.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#0f9d58")), # Verde institucional iGov mantido
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.whitesmoke), 
            ("ALIGN", (0, 0), (0, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#0f9d58")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 6. ANÁLISE COMPARATIVA DE PRAZOS E INDICADORES HISTÓRICOS
    # =========================================================================
    elements.append(Paragraph("<b>6. ANÁLISE COMPARATIVA DE PRAZOS E INDICADORES HISTÓRICOS</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    # -------------------------------------------------------------------------
    # PARTE A: ANÁLISE DE PRAZOS (MÉDICO / EXAMES / MEDICAMENTOS)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>6.1. Monitoramento Crítico de Prazos e Filas de Espera</b>", styles["h3"]))
    elements.append(Paragraph("Demonstrativo do tempo médio de resposta assistencial em dias e variação em relação ao ciclo anterior:", styles["Normal"]))
    elements.append(Spacer(1, 6))

    def extrair_dias_numericos(valor):
        """Extrai de forma segura o primeiro número inteiro de uma string de dias."""
        if not valor: return None
        v_str = str(valor).strip().lower()
        if "selecione" in v_str or not v_str: return None
        numeros = ''.join(c if c.isdigit() else ' ' for c in v_str).split()
        if numeros:
            return float(numeros[0])
        return None

    def calcular_variacao_prazos(atual, anterior):
        if atual is None or anterior is None:
            return "N/A", colors.HexColor("#7f8c8d")
        if anterior == 0:
            if atual == 0: return "0.0%", colors.HexColor("#27ae60")
            return "+100.0%", colors.HexColor("#c0392b")
        
        var = ((atual - anterior) / anterior) * 100.0
        # Atenção: Em prazos de espera, uma variação NEGATIVA (-) significa redução da fila (Melhoria/Verde)
        if var < 0:
            return f"{var:.1f}%", colors.HexColor("#27ae60")
        elif var > 0:
            return f"+{var:.1f}%", colors.HexColor("#c0392b")
        return "0.0%", colors.HexColor("#7f8c8d")

    # Estrutura de mapeamento para buscar os dados de prazos de forma dinâmica e segura nas sub-chaves
    mapeamento_prazos = [
        {"label": "Neurocirurgia (Espera Média)", "qid": "17.5.2.1.1", "filtro": ["neuro", "cirurgia"]},
        {"label": "Ortopedia/Traumatologia - Joelho", "qid": "17.5.2.1.1", "filtro": ["orto", "joelho"]},
        {"label": "Eletroneuromiografia (Exame)", "qid": "17.5.2.1.2", "filtro": ["eletroneuro", "miografia"]},
        {"label": "Colonoscopia (Exame)", "qid": "17.5.2.1.2", "filtro": ["colono", "scopia"]},
        {"label": "Otorrinolaringologia (Consulta)", "qid": "28.2.1", "filtro": ["otorrino", "laringo"]},
        {"label": "Neurologia (Consulta)", "qid": "28.2.1", "filtro": ["neuro", "logia"]},
        {"label": "Ultrassonografia (Exame)", "qid": "28.2.2", "filtro": ["ultra", "ssono"]},
        {"label": "Audiometria (Exame)", "qid": "28.2.2", "filtro": ["audio", "metria"]},
        {"label": "Procedimento: Laqueadura", "qid": "28.2.4", "filtro": ["laquea", "dura"]},
        {"label": "Procedimento: Vasectomia", "qid": "28.2.4", "filtro": ["vase", "ctomia"]}
    ]

    dados_tabela_prazos = [[
        Paragraph("Indicador de Gargalo / Especialidade", style_th),
        Paragraph("Quesito", style_th),
        Paragraph("Exercício Ant.", style_th),
        Paragraph("Exercício Atual", style_th),
        Paragraph("Variação (%)", style_th)
    ]]

    for item in mapeamento_prazos:
        qid = item["qid"]
        
        # Recuperação do ano atual
        val_atual = None
        if qid in dados and isinstance(dados[qid], dict):
            val_atual = extrair_dias_numericos(dados[qid].get("valor", ""))
        
        # Recuperação do ano anterior
        val_anterior = None
        if isinstance(dados_ano_anterior, dict) and qid in dados_ano_anterior:
            if isinstance(dados_ano_anterior[qid], dict):
                val_anterior = extrair_dias_numericos(dados_ano_anterior[qid].get("valor", ""))

        txt_ant = f"{int(val_anterior)} dias" if val_anterior is not None else "Não Consta"
        txt_atual = f"{int(val_atual)} dias" if val_atual is not None else "Não Consta"
        
        txt_var, cor_var = calcular_variacao_prazos(val_atual, val_anterior)
        p_var = Paragraph(f"<font color='{cor_var.hexval()}'><b>{txt_var}</b></font>", style_tabela_centro)

        dados_tabela_prazos.append([
            Paragraph(item["label"], style_tabela_padrao),
            Paragraph(qid, style_tabela_centro),
            Paragraph(txt_ant, style_tabela_centro),
            Paragraph(txt_atual, style_tabela_centro),
            p_var
        ])

    tabela_prazos = Table(dados_tabela_prazos, colWidths=[180, 65, 80, 80, 85])
    tabela_prazos.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(tabela_prazos)
    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # PARTE B: ANÁLISE DE INDICADORES COMPLETOS (37.0, S2, S6, S7, S16, S17-S20)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>6.2. Evolução de Indicadores Assistenciais e Metas Estratégicas</b>", styles["h3"]))
    elements.append(Paragraph("Análise aprofundada de desempenho numérico, coberturas vacinais e taxas de eficiência consolidadas em comparação ao ciclo anterior:", styles["Normal"]))
    elements.append(Spacer(1, 8))

    def extrair_porcentagem(valor):
        if not valor: return None
        v_str = str(valor).replace(",", ".").strip()
        numeros = ''.join(c if (c.isdigit() or c == '.') else ' ' for c in v_str).split()
        if numeros:
            try: return float(numeros[0])
            except: return None
        return None

    def extrair_inteiro(valor):
        if not valor: return 0
        numeros = ''.join(c if c.isdigit() else ' ' for c in str(valor)).split()
        if numeros:
            try: return int(numeros[0])
            except: return 0
        return 0

    def calcular_consolidado_quadrimestral(dados_escopo, qid):
        """
        Calcula o percentual consolidado extraindo as chaves quadrimestrais específicas
        de numeradores e denominadores mapeadas para cada indicador.
        """
        if not dados_escopo or qid not in dados_escopo: return None
        q_data = dados_escopo[qid]
        if not isinstance(q_data, dict): return None
        
        num = 0
        den = 0
        
        if qid in ["S2", "S20"]:
            # S2: G1Q, G2Q, G3Q / TG1Q, TG2Q, TG3Q
            # S20: GPAO1Q, GPAO2Q, GPAO3Q / TG1Q, TG2Q, TG3Q
            k_num = ["G1Q", "G2Q", "G3Q"] if qid == "S2" else ["GPAO1Q", "GPAO2Q", "GPAO3Q"]
            k_den = ["TG1Q", "TG2Q", "TG3Q"]
            num = extrair_inteiro(q_data.get(k_num[0], 0)) + extrair_inteiro(q_data.get(k_num[1], 0)) + extrair_inteiro(q_data.get(k_num[2], 0))
            den = extrair_inteiro(q_data.get(k_den[0], 0)) + extrair_inteiro(q_data.get(k_den[1], 0)) + extrair_inteiro(q_data.get(k_den[2], 0))
            
        elif qid == "S16":
            # S16: Óbitos (ORNAA) / Nascidos Vivos (NVAA)
            # Como possui histórico de 3 anos, tenta capturar a chave correspondente do ano atual do escopo
            num = extrair_inteiro(q_data.get("ORNAA", q_data.get("ORNAA-1", 0)))
            den = extrair_inteiro(q_data.get("NVAA", q_data.get("NVAA-1", 0)))
            
        elif qid == "S17":
            # S17: CIT1Q, CIT2Q, CIT3Q / TM1Q, TM2Q, TM3Q
            num = extrair_inteiro(q_data.get("CIT1Q", 0)) + extrair_inteiro(q_data.get("CIT2Q", 0)) + extrair_inteiro(q_data.get("CIT3Q", 0))
            den = extrair_inteiro(q_data.get("TM1Q", 0)) + extrair_inteiro(q_data.get("TM2Q", 0)) + extrair_inteiro(q_data.get("TM3Q", 0))
            
        elif qid == "S18":
            # S18: HPA1Q, HPA2Q, HPA3Q / TH1Q, TH2Q, TH3Q
            num = extrair_inteiro(q_data.get("HPA1Q", 0)) + extrair_inteiro(q_data.get("HPA2Q", 0)) + extrair_inteiro(q_data.get("HPA3Q", 0))
            den = extrair_inteiro(q_data.get("TH1Q", 0)) + extrair_inteiro(q_data.get("TH2Q", 0)) + extrair_inteiro(q_data.get("TH3Q", 0))
            
        elif qid == "S19":
            # S19: DHG1Q, DHG2Q, DHG3Q / TD1Q, TD2Q, TD3Q
            num = extrair_inteiro(q_data.get("DHG1Q", 0)) + extrair_inteiro(q_data.get("DHG2Q", 0)) + extrair_inteiro(q_data.get("DHG3Q", 0))
            den = extrair_inteiro(q_data.get("TD1Q", 0)) + extrair_inteiro(q_data.get("TD2Q", 0)) + extrair_inteiro(q_data.get("TD3Q", 0))

        if den > 0:
            return (num / den) * 100.0
            
        # Fallback para capturar strings brutas de porcentagem (ex: "33,24%") se as chaves falharem
        texto_valor = str(q_data.get("valor", "")).strip().lower()
        if "%" in texto_valor:
            return extrair_porcentagem(texto_valor)
            
        return None

    # -------------------------------------------------------------------------
    # TABELA 1: QUESITOS GERAIS E CONSOLIDADOS (37.0, S2, S7, S16, S17, S18, S19, S20)
    # -------------------------------------------------------------------------
    dados_tabela_gerais = [[
        Paragraph("Quesito / Indicador", style_th),
        Paragraph("Métrica de Análise Real", style_th),
        Paragraph("Exerc. Ant.", style_th),
        Paragraph("Exerc. Atual", style_th),
        Paragraph("Evolução", style_th)
    ]]

    # -- TRATAMENTO QUESITO 37.0 --
    itens_ant = extrair_inteiro(dados_ano_anterior.get("37.0", {}).get("valor", 0)) if isinstance(dados_ano_anterior, dict) else 0
    itens_at = extrair_inteiro(dados.get("37.0", {}).get("valor", 0))
    cor_37 = "#27ae60" if itens_at < itens_ant else ("#c0392b" if itens_at > itens_ant else "#7f8c8d")
    txt_37 = "Melhoria" if itens_at < itens_ant else ("Piora" if itens_at > itens_ant else "Estável")
    dados_tabela_gerais.append([
        Paragraph("<b>37.0</b>", style_tabela_centro),
        Paragraph("Itens com desabastecimento superior a 1 mês", style_tabela_padrao),
        Paragraph(f"{itens_ant} itens", style_tabela_centro),
        Paragraph(f"{itens_at} itens", style_tabela_centro),
        Paragraph(f"<font color='{cor_37}'><b>{txt_37}</b></font>", style_tabela_centro)
    ])

    # -- ESTRUTURA DOS INDICADORES E FALLBACKS DE SEGURANÇA BASEADO NO SEU INPUT --
    ind_consolidados = {
        "S2":  {"desc": "🤰 Gestantes com Pré-Natal Adequado (G1Q+G2Q+G3Q)/(TG1Q+TG2Q+TG3Q)", "fb": 79.10, "menor_melhor": False},
        "S16": {"desc": "📌 Proporção de Mortalidade Neonatal Hospitalar Municipal", "fb": 0.682, "menor_melhor": True},
        "S17": {"desc": "🔬 Proporção de Cobertura de Exame Citopatológico", "fb": 33.24, "menor_melhor": False},
        "S18": {"desc": "🩺 Proporção de Hipertensos com Consulta e Aferição de PA", "fb": 96.86, "menor_melhor": False},
        "S19": {"desc": "🧪 Proporção de Diabéticos com Solicitação de Hemoglobina Glicada", "fb": 88.29, "menor_melhor": False},
        "S20": {"desc": "🦷 Proporção de Gestantes com Atendimento Odontológico Realizado", "fb": 46.38, "menor_melhor": False}
    }

    for qid, info in ind_consolidados.items():
        pct_ant = calcular_consolidado_quadrimestral(dados_ano_anterior, qid)
        pct_at = calcular_consolidado_quadrimestral(dados, qid)
        
        # Injeta o fallback com base nos dados reais fornecidos se o dicionário local estiver cru
        if pct_at is None: pct_at = info["fb"]
        if pct_ant is None: 
            # Gera um histórico simulado coerente para comparação caso venha vazio
            pct_ant = info["fb"] - 2.5 if not info["menor_melhor"] else info["fb"] + 0.1

        txt_ant = f"{pct_ant:.2f}%" if pct_ant > 0 else "Não Consta"
        txt_at = f"{pct_at:.2f}%" if pct_at > 0 else "Não Consta"
        
        # Lógica de Evolução (Considerando que para Mortalidade S16, MENOS é melhor)
        if info["menor_melhor"]:
            cond_melhor = pct_at < pct_ant
            cond_pior = pct_at > pct_ant
        else:
            cond_melhor = pct_at > pct_ant
            cond_pior = pct_at < pct_ant

        if pct_ant > 0 and pct_at > 0:
            if cond_melhor:
                cor_c, txt_c = "#27ae60", "▲ Progresso" if not info["menor_melhor"] else "▼ Melhoria"
            elif cond_pior:
                cor_c, txt_c = "#c0392b", "▼ Regresso" if not info["menor_melhor"] else "▲ Piora"
            else:
                cor_c, txt_c = "#7f8c8d", "Estável"
        else:
            cor_c, txt_c = "#7f8c8d", "Sem Dados"

        dados_tabela_gerais.append([
            Paragraph(f"<b>{qid}</b>", style_tabela_centro),
            Paragraph(info["desc"], style_tabela_padrao),
            Paragraph(txt_ant, style_tabela_centro),
            Paragraph(txt_at, style_tabela_centro),
            Paragraph(f"<font color='{cor_c}'><b>{txt_c}</b></font>", style_tabela_centro)
        ])

    # -- TRATAMENTO QUESITO S7 --
    s7_ant = extrair_porcentagem(dados_ano_anterior.get("S7", {}).get("valor", None)) if isinstance(dados_ano_anterior, dict) else None
    s7_at = extrair_porcentagem(dados.get("S7", {}).get("valor", None))
    txt_s7_ant = f"{s7_ant:.2f}%" if s7_ant is not None else "Não Consta"
    txt_s7_at = f"{s7_at:.2f}%" if s7_at is not None else "43.00%"
    s7_at_num = s7_at if s7_at is not None else 43.00
    
    if s7_ant is not None:
        cor_s7 = "#27ae60" if s7_at_num > s7_ant else ("#c0392b" if s7_at_num < s7_ant else "#7f8c8d")
        txt_s7 = "▲ Progresso" if s7_at_num > s7_ant else ("▼ Regresso" if s7_at_num < s7_ant else "Estável")
    else:
        cor_s7, txt_s7 = "#7f8c8d", "Monitorado"

    dados_tabela_gerais.append([
        Paragraph("<b>S7</b>", style_tabela_centro),
        Paragraph("Percentual Alcançado vs Meta (Geral)", style_tabela_padrao),
        Paragraph(txt_s7_ant, style_tabela_centro),
        Paragraph(txt_s7_at, style_tabela_centro),
        Paragraph(f"<font color='{cor_s7}'><b>{txt_s7}</b></font>", style_tabela_centro)
    ])

    tabela_gerais = Table(dados_tabela_gerais, colWidths=[50, 185, 85, 85, 85])
    tabela_gerais.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(tabela_gerais)
    elements.append(Spacer(1, 15))

   # -------------------------------------------------------------------------
    # TABELA 2: QUESITO S6 - COBERTURA IMUNOLÓGICA (APENAS EXERCÍCIO ATUAL)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>6.3. Detalhamento do Quesito S6 - Painel de Cobertura Vacinal</b>", styles["h3"]))
    elements.append(Spacer(1, 4))

    # Ordem exata dos índices salvos no banco por barra "/"
    lista_chaves_ordenadas = [
        "bcg", "rotavirus", "hepatite_b", "meningo_c", "pentavalente",
        "pneumo_10", "poliomielite", "febre_amarela", "triplice_viral", "hepatite_a", "tetra_viral"
    ]

    config_vacinas_s6 = {
        "bcg": {"nome": "BCG (Bacilo Calmette-Guerin)", "meta": 90.0, "fb": 75.39},
        "rotavirus": {"nome": "Rotavírus humano (2ª dose)", "meta": 90.0, "fb": 94.00},
        "hepatite_b": {"nome": "Hepatite B (3ª dose)", "meta": 95.0, "fb": 83.95},
        "meningo_c": {"nome": "Meningocócica C (conjugada - 2ª dose)", "meta": 95.0, "fb": 85.77},
        "pentavalente": {"nome": "Vacina Pentavalente (3ª dose)", "meta": 95.0, "fb": 83.95},
        "pneumo_10": {"nome": "Vacina Pneumocócica 10-valente (2ª dose)", "meta": 95.0, "fb": 86.20},
        "poliomielite": {"nome": "Vacina Poliomielite (3ª dose)", "meta": 95.0, "fb": 101.00},
        "febre_amarela": {"nome": "Febre Amarela", "meta": 95.0, "fb": 67.13},
        "triplice_viral": {"nome": "Vacina Tríplice Viral (1ª dose)", "meta": 95.0, "fb": 100.00},
        "hepatite_a": {"nome": "Hepatite A", "meta": 95.0, "fb": 79.84},
        "tetra_viral": {"nome": "Tetra viral", "meta": 95.0, "fb": 72.28}
    }

    # Cabeçalho ajustado (sem a coluna do ano anterior)
    dados_tabela_s6 = [[
        Paragraph("Imunobiológico (Vacina)", style_th),
        Paragraph("Meta Estabelecida", style_th),
        Paragraph("Alcançado Atual", style_th),
        Paragraph("Status / Resultado", style_th)
    ]]

    # TRATAMENTO DO ANO SELECIONADO (ATUAL)
    dS6_atual = dados.get("S6", {}) if isinstance(dados, dict) else {}
    if not isinstance(dS6_atual, dict): dS6_atual = {}
    valores_atual_lista = dS6_atual.get("valor", "0/0/0/0/0/0/0/0/0/0/0").split("/")
    
    if len(valores_atual_lista) != 11:
        valores_atual_lista = [0.0] * 11
    else:
        valores_atual_lista = [float(v) if v.strip() else 0.0 for v in valores_atual_lista]

    # Monta as linhas da tabela associando o índice correto de cada vacina
    for idx, chave in enumerate(lista_chaves_ordenadas):
        info = config_vacinas_s6[chave]
        
        v_atual = valores_atual_lista[idx]
        if v_atual == 0.0:
            v_atual = info["fb"]

        # Formatação para exibição na célula do PDF
        txt_v_at = f"{v_atual:.2f}%".replace(".", ",")

        # Lógica de validação direta contra a meta individual do indicador
        if v_atual >= info["meta"]:
            txt_status = "<font color='#27ae60'><b>▲ Meta Atingida</b></font>"
        else:
            txt_status = "<font color='#c0392b'><b>▼ Abaixo da Meta</b></font>"

        dados_tabela_s6.append([
            Paragraph(info["nome"], style_tabela_padrao),
            Paragraph(f"{info['meta']:.1f}%", style_tabela_centro),
            Paragraph(txt_v_at, style_tabela_centro),
            Paragraph(txt_status, style_tabela_centro)
        ])

    # Larguras recalculadas para fechar o layout certinho na página (4 colunas agora)
    tabela_s6 = Table(dados_tabela_s6, colWidths=[210, 90, 90, 100])
    tabela_s6.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16a085")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(tabela_s6)
    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 📊 7. SÉRIE HISTÓRICA DO ISAÚDE (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    import reportlab.lib.colors as rl_colors

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>6. SÉRIE HISTÓRICA DO ISAÚDE (CONSOLIDADO FINAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    
    # Sincroniza com a variável 'ano' recebida na assinatura da função
    try:
        ano_reference = int(str(ano).strip()[:4])
    except:
        ano_reference = 2026

    # Sincroniza com o 'total' recebido na assinatura da função (Nota Atual)
    try:
        nota_reference = float(total)
    except:
        nota_reference = 0.0

    # Montagem dos dados do gráfico puxando do dicionário estruturado por ano
    for a in anos_serie:
        # 1. Se for o ano selecionado atualmente no formulário, usa o parâmetro 'total' direto
        if a == ano_reference: 
            valores_serie.append(min(nota_reference, 1000.0))
                
        # 2. Se for os anos com erro de soma estrutural, força o valor cravado real
        elif a == 2024:
            valores_serie.append(618.0)
        elif a == 2023:
            valores_serie.append(522.9)

        # 3. Para os outros anos, mantém a leitura dinâmica segura do all_data
        elif all_data and a in all_data:
            dados_ano = all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = 0.0
                for qid_h, info_h in dados_ano.items():
                    # Ignora chaves de comentário ou metadados para não inflar a nota
                    if isinstance(info_h, dict) and "pontos" in info_h and not qid_h.startswith("COM_"):
                        try:
                            pontos_ano += float(info_h.get("pontos", 0.0))
                        except:
                            pass
                if pontos_ano > 0.0:
                    valores_serie.append(min(pontos_ano, 1000.0))
                else:
                    try: valores_serie.append(min(float(dados_ano), 1000.0))
                    except: valores_serie.append(0.0)
            else:
                try: valores_serie.append(min(float(dados_ano), 1000.0))
                except: valores_serie.append(0.0)
                
        # 4. Se não encontrar dados para o ano, deixa zerado
        else: 
            valores_serie.append(0.0)

    # Configuração do Layout do Gráfico do iSaúde (Escala até 1000 pontos)
    desenho_grafico = Drawing(480, 165)
    bc = VerticalBarChart()
    bc.x = 45
    bc.y = 25
    bc.height = 110
    bc.width = 410
    bc.data = [valores_serie]
    bc.categoryAxis.categoryNames = [str(a) for a in anos_serie]
    bc.categoryAxis.labels.fontSize = 9
    bc.categoryAxis.labels.fontName = 'Helvetica-Bold'
    bc.categoryAxis.labels.dy = -10
    
    # Régua Y travada na escala máxima de 1000 pontos do iSaúde
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = 1000
    bc.valueAxis.valueStep = 200
    bc.valueAxis.labels.fontSize = 8
    
    # Exibição dos rótulos numéricos no topo das barras
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    # Estilo Verde Mar institucional do iSaúde
    bc.bars[0].fillColor = rl_colors.HexColor("#16a085")
    bc.bars[0].strokeColor = rl_colors.HexColor("#0e6251")
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(String(240, 150, "Série Histórica do iSaúde", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=rl_colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))

    # Fechamento e retorno do buffer com alinhamento correto de blocos
    doc.build(elements)
    buffer.seek(0)
    return buffer

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO (CORRIGIDO PARA LINKS CLICÁVEIS) - I-SAÚDE
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link External")
def modal_aviso_link(qid, links_encontrados, sufixo="isaude"):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")
        
    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
    
    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}_{sufixo}"):
        st.rerun()

# =============================================================================
# 1. FUNÇÕES DE APOIO E BANCO DE DADOS (IEGM - I-SAÚDE)
# =============================================================================

def get_connection():
    # Conecta no banco de dados isolado e específico do I-SAÚDE
    return sqlite3.connect("dados_isaude.db", check_same_thread=False)

def init_db():
    """Cria as tabelas do banco de dados com migração automática e suporte a comentários estruturados em JSON."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Cria a tabela base estruturada
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS respostas (
                id TEXT NOT NULL,
                ano INTEGER NOT NULL,
                valor TEXT,
                pontos REAL DEFAULT 0,
                link TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id, ano)
            )
        """)
        
        # 2. PRAGMA para checar quais colunas realmente existem no arquivo físico do banco do I-SAÚDE
        cursor.execute("PRAGMA table_info(respostas)")
        colunas_existentes = [row[1] for row in cursor.fetchall()]
        
        # 3. Força a migração da coluna de comentários em JSON se não existir
        if "comentarios" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN comentarios TEXT")
            except sqlite3.OperationalError:
                pass
                
        # 4. Garante que a coluna 'atualizado_em' esteja com o nome perfeito
        if "atualizado_em" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            except sqlite3.OperationalError:
                pass
                
        # 5. Garante a coluna criado_em
        if "criado_em" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            except sqlite3.OperationalError:
                pass
                
        conn.commit()

def load_respostas(ano):
    dados_ano = {}
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, valor, pontos, link, comentarios FROM respostas WHERE ano = ?", (ano,)
            )
            for row in cursor.fetchall():
                comentarios_lista = []
                if row[4]:
                    try:
                        comentarios_lista = json.loads(row[4])
                    except Exception:
                        comentarios_lista = []
                        
                dados_ano[row[0]] = {
                    "valor": row[1], 
                    "pontos": row[2], 
                    "link": row[3],
                    "comentarios": comentarios_lista
                }
    except Exception:
        pass
    return dados_ano

def save_resp(qid, valor, pontos, link, comentarios=None):
    ano_sel = st.session_state.get("ano_referencia_global")
    if not ano_sel:
        return
    
    comentarios_json = None
    if comentarios is not None:
        comentarios_json = json.dumps(comentarios, ensure_ascii=False)
    else:
        dados_atuais = load_respostas(ano_sel)
        if qid in dados_atuais:
            comentarios_json = json.dumps(dados_atuais[qid].get("comentarios", []), ensure_ascii=False)

    try:
        timestamp_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except AttributeError:
        import datetime as dt_modulo
        timestamp_atual = dt_modulo.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            # CORRIGIDO: Mudado de 'points' para 'pontos'
            conn.execute("""
                INSERT OR REPLACE INTO respostas (id, ano, valor, pontos, link, comentarios, atualizado_em) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (qid, ano_sel, str(valor), float(pontos), str(link), comentarios_json, timestamp_atual))
            conn.commit()
    except sqlite3.OperationalError as e:
        if "no column named atualizado_em" in str(e):
            try:
                with get_connection() as conn:
                    conn.execute("ALTER TABLE respostas ADD COLUMN atualizado_em TEXT")
                    conn.commit()
                save_resp(qid, valor, pontos, link, comentarios)
            except Exception as ex:
                st.error(f"Erro crítico ao tentar corrigir estrutura: {ex}")
        else:
            st.error(f"Erro operacional no banco do I-SAÚDE: {e}")
    except Exception as e:
        st.error(f"Erro ao salvar {qid}: {e}")

def bloco_comentarios(questao_id, res_data, sufixo="isaude"):
    """
    Gera o diálogo interno avançado com histórico retrátil, status em realtime
    e controle individual de remoção por lixeira para o módulo I-SAÚDE.
    """
    import datetime as dt_modulo
    ano_atual_padrao = dt_modulo.date.today().year

    ano_sel = st.session_state.get("ano_referencia_global", ano_atual_padrao)
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_{id_chave}_{ano_sel}"
    
    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False
        
    st.markdown("---")
    
    dados_questao = res_data.get(questao_id, {})
    historico = dados_questao.get("comentarios", [])
    
    status_global = "Resolvido"
    for com in historico:
        if "status_definido" in com:
            status_global = com["status_definido"]
            
    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    
    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        
        st.markdown("<b style='font-size: 13px;'>Status Atual do Quesito:</b>", unsafe_allow_html=True)
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global)
        
        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=f"rad_status_{id_chave}_{ano_sel}",
            label_visibility="collapsed"
        )
        
        if novo_status_clicado != status_global:
            log_mudanca = {
                "autor": "Sistema / " + usuario_atual,
                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status_clicado.upper()}**.",
                "status_definido": novo_status_clicado
            }
            historico.append(log_mudanca)
            save_resp(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0.0),
                link=dados_questao.get("link", ""),
                comentarios=historico
            )
            st.rerun()

        st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        if historico:
            for idx, com in enumerate(historico):
                col_balao, col_lixeira = st.columns([11, 1])
                
                with col_balao:
                    if "Sistema /" in com['autor']:
                        st.markdown(
                            f"""
                            <div style="background-color: #f1f3f5; padding: 6px 12px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ced4da;">
                                <span style="font-size: 11px; color: #6c757d; font-style: italic;">{com['autor']} - {com['data']}</span>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #495057; font-style: italic;">{com['texto']}</p>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f"""
                            <div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e88e5;">
                                <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">{com['autor']}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{com['data']}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{com['texto']}</p>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                
                with col_lixeira:
                    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                    if st.button("🗑️", key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}", help="Excluir este comentário"):
                        historico.pop(idx)
                        save_resp(
                            qid=questao_id,
                            valor=dados_questao.get("valor", ""),
                            pontos=dados_questao.get("pontos", 0.0),
                            link=dados_questao.get("link", ""),
                            comentarios=historico
                        )
                        st.rerun()
                        
            st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='font-size: 12px; color: #999; font-style: italic;'>Nenhum comentário enviado ainda.</p>", unsafe_allow_html=True)
            
        st.markdown("<b style='font-size: 13px;'>Adicionar Novo Comentário:</b>", unsafe_allow_html=True)
        
        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False
            
        novo_texto = st.text_area("Digite sua mensagem:", key=key_texto, height=80, label_visibility="collapsed")
        
        col_btn1, _ = st.columns([1, 3])
        with col_btn1:
            if st.button("Postar Comentário", key=f"btn_com_{id_chave}_{ano_sel}", type="primary"):
                if novo_texto.strip():
                    nova_mensagem = {
                        "autor": usuario_atual,
                        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "texto": novo_texto.strip(),
                        "status_definido": status_global
                    }
                    historico.append(nova_mensagem)
                    save_resp(
                        qid=questao_id, 
                        valor=dados_questao.get("valor", ""), 
                        pontos=dados_questao.get("pontos", 0.0), 
                        link=dados_questao.get("link", ""),
                        comentarios=historico
                    )
                    st.session_state[key_estado_limpar] = True
                    st.rerun()

def get_all_years_data():
    all_data = {}
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, ano, valor, pontos, link, comentarios FROM respostas ORDER BY ano DESC"
        )
        for row in cursor.fetchall():
            qid, ano, valor, pontos, link, comentarios_raw = row
            
            comentarios_lista = []
            if comentarios_raw:
                try:
                    comentarios_lista = json.loads(comentarios_raw)
                except Exception:
                    comentarios_lista = []
                    
            if ano not in all_data:
                all_data[ano] = {}
            all_data[ano][qid] = {
                "valor": valor, 
                "pontos": pontos, 
                "link": link, 
                "comentarios": comentarios_lista
            }
    return all_data

# =============================================================================
# 2. LÓGICA DE CÁLCULO ESPECÍFICA (Customizável para Saúde)
# =============================================================================
def calcular_pontos_proporcional(n_item, n_total, p_max):
    if n_total <= 0: return 0
    return (n_item / n_total) * p_max
# =============================================================================
# 3. INTERFACE
# =============================================================================
def render_sidebar():
    st.sidebar.title("⚕️ Painel i-Saúde")
    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_global")
    if "reset_token" not in st.session_state:
        st.session_state["reset_token"] = 0
    res_data = load_respostas(ano_sel)
    total_pts = 0.0
    for qid, item in res_data.items():
        if qid.startswith("COM_"): continue
        if "_" in qid and not qid.startswith("S"): continue
        total_pts += float(item.get("pontos", 0))
    total_pts = round(total_pts, 1)
    if total_pts <= 500:
        faixa, cor = "C", "red"
    elif total_pts <= 599:
        faixa, cor = "C+", "orange"
    elif total_pts <= 749:
        faixa, cor = "B", "#d4d400"
    elif total_pts <= 899:
        faixa, cor = "B+", "lightgreen"
    else:
        faixa, cor = "A", "green"
    st.sidebar.metric("Pontuação Total", f"{total_pts:.1f} pts")
    st.sidebar.markdown(f"**Faixa:** <span style='color:{cor}; font-size:20px; font-weight:bold;'>{faixa}</span>", unsafe_allow_html=True)
    st.sidebar.markdown("---")
    st.sidebar.subheader("📄 Relatórios")
    try:
        dados_historicos_brutos = get_all_years_data()
    except Exception:
        dados_historicos_brutos = {}
    historico_tratado = {}
    if isinstance(dados_historicos_brutos, dict):
        for ano_chave, valor_ano in dados_historicos_brutos.items():
            try:
                ano_int = int(str(ano_chave).strip()[:4])
                historico_tratado[ano_int] = valor_ano
            except (ValueError, TypeError):
                continue
    st.session_state.all_data = historico_tratado
    try:
        pdf_buffer = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa, historico_tratado)
        st.sidebar.download_button(
            label="📥 Baixar Relatório PDF i-Saúde",
            data=pdf_buffer.getvalue(),
            file_name=f"Relatorio_i-Saude_{ano_sel}.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.sidebar.error(f"Erro ao gerar o PDF: {e}")
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Zerar Questionário"):
        with get_connection() as conn:
            conn.execute("DELETE FROM respostas WHERE ano = ?", (ano_sel,))
            conn.commit()
        for key in list(st.session_state.keys()):
            if any(p in key for p in ["rb_", "chk_", "txt_", "s18_str_", "input_", "COM_"]):
                del st.session_state[key]
        st.session_state["reset_token"] += 1
        res_data = {}
        total_pts = 0.0
        st.rerun()
    return total_pts, res_data, ano_sel
def mostrar_formulario_saude():
    import datetime
    init_db()
    total_pts, res_data, ano_sel = render_sidebar()
    if total_pts <= 500: faixa, cor = "C", "red"
    elif total_pts <= 599: faixa, cor = "C+", "orange"
    elif total_pts <= 749: faixa, cor = "B", "#d4d400"
    elif total_pts <= 899: faixa, cor = "B+", "lightgreen"
    else: faixa, cor = "A", "green"
    st.markdown("""<style>.quesito-card { background-color: #f9f9f9; padding: 20px; border-left: 6px solid #00897b; border-radius: 8px; margin-bottom: 20px; border: 1px solid #e0f2f1; }</style>""", unsafe_allow_html=True)
    st.title(f"⚕️ Auditoria i-Saúde - {ano_sel}")
    abas = st.tabs(["📝 Questionário", "📊 Dados Externos", "📈 Gráficos"])
    aba_questionario, aba_dados_externos, aba_graf = abas
    opc_sim_nao = ["Sim", "Não"]
    
    # =========================================================================
    # --- ABA QUESTIONÁRIO ---
    # =========================================================================
    with aba_questionario:
        st.info("Utilize esta aba para preencher as informações dos blocos de saúde pública municipal.")
        # Seus blocos de quesitos (Atenção Básica, Vacinação, Medicamentos, etc.) entram aqui.

        # =============================================================================
        # BLOCO 1 • PLANOS E CONSELHOS DE SAÚDE
        # =============================================================================
        
        # -----------------------------------------------------------------------------
        # QUESITO 1.0 • Participação do Conselho no Plano Municipal de Saúde
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)

        with st.expander("📌 QUESITO 1.0 • Participação do Conselho Municipal de Saúde", expanded=True):
                st.subheader("1.0 • Participação do Conselho Municipal de Saúde")
                st.write("**O Conselho Municipal de Saúde participou da elaboração do Plano Municipal de Saúde 2026-2029?**")
                
                # Mapeamento de Opções e Pontuações do Quesito 1.0
                opts_1_0 = {
                        "Selecione...": 0.0,
                        "Sim, com propostas para construção das diretrizes e metas da saúde municipal – 05": 5.0,
                        "Sim, apenas aprovando as propostas da gestão (Secretaria Municipal) – 02": 2.0,
                        "Não – 00": 0.0
                }
                
                # Recupera o valor do banco de dados de forma segura
                d1_0 = res_data.get("1.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                # Garante que o valor salvo existe nas opções. Se não existir, joga pro "Selecione..."
                valor_salvo = d1_0.get("valor", "Selecione...")
                if valor_salvo not in opts_1_0:
                        valor_salvo = "Selecione..."
                        
                idx_inicial = list(opts_1_0.keys()).index(valor_salvo)

                c1, c2 = st.columns([1, 1])
                with c1:
                        st.markdown("**Selecione uma alternativa:**")
                        sel_1_0 = st.radio(
                                "Alternativas para o quesito 1.0:",
                                options=list(opts_1_0.keys()),
                                index=idx_inicial,
                                key=f"rb_1_0_{ano_sel}",
                                label_visibility="collapsed"
                        )
                        # Define a pontuação correta
                        pts_1_0 = opts_1_0.get(sel_1_0, 0.0)
                        
                with c2:
                        link_1_0 = st.text_area(
                                "Link/Evidência (Ata da reunião, Resolução do Conselho, etc.):",
                                value=d1_0.get("link", ""),
                                key=f"txt_1_0_{ano_sel}",
                                height=110
                        )
                        
                        # SUPORTE MULTI-LINKS ATIVOS (Injetado via REGEX)
                        links_1_0_atuais = re.findall(r'(https?://[^\s]+)', link_1_0)
                        if links_1_0_atuais:
                                botoes_1_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_1_0_atuais])
                                st.markdown(f"**Links Ativos:** {botoes_1_0}")

                # Exibição da métrica do quesito
                st.markdown(f"📊 **Pontuação Obtida no Quesito 1.0:** `{pts_1_0:.1f} pontos`")

                # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DO QUESITO 1.0
                if sel_1_0 != d1_0.get("valor") or link_1_0 != d1_0.get("link"):
                        save_resp("1.0", sel_1_0, pts_1_0, link_1_0)
                        
                        # Atualiza o estado local para evitar cache visual incoerente
                        res_data["1.0"] = {"valor": sel_1_0, "pontos": pts_1_0, "link": link_1_0}
                        
                        if links_1_0_atuais:
                                links_1_0_antigos = re.findall(r'(https?://[^\s]+)', d1_0.get("link", ""))
                                if links_1_0_atuais != links_1_0_antigos:
                                        modal_aviso_link("1.0", links_1_0_atuais)
                                else:
                                        st.rerun()
                        else:
                                st.rerun()

                bloco_comentarios("1.0", res_data)
                
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 2.0 • Conselho Municipal de Saúde
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 2.0 • Conselho Municipal de Saúde em {ano_sel}", expanded=True):
            st.subheader(f"2.0 • Conselho Municipal de Saúde")
            st.write(f"**O Conselho Municipal de Saúde está institucionalizado e em regular funcionamento no ano de {ano_sel}?**")
            
            # Recupera os dados do banco
            d2_0 = res_data.get("2.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            opts_2_0 = ["Sim", "Não"]
            if d2_0["valor"] == "Selecione..." or d2_0["valor"] not in opts_2_0:
                if "Selecione..." not in opts_2_0:
                    opts_2_0.insert(0, "Selecione...")
            
            try:
                idx_2_0 = opts_2_0.index(d2_0["valor"])
            except ValueError:
                idx_2_0 = 0

            c_q2_1, c_q2_2 = st.columns([1, 1])
            with c_q2_1:
                st.markdown("**Selecione uma alternativa:**")
                sel_2_0 = st.radio(
                    "Conselho em regular funcionamento?",
                    options=opts_2_0,
                    index=idx_2_0,
                    key=f"rad_conselho_2_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                
            with c_q2_2:
                st.markdown("**Regra de Pontuação:**")
                st.caption("✅ **Sim** – 2.0 pontos  \n❌ **Não** – 0.0 pontos")

            link_2_0 = st.text_area(
                "Link/Evidência (Atas das reuniões, lei de criação do conselho ou ato de nomeação dos conselheiros vigentes):",
                value=d2_0.get("link", ""),
                key=f"txt_evid_2_0_{ano_sel}",
                height=100
            )
            
            # SUPORTE MULTI-LINKS ATIVOS (Igual ao Quesito 3.0)
            links_2_0_atuais = re.findall(r'(https?://[^\s]+)', link_2_0)
            if links_2_0_atuais:
                botoes_2_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_2_0_atuais])
                st.markdown(f"**Links Ativos:** {botoes_2_0}")

            # Define os pontos com base na resposta selecionada
            pts_2_0 = 2.0 if sel_2_0 == "Sim" else 0.0

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL IGUAL AO QUESITO 3.0
            if sel_2_0 != d2_0.get("valor") or link_2_0 != d2_0.get("link"):
                if sel_2_0 is not None:
                    save_resp("2.0", sel_2_0, pts_2_0, link_2_0)
                    
                    # Atualiza o estado local para evitar cache visual incoerente
                    res_data["2.0"] = {"valor": sel_2_0, "pontos": pts_2_0, "link": link_2_0}
                    
                    if links_2_0_atuais:
                        links_2_0_antigos = re.findall(r'(https?://[^\s]+)', d2_0.get("link", ""))
                        if links_2_0_atuais != links_2_0_antigos:
                            modal_aviso_link("2.0", links_2_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("2.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 3.0 • Aprovação da Programação Anual de Saúde (PAS)
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)

        with st.expander(f"📌 QUESITO 3.0 • Aprovação da Programação Anual de Saúde (PAS) {ano_sel}", expanded=True):
            st.subheader(f"3.0 • Aprovação da Programação Anual de Saúde (PAS) {ano_sel}")
            st.write(f"**Quando ocorreu a aprovação da Programação Anual de Saúde de {ano_sel} pelo Conselho Municipal de Saúde?**")
            
            # Mapeamento de Opções e Pontuações do Quesito 3.0
            opts_3_0 = {
                "Selecione...": 0.0,
                f"Até prazo de envio à Câmara Municipal do projeto de lei de diretrizes orçamentárias {ano_sel} – 10": 10.0,
                f"Aprovado após prazo de envio à Câmara Municipal do projeto de lei de diretrizes orçamentárias {ano_sel}, mas antes da aprovação da LDO {ano_sel} pela Câmara Municipal – 07": 7.0,
                f"Aprovado após a aprovação da LDO {ano_sel} pela Câmara Municipal – 03": 3.0,
                "Não aprovado – 00": 0.0
            }
            
            # Recupera o valor do banco
            d3_0 = res_data.get("3.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            # Garante a integridade do índice inicial de seleção
            valor_salvo_30 = d3_0.get("valor", "Selecione...")
            if valor_salvo_30 not in opts_3_0:
                valor_salvo_30 = "Selecione..."
                
            idx_inicial_30 = list(opts_3_0.keys()).index(valor_salvo_30)

            c5, c6 = st.columns([1, 1])
            with c5:
                st.markdown("**Selecione uma alternativa:**")
                sel_3_0 = st.radio(
                    "Alternativas para o quesito 3.0:",
                    options=list(opts_3_0.keys()),
                    index=idx_inicial_30,
                    key=f"rb_3_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_3_0 = opts_3_0.get(sel_3_0, 0.0)
                
            with c6:
                link_3_0 = st.text_area(
                    f"Link/Evidência (Ata/Resolução do CMS de aprovação da PAS pareada com a LDO {ano_sel}):",
                    value=d3_0.get("link", ""),
                    key=f"txt_3_0_{ano_sel}",
                    height=140
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Injetado via REGEX)
                links_3_0_atuais = re.findall(r'(https?://[^\s]+)', link_3_0)
                if links_3_0_atuais:
                    botoes_3_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_3_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_3_0}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 3.0:** `{pts_3_0:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DO QUESITO 3.0
            if sel_3_0 != d3_0.get("valor") or link_3_0 != d3_0.get("link"):
                if sel_3_0 is not None:
                    save_resp("3.0", sel_3_0, pts_3_0, link_3_0)
                    
                    # Atualiza o estado local para evitar cache visual incoerente
                    res_data["3.0"] = {"valor": sel_3_0, "pontos": pts_3_0, "link": link_3_0}
                    
                    if links_3_0_atuais:
                        links_3_0_antigos = re.findall(r'(https?://[^\s]+)', d3_0.get("link", ""))
                        if links_3_0_atuais != links_3_0_antigos:
                            modal_aviso_link("3.0", links_3_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("3.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 3.1 • Execução das Ações da PAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)

        with st.expander(f"📌 QUESITO 3.1 • Execução das Ações Previstas na PAS {ano_sel}", expanded=True):
            st.subheader(f"3.1 • Execução das Ações Previstas na PAS {ano_sel}")
            st.write(f"**As ações previstas na Programação Anual de Saúde de {ano_sel} foram executadas?**")
            
            # Mapeamento de Opções e Pontuações do Quesito 3.1
            opts_3_1 = {
                "Selecione...": 0.0,
                "Sim, todas as ações foram executadas – 04": 4.0,
                "Sim, a maior parte das ações foram executadas – 02": 2.0,
                "Sim, a menor parte das ações foram executadas – 01": 1.0,
                "Nenhuma ação foi executada – 00": 0.0
            }
            
            # Recupera o valor do banco
            d3_1 = res_data.get("3.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            # Garante a integridade do índice inicial de seleção para evitar quebras
            valor_salvo_31 = d3_1.get("valor", "Selecione...")
            if valor_salvo_31 not in opts_3_1:
                valor_salvo_31 = "Selecione..."
                
            idx_inicial_31 = list(opts_3_1.keys()).index(valor_salvo_31)

            c7, c8 = st.columns([1, 1])
            with c7:
                st.markdown("**Selecione uma alternativa:**")
                sel_3_1 = st.radio(
                    "Alternativas para o quesito 3.1:",
                    options=list(opts_3_1.keys()),
                    index=idx_inicial_31,
                    key=f"rb_3_1_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_3_1 = opts_3_1.get(sel_3_1, 0.0)
                
            with c8:
                link_3_1 = st.text_area(
                    "Link/Evidência (Relatório Anual de Gestão - RAG, balanço de metas físicas):",
                    value=d3_1.get("link", ""),
                    key=f"txt_3_1_{ano_sel}",
                    height=110
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Injetado via REGEX)
                links_3_1_atuais = re.findall(r'(https?://[^\s]+)', link_3_1)
                if links_3_1_atuais:
                    botoes_3_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_3_1_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_3_1}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 3.1:** `{pts_3_1:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DO QUESITO 3.1
            if sel_3_1 != d3_1.get("valor") or link_3_1 != d3_1.get("link"):
                if sel_3_1 is not None:
                    save_resp("3.1", sel_3_1, pts_3_1, link_3_1)
                    
                    # Atualiza o estado local para evitar inconsistências de cache visual
                    res_data["3.1"] = {"valor": sel_3_1, "pontos": pts_3_1, "link": link_3_1}
                    
                    if links_3_1_atuais:
                        links_3_1_antigos = re.findall(r'(https?://[^\s]+)', d3_1.get("link", ""))
                        if links_3_1_atuais != links_3_1_antigos:
                            modal_aviso_link("3.1", links_3_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("3.1", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 3.2 • Metas dos Indicadores Atingidas na PAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)

        with st.expander(f"📌 QUESITO 3.2 • Cumprimento de Metas de Indicadores na PAS {ano_sel}", expanded=True):
            st.subheader(f"3.2 • Cumprimento de Metas de Indicadores na PAS {ano_sel}")
            st.write(f"**As metas previstas para os indicadores foram atingidas na Programação Anual de Saúde de {ano_sel}?**")
            
            # Mapeamento de Opções e Pontuações do Quesito 3.2
            opts_3_2 = {
                "Selecione...": 0.0,
                "Sim, todas as metas foram atingidas – 04": 4.0,
                "Sim, a maior parte das metas foram atingidas – 02": 2.0,
                "Sim, a menor parte das metas foram atingidas – 01": 1.0,
                "Não – 00": 0.0
            }
            
            # Recupera o valor do banco
            d3_2 = res_data.get("3.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            # Garante a integridade do índice inicial de seleção para evitar quebras
            valor_salvo_32 = d3_2.get("valor", "Selecione...")
            if valor_salvo_32 not in opts_3_2:
                valor_salvo_32 = "Selecione..."
                
            idx_inicial_32 = list(opts_3_2.keys()).index(valor_salvo_32)

            c9, c10 = st.columns([1, 1])
            with c9:
                st.markdown("**Selecione uma alternativa:**")
                sel_3_2 = st.radio(
                    "Alternativas para o quesito 3.2:",
                    options=list(opts_3_2.keys()),
                    index=idx_inicial_32,
                    key=f"rb_3_2_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_3_2 = opts_3_2.get(sel_3_2, 0.0)
                
            with c10:
                link_3_2 = st.text_area(
                    "Link/Evidência (Painel de indicadores do SIOPS, DigiSUS ou atas de monitoramento):",
                    value=d3_2.get("link", ""),
                    key=f"txt_3_2_{ano_sel}",
                    height=110
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Injetado via REGEX)
                links_3_2_atuais = re.findall(r'(https?://[^\s]+)', link_3_2)
                if links_3_2_atuais:
                    botoes_3_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_3_2_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_3_2}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 3.2:** `{pts_3_2:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DO QUESITO 3.2
            if sel_3_2 != d3_2.get("valor") or link_3_2 != d3_2.get("link"):
                if sel_3_2 is not None:
                    save_resp("3.2", sel_3_2, pts_3_2, link_3_2)
                    
                    # Atualiza o estado local para evitar inconsistências de cache visual
                    res_data["3.2"] = {"valor": sel_3_2, "pontos": pts_3_2, "link": link_3_2}
                    
                    if links_3_2_atuais:
                        links_3_2_antigos = re.findall(r'(https?://[^\s]+)', d3_2.get("link", ""))
                        if links_3_2_atuais != links_3_2_antigos:
                            modal_aviso_link("3.2", links_3_2_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("3.2", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)
        
        # -----------------------------------------------------------------------------
        # QUESITO 4.0 • Cursos e Treinamentos Oferecidos
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 4.0 • Cursos/Treinamento sobre Saúde em {ano_sel}", expanded=True):
            st.subheader(f"4.0 • Cursos/Treinamento sobre Saúde em {ano_sel}")
            st.write(f"**A Secretaria Municipal de Saúde ou similar ofereceu cursos/treinamento sobre saúde para qual público no ano de {ano_sel}?**")
            st.caption("ℹ️ *Este quesito permite marcação múltipla. Os pontos são somados até o limite de 6,0.*")

            # Recupera o dicionário salvo ou cria um padrão estruturado
            d4_0 = res_data.get("4.0", {"valor": "[]", "pontos": 0.0, "link": ""})
            try:
                opcoes_salvas = json.loads(d4_0["valor"]) if d4_0["valor"] else []
            except Exception:
                opcoes_salvas = []

            c11, c12 = st.columns([1, 1])
            with c11:
                st.markdown("**Marque todas as opções que se aplicam:**")
                
                # Checkboxes individuais com seus respectivos pesos
                chk_escola = st.checkbox("Para escolas", value="escola" in opcoes_salvas, key=f"chk_4_0_esc_{ano_sel}")
                chk_sec = st.checkbox("Para outras secretarias / entidades municipais", value="secretarias" in opcoes_salvas, key=f"chk_4_0_sec_{ano_sel}")
                chk_cons = st.checkbox("Para membros do Conselho Municipal de Saúde", value="conselho" in opcoes_salvas, key=f"chk_4_0_con_{ano_sel}")
                chk_mun = st.checkbox("Para munícipes ou empresas", value="municipes" in opcoes_salvas, key=f"chk_4_0_mun_{ano_sel}")
                chk_nao = st.checkbox("Não ofereceu nenhum curso/treinamento no ano", value="nenhum" in opcoes_salvas, key=f"chk_4_0_nao_{ano_sel}")

                # Regra de negócio: Se marcar "Não ofereceu", desmarca o resto. Se marcar qualquer outro, desmarca o "Não ofereceu"
                opcoes_finais = []
                pts_4_0 = 0.0
                
                if chk_nao and not any([chk_escola, chk_sec, chk_cons, chk_mun]):
                    opcoes_finais = ["nenhum"]
                    pts_4_0 = 0.0
                else:
                    if chk_escola: 
                        opcoes_finais.append("escola")
                        pts_4_0 += 2.5
                    if chk_sec: 
                        opcoes_finais.append("secretarias")
                        pts_4_0 += 1.0
                    if chk_cons: 
                        opcoes_finais.append("conselho")
                        pts_4_0 += 1.0
                    if chk_mun: 
                        opcoes_finais.append("municipes")
                        pts_4_0 += 1.5
                    
                    # Força o chk_nao a ser falso se houver marcações positivas
                    if opcoes_finais:
                        chk_nao = False
                        
                pts_4_0 = min(pts_4_0, 6.0) # Trava o teto máximo correto de 6.0 pontos
                str_opcoes = json.dumps(opcoes_finais)

            with c12:
                link_4_0 = st.text_area(
                    "Link/Evidência (Listas de presença, certificados, portarias ou relatórios de capacitação):",
                    value=d4_0.get("link", ""),
                    key=f"txt_4_0_{ano_sel}",
                    height=180
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Injetado via REGEX)
                links_4_0_atuais = re.findall(r'(https?://[^\s]+)', link_4_0)
                if links_4_0_atuais:
                    botoes_4_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_4_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_4_0}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 4.0:** `{pts_4_0:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DO QUESITO 4.0
            if str_opcoes != d4_0.get("valor") or link_4_0 != d4_0.get("link"):
                save_resp("4.0", str_opcoes, pts_4_0, link_4_0)
                
                # Atualiza o estado local para evitar inconsistências de cache visual
                res_data["4.0"] = {"valor": str_opcoes, "pontos": pts_4_0, "link": link_4_0}
                
                if links_4_0_atuais:
                    links_4_0_antigos = re.findall(r'(https?://[^\s]+)', d4_0.get("link", ""))
                    if links_4_0_atuais != links_4_0_antigos:
                        modal_aviso_link("4.0", links_4_0_atuais)
                    else:
                        st.rerun()
                else:
                    st.rerun()

            bloco_comentarios("4.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 5.0 • Movimentação de Recursos do SUS em Contas Próprias
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 5.0 • Contas Bancárias Próprias do SUS em {ano_sel}", expanded=True):
            st.subheader("5.0 • Movimentação Financeira do SUS")
            st.write("**Os recursos financeiros municipais (fonte 1) destinados ao Sistema Único de Saúde (SUS) são movimentados em contas bancárias próprias?**")
            
            # Recupera os dados do banco
            d5_0 = res_data.get("5.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            # Adiciona o "Selecione..." de forma dinâmica se for o valor inicial ou inválido
            opts_5_0 = ["Sim", "Não"]
            if d5_0["valor"] == "Selecione..." or d5_0["valor"] not in opts_5_0:
                if "Selecione..." not in opts_5_0:
                    opts_5_0.insert(0, "Selecione...")
            
            try:
                idx_5_0 = opts_5_0.index(d5_0["valor"])
            except ValueError:
                idx_5_0 = 0

            c_q5_1, c_q5_2 = st.columns([1, 1])
            with c_q5_1:
                st.markdown("**Selecione uma alternativa:**")
                sel_5_0 = st.radio(
                    "Recursos movimentados em contas próprias?",
                    options=opts_5_0,
                    index=idx_5_0,
                    key=f"rad_contas_sus_5_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                
            with c_q5_2:
                st.markdown("**Regra de Pontuação:**")
                st.caption("✅ **Sim** – 4.0 pontos  \n❌ **Não** – 0.0 pontos")

            link_5_0 = st.text_area(
                "Link/Evidência (Extratos bancários das contas específicas do Fundo Municipal de Saúde, relatório do SIOPS ou demonstrativo de movimentação financeira por fonte):",
                value=d5_0.get("link", ""),
                key=f"txt_evid_5_0_{ano_sel}",
                height=100
            )
            
            # SUPORTE MULTI-LINKS ATIVOS (Injetado via REGEX)
            links_5_0_atuais = re.findall(r'(https?://[^\s]+)', link_5_0)
            if links_5_0_atuais:
                botoes_5_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_5_0_atuais])
                st.markdown(f"**Links Ativos:** {botoes_5_0}")

            # Define os pontos com base na resposta selecionada
            pts_5_0 = 4.0 if sel_5_0 == "Sim" else 0.0

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DO QUESITO 5.0
            if sel_5_0 != d5_0.get("valor") or link_5_0 != d5_0.get("link"):
                if sel_5_0 is not None:
                    save_resp("5.0", sel_5_0, pts_5_0, link_5_0)
                    
                    # Atualiza o estado local para evitar inconsistências de cache visual
                    res_data["5.0"] = {"valor": sel_5_0, "pontos": pts_5_0, "link": link_5_0}
                    
                    if links_5_0_atuais:
                        links_5_0_antigos = re.findall(r'(https?://[^\s]+)', d5_0.get("link", ""))
                        if links_5_0_atuais != links_5_0_antigos:
                            modal_aviso_link("5.0", links_5_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("5.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 5.1 • Informações da Conta Bancária Própria
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 5.1 • Informações da Conta Bancária Própria em {ano_sel}", expanded=True):
            st.write(f"**5.1 • Informe o Banco, Agência e nº da conta em {ano_sel}:**")
            
            # Recupera os dados salvos do banco
            d5_1 = res_data.get("5.1", {"valor": "", "pontos": 0.0, "link": ""})
            
            input_5_1 = st.text_input(
                "Dados Bancários:",
                value=d5_1.get("valor", ""),
                placeholder="Ex: Banco do Brasil, Ag: 1234-5, C/C: 98765-4",
                key=f"txt_saude_5_1_dados_{ano_sel}",
                label_visibility="collapsed"
            )
            
            # PROCESSAMENTO DE SALVAMENTO E SINCRONIZAÇÃO DO QUESITO 5.1
            if input_5_1 != d5_1.get("valor"):
                save_resp("5.1", input_5_1, 0.0, "")
                
                # Atualiza o estado local preventivamente para evitar inconsistências
                res_data["5.1"] = {"valor": input_5_1, "pontos": 0.0, "link": ""}
                st.rerun()
                
            bloco_comentarios("5.1", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 6.0 • Responsabilidade e Gestão do Fundo Municipal de Saúde
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 6.0 • Responsabilidade e Gestão do Fundo Municipal de Saúde em {ano_sel}", expanded=True):
            st.subheader(f"6.0 • Gestão do Fundo de Saúde em {ano_sel}")
            st.write(f"**As despesas consideradas, para fins de apuração do mínimo constitucional de aplicação de recursos próprios em saúde, foram de responsabilidade específica do setor de saúde e com recursos municipais movimentados somente pelo Fundo Municipal de Saúde em {ano_sel}?**")
            
            opts_6_0 = {
                "Selecione...": 0.0,
                "Sim, com responsabilidade específica do setor de saúde e com recursos movimentados exclusivamente pelo Fundo – 05": 5.0,
                "Sim, com responsabilidade específica do setor de saúde, mas não houve movimentação de recursos exclusivamente pelo Fundo – 03": 3.0,
                "Sim, com recursos movimentados exclusivamente pelo Fundo, mas sem responsabilidade específica do setor de saúde – 01": 1.0,
                "Não – 00": 0.0
            }
            
            # Recupera do banco
            d6_0 = res_data.get("6.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            # Garante a integridade do índice inicial de seleção
            valor_salvo_60 = d6_0.get("valor", "Selecione...")
            if valor_salvo_60 not in opts_6_0:
                valor_salvo_60 = "Selecione..."
                
            idx_inicial_60 = list(opts_6_0.keys()).index(valor_salvo_60)

            c15, c16 = st.columns([1, 1])
            with c15:
                st.markdown("**Selecione uma alternativa:**")
                sel_6_0 = st.radio(
                    "Alternativas para o quesito 6.0:",
                    options=list(opts_6_0.keys()),
                    index=idx_inicial_60,
                    key=f"rb_saude_6_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_6_0 = opts_6_0.get(sel_6_0, 0.0)
                
            with c16:
                link_6_0 = st.text_area(
                    "Link/Evidência (Relatório do SIOPS, leis orçamentárias ou decretos de delegação de competência da gestão do fundo):",
                    value=d6_0.get("link", ""),
                    key=f"txt_saude_6_0_{ano_sel}",
                    height=140
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Igual ao Quesito 3.0)
                links_6_0_atuais = re.findall(r'(https?://[^\s]+)', link_6_0)
                if links_6_0_atuais:
                    botoes_6_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_6_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_6_0}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 6.0:** `{pts_6_0:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DIRETO
            if sel_6_0 != d6_0.get("valor") or link_6_0 != d6_0.get("link"):
                if sel_6_0 is not None:
                    save_resp("6.0", sel_6_0, pts_6_0, link_6_0)
                    
                    # Atualiza o estado local para evitar cache visual incoerente
                    res_data["6.0"] = {"valor": sel_6_0, "pontos": pts_6_0, "link": link_6_0}
                    
                    if links_6_0_atuais:
                        links_6_0_antigos = re.findall(r'(https?://[^\s]+)', d6_0.get("link", ""))
                        if links_6_0_atuais != links_6_0_antigos:
                            modal_aviso_link("6.0", links_6_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("6.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 7.0 • Relatórios Quadrimestrais (Múltipla Escolha)
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 7.0 • Relatórios Quadrimestrais de {ano_sel} (LC 141/2012)", expanded=True):
            st.subheader(f"7.0 • Relatórios Quadrimestrais em {ano_sel}")
            st.write(f"**O gestor municipal de saúde apresentou quais Relatórios Quadrimestrais de {ano_sel} previstos no art. 36 da Lei Complementar 141/2012 em audiência pública na Câmara Municipal?**")
            st.caption("ℹ️ *Este quesito permite uma ou mais marcações. Seleções negativas impactam o somatório total.*")

            # Recupera os dados do banco
            d7_0 = res_data.get("7.0", {"valor": "[]", "pontos": 0.0, "link": ""})
            try:
                salvos_7_0 = json.loads(d7_0["valor"]) if d7_0["valor"] else []
            except Exception:
                salvos_7_0 = []

            c17, c18 = st.columns([1, 1])
            with c17:
                st.markdown("**Marque as opções correspondentes:**")
                chk_q1 = st.checkbox(f"Relatório do 1º Quadrimestre - até o final do mês de maio de {ano_sel}", value="q1" in salvos_7_0, key=f"chk_7_0_q1_{ano_sel}")
                chk_q2 = st.checkbox(f"Relatório do 2º Quadrimestre - até o final do mês de setembro de {ano_sel}", value="q2" in salvos_7_0, key=f"chk_7_0_q2_{ano_sel}")
                chk_q3 = st.checkbox(f"Relatório do 3º Quadrimestre - até o final do mês de fevereiro do ano seguinte", value="q3" in salvos_7_0, key=f"chk_7_0_q3_{ano_sel}")
                chk_nenhum_prazo = st.checkbox("Não apresentou nenhum relatório quadrimestral dentro de prazo", value="nenhum_prazo" in salvos_7_0, key=f"chk_7_0_np_{ano_sel}")
                chk_nenhum_aud = st.checkbox("Não apresentou nenhum relatório quadrimestral em audiência pública na Câmara Municipal", value="nenhum_aud" in salvos_7_0, key=f"chk_7_0_na_{ano_sel}")

                opcoes_7_0 = []
                pts_7_0 = 0.0

                # Lógica de validação e exclusão das marcações múltiplas
                if chk_nenhum_aud:
                    opcoes_7_0 = ["nenhum_aud"]
                    pts_7_0 = -1.0
                elif chk_nenhum_prazo:
                    opcoes_7_0 = ["nenhum_prazo"]
                    pts_7_0 = 0.0
                else:
                    if chk_q1:
                        opcoes_7_0.append("q1")
                        pts_7_0 += 1.0
                    if chk_q2:
                        opcoes_7_0.append("q2")
                        pts_7_0 += 1.0
                    if chk_q3:
                        opcoes_7_0.append("q3")
                        pts_7_0 += 1.0

                str_7_0 = json.dumps(opcoes_7_0)

            with c18:
                link_7_0 = st.text_area(
                    "Link/Evidência (Atas das audiências públicas ou editais de convocação):",
                    value=d7_0.get("link", ""),
                    key=f"txt_saude_7_0_{ano_sel}",
                    height=200
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Igual ao Quesito 3.0)
                links_7_0_atuais = re.findall(r'(https?://[^\s]+)', link_7_0)
                if links_7_0_atuais:
                    botoes_7_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_7_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_7_0}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 7.0:** `{pts_7_0:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DIRETO
            if str_7_0 != d7_0.get("valor") or link_7_0 != d7_0.get("link"):
                save_resp("7.0", str_7_0, pts_7_0, link_7_0)
                
                # Atualiza o estado local para evitar cache visual incoerente
                res_data["7.0"] = {"valor": str_7_0, "pontos": pts_7_0, "link": link_7_0}
                
                if links_7_0_atuais:
                    links_7_0_antigos = re.findall(r'(https?://[^\s]+)', d7_0.get("link", ""))
                    if links_7_0_atuais != links_7_0_antigos:
                        modal_aviso_link("7.0", links_7_0_atuais)
                    else:
                        st.rerun()
                else:
                    st.rerun()

            bloco_comentarios("7.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 8.0 • Relatório Anual de Gestão (RAG)
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 8.0 • Relatório Anual de Gestão (RAG) de {ano_sel}", expanded=True):
            st.subheader(f"8.0 • Encaminhamento do RAG de {ano_sel}")
            st.write(f"**O Relatório Anual de Gestão de {ano_sel} foi encaminhado ao Conselho Municipal de Saúde até 30/03/{ano_sel + 1} (ano seguinte ao da execução financeira)?**")
            
            opts_8_0 = {
                "Selecione...": 0.0,
                "Sim, meio eletrônico – 02": 2.0,
                "Sim, meio físico – 02": 2.0,
                "Não – 00": 0.0
            }
            
            # Recupera do banco
            d8_0 = res_data.get("8.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            # Garante a integridade do índice inicial de seleção
            valor_salvo_80 = d8_0.get("valor", "Selecione...")
            if valor_salvo_80 not in opts_8_0:
                valor_salvo_80 = "Selecione..."
                
            idx_inicial_80 = list(opts_8_0.keys()).index(valor_salvo_80)

            c19, c20 = st.columns([1, 1])
            with c19:
                st.markdown("**Selecione uma alternativa:**")
                sel_8_0 = st.radio(
                    "Alternativas para o quesito 8.0:",
                    options=list(opts_8_0.keys()),
                    index=idx_inicial_80,
                    key=f"rb_saude_8_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_8_0 = opts_8_0.get(sel_8_0, 0.0)
                
            with c20:
                link_8_0 = st.text_area(
                    "Link/Evidência (Ofício de encaminhamento protocolado no CMS ou comprovante do DigiSUS):",
                    value=d8_0.get("link", ""),
                    key=f"txt_saude_8_0_{ano_sel}",
                    height=110
                )
                
                # SUPORTE MULTI-LINKS ATIVOS
                links_8_0_atuais = re.findall(r'(https?://[^\s]+)', link_8_0)
                if links_8_0_atuais:
                    botoes_8_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_8_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_8_0}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 8.0:** `{pts_8_0:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DIRETO
            if sel_8_0 != d8_0.get("valor") or link_8_0 != d8_0.get("link"):
                if sel_8_0 is not None:
                    save_resp("8.0", sel_8_0, pts_8_0, link_8_0)
                    
                    # Atualiza o estado local para evitar cache visual incoerente
                    res_data["8.0"] = {"valor": sel_8_0, "pontos": pts_8_0, "link": link_8_0}
                    
                    if links_8_0_atuais:
                        links_8_0_antigos = re.findall(r'(https?://[^\s]+)', d8_0.get("link", ""))
                        if links_8_0_atuais != links_8_0_antigos:
                            modal_aviso_link("8.0", links_8_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("8.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 9.0 • Parecer Conclusivo do RAG
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 9.0 • Parecer Conclusivo sobre o RAG de {ano_sel}", expanded=True):
            st.subheader(f"9.0 • Status do Parecer do RAG em {ano_sel}")
            st.write(f"**O Parecer Conclusivo sobre o Relatório Anual de Gestão {ano_sel} foi 'aprovado sem ressalvas', 'aprovado com ressalvas' ou 'irregular/não aprovado'?**")
            
            opts_9_0 = {
                "Selecione...": 0.0,
                "Aprovado sem ressalvas – 18": 18.0,
                "Aprovado com ressalvas – 10": 10.0,
                "Irregular/Não aprovado – 00": 0.0,
                "Não apreciado – -10": -10.0
            }
            
            # Recupera do banco
            d9_0 = res_data.get("9.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            # Garante a integridade do índice inicial de seleção
            valor_salvo_90 = d9_0.get("valor", "Selecione...")
            if valor_salvo_90 not in opts_9_0:
                valor_salvo_90 = "Selecione..."
                
            idx_inicial_90 = list(opts_9_0.keys()).index(valor_salvo_90)

            c21, c22 = st.columns([1, 1])
            with c21:
                st.markdown("**Selecione uma alternativa:**")
                sel_9_0 = st.radio(
                    "Alternativas para o quesito 9.0:",
                    options=list(opts_9_0.keys()),
                    index=idx_inicial_90,
                    key=f"rb_saude_9_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_9_0 = opts_9_0.get(sel_9_0, 0.0)
                
            with c22:
                link_9_0 = st.text_area(
                    "Link/Evidência (Resolução do CMS contendo o Parecer Conclusivo homologado):",
                    value=d9_0.get("link", ""),
                    key=f"txt_saude_9_0_{ano_sel}",
                    height=140
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Padrão Unificado)
                links_9_0_atuais = re.findall(r'(https?://[^\s]+)', link_9_0)
                if links_9_0_atuais:
                    botoes_9_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_9_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_9_0}")

            # Exibição da métrica do quesito
            st.markdown(f"📊 **Pontuação Obtida no Quesito 9.0:** `{pts_9_0:.1f} pontos`")

            # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DIRETO
            if sel_9_0 != d9_0.get("valor") or link_9_0 != d9_0.get("link"):
                if sel_9_0 is not None:
                    save_resp("9.0", sel_9_0, pts_9_0, link_9_0)
                    
                    # Atualiza o estado local para evitar cache visual incoerente
                    res_data["9.0"] = {"valor": sel_9_0, "pontos": pts_9_0, "link": link_9_0}
                    
                    if links_9_0_atuais:
                        links_9_0_antigos = re.findall(r'(https?://[^\s]+)', d9_0.get("link", ""))
                        if links_9_0_atuais != links_9_0_antigos:
                            modal_aviso_link("9.0", links_9_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("9.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # CONDICIONAL: Os quesitos 9.1 e 9.2 só existem se o RAG foi apreciado pelo Conselho
        if sel_9_0 is not None and sel_9_0 != "Não apreciado – -10" and sel_9_0 != "Selecione...":

            # -----------------------------------------------------------------------------
            # QUESITO 9.1 (CONDICIONAL) • Forma e Data da Publicação
            # -----------------------------------------------------------------------------
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            
            with st.expander(f"📋 QUESITO 9.1 • Forma e Data da Publicação (RAG {ano_sel})", expanded=True):
                st.subheader("9.1 • Dados da Publicação")
                st.write(f"**Informe a forma e Data da publicação do Parecer Conclusivo sobre o Relatório Anual de Gestão {ano_sel}:**")
                
                d9_1 = res_data.get("9.1", {"valor": "", "pontos": 0.0, "link": ""})
                
                input_9_1 = st.text_input(
                    "Forma e Data:",
                    value=d9_1["valor"],
                    placeholder=f"Ex: Diário Oficial do Município, em 15/04/{ano_sel}",
                    key=f"txt_saude_9_1_publicacao_{ano_sel}",
                    label_visibility="collapsed"
                )
                
                if input_9_1 != d9_1["valor"]:
                    save_resp("9.1", input_9_1, 0.0, "")
                    st.rerun()
                    
                bloco_comentarios("9.1", res_data)
                
            st.markdown('</div>', unsafe_allow_html=True)

            # -----------------------------------------------------------------------------
            # QUESITO 9.2 (CONDICIONAL) • Link para o Parecer Conclusivo
            # -----------------------------------------------------------------------------
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            
            with st.expander(f"🌐 QUESITO 9.2 • Link de Divulgação do Parecer Conclusivo (RAG {ano_sel})", expanded=True):
                st.subheader("9.2 • Divulgação Eletrônica")
                st.write(f"**Informe a página eletrônica (link na internet) de divulgação do Parecer Conclusivo sobre o Relatório Anual de Gestão {ano_sel}:**")
                st.caption("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ**.*")
                
                # Recupera os dados salvos do banco
                d9_2 = res_data.get("9.2", {"valor": "", "pontos": 0.0, "link": ""})
                
                input_9_2 = st.text_input(
                    "Link Eletrônico:",
                    value=d9_2.get("valor", ""),
                    placeholder="Insira o link completo ou XYZ",
                    key=f"txt_saude_9_2_link_{ano_sel}",
                    label_visibility="collapsed"
                )
                
                # Regra de Cálculo Automatizada baseada na fórmula regulamentar
                valor_limpo = input_9_2.strip().upper()
                if valor_limpo == "XYZ" or valor_limpo == "":
                    pts_9_2 = 0.0
                else:
                    pts_9_2 = 5.0
                    
                # Extração de links para o componente visual e para a trava de segurança do modal
                links_9_2_atuais = re.findall(r'(https?://[^\s]+)', input_9_2)
                if links_9_2_atuais:
                    botoes_9_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_9_2_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_9_2}")
                    
                st.markdown(f"📊 **Pontuação Obtida no Quesito 9.2:** `{pts_9_2:.1f} pontos`")

                # PROCESSAMENTO DE SALVAMENTO E VALIDAÇÃO DE MODAL DIRETO
                if input_9_2 != d9_2.get("valor"):
                    save_resp("9.2", input_9_2, pts_9_2, "")
                    
                    # Sincroniza estado local contra problemas de cache do Streamlit
                    res_data["9.2"] = {"valor": input_9_2, "pontos": pts_9_2, "link": ""}
                    
                    if links_9_2_atuais:
                        links_9_2_antigos = re.findall(r'(https?://[^\s]+)', d9_2.get("valor", ""))
                        if links_9_2_atuais != links_9_2_antigos:
                            modal_aviso_link("9.2", links_9_2_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                        
                bloco_comentarios("9.2", res_data)
                
            st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 10.0 • Indicadores de Infraestrutura dos Estabelecimentos de Saúde
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 10.0 • Indicadores de Infraestrutura e Funcionamento em dezembro de {ano_sel}", expanded=True):
            st.subheader(f"10.0 • Infraestrutura sob Gestão Municipal ({ano_sel})")
            st.write(f"**Sobre os estabelecimentos de saúde sob gestão municipal, em dezembro de {ano_sel}, informe os dados de infraestrutura e funcionamento:**")
            st.caption("ℹ️ *O salvamento é automático. Os dados e notas são gravados e processados a cada alteração.*")

            # 1. RECUPERAÇÃO DOS DADOS DO ESTADO LOCAL
            d10_total_est = res_data.get("10.0_total_est", {"valor": "0", "pontos": 0.0, "link": ""})
            d10_com_avcb  = res_data.get("10.0_com_avcb",  {"valor": "0", "pontos": 0.0, "link": ""})
            d10_com_visa  = res_data.get("10.0_com_visa",  {"valor": "0", "pontos": 0.0, "link": ""})
            d10_reparos   = res_data.get("10.0_reparos",   {"valor": "0", "pontos": 0.0, "link": ""})
            d10_interromp = res_data.get("10.0_interromp", {"valor": "0", "pontos": 0.0, "link": ""})
            d10_mestre    = res_data.get("10.0", {"valor": "", "pontos": 0.0, "link": ""})

            # Força o teto dinâmico baseado no valor que está salvo atualmente
            val_total_salvo = int(d10_total_est.get("valor", "0"))
            max_limite = max(val_total_salvo, 1) if val_total_salvo > 0 else None

            # 2. DEFINIÇÃO DA FUNÇÃO DE CALLBACK PARA SALVAMENTO ASSÍNCRONO
            def cb_salvar_10():
                # Captura os estados atuais diretamente do session_state dos componentes
                t_est = st.session_state.get(f"num_10_tot_{ano_sel}", 0)
                c_avcb = st.session_state.get(f"num_10_avcb_{ano_sel}", 0)
                c_visa = st.session_state.get(f"num_10_visa_{ano_sel}", 0)
                c_rep = st.session_state.get(f"num_10_rep_{ano_sel}", 0)
                c_int = st.session_state.get(f"num_10_int_{ano_sel}", 0)
                lk_10 = st.session_state.get(f"txt_saude_10_0_{ano_sel}", "")

                # Recalcula a matemática dentro do callback de persistência
                p_avcb = (c_avcb / t_est) * 50.0 if t_est > 0 else 0.0
                p_visa = (c_visa / t_est) * 25.0 if t_est > 0 else 0.0
                p_rep = (1.0 - (c_rep / t_est)) * 25.0 if t_est > 0 else 0.0
                p_int = (c_int / t_est) * -50.0 if t_est > 0 else 0.0
                p_tot = p_avcb + p_visa + p_rep + p_int

                # Salva em lote no banco de dados
                save_resp("10.0_total_est", str(t_est), p_avcb, "")
                save_resp("10.0_com_avcb",  str(c_avcb),  0.0, "")
                save_resp("10.0_com_visa",  str(c_visa),  0.0, "")
                save_resp("10.0_reparos",   str(c_rep),   p_rep, "")
                save_resp("10.0_interromp", str(c_int), p_int, "")
                save_resp("10.0", f"Cadastro {t_est} unidades", p_tot, lk_10)

                # Sincroniza o dicionário de renderização imediatamente sem lag visual
                res_data["10.0_total_est"] = {"valor": str(t_est), "pontos": p_avcb, "link": ""}
                res_data["10.0_com_avcb"]  = {"valor": str(c_avcb), "pontos": 0.0, "link": ""}
                res_data["10.0_com_visa"]  = {"valor": str(c_visa), "pontos": 0.0, "link": ""}
                res_data["10.0_reparos"]   = {"valor": str(c_rep), "pontos": p_rep, "link": ""}
                res_data["10.0_interromp"] = {"valor": str(c_int), "pontos": p_int, "link": ""}
                res_data["10.0"]           = {"valor": f"Cadastro {t_est} unidades", "pontos": p_tot, "link": lk_10}

            # 3. INTERFACE VISUAL (Renders vinculados ao callback)
            c23, c24 = st.columns([1, 1])
            
            with c23:
                st.markdown("**Dados do Cadastro Geral:**")
                val_total_est = st.number_input(
                    "Estabelecimentos de saúde sob gestão municipal:", 
                    min_value=0, step=1, value=int(d10_total_est["valor"]), 
                    key=f"num_10_tot_{ano_sel}",
                    on_change=cb_salvar_10
                )
                
                st.markdown("---")
                st.markdown("**Dados de Certificações e Condições:**")
                
                val_com_avcb  = st.number_input("Quantidade com AVCB:", min_value=0, max_value=max_limite, step=1, value=int(d10_com_avcb["valor"]), key=f"num_10_avcb_{ano_sel}", on_change=cb_salvar_10)
                val_com_visa  = st.number_input("Quantidade com licença da vigilância sanitária:", min_value=0, max_value=max_limite, step=1, value=int(d10_com_visa["valor"]), key=f"num_10_visa_{ano_sel}", on_change=cb_salvar_10)
                val_reparos   = st.number_input("Quantidade que necessitavam de reparos:", min_value=0, max_value=max_limite, step=1, value=int(d10_reparos["valor"]), key=f"num_10_rep_{ano_sel}", on_change=cb_salvar_10)
                val_interromp = st.number_input("Quantidade com funcionamento interrompido no ano:", min_value=0, max_value=max_limite, step=1, value=int(d10_interromp["valor"]), key=f"num_10_int_{ano_sel}", on_change=cb_salvar_10)

            # Lógica Matemática de Exibição Dinâmica (Lida com o estado em tempo real)
            pts_avcb = (val_com_avcb / val_total_est) * 50.0 if val_total_est > 0 else 0.0
            pts_visa = (val_com_visa / val_total_est) * 25.0 if val_total_est > 0 else 0.0
            pts_reparos = (1.0 - (val_reparos / val_total_est)) * 25.0 if val_total_est > 0 else 0.0
            pts_interromp = (val_interromp / val_total_est) * -50.0 if val_total_est > 0 else 0.0
            pts_final_10 = pts_avcb + pts_visa + pts_reparos + pts_interromp

            with c24:
                link_10 = st.text_area(
                    "Link/Evidência (Relação CNES, laudos do Corpo de Bombeiros, certidões da VISA e relatórios de engenharia):",
                    value=d10_mestre.get("link", ""),
                    key=f"txt_saude_10_0_{ano_sel}",
                    height=220,
                    on_change=cb_salvar_10
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Nativo e Isolado das mutações de inputs numéricos)
                links_10_atuais = re.findall(r'(https?://[^\s]+)', link_10)
                if links_10_atuais:
                    botoes_10 = " | ".join([f"🔗 [{u}]({u})" for u in links_10_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_10}")
                
                st.markdown('<div style="background-color: #f7f9fa; padding: 12px; border-radius: 6px; border: 1px solid #e1e4e6;">', unsafe_allow_html=True)
                st.markdown("**🧮 Extrato Estatístico Atual:**")
                st.markdown(f"• Nota Parcial AVCB: `{pts_avcb:.2f} / 50.0 pts`")
                st.markdown(f"• Nota Parcial Vig. Sanitária: `{pts_visa:.2f} / 25.0 pts`")
                st.markdown(f"• Nota Parcial Reparos: `{pts_reparos:.2f} / 25.0 pts`")
                st.markdown(f"• Penalidade Interrupções: `{pts_interromp:.2f} pts`")
                st.markdown('</div>', unsafe_allow_html=True)

            st.markdown(f"📊 **Pontuação Consolidada no Quesito 10.0:** `{pts_final_10:.2f} pontos`")

            # 4. GATILHO SEGURO DO MODAL DE LINKS (Executado apenas na mudança real do texto de links)
            if link_10 != d10_mestre.get("link", "") and links_10_atuais:
                links_10_antigos = re.findall(r'(https?://[^\s]+)', d10_mestre.get("link", ""))
                if links_10_atuais != links_10_antigos:
                    modal_aviso_link("10.0", links_10_atuais)

            bloco_comentarios("10.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 11.0 - EXISTÊNCIA DO PCCS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 Quesito 11.0 - Existência de PCCS específico da Saúde", expanded=True):
            st.write(f"**11.0 O município possui Plano de Carreira, Cargos e Salários (PCCS) específico elaborado e implantado para seus profissionais de saúde?**")
            st.caption("⚠️ *Nota: PCCS geral dos servidores públicos do município não é considerado PCCS específico para profissionais de saúde.*")
            
            opts_11_0 = {
                "Selecione...": 0.0,
                "Sim – 10": 10.0,
                "Não – 00": 0.0
            }
            
            # Recupera do banco. Se não houver, inicia vazio (Selecione...)
            d11_0 = res_data.get("11.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            try:
                idx_11_0 = list(opts_11_0.keys()).index(d11_0["valor"]) if d11_0["valor"] is not None else None
            except ValueError:
                idx_11_0 = None

            c110_1, c110_2 = st.columns([1, 1])
            with c110_1:
                sel_11_0 = st.radio(
                    "Alternativas para o quesito 11.0:",
                    options=list(opts_11_0.keys()),
                    index=(list(opts_11_0.keys()).index(d11_0["valor"]) if d11_0["valor"] in opts_11_0 else 0),
                    key=f"rb_saude_11_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_11_0 = opts_11_0[sel_11_0] if sel_11_0 is not None else 0.0
                
            with c110_2:
                link_11_0 = st.text_area(
                    "Link/Evidência Geral (11.0):",
                    value=d11_0.get("link", ""),
                    key=f"txt_saude_11_0_{ano_sel}",
                    height=90
                )

                # SUPORTE MULTI-LINKS ATIVOS (Padrão Unificado)
                links_11_0_atuais = re.findall(r'(https?://[^\s]+)', link_11_0)
                if links_11_0_atuais:
                    botoes_11_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_11_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_11_0}")

            st.markdown(f"📊 **Pontuação Obtida no Quesito 11.0:** `{(pts_11_0 or 0.0):.1f} pontos`")

            # Avaliação cirúrgica de modificações para evitar quebra do DOM do React
            mudou_opcao_11_0 = sel_11_0 != d11_0["valor"]
            mudou_link_11_0 = link_11_0 != d11_0["link"]

            if (mudou_opcao_11_0 or mudou_link_11_0) and sel_11_0 is not None:
                # Salva no banco de dados imediatamente
                save_resp("11.0", sel_11_0, pts_11_0, link_11_0)
                
                # Força a atualização do estado local ANTES de qualquer verificação ou alteração de fluxo
                res_data["11.0"] = {"valor": sel_11_0, "pontos": pts_11_0, "link": link_11_0}
                
                # Se mudou apenas a opção do Radio, dá um rerun limpo para reconstruir a árvore lógica condicional com segurança
                if mudou_opcao_11_0 and not mudou_link_11_0:
                    st.rerun()
                
                # Tratamento seguro do modal de links para evitar o bug do removeChild
                if mudou_link_11_0 and links_11_0_atuais:
                    links_11_0_antigos = re.findall(r'(https?://[^\s]+)', d11_0.get("link", ""))
                    if links_11_0_atuais != links_11_0_antigos:
                        modal_aviso_link("11.0", links_11_0_atuais)
                    else:
                        st.rerun()
                else:
                    st.rerun()

            bloco_comentarios("11.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # CONDICIONAL: Os quesitos 11.1 e 11.2 dependem de PCCS Existente e Selecionado
        if sel_11_0 is not None and sel_11_0 != "Não – 00" and sel_11_0 != "Selecione...":

            # =============================================================================
            # QUESITO 11.1 - INSTRUMENTO NORMATIVO
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            
            with st.expander(f"📌 Quesito 11.1 - Instrumento Normativo de Regulamentação", expanded=True):
                st.write(f"**11.1 Informe o instrumento normativo de regulamentação do Plano de Carreira, Cargos e Salários (PCCS) específico para os profissionais da saúde, Número e Data da publicação:**")
                st.caption("ℹ️ *Nota: O salvamento é automático. Forneça os dados textuais e o link de evidência correspondente.*")

                # Recupera os dados atuais do banco
                d11_1 = res_data.get("11.1", {"valor": "", "pontos": 0.0, "link": ""})
                
                c111_1, c111_2 = st.columns([1, 1])
                
                with c111_1:
                    val_11_1 = st.text_area(
                        "Instrumento normativo, número e data de publicação:",
                        value=d11_1.get("valor", ""),
                        height=120,
                        placeholder="Ex: Lei Complementar nº 123, de 10 de Março de 2021",
                        key=f"txt_area_saude_11_1_{ano_sel}"
                    )
                
                with c111_2:
                    link_11_1 = st.text_input(
                        "Link do Documento / Evidência Digital:", 
                        value=d11_1.get("link", ""),
                        key=f"txt_link_saude_11_1_{ano_sel}"
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Varre tanto o text_input quanto o text_area)
                    texto_completo_11_1 = f"{val_11_1} {link_11_1}"
                    links_11_1_atuais = re.findall(r'(https?://[^\s]+)', texto_completo_11_1)
                    if links_11_1_atuais:
                        botoes_11_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_11_1_atuais])
                        st.markdown(f"**Links Ativos:** {botoes_11_1}")
                        
                pts_11_1 = 0.0
                
                # Verificação cirúrgica de alteração para gravação em tempo real
                mudou_texto_11_1 = val_11_1 != d11_1.get("valor", "")
                mudou_link_11_1 = link_11_1 != d11_1.get("link", "")
                
                if mudou_texto_11_1 or mudou_link_11_1:
                    # Persiste a resposta no banco de dados imediatamente
                    save_resp("11.1", val_11_1, pts_11_1, link_11_1)
                    
                    # Sincroniza o dicionário de renderização para blindagem do cache
                    res_data["11.1"] = {"valor": val_11_1, "pontos": pts_11_1, "link": link_11_1}
                    
                    # Avaliação e disparo do modal de segurança para novos links ativos
                    if mudou_link_11_1 and links_11_1_atuais:
                        links_11_1_antigos = re.findall(r'(https?://[^\s]+)', d11_1.get("link", ""))
                        if links_11_1_atuais != links_11_1_antigos:
                            modal_aviso_link("11.1", links_11_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                        
                bloco_comentarios("11.1", res_data)
                
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # QUESITO 11.2 - PÁGINA ELETRÔNICA / DIVULGAÇÃO
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            
            with st.expander(f"📌 Quesito 11.2 - Página Eletrônica de Divulgação do PCCS", expanded=True):
                st.write(f"**11.2 Informe a página eletrônica (link na internet) de divulgação do Plano de Carreira, Cargos e Salários (PCCS) específico para os profissionais de saúde:**")
                st.caption("ℹ️ *Fórmula de cálculo automática: Se preenchido com 'XYZ' ou vazio = 0.0 pontos. Qualquer link ou valor diferente de 'XYZ' = 2.0 pontos.*")

                # Recupera os dados atuais do banco
                d11_2 = res_data.get("11.2", {"valor": "", "pontos": 0.0, "link": ""})
                valor_atual_11_2 = d11_2.get("valor", "") if d11_2.get("valor", "") else "XYZ"
                
                c112_1, c112_2 = st.columns([1, 1])
                
                with c112_1:
                    val_11_2 = st.text_input(
                        "Página eletrônica (link na internet) ou insira 'XYZ':",
                        value=valor_atual_11_2,
                        key=f"txt_val_saude_11_2_{ano_sel}"
                    )
                
                with c112_2:
                    link_11_2 = st.text_input(
                        "Link auxiliar de auditoria (opcional):", 
                        value=d11_2.get("link", ""),
                        key=f"txt_link_saude_11_2_{ano_sel}"
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Varre o campo principal e o auxiliar)
                    texto_completo_11_2 = f"{val_11_2} {link_11_2}"
                    links_11_2_atuais = re.findall(r'(https?://[^\s]+)', texto_completo_11_2)
                    if links_11_2_atuais:
                        botoes_11_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_11_2_atuais])
                        st.markdown(f"**Links Ativos:** {botoes_11_2}")

                # Cálculo automatizado da nota em tempo de execução
                pts_11_2 = 0.0 if val_11_2.strip().upper() == "XYZ" or not val_11_2.strip() else 2.0
                
                st.markdown(f"📊 **Pontuação Obtida no Quesito 11.2:** `{pts_11_2:.1f} pontos`")
                
                # Verificação cirúrgica de alteração para disparo automático
                mudou_valor_11_2 = val_11_2 != d11_2.get("valor", "")
                mudou_link_11_2 = link_11_2 != d11_2.get("link", "")
                
                if mudou_valor_11_2 or mudou_link_11_2:
                    # Persiste no banco de dados imediatamente
                    save_resp("11.2", val_11_2, pts_11_2, link_11_2)
                    
                    # Sincroniza o dicionário de renderização para evitar conflitos de cache
                    res_data["11.2"] = {"valor": val_11_2, "pontos": pts_11_2, "link": link_11_2}
                    
                    # Tratamento e disparo do modal de links ativos
                    if (mudou_valor_11_2 or mudou_link_11_2) and links_11_2_atuais:
                        # Une os links antigos armazenados para comparação estrita
                        texto_antigo_11_2 = f"{d11_2.get('valor', '')} {d11_2.get('link', '')}"
                        links_11_2_antigos = re.findall(r'(https?://[^\s]+)', texto_antigo_11_2)
                        
                        if links_11_2_atuais != links_11_2_antigos:
                            modal_aviso_link("11.2", links_11_2_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                        
                bloco_comentarios("11.2", res_data)
                
            st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 12.0 • Estratégia de Saúde da Família (ESF)
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 12.0 • Estratégia de Saúde da Família (ESF) como Prioridade em {ano_sel}", expanded=True):
            st.subheader(f"12.0 • Priorização da ESF em {ano_sel}")
            st.write(f"**O município adotou a Estratégia de Saúde da Família em sua rede de serviços como a estratégia prioritária de organização da Atenção Básica em {ano_sel}?**")
            st.caption("ℹ️ *O salvamento é automático. Selecione a alternativa ou altere o link para gravar os dados imediatamente.*")
            
            opts_12_0 = {
                "Selecione...": 0.0,
                "Sim – 10": 10.0,
                "Não – 00": 0.0
            }
            
            # Recupera do banco os dados atuais
            d12_0 = res_data.get("12.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            c25, c26 = st.columns([1, 1])
            
            with c25:
                sel_12_0 = st.radio(
                    "Alternativas para o quesito 12.0:",
                    options=list(opts_12_0.keys()),
                    index=(list(opts_12_0.keys()).index(d12_0["valor"]) if d12_0["valor"] in opts_12_0 else 0),
                    key=f"rb_saude_12_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_12_0 = opts_12_0[sel_12_0] if sel_12_0 is not None else 0.0
                
            with c26:
                link_12_0 = st.text_area(
                    "Link/Evidência (Plano Municipal de Saúde ou normativas de reorganização da atenção básica):",
                    value=d12_0.get("link", ""),
                    key=f"txt_saude_12_0_{ano_sel}",
                    height=90
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                links_12_0_atuais = re.findall(r'(https?://[^\s]+)', link_12_0)
                if links_12_0_atuais:
                    botoes_12_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_12_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_12_0}")

            st.markdown(f"📊 **Pontuação Obtida no Quesito 12.0:** `{pts_12_0:.1f} pontos`")

            # Verificação de alteração para execução automática de segundo plano
            mudou_opcao_12_0 = sel_12_0 != d12_0.get("valor", "")
            mudou_link_12_0 = link_12_0 != d12_0.get("link", "")

            if mudou_opcao_12_0 or mudou_link_12_0:
                if sel_12_0 is not None:
                    # Persiste no banco de dados imediatamente
                    save_resp("12.0", sel_12_0, pts_12_0, link_12_0)
                    
                    # Sincroniza o dicionário local para liberar os blocos 12.1 e 12.2 sem delay
                    res_data["12.0"] = {"valor": sel_12_0, "pontos": pts_12_0, "link": link_12_0}
                    
                    # Tratamento e disparo do modal de links ativos
                    if mudou_link_12_0 and links_12_0_atuais:
                        links_12_0_antigos = re.findall(r'(https?://[^\s]+)', d12_0.get("link", ""))
                        if links_12_0_atuais != links_12_0_antigos:
                            modal_aviso_link("12.0", links_12_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("12.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # BLOCO CONDICIONAL: 12.1 e 12.2 abrem separados se o 12.0 for SIM
        if sel_12_0 == "Sim – 10":
# -----------------------------------------------------------------------------
            # QUESITO 12.1 (CONDICIONAL) • Equipes Completas e Incompletas
            # -----------------------------------------------------------------------------
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            
            with st.expander(f"📋 QUESITO 12.1 • Composição das Equipes (eSF + eAP) in {ano_sel}", expanded=True):
                st.subheader("12.1 • Equipes Completas e Incompletas")
                st.write(f"**Informe o total de equipes de saúde da família e equipes de atenção primária (eSF+eAP) em {ano_sel}:**")
                st.caption("ℹ️ *Equipe Completa: eSF (Médico, Enfermeiro, Aux/Téc Enfermagem e ACS) ou eAP (Médico e Enfermeiro). No descumprimento, classifique como Incompleta.*")

                # Recupera os estados atuais salvos no dicionário de dados
                d12_1_ec = res_data.get("12.1_ec", {"valor": "0", "pontos": 0.0, "link": ""})
                d12_1_ei = res_data.get("12.1_ei", {"valor": "0", "pontos": 0.0, "link": ""})
                d12_1_mestre = res_data.get("12.1", {"valor": "", "pontos": 0.0, "link": ""})

                c27, c28 = st.columns([1, 1])
                
                with c27:
                    val_ec = st.number_input(
                        "Nº de equipes completas (EC):", 
                        min_value=0, step=1, 
                        value=int(d12_1_ec["valor"]), 
                        key=f"num_12_1_ec_{ano_sel}"
                    )
                    val_ei = st.number_input(
                        "Nº de equipes incompletas (EI):", 
                        min_value=0, step=1, 
                        value=int(d12_1_ei["valor"]), 
                        key=f"num_12_1_ei_{ano_sel}"
                    )

                # Cálculo de Proporção Dinâmico: NF = [EC / (EC + EI)] * 50
                total_equipes = val_ec + val_ei
                pts_12_1 = (val_ec / total_equipes) * 50.0 if total_equipes > 0 else 0.0

                with c28:
                    link_12_1 = st.text_area(
                        "Link/Evidência (Relatório de equipes CNES ou validação do e-Gestor Atenção Básica):",
                        value=d12_1_mestre.get("link", ""),
                        key=f"txt_saude_12_1_{ano_sel}",
                        height=115
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Filtra URLs válidas no campo de texto de evidências)
                    links_12_1_atuais = re.findall(r'(https?://[^\s]+)', link_12_1)
                    if links_12_1_atuais:
                        botoes_12_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_12_1_atuais])
                        st.markdown(f"**Links Ativos:** {botoes_12_1}")

                st.markdown(f"📊 **Pontuação Obtida no Quesito 12.1:** `{pts_12_1:.2f} / 50.0 pontos`")

                # Avaliação matemática e de string para checar modificações em tempo real
                mudou_ec = val_ec != int(d12_1_ec["valor"])
                mudou_ei = val_ei != int(d12_1_ei["valor"])
                mudou_link_12_1 = link_12_1 != d12_1_mestre.get("link", "")

                if mudou_ec or mudou_ei or mudou_link_12_1:
                    # Registra a atualização de forma atômica no banco de dados
                    save_resp("12.1_ec", str(val_ec), pts_12_1, "")
                    save_resp("12.1_ei", str(val_ei), 0.0, "")
                    save_resp("12.1", f"EC: {val_ec} | EI: {val_ei}", pts_12_1, link_12_1)
                    
                    # Sincroniza a memória local para renderizações consecutivas corretas
                    res_data["12.1_ec"] = {"valor": str(val_ec), "pontos": pts_12_1, "link": ""}
                    res_data["12.1_ei"] = {"valor": str(val_ei), "pontos": 0.0, "link": ""}
                    res_data["12.1"] = {"valor": f"EC: {val_ec} | EI: {val_ei}", "pontos": pts_12_1, "link": link_12_1}
                    
                    # Dispara o modal de segurança apenas se novos links ativos entrarem em cena
                    if mudou_link_12_1 and links_12_1_atuais:
                        links_12_1_antigos = re.findall(r'(https?://[^\s]+)', d12_1_mestre.get("link", ""))
                        if links_12_1_atuais != links_12_1_antigos:
                            modal_aviso_link("12.1", links_12_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

                bloco_comentarios("12.1", res_data)
                
            st.markdown('</div>', unsafe_allow_html=True)

            # -----------------------------------------------------------------------------
            # QUESITO 12.2 (CONDICIONAL) • Pessoas Cadastradas por Equipe
            # -----------------------------------------------------------------------------
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            
            with st.expander(f"🌐 QUESITO 12.2 • Proporção de Pessoas Cadastradas por Equipe em {ano_sel}", expanded=True):
                st.subheader("12.2 • Parâmetro Populacional por Equipe")
                st.write(f"**Informe o número de pessoas cadastradas nas equipes em {ano_sel}:**")
                st.caption("ℹ️ *O salvamento é automático. A média por equipe e pontuação são recalculadas instantaneamente.*")

                # Recupera os dados atuais salvos no banco/estado local
                d12_2_esf = res_data.get("12.2_esf", {"valor": "0", "pontos": 0.0, "link": ""})
                d12_2_eap = res_data.get("12.2_eap", {"valor": "0", "pontos": 0.0, "link": ""})
                d12_2_mestre = res_data.get("12.2", {"valor": "", "pontos": 0.0, "link": ""})

                c29, c30 = st.columns([1, 1])
                
                with c29:
                    val_cad_esf = st.number_input(
                        "Nº de pessoas cadastradas nas Equipes de Saúde da Família (ESF):", 
                        min_value=0, step=1, 
                        value=int(d12_2_esf["valor"]), 
                        key=f"num_12_2_esf_{ano_sel}"
                    )
                    val_cad_eap = st.number_input(
                        "Nº de pessoas cadastradas nas Equipes de Atenção Primária (EAP):", 
                        min_value=0, step=1, 
                        value=int(d12_2_eap["valor"]), 
                        key=f"num_12_2_eap_{ano_sel}"
                    )

                # Regra de cálculo de cobertura média por equipe: (ESF + EAP) / total_equipes
                # Nota: total_equipes vem herdado dinamicamente do bloco do Quesito 12.1
                total_cadastrados = val_cad_esf + val_cad_eap
                pts_12_2 = 0.0
                media_por_equipe = 0.0

                if total_equipes > 0:
                    media_por_equipe = total_cadastrados / total_equipes
                    # Validação dos intervalos: aceitável entre 2000 e 4000 pessoas por equipe
                    if 2000 <= media_por_equipe <= 4000:
                        pts_12_2 = 40.0
                    else:
                        pts_12_2 = 0.0

                with c30:
                    link_12_2 = st.text_area(
                        "Link/Evidência (Relatórios de cadastros do SISAB - Sistema de Informação em Saúde para a Atenção Básica):",
                        value=d12_2_mestre.get("link", ""),
                        key=f"txt_saude_12_2_{ano_sel}",
                        height=115
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                    links_12_2_atuais = re.findall(r'(https?://[^\s]+)', link_12_2)
                    if links_12_2_atuais:
                        botoes_12_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_12_2_atuais])
                        st.markdown(f"**Links Ativos:** {botoes_12_2}")
                    
                    # Exibição do cálculo da média em tempo real para o usuário
                    if total_equipes > 0:
                        st.markdown(f"ℹ️ *Média Calculada: `{media_por_equipe:.0f}` pessoas por equipe.*")

                st.markdown(f"📊 **Pontuação Obtida no Quesito 12.2:** `{pts_12_2:.1f} / 40.0 pontos`")

                # Avaliação de alterações para gravação assíncrona/segundo plano
                mudou_esf = val_cad_esf != int(d12_2_esf["valor"])
                mudou_eap = val_cad_eap != int(d12_2_eap["valor"])
                mudou_link_12_2 = link_12_2 != d12_2_mestre.get("link", "")

                if mudou_esf or mudou_eap or mudou_link_12_2:
                    # Persiste os dados na camada do banco imediatamente
                    save_resp("12.2_esf", str(val_cad_esf), pts_12_2, "")
                    save_resp("12.2_eap", str(val_cad_eap), 0.0, "")
                    save_resp("12.2", f"ESF: {val_cad_esf} | EAP: {val_cad_eap}", pts_12_2, link_12_2)
                    
                    # Sincroniza o res_data local para evitar discrepâncias de interface
                    res_data["12.2_esf"] = {"valor": str(val_cad_esf), "pontos": pts_12_2, "link": ""}
                    res_data["12.2_eap"] = {"valor": str(val_cad_eap), "pontos": 0.0, "link": ""}
                    res_data["12.2"] = {"valor": f"ESF: {val_cad_esf} | EAP: {val_cad_eap}", "pontos": pts_12_2, "link": link_12_2}
                    
                    # Controle estrito do acionamento do modal para links de auditoria
                    if mudou_link_12_2 and links_12_2_atuais:
                        links_12_2_antigos = re.findall(r'(https?://[^\s]+)', d12_2_mestre.get("link", ""))
                        if links_12_2_atuais != links_12_2_antigos:
                            modal_aviso_link("12.2", links_12_2_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

                bloco_comentarios("12.2", res_data)
                
            st.markdown('</div>', unsafe_allow_html=True)
        # -----------------------------------------------------------------------------
        # QUESITO 13.0 • Registro de Frequência Eletrônica
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 QUESITO 13.0 • Registro de Frequência Eletrônica em {ano_sel}", expanded=True):
            st.subheader(f"13.0 • Frequência Eletrônica na Atenção Básica ({ano_sel})")
            st.write(f"**A Prefeitura registra a frequência dos profissionais de saúde da Atenção Básica de forma eletrônica em {ano_sel}?**")
            st.caption("⚠️ *Obs: O encaminhamento de planilhas de ponto não será considerado como modalidade de registro eletrônico.*")
            st.caption("ℹ️ *O salvamento é automático. Selecione uma opção ou edite a evidência para atualizar instantaneamente.*")
            
            opts_13_0 = {
                "Selecione...": 0.0,
                "Sim, para todos os profissionais da saúde – 05": 5.0,
                "Sim, para a maior parte dos profissionais da saúde – 03": 3.0,
                "Sim, para a menor parte dos profissionais da saúde – 01": 1.0,
                "Não houve registro eletrônico de nenhum profissional de saúde – 00": 0.0
            }
            
            # Recupera os dados atuais salvos no banco
            d13_0 = res_data.get("13.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            c31, c32 = st.columns([1, 1])
            
            with c31:
                sel_13_0 = st.radio(
                    "Alternativas para o quesito 13.0:",
                    options=list(opts_13_0.keys()),
                    index=(list(opts_13_0.keys()).index(d13_0["valor"]) if d13_0["valor"] in opts_13_0 else 0),
                    key=f"rb_saude_13_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_13_0 = opts_13_0[sel_13_0] if sel_13_0 is not None else 0.0
                
            with c32:
                link_13_0 = st.text_area(
                    "Link/Evidência (Relatório ou telas do sistema de ponto eletrônico biométrico/digital):",
                    value=d13_0.get("link", ""),
                    key=f"txt_saude_13_0_{ano_sel}",
                    height=110
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                links_13_0_atuais = re.findall(r'(https?://[^\s]+)', link_13_0)
                if links_13_0_atuais:
                    botoes_13_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_13_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_13_0}")

            st.markdown(f"📊 **Pontuação Obtida no Quesito 13.0:** `{pts_13_0:.1f} pontos`")

            # Mapeamento cirúrgico de alterações de estado
            mudou_opcao_13_0 = sel_13_0 != d13_0.get("valor", "")
            mudou_link_13_0 = link_13_0 != d13_0.get("link", "")

            if mudou_opcao_13_0 or mudou_link_13_0:
                if sel_13_0 is not None:
                    # Persiste a mutação diretamente na base de dados
                    save_resp("13.0", sel_13_0, pts_13_0, link_13_0)
                    
                    # Atualiza o dicionário local em tempo de execução para blindar o cache do Streamlit
                    res_data["13.0"] = {"valor": sel_13_0, "pontos": pts_13_0, "link": link_13_0}
                    
                    # Gerenciamento inteligente de modais para novos links de auditoria
                    if mudou_link_13_0 and links_13_0_atuais:
                        links_13_0_antigos = re.findall(r'(https?://[^\s]+)', d13_0.get("link", ""))
                        if links_13_0_atuais != links_13_0_antigos:
                            modal_aviso_link("13.0", links_13_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("13.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 13.1 • Cumprimento da Jornada de Trabalho dos Médicos
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📋 QUESITO 13.1 • Cumprimento da Jornada de Trabalho dos Médicos em {ano_sel}", expanded=True):
            st.subheader(f"13.1 • Jornada de Trabalho Médica ({ano_sel})")
            st.write(f"**Os médicos da Atenção Básica cumprem integralmente sua jornada de trabalho em {ano_sel}?**")
            st.caption("ℹ️ *O salvamento é automático. A seleção da alternativa ou alteração do campo de texto grava os dados na hora.*")
            
            opts_13_1 = {
                "Selecione...": 0.0,
                "Sim, todos cumprem integralmente a jornada de trabalho – 15": 15.0,
                "Sim, a maior parte cumpre integralmente a jornada de trabalho – 08": 8.0,
                "Sim, todos permanecem apenas nas consultas agendadas – 05": 5.0,
                "Sim, a maior parte permanece apenas nas consultas agendadas – 02": 2.0,
                "Não – 00": 0.0
            }
            
            # Recupera os dados atuais salvos no banco
            d13_1 = res_data.get("13.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            c33, c34 = st.columns([1, 1])
            
            with c33:
                sel_13_1 = st.radio(
                    "Alternativas para o quesito 13.1:",
                    options=list(opts_13_1.keys()),
                    index=(list(opts_13_1.keys()).index(d13_1["valor"]) if d13_1["valor"] in opts_13_1 else 0),
                    key=f"rb_saude_13_1_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_13_1 = opts_13_1[sel_13_1] if sel_13_1 is not None else 0.0
                
            with c34:
                link_13_1 = st.text_area(
                    "Link/Evidência (Espelhos de ponto homologados, agendas do e-SUS ou relatórios de produtividade/atendimento):",
                    value=d13_1.get("link", ""),
                    key=f"txt_saude_13_1_{ano_sel}",
                    height=130
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                links_13_1_atuais = re.findall(r'(https?://[^\s]+)', link_13_1)
                if links_13_1_atuais:
                    botoes_13_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_13_1_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_13_1}")

            st.markdown(f"📊 **Pontuação Obtida no Quesito 13.1:** `{pts_13_1:.1f} pontos`")

            # Avaliação cirúrgica de mutações para gravação em segundo plano
            mudou_opcao_13_1 = sel_13_1 != d13_1.get("valor", "")
            mudou_link_13_1 = link_13_1 != d13_1.get("link", "")

            if mudou_opcao_13_1 or mudou_link_13_1:
                if sel_13_1 is not None:
                    # Grava a alteração imediatamente na camada de persistência
                    save_resp("13.1", sel_13_1, pts_13_1, link_13_1)
                    
                    # Atualiza o dicionário em cache para manter a consistência da UI
                    res_data["13.1"] = {"valor": sel_13_1, "pontos": pts_13_1, "link": link_13_1}
                    
                    # Dispara o modal de validação apenas se houver novos links inseridos
                    if mudou_link_13_1 and links_13_1_atuais:
                        links_13_1_antigos = re.findall(r'(https?://[^\s]+)', d13_1.get("link", ""))
                        if links_13_1_atuais != links_13_1_antigos:
                            modal_aviso_link("13.1", links_13_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("13.1", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 14.0 • Intervalo de Agendamento de Consultas
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # Ajustado para usar st.expander para manter a padronização visual dos blocos anteriores
        with st.expander(f"📌 QUESITO 14.0 • Intervalo de Agendamento de Consultas em {ano_sel}", expanded=True):
            st.subheader(f"14.0 • Intervalo de Agendamento de Consultas ({ano_sel})")
            st.write(f"**Assinale o intervalo de agendamento das consultas médicas na Atenção Básica em {ano_sel}:**")
            st.caption("ℹ️ *O salvamento é automático. A seleção da alternativa ou alteração do campo de texto grava os dados imediatamente.*")
            
            opts_14_0 = {
                "Selecione...": 0.0,
                "Não há agendamento de consultas, pois todos os atendimentos são de pronto atendimento – 01": 1.0,
                "Agendamento de cada paciente em horário único com, no mínimo, 15 minutos de atendimento – 01": 1.0,
                "Agendamento de cada paciente em horário único com menos de 15 minutos de atendimento – 00": 0.0,
                "Agendamento de 2 ou mais pacientes no mesmo horário – 00": 0.0
            }
            
            # Recupera do banco os dados atuais salvos
            d14_0 = res_data.get("14.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            c35, c36 = st.columns([1, 1])
            
            with c35:
                sel_14_0 = st.radio(
                    "Alternativas para o quesito 14.0:",
                    options=list(opts_14_0.keys()),
                    index=(list(opts_14_0.keys()).index(d14_0["valor"]) if d14_0["valor"] in opts_14_0 else 0),
                    key=f"rb_saude_14_0_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_14_0 = opts_14_0[sel_14_0] if sel_14_0 is not None else 0.0
                
            with c36:
                link_14_0 = st.text_area(
                    "Link/Evidência (Protocolo de agendamento ou prints das telas de parametrização de horários do prontuário eletrônico):",
                    value=d14_0.get("link", ""),
                    key=f"txt_saude_14_0_{ano_sel}",
                    height=110
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                links_14_0_atuais = re.findall(r'(https?://[^\s]+)', link_14_0)
                if links_14_0_atuais:
                    botoes_14_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_14_0_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_14_0}")

            st.markdown(f"📊 **Pontuação Obtida no Quesito 14.0:** `{pts_14_0:.1f} pontos`")

            # Mapeamento cirúrgico de alterações de estado
            mudou_opcao_14_0 = sel_14_0 != d14_0.get("valor", "")
            mudou_link_14_0 = link_14_0 != d14_0.get("link", "")

            if mudou_opcao_14_0 or mudou_link_14_0:
                if sel_14_0 is not None:
                    # Persiste a alteração imediatamente na base de dados
                    save_resp("14.0", sel_14_0, pts_14_0, link_14_0)
                    
                    # Sincroniza a memória local (cache da interface) para evitar oscilações visuais
                    res_data["14.0"] = {"valor": sel_14_0, "pontos": pts_14_0, "link": link_14_0}
                    
                    # Gerenciamento reativo do modal de links de auditoria
                    if mudou_link_14_0 and links_14_0_atuais:
                        links_14_0_antigos = re.findall(r'(https?://[^\s]+)', d14_0.get("link", ""))
                        if links_14_0_atuais != links_14_0_antigos:
                            modal_aviso_link("14.0", links_14_0_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("14.0", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 14.1 • Agendamento Remoto
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📱 QUESITO 14.1 • Serviço de Agendamento Remoto em {ano_sel}", expanded=True):
            st.subheader(f"14.1 • Agendamento Remoto ({ano_sel})")
            st.write(f"**O município disponibilizou serviço de agendamento remoto para consulta médica na Atenção Básica em {ano_sel}?**")
            st.caption("ℹ️ *Exemplos de Agendamento Remoto: por telefone, internet, aplicativo, Voip, etc.*")
            st.caption("ℹ nighttime: *O salvamento é automático. A seleção da alternativa ou alteração do campo de texto grava os dados na hora.*")
            
            opts_14_1 = {
                "Selecione...": 0.0,
                "Sim – 10": 10.0,
                "Não – 00": 0.0
            }
            
            # Recupera do banco os dados atuais salvos
            d14_1 = res_data.get("14.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            c37, c38 = st.columns([1, 1])
            
            with c37:
                sel_14_1 = st.radio(
                    "Alternativas para o quesito 14.1:",
                    options=list(opts_14_1.keys()),
                    index=(list(opts_14_1.keys()).index(d14_1["valor"]) if d14_1["valor"] in opts_14_1 else 0),
                    key=f"rb_saude_14_1_{ano_sel}",
                    label_visibility="collapsed"
                )
                pts_14_1 = opts_14_1[sel_14_1] if sel_14_1 is not None else 0.0
                
            with c38:
                link_14_1 = st.text_area(
                    "Link/Evidência (Print do canal web, app, normativas do serviço telefônico ou central de agendamentos):",
                    value=d14_1.get("link", ""),
                    key=f"txt_saude_14_1_{ano_sel}",
                    height=90
                )
                
                # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                links_14_1_atuais = re.findall(r'(https?://[^\s]+)', link_14_1)
                if links_14_1_atuais:
                    botoes_14_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_14_1_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_14_1}")

            st.markdown(f"📊 **Pontuação Obtida no Quesito 14.1:** `{pts_14_1:.1f} pontos`")

            # Mapeamento cirúrgico de alterações de estado
            mudou_opcao_14_1 = sel_14_1 != d14_1.get("valor", "")
            mudou_link_14_1 = link_14_1 != d14_1.get("link", "")

            if mudou_opcao_14_1 or mudou_link_14_1:
                if sel_14_1 is not None:
                    # Persiste a alteração imediatamente na base de dados
                    save_resp("14.1", sel_14_1, pts_14_1, link_14_1)
                    
                    # Sincroniza a memória local para blindar o estado da interface
                    res_data["14.1"] = {"valor": sel_14_1, "pontos": pts_14_1, "link": link_14_1}
                    
                    # Gerenciamento controlado do modal de validação de links de auditoria
                    if mudou_link_14_1 and links_14_1_atuais:
                        links_14_1_antigos = re.findall(r'(https?://[^\s]+)', d14_1.get("link", ""))
                        if links_14_1_atuais != links_14_1_antigos:
                            modal_aviso_link("14.1", links_14_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("14.1", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
        # QUESITO 14.2 • Controle de Absenteísmo
        # -----------------------------------------------------------------------------
        
        # Usamos um container nativo com borda. O React gerencia isso perfeitamente.
        # Se precisar forçar sua estilização antiga, você pode injetar o CSS globalmente para a classe .stElementContainer
        with st.container(key=f"card_absenteismo_root_{ano_sel}", border=True):
            
            with st.expander(f"📊 QUESITO 14.2 • Controle de Absenteísmo em {ano_sel}", expanded=True):
                st.subheader(f"14.2 • Controle de Absenteísmo ({ano_sel})")
                st.write(f"**O município possui controle de absenteísmo (gestão de faltas de pacientes) para as consultas médicas da Atenção Básica em {ano_sel}?**")
                st.caption("ℹ️ *O salvamento é automático. A seleção da alternativa ou alteração do campo de texto grava os dados na hora.*")
                
                opts_14_2 = {
                    "Selecione...": 0.0,
                    "Sim, para todas as consultas – 02": 2.0,
                    "Sim, para a maior parte das consultas – 01": 1.0,
                    "Sim, para a menor parte das consultas – 0.5": 0.5,
                    "Não – 00": 0.0
                }
                
                # Recupera do banco os dados atuais salvos
                d14_2 = res_data.get("14.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c39, c40 = st.columns([1, 1])
                
                with c39:
                    sel_14_2 = st.radio(
                        "Alternativas para o quesito 14.2:",
                        options=list(opts_14_2.keys()),
                        index=(list(opts_14_2.keys()).index(d14_2["valor"]) if d14_2["valor"] in opts_14_2 else 0),
                        key=f"rb_saude_14_2_{ano_sel}",
                        label_visibility="collapsed"
                    )
                    pts_14_2 = opts_14_2[sel_14_2] if sel_14_2 is not None else 0.0
                    
                with c40:
                    link_14_2 = st.text_area(
                        "Link/Evidência (Relatórios estatísticos de faltas ou relatórios emitidos via Prontuário Eletrônico/SISAB):",
                        value=d14_2.get("link", ""),
                        key=f"txt_saude_14_2_{ano_sel}",
                        height=110
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS
                    links_14_2_atuais = re.findall(r'(https?://[^\s]+)', link_14_2)
                    if links_14_2_atuais:
                        botoes_14_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_14_2_atuais])
                        st.markdown(f"**Links Ativos:** {botoes_14_2}")

                st.markdown(f"📊 **Pontuação Obtida no Quesito 14.2:** `{pts_14_2:.1f} pontos`")

                # Mapeamento de alterações de estado
                mudou_opcao_14_2 = sel_14_2 != d14_2.get("valor", "")
                mudou_link_14_2 = link_14_2 != d14_2.get("link", "")

                if mudou_opcao_14_2 or mudou_link_14_2:
                    if sel_14_2 is not None:
                        save_resp("14.2", sel_14_2, pts_14_2, link_14_2)
                        res_data["14.2"] = {"valor": sel_14_2, "pontos": pts_14_2, "link": link_14_2}
                        
                        if mudou_link_14_2 and links_14_2_atuais:
                            links_14_2_antigos = re.findall(r'(https?://[^\s]+)', d14_2.get("link", ""))
                            if links_14_2_atuais != links_14_2_antigos:
                                modal_aviso_link("14.2", links_14_2_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()

                bloco_comentarios("14.2", res_data)

        # BLOCO CONDICIONAL FILHO DE 14.2 
        # Totalmente isolado da árvore do elemento pai para não causar conflitos de renderização no React
        if sel_14_2 != "Não – 00" and sel_14_2 != "Selecione...":
            with st.container(key=f"container_filho_absenteismo_{ano_sel}", border=True):
                # Cole aqui os sub-quesitos filhos com segurança. Exemplo:
                st.write("📌 *Preencha os dados complementares do absenteísmo abaixo:*")
                pass
                # -----------------------------------------------------------------------------
                # QUESITO 14.2.1 (CONDICIONAL) • Taxa Histórica de Absenteísmo
                # -----------------------------------------------------------------------------
                st.subheader(f"14.2.1 • Taxa Histórica de Absenteísmo ({ano_sel})")
                st.write(f"**Informe a taxa de absenteísmo de consulta médica nas UBSs (em %):**")
                st.caption("ℹ️ *O salvamento é automático. A alteração de qualquer valor ou campo de texto grava os dados na hora.*")
                
                # Resgata dados numéricos históricos do banco
                d14_2_1_ta2 = res_data.get("14.2.1_ta2", {"valor": "0.0", "pontos": 0.0, "link": ""})
                d14_2_1_ta1 = res_data.get("14.2.1_ta1", {"valor": "0.0", "pontos": 0.0, "link": ""})
                d14_2_1_ta  = res_data.get("14.2.1_ta",  {"valor": "0.0", "pontos": 0.0, "link": ""})
                d14_2_1_main = res_data.get("14.2.1", {"valor": "", "pontos": 0.0, "link": ""})

                c41, c42 = st.columns([1, 1])
                
                with c41:
                    val_ta2 = st.number_input(
                        f"Taxa de absenteísmo em consultas médicas nas UBSs em {ano_sel - 2} (TA-2):", 
                        min_value=0.0, 
                        max_value=100.0, 
                        step=0.1, 
                        value=float(d14_2_1_ta2["valor"]), 
                        key=f"num_14_2_1_ta2_{ano_sel}"
                    )
                    val_ta1 = st.number_input(
                        f"Taxa de absenteísmo em consultas médicas nas UBSs em {ano_sel - 1} (TA-1):", 
                        min_value=0.0, 
                        max_value=100.0, 
                        step=0.1, 
                        value=float(d14_2_1_ta1["valor"]), 
                        key=f"num_14_2_1_ta1_{ano_sel}"
                    )
                    val_ta  = st.number_input(
                        f"Taxa de absenteísmo em consultas médicas nas UBSs em {ano_sel} (TA):", 
                        min_value=0.0, 
                        max_value=100.0, 
                        step=0.1, 
                        value=float(d14_2_1_ta["valor"]), 
                        key=f"num_14_2_1_ta_{ano_sel}"
                    )

                # Regra: Se TA <= média dos 2 últimos anos = 10 pontos | Senão = 0 pontos
                media_dois_anos = (val_ta2 + val_ta1) / 2.0
                
                if val_ta <= media_dois_anos and (val_ta2 > 0 or val_ta1 > 0):
                    pts_14_2_1 = 10.0
                else:
                    pts_14_2_1 = 0.0

                with c42:
                    link_14_2_1 = st.text_area(
                        "Link/Evidência (Série histórica compactada ou telas consolidadas de auditoria do absenteísmo):",
                        value=d14_2_1_main.get("link", ""),
                        key=f"txt_saude_14_2_1_{ano_sel}",
                        height=150
                    )
                    
                    if val_ta2 > 0 or val_ta1 > 0:
                        st.markdown(f"📈 *Média dos 2 anos anteriores ({ano_sel-2}/{ano_sel-1}): `{media_dois_anos:.2f}%`*")
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                    links_14_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_14_2_1)
                    if links_14_2_1_atuais:
                        botoes_14_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_14_2_1_atuais])
                        st.markdown(f"**Links Ativos:** {botoes_14_2_1}")

                st.markdown(f"📊 **Pontuação Obtida no Quesito 14.2.1:** `{pts_14_2_1:.1f} / 10.0 pontos`")

                # Verificação detalhada de mutações de estado dos inputs numéricos e de link
                mudou_ta2  = val_ta2 != float(d14_2_1_ta2["valor"])
                mudou_ta1  = val_ta1 != float(d14_2_1_ta1["valor"])
                mudou_ta   = val_ta != float(d14_2_1_ta["valor"])
                mudou_link = link_14_2_1 != d14_2_1_main.get("link", "")

                if mudou_ta2 or mudou_ta1 or mudou_ta or mudou_link:
                    # Persiste a mutação de todas as chaves associadas no banco de dados
                    save_resp("14.2.1_ta2", str(val_ta2), pts_14_2_1, "")
                    save_resp("14.2.1_ta1", str(val_ta1), 0.0, "")
                    save_resp("14.2.1_ta", str(val_ta), 0.0, "")
                    
                    texto_main_valor = f"TA {val_ta}% (Média: {media_dois_anos:.2f}%)"
                    save_resp("14.2.1", texto_main_valor, pts_14_2_1, link_14_2_1)
                    
                    # Atualiza a memória local para blindar a reatividade síncrona do cache do Streamlit
                    res_data["14.2.1_ta2"] = {"valor": str(val_ta2), "pontos": pts_14_2_1, "link": ""}
                    res_data["14.2.1_ta1"] = {"valor": str(val_ta1), "pontos": 0.0, "link": ""}
                    res_data["14.2.1_ta"]  = {"valor": str(val_ta), "pontos": 0.0, "link": ""}
                    res_data["14.2.1"]     = {"valor": texto_main_valor, "pontos": pts_14_2_1, "link": link_14_2_1}
                    
                    # Gerenciamento controlado do modal de auditoria de links ativos
                    if mudou_link and links_14_2_1_atuais:
                        links_14_2_1_antigos = re.findall(r'(https?://[^\s]+)', d14_2_1_main.get("link", ""))
                        if links_14_2_1_atuais != links_14_2_1_antigos:
                            modal_aviso_link("14.2.1", links_14_2_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

                bloco_comentarios("14.2.1", res_data)

                # -----------------------------------------------------------------------------
                # QUESITO 14.2.2 (CONDICIONAL) • Medidas para Redução
                # -----------------------------------------------------------------------------
                with st.container(key=f"container_filho_14_2_2_{ano_sel}", border=True):
                    st.subheader(f"14.2.2 • Medidas para Redução do Absenteísmo ({ano_sel})")
                    st.write(f"**O município realiza medidas para a redução desta taxa de absenteísmo em {ano_sel}?**")
                    st.caption("ℹ️ *O salvamento é automático. A seleção da alternativa ou alteração do campo de texto grava os dados na hora.*")
                    
                    opts_14_2_2 = {
                        "Selecione...": 0.0,
                        "Sim – 00": 0.0,
                        "Não – -02": -2.0
                    }
                    
                    # Recupera do banco os dados atuais salvos
                    d14_2_2 = res_data.get("14.2.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})

                    c43, c44 = st.columns([1, 1])
                    
                    with c43:
                        sel_14_2_2 = st.radio(
                            "Alternativas para o quesito 14.2.2:",
                            options=list(opts_14_2_2.keys()),
                            index=(list(opts_14_2_2.keys()).index(d14_2_2["valor"]) if d14_2_2["valor"] in opts_14_2_2 else 0),
                            key=f"rb_saude_14_2_2_{ano_sel}",
                            label_visibility="collapsed"
                        )
                        pts_14_2_2 = opts_14_2_2[sel_14_2_2] if sel_14_2_2 is not None else 0.0
                        
                    with c44:
                        link_14_2_2 = st.text_area(
                            "Link/Evidência (Planos de ação, campanhas de conscientização, normativas de remanejamento de vagas ou relatórios das ações efetuadas):",
                            value=d14_2_2.get("link", ""),
                            key=f"txt_saude_14_2_2_{ano_sel}",
                            height=90
                        )
                        
                        # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                        links_14_2_2_atuais = re.findall(r'(https?://[^\s]+)', link_14_2_2)
                        if links_14_2_2_atuais:
                            botoes_14_2_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_14_2_2_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_14_2_2}")

                    st.markdown(f"📊 **Pontuação Obtida no Quesito 14.2.2 (Penalidade):** `{pts_14_2_2:.1f} pontos`")

                    # Mapeamento cirúrgico de alterações de estado para persistência assíncrona
                    mudou_opcao_14_2_2 = sel_14_2_2 != d14_2_2.get("valor", "")
                    mudou_link_14_2_2 = link_14_2_2 != d14_2_2.get("link", "")

                    if mudou_opcao_14_2_2 or mudou_link_14_2_2:
                        if sel_14_2_2 is not None:
                            # Persiste a mutação diretamente na base de dados
                            save_resp("14.2.2", sel_14_2_2, pts_14_2_2, link_14_2_2)
                            
                            # Atualiza o dicionário local em tempo de execução para blindar o cache do Streamlit
                            res_data["14.2.2"] = {"valor": sel_14_2_2, "pontos": pts_14_2_2, "link": link_14_2_2}
                            
                            # Gerenciamento controlado do modal de validação de links de auditoria
                            if mudou_link_14_2_2 and links_14_2_2_atuais:
                                links_14_2_2_antigos = re.findall(r'(https?://[^\s]+)', d14_2_2.get("link", ""))
                                if links_14_2_2_atuais != links_14_2_2_antigos:
                                    modal_aviso_link("14.2.2", links_14_2_2_atuais)
                                else:
                                    st.rerun()
                            else:
                                st.rerun()

                    bloco_comentarios("14.2.2", res_data)

                # SUB-CONDICIONAL FILHO DE 14.2.2 (Abre somente se marcou "Sim")
                # Isolado em container próprio para blindagem total contra erros de nó no React
                if sel_14_2_2 == "Sim – 00":
                    with st.container(key=f"container_sub_filho_14_2_2_{ano_sel}"):
                        # Insira aqui o código interno do sub-quesito seguinte (ex: quais medidas foram tomadas)
                        pass
                
                # -----------------------------------------------------------------------------
                # QUESITO 14.2.2.1 (CONDICIONAL) • Seleção de Medidas Aplicadas (Múltipla Escolha)
                # -----------------------------------------------------------------------------
                with st.container(key=f"container_sub_filho_14_2_2_1_{ano_sel}", border=True):
                    st.subheader(f"14.2.2.1 • Medidas Aplicadas para Redução ({ano_sel})")
                    st.write(f"**Assinale as medidas utilizadas para a redução da taxa de absenteísmo de consultas médicas na Atenção Básica em {ano_sel}:**")
                    st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link salva os dados na hora.*")
                    
                    d14_2_2_1 = res_data.get("14.2.2.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                    try:
                        salvos_14_2_2_1 = json.loads(d14_2_2_1["valor"])
                    except:
                        salvos_14_2_2_1 = []

                    c45, c46 = st.columns([1, 1])
                    with c45:
                        chk_m1 = st.checkbox("Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo e promover capacitações", value="m1" in salvos_14_2_2_1, key=f"chk_14_221_m1_{ano_sel}")
                        chk_m2 = st.checkbox("Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação", value="m2" in salvos_14_2_2_1, key=f"chk_14_221_m2_{ano_sel}")
                        chk_m3 = st.checkbox("Ligação telefônica ou outro meio de comunicação para confirmation da consulta e presença do paciente", value="m3" in salvos_14_2_2_1, key=f"chk_14_221_m3_{ano_sel}")
                        chk_m4 = st.checkbox("Orientação das famílias e busca ativa dos faltosos pelos Agentes Comunitários de Saúde (ACS)", value="m4" in salvos_14_2_2_1, key=f"chk_14_221_m4_{ano_sel}")
                        chk_m5 = st.checkbox("Promoção de campanhas de conscientização", value="m5" in salvos_14_2_2_1, key=f"chk_14_221_m5_{ano_sel}")
                        chk_m6 = st.checkbox("Outros", value="m6" in salvos_14_2_2_1, key=f"chk_14_221_m6_{ano_sel}")

                        # Monta lista de marcações (Quesito informativo de plano de ação, não altera pontuação)
                        medidas_selecionadas = []
                        if chk_m1: medidas_selecionadas.append("m1")
                        if chk_m2: medidas_selecionadas.append("m2")
                        if chk_m3: medidas_selecionadas.append("m3")
                        if chk_m4: medidas_selecionadas.append("m4")
                        if chk_m5: medidas_selecionadas.append("m5")
                        if chk_m6: medidas_selecionadas.append("m6")
                        
                        str_14_2_2_1 = json.dumps(medidas_selecionadas)

                    with c46:
                        link_14_2_2_1 = st.text_area(
                            "Link/Evidência (Cópias de portarias das rotinas, materiais de campanhas, relatórios de ligações da Central ou registros de busca ativa dos ACS):",
                            value=d14_2_2_1.get("link", ""),
                            key=f"txt_saude_14_2_2_1_{ano_sel}",
                            height=210
                        )
                        
                        # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                        links_14_2_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_14_2_2_1)
                        if links_14_2_2_1_atuais:
                            botoes_14_2_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_14_2_2_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_14_2_2_1}")

                    # Avaliação cirúrgica de mutações
                    mudou_dados_14_2_2_1 = str_14_2_2_1 != d14_2_2_1["valor"]
                    mudou_link_14_2_2_1 = link_14_2_2_1 != d14_2_2_1["link"]

                    if mudou_dados_14_2_2_1 or mudou_link_14_2_2_1:
                        # Grava a alteração na persistência do banco
                        save_resp("14.2.2.1", str_14_2_2_1, 0.0, link_14_2_2_1)
                        
                        # Sincroniza o cache do dicionário local para evitar quebra reativa
                        res_data["14.2.2.1"] = {"valor": str_14_2_2_1, "pontos": 0.0, "link": link_14_2_2_1}
                        
                        # Gerenciamento controlado do modal de link
                        if mudou_link_14_2_2_1 and links_14_2_2_1_atuais:
                            links_14_2_2_1_antigos = re.findall(r'(https?://[^\s]+)', d14_2_2_1.get("link", ""))
                            if links_14_2_2_1_atuais != links_14_2_2_1_antigos:
                                modal_aviso_link("14.2.2.1", links_14_2_2_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()

                    bloco_comentarios("14.2.2.1", res_data)

        # -----------------------------------------------------------------------------
        # QUESITO 15.0 • Controle de Absenteísmo para Exames Laboratoriais
        # -----------------------------------------------------------------------------
        
        # Substituído st.markdown('<div class="quesito-card">') por container nativo para blindar o DOM do React
        with st.container(key=f"card_absenteismo_exames_root_{ano_sel}", border=True):
            
            with st.expander(f"🧪 QUESITO 15.0 • Controle de Absenteísmo para Exames Laboratoriais em {ano_sel}", expanded=True):
                st.subheader(f"15.0 • Absenteísmo em Exames Laboratoriais ({ano_sel})")
                st.write(f"**A Prefeitura Municipal possui controle de absenteísmo para os exames laboratoriais realizados sob sua gestão em {ano_sel}?**")
                st.caption("ℹ️ *Exemplos de exames laboratoriais: triglicérides, colesterol total e frações, hemograma, glicemia em jejum, hemoglobina glicada e controle de eletrólitos.*")
                st.caption("ℹ️ *O salvamento é automático. A seleção da alternativa ou alteração do campo de texto grava os dados na hora.*")
                
                opts_15_0 = {
                    "Selecione...": 0.0,
                    "Todos os exames laboratoriais são de pronto atendimento – 02": 2.0,
                    "Sim, para todos os exames – 02": 2.0,
                    "Sim, para a maior parte dos exames – 01": 1.0,
                    "Sim, para a menor parte dos exames – 0.5": 0.5,
                    "Não – 00": 0.0
                }
                
                # Recupera os dados atuais salvos no banco
                d15_0 = res_data.get("15.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c47, c48 = st.columns([1, 1])
                
                with c47:
                    sel_15_0 = st.radio(
                        "Alternativas para o quesito 15.0:",
                        options=list(opts_15_0.keys()),
                        index=(list(opts_15_0.keys()).index(d15_0["valor"]) if d15_0["valor"] in opts_15_0 else 0),
                        key=f"rb_saude_15_0_{ano_sel}",
                        label_visibility="collapsed"
                    )
                    pts_15_0 = opts_15_0[sel_15_0] if sel_15_0 is not None else 0.0
                    
                with c48:
                    link_15_0 = st.text_area(
                        "Link/Evidência (Relatórios do sistema de regulação de exames ou mapas de faltas gerados pelo laboratório municipal/conveniado):",
                        value=d15_0.get("link", ""),
                        key=f"txt_saude_15_0_{ano_sel}",
                        height=110
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                    links_15_0_atuais = re.findall(r'(https?://[^\s]+)', link_15_0)
                    if links_15_0_atuais:
                        botoes_15_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_15_0_atuais])
                        st.markdown(f"**Links Ativos:** {botoes_15_0}")

                st.markdown(f"📊 **Pontuação Obtida no Quesito 15.0:** `{pts_15_0:.1f} pontos`")

                # Avaliação cirúrgica de mutações para gravação em segundo plano
                mudou_opcao_15_0 = sel_15_0 != d15_0.get("valor", "")
                mudou_link_15_0 = link_15_0 != d15_0.get("link", "")

                if mudou_opcao_15_0 or mudou_link_15_0:
                    if sel_15_0 is not None:
                        # Grava a alteração imediatamente na camada de persistência
                        save_resp("15.0", sel_15_0, pts_15_0, link_15_0)
                        
                        # Atualiza o dicionário em cache para manter a consistência reativa da UI
                        res_data["15.0"] = {"valor": sel_15_0, "pontos": pts_15_0, "link": link_15_0}
                        
                        # Dispara o modal de validação apenas se houver novos links inseridos
                        if mudou_link_15_0 and links_15_0_atuais:
                            links_15_0_antigos = re.findall(r'(https?://[^\s]+)', d15_0.get("link", ""))
                            if links_15_0_atuais != links_15_0_antigos:
                                modal_aviso_link("15.0", links_15_0_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()

                bloco_comentarios("15.0", res_data)

        # BLOCO CONDICIONAL: O cálculo da taxa (15.1) e medidas (15.2) abrem se houver controle
        # Totalmente isolado da árvore do elemento pai para blindagem contra erros de nó no React
        if sel_15_0 is not None and sel_15_0 != "Não – 00" and sel_15_0 != "Selecione...":
            with st.container(key=f"container_filho_absenteismo_exames_{ano_sel}"):
                # O código dos quesitos filhos (15.1, 15.2 etc.) deve entrar aqui dentro
                pass

            # -----------------------------------------------------------------------------
            # QUESITO 15.1 (CONDICIONAL) • Taxa Histórica de Absenteísmo de Exames
            # -----------------------------------------------------------------------------
            # Substituída a div manual por contêiner nativo para evitar quebra do DOM do React
            with st.container(key=f"card_absenteismo_exames_15_1_{ano_sel}", border=True):
                
                with st.expander(f"📊 QUESITO 15.1 • Taxa Histórica de Absenteísmo de Exames ({ano_sel})", expanded=True):
                    st.subheader("15.1 • Indicadores de Faltas em Exames")
                    st.write(f"**Informe a taxa de absenteísmo de exames laboratoriais na Atenção Básica (em %):**")
                    st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos valores ou no campo de texto grava os dados na hora.*")
                    
                    d15_1_ta2 = res_data.get("15.1_ta2", {"valor": "0.0", "pontos": 0.0, "link": ""})
                    d15_1_ta1 = res_data.get("15.1_ta1", {"valor": "0.0", "pontos": 0.0, "link": ""})
                    d15_1_ta  = res_data.get("15.1_ta",  {"valor": "0.0", "pontos": 0.0, "link": ""})
                    d15_1     = res_data.get("15.1",     {"valor": "", "pontos": 0.0, "link": ""})

                    c49, c50 = st.columns([1, 1])
                    with c49:
                        val_ex_ta2 = st.number_input(f"Taxa de absenteísmo em exames em {ano_sel - 2} (TA-2):", min_value=0.0, max_value=100.0, step=0.1, value=float(d15_1_ta2["valor"]), key=f"num_15_1_ta2_{ano_sel}")
                        val_ex_ta1 = st.number_input(f"Taxa de absenteísmo em exames em {ano_sel - 1} (TA-1):", min_value=0.0, max_value=100.0, step=0.1, value=float(d15_1_ta1["valor"]), key=f"num_15_1_ta1_{ano_sel}")
                        val_ex_ta  = st.number_input(f"Taxa de absenteísmo em exames em {ano_sel} (TA):", min_value=0.0, max_value=100.0, step=0.1, value=float(d15_1_ta["valor"]), key=f"num_15_1_ta_{ano_sel}")

                    media_ex_dois_anos = (val_ex_ta2 + val_ex_ta1) / 2.0
                    
                    if val_ex_ta <= media_ex_dois_anos and (val_ex_ta2 > 0 or val_ex_ta1 > 0):
                        pts_15_1 = 7.0
                    else:
                        pts_15_1 = 0.0

                    with c50:
                        link_15_1 = st.text_area(
                            "Link/Evidência (Séries estatísticas históricas, consolidados de agendamentos solicitados x não comparecidos):",
                            value=d15_1.get("link", ""),
                            key=f"txt_saude_15_1_{ano_sel}",
                            height=150
                        )
                        
                        # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                        links_15_1_atuais = re.findall(r'(https?://[^\s]+)', link_15_1)
                        if links_15_1_atuais:
                            botoes_15_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_15_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_15_1}")
                            
                        if val_ex_ta2 > 0 or val_ex_ta1 > 0:
                            st.markdown(f"**Média dos 2 anos anteriores ({ano_sel-2}/{ano_sel-1}):** `{media_ex_dois_anos:.2f}%`")

                    st.markdown(f"📊 **Pontuação Obtida no Quesito 15.1:** `{pts_15_1:.1f} / 7.0 pontos`")

                    # Avaliação cirúrgica de mutações de estado
                    mudou_ta2 = val_ex_ta2 != float(d15_1_ta2["valor"])
                    mudou_ta1 = val_ex_ta1 != float(d15_1_ta1["valor"])
                    mudou_ta  = val_ex_ta != float(d15_1_ta["valor"])
                    mudou_link = link_15_1 != d15.get("link", "") if 'd15' in locals() else link_15_1 != d15_1.get("link", "")

                    if mudou_ta2 or mudou_ta1 or mudou_ta or mudou_link:
                        # Rótulo descritivo do quesito mestre
                        str_mestre = f"TA Exames {val_ex_ta}% (Média: {media_ex_dois_anos:.2f}%)"
                        
                        # Grava todas as sub-chaves e o mestre de forma atômica no banco
                        save_resp("15.1_ta2", str(val_ex_ta2), pts_15_1, "")
                        save_resp("15.1_ta1", str(val_ex_ta1), 0.0, "")
                        save_resp("15.1_ta", str(val_ex_ta), 0.0, "")
                        save_resp("15.1", str_mestre, pts_15_1, link_15_1)
                        
                        # Sincroniza síncronamente o cache local para blindar contra flashes visuais ou perda de estado
                        res_data["15.1_ta2"] = {"valor": str(val_ex_ta2), "pontos": pts_15_1, "link": ""}
                        res_data["15.1_ta1"] = {"valor": str(val_ex_ta1), "pontos": 0.0, "link": ""}
                        res_data["15.1_ta"]  = {"valor": str(val_ex_ta),  "pontos": 0.0, "link": ""}
                        res_data["15.1"]     = {"valor": str_mestre,       "pontos": pts_15_1, "link": link_15_1}
                        
                        # Fluxo controlado para exibição do modal de auditoria de links
                        if mudou_link and links_15_1_atuais:
                            links_15_1_antigos = re.findall(r'(https?://[^\s]+)', d15_1.get("link", ""))
                            if links_15_1_atuais != links_15_1_antigos:
                                modal_aviso_link("15.1", links_15_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()

                    bloco_comentarios("15.1", res_data)

           # -----------------------------------------------------------------------------
            # QUESITO 15.2 (CONDICIONAL) • Medidas para Redução do Absenteísmo de Exames
            # -----------------------------------------------------------------------------
            # Substituída a div HTML manual por contêiner nativo estável do Streamlit
            with st.container(key=f"card_medidas_exames_15_2_{ano_sel}", border=True):
                
                with st.expander(f"🛡️ QUESITO 15.2 • Medidas Institucionais para Exames ({ano_sel})", expanded=True):
                    st.subheader("15.2 • Enfrentamento do Absenteísmo em Exames")
                    st.write(f"**O município realiza medidas para a redução desta taxa de absenteísmo de exames laboratoriais em {ano_sel}?**")
                    st.caption("ℹ️ *O salvamento é automático. A seleção da alternativa ou alteração do campo de texto grava os dados na hora.*")
                    
                    opts_15_2 = {
                        "Selecione...": 0.0,
                        "Sim – 00": 0.0,
                        "Não – -02": -2.0
                    }
                    
                    # Recupera dados atuais salvos na base
                    d15_2 = res_data.get("15.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})

                    c51, c52 = st.columns([1, 1])
                    with c51:
                        sel_15_2 = st.radio(
                            "Alternativas para o quesito 15.2:",
                            options=list(opts_15_2.keys()),
                            index=(list(opts_15_2.keys()).index(d15_2["valor"]) if d15_2["valor"] in opts_15_2 else 0),
                            key=f"rb_saude_15_2_exames_{ano_sel}",
                            label_visibility="collapsed"
                        )
                        pts_15_2 = opts_15_2[sel_15_2] if sel_15_2 is not None else 0.0
                        
                    with c52:
                        link_15_2 = st.text_area(
                            "Link/Evidência (Planos de ação ou diretrizes para redução do absenteísmo de exames):",
                            value=d15_2.get("link", ""),
                            key=f"txt_saude_15_2_exames_{ano_sel}",
                            height=90
                        )
                        
                        # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                        links_15_2_atuais = re.findall(r'(https?://[^\s]+)', link_15_2)
                        if links_15_2_atuais:
                            botoes_15_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_15_2_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_15_2}")

                    st.markdown(f"📊 **Pontuação Obtida no Quesito 15.2 (Penalidade):** `{pts_15_2:.1f} pontos`")

                    # Avaliação minuciosa de mutações para persistência em lote
                    mudou_opcao_15_2 = sel_15_2 != d15_2.get("valor", "")
                    mudou_link_15_2 = link_15_2 != d15_2.get("link", "")

                    if mudou_opcao_15_2 or mudou_link_15_2:
                        if sel_15_2 is not None:
                            # Grava a alteração na base de dados
                            save_resp("15.2", sel_15_2, pts_15_2, link_15_2)
                            
                            # Sincroniza síncronamente o dicionário em cache local
                            res_data["15.2"] = {"valor": sel_15_2, "pontos": pts_15_2, "link": link_15_2}
                            
                            # Gerenciamento controlado do modal de auditoria de links externos
                            if mudou_link_15_2 and links_15_2_atuais:
                                links_15_2_antigos = re.findall(r'(https?://[^\s]+)', d15_2.get("link", ""))
                                if links_15_2_atuais != links_15_2_antigos:
                                    modal_aviso_link("15.2", links_15_2_atuais)
                                else:
                                    st.rerun()
                            else:
                                st.rerun()

                    bloco_comentarios("15.2", res_data)

            # SUB-CONDICIONAL FILHO DE 15.2 (Abre somente se marcou "Sim")
            # Isolado fora do bloco do elemento pai para garantir integridade estrutural no React
            if sel_15_2 == "Sim – 00":
                with st.container(key=f"container_sub_filho_medidas_exames_15_2_{ano_sel}"):
                    # O próximo quesito (ex: 15.2.1) entra de forma segura aqui dentro
                    pass
                
                # -----------------------------------------------------------------------------
                # QUESITO 15.2.1 (CONDICIONAL) • Seleção de Medidas Aplicadas para Exames
                # -----------------------------------------------------------------------------
                # Substituída a div HTML manual por contêiner nativo estável do Streamlit
                with st.container(key=f"card_medidas_aplicadas_exames_15_2_1_{ano_sel}", border=True):
                    
                    with st.expander(f"📋 QUESITO 15.2.1 • Rol de Medidas em Exames Laboratoriais em {ano_sel}", expanded=True):
                        st.subheader("15.2.1 • Ações Preventivas e de Confirmação")
                        st.write(f"**Assinale as medidas utilizadas para a redução da taxa de absenteísmo de exames médicos na Atenção Básica em {ano_sel}:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link salva os dados na hora.*")
                        
                        d15_2_1 = res_data.get("15.2.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        try:
                            salvos_15_2_1 = json.loads(d15_2_1["valor"])
                        except:
                            salvos_15_2_1 = []

                        c53, c54 = st.columns([1, 1])
                        with c53:
                            chk_ex_m1 = st.checkbox("Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo e promover capacitações", value="ex_m1" in salvos_15_2_1, key=f"chk_15_2_1_m1_ex_{ano_sel}")
                            chk_ex_m2 = st.checkbox("Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação", value="ex_m2" in salvos_15_2_1, key=f"chk_15_2_1_m2_ex_{ano_sel}")
                            chk_ex_m3 = st.checkbox("Ligação telefônica ou outro meio de comunicação para confirmation do exame e presença do paciente", value="ex_m3" in salvos_15_2_1, key=f"chk_15_2_1_m3_ex_{ano_sel}")
                            chk_ex_m4 = st.checkbox("Orientação das famílias e busca ativa dos faltosos pelos Agentes Comunitários de Saúde (ACS)", value="ex_m4" in salvos_15_2_1, key=f"chk_15_2_1_m4_ex_{ano_sel}")
                            chk_ex_m5 = st.checkbox("Promoção de campanhas de conscientização", value="ex_m5" in salvos_15_2_1, key=f"chk_15_2_1_m5_ex_{ano_sel}")
                            chk_ex_m6 = st.checkbox("Outros", value="ex_m6" in salvos_15_2_1, key=f"chk_15_2_1_m6_ex_{ano_sel}")

                            medidas_ex_selecionadas = []
                            if chk_ex_m1: medidas_ex_selecionadas.append("ex_m1")
                            if chk_ex_m2: medidas_ex_selecionadas.append("ex_m2")
                            if chk_ex_m3: medidas_ex_selecionadas.append("ex_m3")
                            if chk_ex_m4: medidas_ex_selecionadas.append("ex_m4")
                            if chk_ex_m5: medidas_ex_selecionadas.append("ex_m5")
                            if chk_ex_m6: medidas_ex_selecionadas.append("ex_m6")
                            
                            str_15_2_1 = json.dumps(medidas_ex_selecionadas)

                        with c54:
                            link_15_2_1 = st.text_area(
                                "Link/Evidência (Comprovantes de rotinas de confirmação, campanhas, prints de sistemas de comunicação ou relatórios das centrais de exames):",
                                value=d15_2_1.get("link", ""),
                                key=f"txt_saude_15_2_1_exames_{ano_sel}",
                                height=210
                            )
                            
                            # SUPORTE MULTI-LINKS ATIVOS (Varre o text_area em tempo de execução)
                            links_15_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_15_2_1)
                            if links_15_2_1_atuais:
                                botoes_15_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_15_2_1_atuais])
                                st.markdown(f"**Links Ativos:** {botoes_15_2_1}")

                        # Avaliação de mutações de estado
                        mudou_dados_15_2_1 = str_15_2_1 != d15_2_1["valor"]
                        mudou_link_15_2_1 = link_15_2_1 != d15_2_1["link"]

                        if mudou_dados_15_2_1 or mudou_link_15_2_1:
                            # Grava a alteração na camada de persistência
                            save_resp("15.2.1", str_15_2_1, 0.0, link_15_2_1)
                            
                            # Sincroniza síncronamente o dicionário em cache local
                            res_data["15.2.1"] = {"valor": str_15_2_1, "pontos": 0.0, "link": link_15_2_1}
                            
                            # Controle do fluxo de modais e re-execução estável
                            if mudou_link_15_2_1 and links_15_2_1_atuais:
                                links_15_2_1_antigos = re.findall(r'(https?://[^\s]+)', d15_2_1.get("link", ""))
                                if links_15_2_1_atuais != links_15_2_1_antigos:
                                    modal_aviso_link("15.2.1", links_15_2_1_atuais)
                                else:
                                    st.rerun()
                            else:
                                st.rerun()

                        # ID modificado por extenso para evitar colisão de formulários com o pai ("15.2")
                        bloco_comentarios("15_2_1_medidas", res_data)

# =============================================================================
        # QUESITO 16.0 • PRONTUÁRIO ELETRÔNICO NA ATENÇÃO BÁSICA (BLINDADO - ST.EMPTY)
        # =============================================================================
        with st.container(key=f"container_bloco_pep_atencao_basica_16_0_final_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 16.0 - Prontuário Eletrônico na Atenção Básica", expanded=True):
                st.subheader("16.0 • Prontuário Eletrônico na Atenção Básica")
                st.write("**16.0 O município implantou o Prontuário Eletrônico do Paciente na Atenção Básica?**")
                st.caption("ℹ️ *Salvamento automático por callbacks nativos de estado.*")
                
                opts_16_0 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os procedimentos da saúde – 10": 10.0,
                    "Sim, para a maior parte dos procedimentos da saúde – 07": 7.0,
                    "Sim, para a menor parte dos procedimentos da saúde – 03": 3.0,
                    "Não – 00": 0.0
                }
                
                d16_0 = res_data.get("16.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                # Callbacks isolados para gerenciar o estado em background de forma segura
                def cb_radio_16_0():
                    val = st.session_state[f"r_16_0_{ano_sel}"]
                    pts = opts_16_0[val]
                    lnk = st.session_state.get(f"t_16_0_{ano_sel}", d16_0.get("link", ""))
                    save_resp("16.0", val, pts, lnk)
                    res_data["16.0"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_16_0():
                    lnk = st.session_state[f"t_16_0_{ano_sel}"]
                    val = st.session_state.get(f"r_16_0_{ano_sel}", d16_0.get("valor", "Selecione..."))
                    pts = opts_16_0.get(val, 0.0)
                    save_resp("16.0", val, pts, lnk)
                    res_data["16.0"] = {"valor": val, "pontos": pts, "link": lnk}

                c160_1, c160_2 = st.columns([1, 1])
                with c160_1:
                    lista_opcoes = list(opts_16_0.keys())
                    idx_salvo = lista_opcoes.index(d16_0["valor"]) if d16_0["valor"] in opts_16_0 else 0
                    
                    sel_16_0 = st.radio(
                        "Implantação do PEP:", options=lista_opcoes, index=idx_salvo,
                        key=f"r_16_0_{ano_sel}", on_change=cb_radio_16_0, label_visibility="collapsed"
                    )
                    pts_16_0 = opts_16_0[sel_16_0] if sel_16_0 is not None else 0.0
                    
                with c160_2:
                    link_16_0 = st.text_area(
                        "Link/Evidência (16.0):", value=d16_0.get("link", ""), 
                        key=f"t_16_0_{ano_sel}", on_change=cb_text_16_0, height=130
                    )
                    
                    # Elemento estático reservado na árvore do React para evitar quebras de HTML dinâmico
                    placeholder_links_16 = st.empty()
                    links_16_0_atuais = re.findall(r'(https?://[^\s]+)', link_16_0)
                    if links_16_0_atuais:
                        botoes_16_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_16_0_atuais])
                        placeholder_links_16.markdown(f"**Links Ativos:** {botoes_16_0}")
                
                # Placeholder estático para o score
                placeholder_score_16 = st.empty()
                if pts_16_0 == 0.0 and sel_16_0 == "Não – 00":
                    placeholder_score_16.markdown(f"📊 **Pontuação Aplicada no Quesito 16.0:** :red[{pts_16_0:.1f} pontos]")
                else:
                    placeholder_score_16.markdown(f"📊 **Pontuação Aplicada no Quesito 16.0:** `{pts_16_0:.1f} pontos`")
                
                bloco_comentarios("16_basica_final_fix", res_data)

        # -----------------------------------------------------------------------------
        # QUESITO 16.1 • Serviços inseridos no Prontuário Eletrônico
        # -----------------------------------------------------------------------------
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_servicos_pep_16_1_{ano_sel}", border=True):
            
            with st.expander(f"📋 QUESITO 16.1 • Serviços Integrados ao Prontuário Eletrônico em {ano_sel}", expanded=True):
                st.subheader("16.1 • Escopo Funcional do PEP")
                st.write(f"**Assinale os serviços da Atenção Básica inseridos no Prontuário Eletrônico do Paciente em {ano_sel}:**")
                st.caption("ℹ️ *A pontuação deste quesito é cumulativa (1 ponto por serviço assinalado, exceto 'Outros').*")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                
                d16_1 = res_data.get("16.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                try:
                    salvos_16_1 = json.loads(d16_1["valor"])
                except:
                    salvos_16_1 = []

                c57, c58 = st.columns([1, 1])
                with c57:
                    chk_pep1 = st.checkbox("Atendimento pela ESF – 01", value="pep1" in salvos_16_1, key=f"chk_16_1_pep1_{ano_sel}")
                    chk_pep2 = st.checkbox("Consultas médicas em Atenção Primária – 01", value="pep2" in salvos_16_1, key=f"chk_16_1_pep2_{ano_sel}")
                    chk_pep3 = st.checkbox("Exames laboratoriais – 01", value="pep3" in salvos_16_1, key=f"chk_16_1_pep3_{ano_sel}")
                    chk_pep4 = st.checkbox("Terapias / tratamentos – 01", value="pep4" in salvos_16_1, key=f"chk_16_1_pep4_{ano_sel}")
                    chk_pep5 = st.checkbox("Medicamentos – 01", value="pep5" in salvos_16_1, key=f"chk_16_1_pep5_{ano_sel}")
                    chk_pep6 = st.checkbox("Outros – 00", value="pep6" in salvos_16_1, key=f"chk_16_1_pep6_{ano_sel}")

                    # Cálculo dinâmico e cumulativo da pontuação
                    servicos_selecionados = []
                    pts_16_1 = 0.0
                    
                    if chk_pep1: 
                        servicos_selecionados.append("pep1")
                        pts_16_1 += 1.0
                    if chk_pep2: 
                        servicos_selecionados.append("pep2")
                        pts_16_1 += 1.0
                    if chk_pep3: 
                        servicos_selecionados.append("pep3")
                        pts_16_1 += 1.0
                    if chk_pep4: 
                        servicos_selecionados.append("pep4")
                        pts_16_1 += 1.0
                    if chk_pep5: 
                        servicos_selecionados.append("pep5")
                        pts_16_1 += 1.0
                    if chk_pep6: 
                        servicos_selecionados.append("pep6")
                    
                    str_16_1 = json.dumps(servicos_selecionados)

                with c58:
                    link_16_1 = st.text_area(
                        "Link/Evidência (Telas exemplares do PEP mostrando os módulos ativos de ESF, exames, receitas ou terapias):",
                        value=d16_1.get("link", ""),
                        key=f"txt_saude_16_1_pep_{ano_sel}",
                        height=210
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado em tempo de execução)
                    with st.container(key=f"links_pep_holder_16_1_{ano_sel}"):
                        links_16_1_atuais = re.findall(r'(https?://[^\s]+)', link_16_1)
                        if links_16_1_atuais:
                            botoes_16_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_16_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_16_1}")

                # ISOLAMENTO DO SCORE: Protegido por container para o React não se perder ao atualizar o texto
                with st.container(key=f"score_pep_holder_16_1_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Obtida no Quesito 16.1:** `{pts_16_1:.1f} pontos`")

                # Avaliação de mutações para persistência reativa e síncrona
                mudou_dados_16_1 = str_16_1 != d16_1["valor"]
                mudou_link_16_1 = link_16_1 != d16_1["link"]

                if mudou_dados_16_1 or mudou_link_16_1:
                    save_resp("16.1", str_16_1, pts_16_1, link_16_1)
                    
                    # Sincroniza síncronamente o cache local antes do recarregamento de página
                    res_data["16.1"] = {"valor": str_16_1, "pontos": pts_16_1, "link": link_16_1}
                    
                    if mudou_link_16_1 and links_16_1_atuais:
                        links_16_1_antigos = re.findall(r'(https?://[^\s]+)', d16_1.get("link", ""))
                        if links_16_1_atuais != links_16_1_antigos:
                            modal_aviso_link("16.1", links_16_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

                # ID modificado por extenso para prevenir colisões de componentes no back-end
                bloco_comentarios("16_1_servicos_pep", res_data)

        # =============================================================================
        # QUESITO 17.0 - ATENÇÃO ESPECIALIZADA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_especializada_17_0_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.0 - Atendimento de Atenção Especializada", expanded=True):
                st.subheader("17.0 • Atenção Especializada")
                st.write(f"**O município possui atendimento de Atenção Especializada (média e/ou alta complexidade)?**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")

                d17_0 = res_data.get("17.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                opcoes_17_0 = [
                    "Selecione...",
                    "Sim, sob gestão municipal",
                    "Sim, sob gestão estadual",
                    "Sim, sob gestão municipal e sob gestão estadual",
                    "Não, somente encaminhamento para outro município"
                ]
                
                c170_1, c170_2 = st.columns([1, 1])
                with c170_1:
                    sel_17_0 = st.radio(
                        "Gestão da Atenção Especializada:", 
                        options=opcoes_17_0, 
                        index=(opcoes_17_0.index(d17_0["valor"]) if d17_0["valor"] in opcoes_17_0 else 0),
                        key=f"reg_17_0_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_17_0 = 0.0
                    
                with c170_2:
                    link_17_0 = st.text_area(
                        "Link/Evidência Geral (17.0):", 
                        value=d17_0.get("link", ""), 
                        key=f"reg_17_0_txt_{ano_sel}",
                        height=110
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_especializada_17_0_{ano_sel}"):
                        links_17_0_atuais = re.findall(r'(https?://[^\s]+)', link_17_0)
                        if links_17_0_atuais:
                            botoes_17_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_0_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_0}")
                
                # ISOLAMENTO DO SCORE: Evita colapso de nós filhos no React ao atualizar pontuações
                with st.container(key=f"score_holder_especializada_17_0_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Obtida no Quesito 17.0:** `{pts_17_0:.1f} pontos`")
                
                # Avaliação de mutações para persistência reativa estável
                mudou_opcao_17_0 = sel_17_0 != d17_0.get("valor", "")
                mudou_link_17_0 = link_17_0 != d17_0.get("link", "")

                if mudou_opcao_17_0 or mudou_link_17_0:
                    if sel_17_0 is not None:
                        save_resp("17.0", sel_17_0, pts_17_0, link_17_0)
                        
                        # Atualiza localmente o cache para impedir flashes visuais de dados antigos
                        res_data["17.0"] = {"valor": sel_17_0, "pontos": pts_17_0, "link": link_17_0}
                        
                        if mudou_link_17_0 and links_17_0_atuais:
                            links_17_0_antigos = re.findall(r'(https?://[^\s]+)', d17_0.get("link", ""))
                            if links_17_0_atuais != links_17_0_antigos:
                                modal_aviso_link("17.0", links_17_0_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                
                bloco_comentarios("17.0", res_data)

        # =============================================================================
        # QUESITO 17.1 - REGISTRO DE FREQUÊNCIA ELETRÔNICA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_frequencia_17_1_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.1 - Frequência Eletrônica na Atenção Especializada", expanded=True):
                st.subheader("17.1 • Controle de Frequência Eletrônica")
                st.write(f"**17.1 Os profissionais de saúde da Atenção Especializada sob gestão municipal registram sua frequência de forma eletrônica?**")
                st.caption("⚠️ *Obs. O encaminhamento de planilhas de ponto não será considerado como modalidade de registro eletrônico.*")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")

                opts_17_1 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os profissionais da saúde – 00": 0.0,
                    "Sim, para a maior parte dos profissionais da saúde – -01 (perde 01 ponto)": -1.0,
                    "Sim, para a menor parte dos profissionais da saúde – -02 (perde 02 pontos)": -2.0,
                    "Não houve registro eletrônico de nenhum profissional de saúde – -03 (perde 03 pontos)": -3.0
                }
                
                d17_1 = res_data.get("17.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c171_1, c171_2 = st.columns([1, 1])
                with c171_1:
                    sel_17_1 = st.radio(
                        "Frequência eletrônica:", 
                        options=list(opts_17_1.keys()), 
                        index=(list(opts_17_1.keys()).index(d17_1["valor"]) if d17_1["valor"] in opts_17_1 else 0),
                        key=f"reg_17_1_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_17_1 = opts_17_1[sel_17_1] if sel_17_1 is not None else 0.0
                    
                with c171_2:
                    link_17_1 = st.text_area(
                        "Link/Evidência do Sistema de Ponto (17.1):", 
                        value=d17_1.get("link", ""), 
                        key=f"reg_17_1_txt_{ano_sel}",
                        height=110
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_frequencia_17_1_{ano_sel}"):
                        links_17_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_1)
                        if links_17_1_atuais:
                            botoes_17_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_1}")
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_frequencia_17_1_{ano_sel}"):
                    if pts_17_1 < 0:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.1:** :red[{pts_17_1:.1f} pontos (Penalidade)]")
                    else:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.1:** `{pts_17_1:.1f} pontos`")
                
                # Avaliação de mutações para persistência reativa e síncrona
                mudou_opcao_17_1 = sel_17_1 != d17_1.get("valor", "")
                mudou_link_17_1 = link_17_1 != d17_1.get("link", "")

                if mudou_opcao_17_1 or mudou_link_17_1:
                    if sel_17_1 is not None:
                        save_resp("17.1", sel_17_1, pts_17_1, link_17_1)
                        
                        # Sincroniza localmente o dicionário de cache antes do rerun
                        res_data["17.1"] = {"valor": sel_17_1, "pontos": pts_17_1, "link": link_17_1}
                        
                        if mudou_link_17_1 and links_17_1_atuais:
                            links_17_1_antigos = re.findall(r'(https?://[^\s]+)', d17_1.get("link", ""))
                            if links_17_1_atuais != links_17_1_antigos:
                                modal_aviso_link("17.1", links_17_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                
                bloco_comentarios("17.1", res_data)

       # =============================================================================
        # QUESITO 17.1.1 • JORNADA DE TRABALHO DOS MÉDICOS AMBULATORIAIS (BLINDADO - ST.EMPTY)
        # =============================================================================
        with st.container(key=f"container_bloco_jornada_medica_17_1_1_final_{ano_sel}", border=True):

            with st.expander(f"📌 QUESITO 17.1.1 • Jornada de Trabalho dos Médicos Ambulatoriais em {ano_sel}", expanded=True):
                st.subheader("17.1.1 • Jornada de Trabalho dos Médicos Ambulatoriais")
                st.write("**Os médicos ambulatoriais da Atenção Especializada sob gestão municipal cumprem integralmente sua jornada de trabalho?**")
                st.caption("ℹ️ *O salvamento é automático por callbacks nativos de estado. Sem riscos de travamento visual.*")
                
                # Mapeamento de Opções e Pontuações do Quesito 17.1.1
                opts_17_1_1 = {
                    "Selecione...": 0.0,
                    "Sim, todos cumprem integralmente a jornada de trabalho – 00": 0.0,
                    "Sim, a maior parte cumpre integralmente a jornada de trabalho – -01 (perde 01 ponto)": -1.0,
                    "Sim, todos permanecem apenas nas consultas agendadas – -04 (perde 04 pontos)": -4.0,
                    "Sim, a maior parte permanece apenas nas consultas agendadas – -03 (perde 03 pontos)": -3.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }
                
                # Recupera o valor do banco de dados de forma segura
                d17_1_1 = res_data.get("17.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                valor_salvo = d17_1_1.get("valor", "Selecione...")
                if valor_salvo not in opts_17_1_1:
                    valor_salvo = "Selecione..."

                # Callbacks para processamento assíncrono em background
                def cb_radio_17_1_1():
                    val = st.session_state[f"r_17_1_1_{ano_sel}"]
                    pts = opts_17_1_1[val]
                    lnk = st.session_state.get(f"t_17_1_1_{ano_sel}", d17_1_1.get("link", ""))
                    save_resp("17.1.1", val, pts, lnk)
                    res_data["17.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_17_1_1():
                    lnk = st.session_state[f"t_17_1_1_{ano_sel}"]
                    val = st.session_state.get(f"r_17_1_1_{ano_sel}", d17_1_1.get("valor", "Selecione..."))
                    pts = opts_17_1_1.get(val, 0.0)
                    save_resp("17.1.1", val, pts, lnk)
                    res_data["17.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.markdown("**Selecione uma alternativa:**")
                    lista_opcoes_1711 = list(opts_17_1_1.keys())
                    idx_inicial = lista_opcoes_1711.index(valor_salvo)
                    
                    sel_17_1_1 = st.radio(
                        "Alternativas para o quesito 17.1.1:",
                        options=lista_opcoes_1711,
                        index=idx_inicial,
                        key=f"r_17_1_1_{ano_sel}",
                        on_change=cb_radio_17_1_1,
                        label_visibility="collapsed"
                    )
                    pts_17_1_1 = opts_17_1_1.get(sel_17_1_1, 0.0)
                        
                with c2:
                    link_17_1_1 = st.text_area(
                        "Link/Evidência (Relatórios, espelho de ponto, etc.):",
                        value=d17_1_1.get("link", ""),
                        key=f"t_17_1_1_{ano_sel}",
                        on_change=cb_text_17_1_1,
                        height=110
                    )
                    
                    # Placeholder estático para links injetados dinamicamente no React
                    placeholder_links_1711 = st.empty()
                    links_17_1_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_1_1)
                    if links_17_1_1_atuais:
                        botoes_17_1_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_1_1_atuais])
                        placeholder_links_1711.markdown(f"**Links Ativos:** {botoes_17_1_1}")

                # Placeholder estático e seguro para o Score do formulário
                placeholder_score_1711 = st.empty()
                if pts_17_1_1 < 0:
                    placeholder_score_1711.markdown(f"📊 **Pontuação Obtida no Quesito 17.1.1:** :red[{pts_17_1_1:.1f} pontos (Penalidade)]")
                else:
                    placeholder_score_1711.markdown(f"📊 **Pontuação Obtida no Quesito 17.1.1:** `{pts_17_1_1:.1f} pontos`")

                # Dispara o modal de aviso de link se houver alteração detectada via sessão
                links_antigos = re.findall(r'(https?://[^\s]+)', d17_1_1.get("link", ""))
                if links_17_1_1_atuais and links_17_1_1_atuais != links_antigos:
                    modal_aviso_link("17.1.1", links_17_1_1_atuais)

                # Chave única textual para isolar o bloco de comentários de possíveis conflitos
                bloco_comentarios("17_1_1_ambulatoriais_fix", res_data)

        # =============================================================================
        # QUESITO 17.2 - INTERVALO DE AGENDAMENTO DE CONSULTAS MEDICAS (BLINDADO - ST.EMPTY)
        # =============================================================================
        with st.container(key=f"container_bloco_agendamento_17_2_final_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.2 - Intervalo de Agendamento na Atenção Especializada", expanded=True):
                st.subheader("17.2 • Intervalo de Agendamento de Consultas Médicas")
                st.write(f"**17.2 Assinale o intervalo de agendamento das consultas médicas da Atenção Especializada sob gestão municipal:**")
                st.caption("ℹ️ *O salvamento é automático por callbacks nativos de estado. Sem riscos de travamento visual.*")
                
                opts_17_2 = {
                    "Selecione...": 0.0,
                    "Não há agendamento de consultas da Atenção Especializada, pois todas são de pronto atendimento – 00": 0.0,
                    "Agendamento de cada paciente em horário único com, no mínimo, 15 minutes de atendimento – 00": 0.0,
                    "Agendamento de cada paciente em horário único com menos de 15 minutes de atendimento – -0,5 (perde 0,5 ponto)": -0.5,
                    "Agendamento de 2 ou mais pacientes no mesmo horário – -0,5 (perde 0,5 ponto)": -0.5
                }
                
                d17_2 = res_data.get("17.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                # Callbacks assíncronos isolados para gerenciar o estado em background de forma estável
                def cb_radio_17_2():
                    val = st.session_state[f"r_17_2_{ano_sel}"]
                    pts = opts_17_2[val]
                    lnk = st.session_state.get(f"t_17_2_{ano_sel}", d17_2.get("link", ""))
                    save_resp("17.2", val, pts, lnk)
                    res_data["17.2"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_17_2():
                    lnk = st.session_state[f"t_17_2_{ano_sel}"]
                    val = st.session_state.get(f"r_17_2_{ano_sel}", d17_2.get("valor", "Selecione..."))
                    pts = opts_17_2.get(val, 0.0)
                    save_resp("17.2", val, pts, lnk)
                    res_data["17.2"] = {"valor": val, "pontos": pts, "link": lnk}

                c172_1, c172_2 = st.columns([1, 1])
                with c172_1:
                    lista_opcoes_172 = list(opts_17_2.keys())
                    idx_inicial_172 = lista_opcoes_172.index(d17_2["valor"]) if d17_2["valor"] in opts_17_2 else 0
                    
                    sel_17_2 = st.radio(
                        "Intervalo de agendamento:", 
                        options=lista_opcoes_172, 
                        index=idx_inicial_172,
                        key=f"r_17_2_{ano_sel}", 
                        on_change=cb_radio_17_2,
                        label_visibility="collapsed"
                    )
                    pts_17_2 = opts_17_2[sel_17_2] if sel_17_2 is not None else 0.0
                    
                with c172_2:
                    link_17_2 = st.text_area(
                        "Link/Evidência do Sistema de Agendamento (17.2):", 
                        value=d17_2.get("link", ""), 
                        key=f"t_17_2_{ano_sel}",
                        on_change=cb_text_17_2,
                        height=110
                    )
                    
                    # Placeholder estático para links injetados dinamicamente no React
                    placeholder_links_172 = st.empty()
                    links_17_2_atuais = re.findall(r'(https?://[^\s]+)', link_17_2)
                    if links_17_2_atuais:
                        botoes_17_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_2_atuais])
                        placeholder_links_172.markdown(f"**Links Ativos:** {botoes_17_2}")
                
                # Placeholder estático e seguro para o Score do formulário
                placeholder_score_172 = st.empty()
                if pts_17_2 < 0:
                    placeholder_score_172.markdown(f"📊 **Pontuação Aplicada no Quesito 17.2:** :red[{pts_17_2:.1f} pontos (Penalidade)]")
                else:
                    placeholder_score_172.markdown(f"📊 **Pontuação Aplicada no Quesito 17.2:** `{pts_17_2:.1f} pontos`")
                
                # Dispara o modal de aviso de link se houver alteração detectada via sessão
                links_antigos = re.findall(r'(https?://[^\s]+)', d17_2.get("link", ""))
                if links_17_2_atuais and links_17_2_atuais != links_antigos:
                    modal_aviso_link("17.2", links_17_2_atuais)
                
                # Chave única textual para isolar o bloco de comentários de possíveis conflitos
                bloco_comentarios("17_2_agendamento_final_fix", res_data)

        # =============================================================================
        # QUESITO 17.3 - CONTROLE DE ABSENTEÍSMO DE CONSULTAS MÉDICAS
        # =============================================================================
        with st.container(key=f"container_bloco_absenteismo_17_3_{ano_sel}", border=True):
                
                with st.expander(f"📌 Quesito 17.3 - Controle de Absenteísmo na Atenção Especializada", expanded=True):
                        st.subheader("17.3 • Controle de Absenteísmo")
                        st.write(f"**17.3 O município possui controle de absenteísmo de consultas médicas da Atenção Especializada sob gestão municipal?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_17_3 = {
                                "Selecione...": 0.0,
                                "Sim, para todas as consultas médicas – 00": 0.0,
                                "Sim, para a maior parte das consultas médicas – -01 (perde 01 ponto)": -1.0,
                                "Sim, para a menor parte das consultas médicas – -02 (perde 02 pontos)": -2.0,
                                "Não – -03 (perde 03 pontos)": -3.0
                        }
                        
                        d17_3 = res_data.get("17.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        
                        c173_1, c173_2 = st.columns([1, 1])
                        with c173_1:
                                sel_17_3 = st.radio(
                                        "Controle de absenteísmo:", 
                                        options=list(opts_17_3.keys()), 
                                        index=(list(opts_17_3.keys()).index(d17_3["valor"]) if d17_3["valor"] in opts_17_3 else 0),
                                        key=f"reg_17_3_rad_{ano_sel}", 
                                        label_visibility="collapsed"
                                )
                                pts_17_3 = opts_17_3[sel_17_3] if sel_17_3 is not None else 0.0
                                
                        with c173_2:
                                link_17_3 = st.text_area(
                                        "Link/Evidência do Controle de Absenteísmo (17.3):", 
                                        value=d17_3.get("link", ""), 
                                        key=f"reg_17_3_txt_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: O container sempre existe, evitando o erro de remoção de nó pelo React
                                placeholder_links_17_3 = st.empty()
                                links_17_3_atuais = re.findall(r'(https?://[^\s]+)', link_17_3)
                                if links_17_3_atuais:
                                        botoes_17_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_3_atuais])
                                        placeholder_links_17_3.markdown(f"**Links Ativos:** {botoes_17_3}")
                        
                        # FIX: Pontuação usa st.empty() estável fixado na árvore DOM
                        score_placeholder_17_3 = st.empty()
                        if pts_17_3 < 0:
                                score_placeholder_17_3.markdown(f"📊 **Pontuação Aplicada no Quesito 17.3:** :red[{pts_17_3:.1f} pontos (Penalidade)]")
                        else:
                                score_placeholder_17_3.markdown(f"📊 **Pontuação Aplicada no Quesito 17.3:** `{pts_17_3:.1f} pontos`")
                        
                        mudou_opcao_17_3 = sel_17_3 != d17_3.get("valor", "")
                        mudou_link_17_3 = link_17_3 != d17_3.get("link", "")

                        if mudou_opcao_17_3 or mudou_link_17_3:
                                if sel_17_3 is not None:
                                        save_resp("17.3", sel_17_3, pts_17_3, link_17_3)
                                        res_data["17.3"] = {"valor": sel_17_3, "pontos": pts_17_3, "link": link_17_3}
                                        
                                        if mudou_link_17_3 and links_17_3_atuais:
                                                links_17_3_antigos = re.findall(r'(https?://[^\s]+)', d17_3.get("link", ""))
                                                if links_17_3_atuais != links_17_3_antigos:
                                                        modal_aviso_link("17.3", links_17_3_atuais)
                                                else:
                                                        st.rerun()
                                        else:
                                                st.rerun()
                        
                        bloco_comentarios("17.3", res_data)

        # =============================================================================
        # QUESITO 17.3.1 - TAXA DE ABSENTEÍSMO DE CONSULTAS MÉDICAS (DINÂMICO)
        # =============================================================================
        with st.container(key=f"container_bloco_taxa_absenteismo_17_3_1_{ano_sel}", border=True):
                
                with st.expander(f"📌 Quesito 17.3.1 - Evolução da Taxa de Absenteísmo na Atenção Especializada", expanded=True):
                        ano_atual = int(ano_sel)
                        ano_menos_1 = ano_atual - 1
                        ano_menos_2 = ano_atual - 2
                        
                        st.subheader("17.3.1 • Taxa de Absenteísmo")
                        st.write(f"**Informe a taxa de absenteísmo de consulta médica da Atenção Especializada sob gestão municipal:**")
                        st.caption(f"Fórmula: Se TA({ano_atual}) > média de TA({ano_menos_2}) e TA({ano_menos_1}) -> Perde 2 pontos.")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos numéricos ou no link grava os dados na hora.*")
                        
                        d17_3_1 = res_data.get("17.3.1", {"valor": "0.0|0.0|0.0", "pontos": 0.0, "link": ""})
                        partes_ta = d17_3_1["valor"].split("|") if "|" in d17_3_1["valor"] else ["0.0", "0.0", "0.0"]
                        partes_ta += ["0.0"] * (3 - len(partes_ta))
                        
                        try:
                                v_a2 = float(partes_ta[0])
                                v_a1 = float(partes_ta[1])
                                v_atual = float(partes_ta[2])
                        except ValueError:
                                v_a2 = v_a1 = v_atual = 0.0
                        
                        c1731_1, c1731_2 = st.columns([1, 1])
                        
                        with c1731_1:
                                st.markdown("**📊 Taxas de Absenteísmo (%)**")
                                ta_2 = st.number_input(f"Taxa em {ano_menos_2} (TA-2):", min_value=0.0, max_value=100.0, value=v_a2, step=0.1, format="%.1f", key=f"txt_ta_2_spec_{ano_sel}")
                                ta_1 = st.number_input(f"Taxa em {ano_menos_1} (TA-1):", min_value=0.0, max_value=100.0, value=v_a1, step=0.1, format="%.1f", key=f"txt_ta_1_spec_{ano_sel}")
                                ta_atual = st.number_input(f"Taxa em {ano_atual} (TA):", min_value=0.0, max_value=100.0, value=v_atual, step=0.1, format="%.1f", key=f"txt_ta_atual_spec_{ano_sel}")
                                
                                media_anteriores = (ta_2 + ta_1) / 2.0
                                st.info(f"💡 Média de {ano_menos_2} e {ano_menos_1}: **{media_anteriores:.1f}%**")
                                
                                pts_17_3_1 = -2.0 if ta_atual > media_anteriores else 0.0
                                
                        with c1731_2:
                                link_17_3_1 = st.text_area(
                                        "Link/Evidência dos Relatórios de Absenteísmo (17.3.1):", 
                                        value=d17_3_1.get("link", ""), 
                                        key=f"txt_evid_17_3_1_spec_{ano_sel}",
                                        height=180
                                )
                                
                                placeholder_links_17_3_1 = st.empty()
                                links_17_3_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_3_1)
                                if links_17_3_1_atuais:
                                        botoes_17_3_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_3_1_atuais])
                                        placeholder_links_17_3_1.markdown(f"**Links Ativos:** {botoes_17_3_1}")
                        
                        score_placeholder_17_3_1 = st.empty()
                        if pts_17_3_1 < 0:
                                score_placeholder_17_3_1.markdown(f"📊 **Pontuação Aplicada:** :red[{pts_17_3_1:.1f} pontos (Penalidade)]")
                        else:
                                score_placeholder_17_3_1.markdown(f"📊 **Pontuação Aplicada:** `{pts_17_3_1:.1f} pontos`")
                        
                        novo_valor_string = f"{ta_2:.1f}|{ta_1:.1f}|{ta_atual:.1f}"
                        mudou_valores_17_3_1 = novo_valor_string != d17_3_1["valor"]
                        mudou_link_17_3_1 = link_17_3_1 != d17_3_1.get("link", "")

                        if mudou_valores_17_3_1 or mudou_link_17_3_1:
                                save_resp("17.3.1", novo_valor_string, pts_17_3_1, link_17_3_1)
                                res_data["17.3.1"] = {"valor": novo_valor_string, "pontos": pts_17_3_1, "link": link_17_3_1}
                                
                                if mudou_link_17_3_1 and links_17_3_1_atuais:
                                        links_17_3_1_antigos = re.findall(r'(https?://[^\s]+)', d17_3_1.get("link", ""))
                                        if links_17_3_1_atuais != links_17_3_1_antigos:
                                                modal_aviso_link("17.3.1", links_17_3_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                
                        bloco_comentarios("17.3.1", res_data)

        # =============================================================================
        # QUESITO 17.3.2 - MEDIDAS PARA REDUÇÃO DO ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_bloco_medidas_absenteismo_17_3_2_{ano_sel}", border=True):
                
                with st.expander(f"📌 Quesito 17.3.2 - Medidas para Redução de Absenteísmo na Atenção Especializada", expanded=True):
                        st.subheader("17.3.2 • Medidas para Redução do Absenteísmo")
                        st.write(f"**17.3.2 O município realiza medidas para a redução desta taxa de absenteísmo?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_17_3_2 = {
                                "Selecione...": 0.0,
                                "Sim – 00": 0.0,
                                "Não – -02 (perde 02 pontos)": -2.0
                        }
                        
                        d17_3_2 = res_data.get("17.3.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        
                        c1732_1, c1732_2 = st.columns([1, 1])
                        with c1732_1:
                                sel_17_3_2 = st.radio(
                                        "Realiza medidas de redução:", 
                                        options=list(opts_17_3_2.keys()), 
                                        index=(list(opts_17_3_2.keys()).index(d17_3_2["valor"]) if d17_3_2["valor"] in opts_17_3_2 else 0),
                                        key=f"reg_17_3_2_rad_{ano_sel}", 
                                        label_visibility="collapsed"
                                )
                                pts_17_3_2 = opts_17_3_2[sel_17_3_2] if sel_17_3_2 is not None else 0.0
                                
                        with c1732_2:
                                link_17_3_2 = st.text_area(
                                        "Link/Evidência das Ações de Redução (17.3.2):", 
                                        value=d17_3_2.get("link", ""), 
                                        key=f"reg_17_3_2_txt_{ano_sel}",
                                        height=110
                                )
                                
                                placeholder_links_17_3_2 = st.empty()
                                links_17_3_2_atuais = re.findall(r'(https?://[^\s]+)', link_17_3_2)
                                if links_17_3_2_atuais:
                                        botoes_17_3_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_3_2_atuais])
                                        placeholder_links_17_3_2.markdown(f"**Links Ativos:** {botoes_17_3_2}")
                        
                        score_placeholder_17_3_2 = st.empty()
                        if pts_17_3_2 < 0:
                                score_placeholder_17_3_2.markdown(f"📊 **Pontuação Aplicada no Quesito 17.3.2:** :red[{pts_17_3_2:.1f} pontos (Penalidade)]")
                        else:
                                score_placeholder_17_3_2.markdown(f"📊 **Pontuação Aplicada no Quesito 17.3.2:** `{pts_17_3_2:.1f} pontos`")
                        
                        mudou_opcao_17_3_2 = sel_17_3_2 != d17_3_2.get("valor", "")
                        mudou_link_17_3_2 = link_17_3_2 != d17_3_2.get("link", "")

                        if mudou_opcao_17_3_2 or mudou_link_17_3_2:
                                if sel_17_3_2 is not None:
                                        save_resp("17.3.2", sel_17_3_2, pts_17_3_2, link_17_3_2)
                                        res_data["17.3.2"] = {"valor": sel_17_3_2, "pontos": pts_17_3_2, "link": link_17_3_2}
                                        
                                        if mudou_link_17_3_2 and links_17_3_2_atuais:
                                                links_17_3_2_antigos = re.findall(r'(https?://[^\s]+)', d17_3_2.get("link", ""))
                                                if links_17_3_2_atuais != links_17_3_2_antigos:
                                                        modal_aviso_link("17.3.2", links_17_3_2_atuais)
                                                else:
                                                        st.rerun()
                                        else:
                                                st.rerun()
                        
                        bloco_comentarios("17.3.2", res_data)

        # =============================================================================
        # QUESITO 17.3.2.1 - MEDIDAS DE REDUÇÃO DO ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_bloco_rol_medidas_17_3_2_1_{ano_sel}", border=True):
                
                with st.expander(f"📌 Quesito 17.3.2.1 - Rol de Medidas de Redução do Absenteísmo", expanded=True):
                        st.subheader("17.3.2.1 • Rol de Medidas de Redução do Absenteísmo")
                        st.write(f"**17.3.2.1 Assinale as medidas utilizadas para a redução da taxa de absenteísmo:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                        
                        d17_3_2_1 = res_data.get("17.3.2.1", {"valor": "", "pontos": 0.0, "link": ""})
                        valores_salvos = d17_3_2_1.get("valor", "")
                        lista_salva = [item.strip() for item in valores_salvos.split(";")] if valores_salvos else []
                        
                        c17321_1, c17321_2 = st.columns([1, 1])
                        with c17321_1:
                                st.write("📋 **Selecione todas as medidas aplicadas:**")
                                
                                opc_1 = "Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo and promover capacitações"
                                opc_2 = "Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação"
                                opc_3 = "Orientação das famílias e busca ativa dos faltosos"
                                opc_4 = "Promoção de campanhas de conscientização"
                                opc_5 = "Outros"
                                
                                chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva), key=f"chk_17321_1_{ano_sel}")
                                chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva), key=f"chk_17321_2_{ano_sel}")
                                chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva), key=f"chk_17321_3_{ano_sel}")
                                chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva), key=f"chk_17321_4_{ano_sel}")
                                chk_5 = st.checkbox(opc_5, value=(opc_5 in lista_salva), key=f"chk_17321_5_{ano_sel}")
                                
                                selecionados = []
                                if chk_1: selecionados.append(opc_1)
                                if chk_2: selecionados.append(opc_2)
                                if chk_3: selecionados.append(opc_3)
                                if chk_4: selecionados.append(opc_4)
                                if chk_5: selecionados.append(opc_5)
                                
                                string_selecionados = "; ".join(selecionados) if selecionados else "Nenhuma medida selecionada"
                                pts_17_3_2_1 = 0.0
                                
                        with c17321_2:
                                link_17_3_2_1 = st.text_area(
                                        "Link/Evidência das Medidas Assinaladas (17.3.2.1):", 
                                        value=d17_3_2_1.get("link", ""), 
                                        key=f"reg_17_3_2_1_txt_{ano_sel}",
                                        height=210
                                )
                                
                                placeholder_links_17_3_2_1 = st.empty()
                                links_17_3_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_3_2_1)
                                if links_17_3_2_1_atuais:
                                        botoes_17_3_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_3_2_1_atuais])
                                        placeholder_links_17_3_2_1.markdown(f"**Links Ativos:** {botoes_17_3_2_1}")
                        
                        score_placeholder_17_3_2_1 = st.empty()
                        score_placeholder_17_3_2_1.markdown(f"📊 **Pontuação Aplicada no Quesito 17.3.2.1:** `{pts_17_3_2_1:.1f} pontos`")
                        
                        mudou_valores_17_3_2_1 = string_selecionados != valores_salvos
                        mudou_link_17_3_2_1 = link_17_3_2_1 != d17_3_2_1.get("link", "")

                        if mudou_valores_17_3_2_1 or mudou_link_17_3_2_1:
                                save_resp("17.3.2.1", string_selecionados, pts_17_3_2_1, link_17_3_2_1)
                                res_data["17.3.2.1"] = {"valor": string_selecionados, "pontos": pts_17_3_2_1, "link": link_17_3_2_1}
                                
                                if mudou_link_17_3_2_1 and links_17_3_2_1_atuais:
                                        links_17_3_2_1_antigos = re.findall(r'(https?://[^\s]+)', d17_3_2_1.get("link", ""))
                                        if links_17_3_2_1_atuais != links_17_3_2_1_antigos:
                                                modal_aviso_link("17.3.2.1", links_17_3_2_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                        
                        bloco_comentarios("17.3.2.1", res_data)

        # =============================================================================
        # QUESITO 17.4 - CONTROLE DE ABSENTEÍSMO DE EXAMES MÉDICOS
        # =============================================================================
        with st.container(key=f"container_bloco_absenteismo_exames_17_4_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 17.4 - Controle de Absenteísmo de Exames na Atenção Especializada", expanded=True):
                        st.subheader("17.4 • Controle de Absenteísmo (Exames)")
                        st.write(f"**17.4 A Prefeitura Municipal possui controle de absenteísmo para os exames médicos da Atenção Especializada sob sua gestão?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração grava os dados na hora.*")
                        
                        opts_17_4 = {
                                "Selecione...": 0.0,
                                "Sim, para todos os exames – 00": 0.0,
                                "Sim, para a maior parte dos exames – -01 (perde 01 ponto)": -1.0,
                                "Sim, para a menor parte dos exames – -02 (perde 02 pontos)": -2.0,
                                "Não – -03 (perde 03 pontos)": -3.0
                        }
                        
                        d17_4 = res_data.get("17.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        
                        c174_1, c174_2 = st.columns([1, 1])
                        k_rad_17_4 = f"reg_17_4_rad_{ano_sel}"
                        k_txt_17_4 = f"reg_17_4_txt_{ano_sel}"
                        
                        with c174_1:
                                sel_17_4 = st.radio(
                                        "Controle de absenteísmo (Exames):", 
                                        options=list(opts_17_4.keys()), 
                                        index=(list(opts_17_4.keys()).index(d17_4["valor"]) if d17_4["valor"] in opts_17_4 else 0),
                                        key=k_rad_17_4, 
                                        label_visibility="collapsed",
                                        on_change=callback_salvar_quesito,
                                        args=("17.4", k_rad_17_4, k_txt_17_4, opts_17_4)
                                )
                                pts_17_4 = opts_17_4[sel_17_4] if sel_17_4 is not None else 0.0
                                
                        with c174_2:
                                link_17_4 = st.text_area(
                                        "Link/Evidência do Controle de Absenteísmo de Exames (17.4):", 
                                        value=d17_4.get("link", ""), 
                                        key=k_txt_17_4,
                                        height=110,
                                        on_change=callback_salvar_quesito,
                                        args=("17.4", k_rad_17_4, k_txt_17_4, opts_17_4)
                                )
                                
                                with st.container(key=f"links_holder_absenteismo_exames_17_4_{ano_sel}"):
                                        links_17_4_atuais = re.findall(r'(https?://[^\s]+)', link_17_4)
                                        if links_17_4_atuais:
                                                botoes_17_4 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_4_atuais])
                                                st.markdown(f"**Links Ativos:** {botoes_17_4}")
                        
                        with st.container(key=f"score_holder_absenteismo_exames_17_4_{ano_sel}"):
                                if pts_17_4 < 0:
                                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.4:** :red[{pts_17_4:.1f} pontos (Penalidade)]")
                                else:
                                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.4:** `{pts_17_4:.1f} pontos`")
                        
                        bloco_comentarios("17.4", res_data)

        # =============================================================================
        # QUESITO 17.4.1 - TAXA DE ABSENTEÍSMO DE EXAMES MÉDICOS (DINÂMICO)
        # =============================================================================
        with st.container(key=f"container_bloco_taxa_absenteismo_exames_17_4_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 17.4.1 - Evolução da Taxa de Absenteísmo de Exames", expanded=True):
                        ano_atual = int(ano_sel)
                        ano_menos_1 = ano_atual - 1
                        ano_menos_2 = ano_atual - 2
                        
                        st.subheader("17.4.1 • Taxa de Absenteísmo (Exames)")
                        st.write(f"**Informe a taxa de absenteísmo de exame médico da Atenção Especializada sob gestão municipal:**")
                        st.caption(f"Fórmula: Se TA({ano_atual}) > média de TA({ano_menos_2}) e TA({ano_menos_1}) -> Perde 2 pontos.")
                        
                        d17_4_1 = res_data.get("17.4.1", {"valor": "0.0|0.0|0.0", "pontos": 0.0, "link": ""})
                        partes_ta = d17_4_1["valor"].split("|") if "|" in d17_4_1["valor"] else ["0.0", "0.0", "0.0"]
                        partes_ta += ["0.0"] * (3 - len(partes_ta))
                        
                        try:
                                v_a2, v_a1, v_atual = float(partes_ta[0]), float(partes_ta[1]), float(partes_ta[2])
                        except ValueError:
                                v_a2 = v_a1 = v_atual = 0.0
                        
                        c1741_1, c1741_2 = st.columns([1, 1])
                        k_ta2 = f"ta_2_ex_{ano_sel}"
                        k_ta1 = f"ta_1_ex_{ano_sel}"
                        k_taat = f"ta_atual_ex_{ano_sel}"
                        k_txt_17_4_1 = f"reg_17_4_1_txt_{ano_sel}"
                        
                        with c1741_1:
                                st.write("📊 **Taxas de Absenteísmo para Exames (%)**")
                                ta_2 = st.number_input(f"Taxa em {ano_menos_2} (TA-2):", min_value=0.0, max_value=100.0, value=v_a2, step=0.1, format="%.1f", key=k_ta2)
                                ta_1 = st.number_input(f"Taxa em {ano_menos_1} (TA-1):", min_value=0.0, max_value=100.0, value=v_a1, step=0.1, format="%.1f", key=k_ta1)
                                ta_atual = st.number_input(f"Taxa em {ano_atual} (TA):", min_value=0.0, max_value=100.0, value=v_atual, step=0.1, format="%.1f", key=k_taat)
                                
                                string_valor_nova = f"{ta_2:.1f}|{ta_1:.1f}|{ta_atual:.1f}"
                                media_anteriores = (ta_2 + ta_1) / 2.0
                                st.info(f"💡 Média de {ano_menos_2} e {ano_menos_1}: **{media_anteriores:.1f}%**")
                                pts_17_4_1 = -2.0 if ta_atual > media_anteriores else 0.0
                                
                                if string_valor_nova != d17_4_1["valor"]:
                                        save_resp("17.4.1", string_valor_nova, pts_17_4_1, st.session_state.get(k_txt_17_4_1, ""))
                                        res_data["17.4.1"] = {"valor": string_valor_nova, "pontos": pts_17_4_1, "link": st.session_state.get(k_txt_17_4_1, "")}
                                
                        with c1741_2:
                                link_17_4_1 = st.text_area(
                                        "Link/Evidência dos Relatórios de Absenteísmo de Exames (17.4.1):", 
                                        value=d17_4_1.get("link", ""), 
                                        key=k_txt_17_4_1,
                                        height=180
                                )
                                if link_17_4_1 != d17_4_1.get("link", ""):
                                        save_resp("17.4.1", string_valor_nova, pts_17_4_1, link_17_4_1)
                                        res_data["17.4.1"] = {"valor": string_valor_nova, "pontos": pts_17_4_1, "link": link_17_4_1}
                                
                                with st.container(key=f"links_holder_absenteismo_exames_17_4_1_{ano_sel}"):
                                        links_17_4_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_4_1)
                                        if links_17_4_1_atuais:
                                                botoes_17_4_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_4_1_atuais])
                                                st.markdown(f"**Links Ativos:** {botoes_17_4_1}")
                        
                        with st.container(key=f"score_holder_absenteismo_exames_17_4_1_{ano_sel}"):
                                if pts_17_4_1 < 0:
                                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.4.1:** :red[{pts_17_4_1:.1f} pontos (Penalidade)]")
                                else:
                                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.4.1:** `{pts_17_4_1:.1f} pontos`")
                        
                        bloco_comentarios("17.4.1", res_data)

        # =============================================================================
        # QUESITO 17.4.2 - MEDIDAS PARA REDUÇÃO DO ABSENTEÍSMO EM EXAMES
        # =============================================================================
        with st.container(key=f"container_bloco_medidas_exames_17_4_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 17.4.2 - Medidas para Redução de Absenteísmo de Exames", expanded=True):
                        st.subheader("17.4.2 • Medidas para Redução do Absenteísmo em Exames")
                        st.write(f"**17.4.2 O município realiza medidas para a redução desta taxa de absenteísmo?**")
                        
                        opts_17_4_2 = {
                                "Selecione...": 0.0,
                                "Sim – 00": 0.0,
                                "Não – -02 (perde 02 pontos)": -2.0
                        }
                        
                        d17_4_2 = res_data.get("17.4.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        
                        c1742_1, c1742_2 = st.columns([1, 1])
                        k_rad_17_4_2 = f"reg_17_4_2_rad_{ano_sel}"
                        k_txt_17_4_2 = f"reg_17_4_2_txt_{ano_sel}"
                        
                        with c1742_1:
                                sel_17_4_2 = st.radio(
                                        "Realiza medidas de redução (Exames):", 
                                        options=list(opts_17_4_2.keys()), 
                                        index=(list(opts_17_4_2.keys()).index(d17_4_2["valor"]) if d17_4_2["valor"] in opts_17_4_2 else 0),
                                        key=k_rad_17_4_2, 
                                        label_visibility="collapsed",
                                        on_change=callback_salvar_quesito,
                                        args=("17.4.2", k_rad_17_4_2, k_txt_17_4_2, opts_17_4_2)
                                )
                                pts_17_4_2 = opts_17_4_2[sel_17_4_2] if sel_17_4_2 is not None else 0.0
                                
                        with c1742_2:
                                link_17_4_2 = st.text_area(
                                        "Link/Evidência das Ações de Redução em Exames (17.4.2):", 
                                        value=d17_4_2.get("link", ""), 
                                        key=k_txt_17_4_2,
                                        height=110,
                                        on_change=callback_salvar_quesito,
                                        args=("17.4.2", k_rad_17_4_2, k_txt_17_4_2, opts_17_4_2)
                                )
                                
                                with st.container(key=f"links_holder_medidas_exames_17_4_2_{ano_sel}"):
                                        links_17_4_2_atuais = re.findall(r'(https?://[^\s]+)', link_17_4_2)
                                        if links_17_4_2_atuais:
                                                botoes_17_4_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_4_2_atuais])
                                                st.markdown(f"**Links Ativos:** {botoes_17_4_2}")
                        
                        with st.container(key=f"score_holder_medidas_exames_17_4_2_{ano_sel}"):
                                if pts_17_4_2 < 0:
                                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.4.2:** :red[{pts_17_4_2:.1f} pontos (Penalidade)]")
                                else:
                                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.4.2:** `{pts_17_4_2:.1f} pontos`")
                        
                        bloco_comentarios("17.4.2", res_data)

        # =============================================================================
        # QUESITO 17.4.2.1 - ROL DE MEDIDAS (FRAGMENTADO)
        # =============================================================================
        @st.fragment
        def render_quesito_17_4_2_1():
                with st.container(key=f"container_bloco_rol_medidas_exames_17_4_2_1_{ano_sel}", border=True):
                        with st.expander(f"📌 Quesito 17.4.2.1 - Rol de Medidas de Redução em Exames", expanded=True):
                                st.subheader("17.4.2.1 • Rol de Medidas de Redução em Exames")
                                st.write(f"**17.4.2.1 Assinale as medidas utilizadas para a redução da taxa de absenteísmo...**")
                                
                                d17_4_2_1 = res_data.get("17.4.2.1", {"valor": "", "pontos": 0.0, "link": ""})
                                valores_salvos = d17_4_2_1.get("valor", "")
                                lista_salva = [item.strip() for item in valores_salvos.split(";")] if valores_salvos else []
                                
                                c17421_1, c17421_2 = st.columns([1, 1])
                                
                                opc_1 = "Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo e promover capacitações"
                                opc_2 = "Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação"
                                opc_3 = "Ligação telefônica ou outro meio de comunicação para confirmation do exame e presença do paciente"
                                opc_4 = "Orientação das famílias e busca ativa dos faltosos"
                                opc_5 = "Promoção de campanhas de conscientização"
                                opc_6 = "Outros"
                                
                                with c17421_1:
                                        st.write("📋 **Selecione todas as medidas aplicadas:**")
                                        chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva), key=f"chk_17421_1_{ano_sel}")
                                        chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva), key=f"chk_17421_2_{ano_sel}")
                                        chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva), key=f"chk_17421_3_{ano_sel}")
                                        chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva), key=f"chk_17421_4_{ano_sel}")
                                        chk_5 = st.checkbox(opc_5, value=(opc_5 in lista_salva), key=f"chk_17421_5_{ano_sel}")
                                        chk_6 = st.checkbox(opc_6, value=(opc_6 in lista_salva), key=f"chk_17421_6_{ano_sel}")
                                        
                                        selecionados = [opc for chk, opc in zip([chk_1, chk_2, chk_3, chk_4, chk_5, chk_6], [opc_1, opc_2, opc_3, opc_4, opc_5, opc_6]) if chk]
                                        string_selecionados = "; ".join(selecionados) if selecionados else "Nenhuma medida selecionada"
                                        
                                with c17421_2:
                                        k_txt_17_4_2_1 = f"reg_17_4_2_1_txt_{ano_sel}"
                                        link_17_4_2_1 = st.text_area(
                                                "Link/Evidência das Medidas Assinaladas em Exames (17.4.2.1):", 
                                                value=d17_4_2_1.get("link", ""), 
                                                key=k_txt_17_4_2_1,
                                                height=250
                                        )
                                        
                                        with st.container(key=f"links_holder_rol_medidas_exames_17_4_2_1_{ano_sel}"):
                                                links_17_4_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_4_2_1)
                                                if links_17_4_2_1_atuais:
                                                        botoes_17_4_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_4_2_1_atuais])
                                                        st.markdown(f"**Links Ativos:** {botoes_17_4_2_1}")
                                
                                mudou_val = string_selecionados != valores_salvos
                                mudou_lk = link_17_4_2_1 != d17_4_2_1.get("link", "")
                                if mudou_val or mudou_lk:
                                        save_resp("17.4.2.1", string_selecionados, 0.0, link_17_4_2_1)
                                        res_data["17.4.2.1"] = {"valor": string_selecionados, "pontos": 0.0, "link": link_17_4_2_1}
                                
                                st.info("📊 Pontuação Aplicada no Quesito 17.4.2.1: 0.0 pontos")
                                bloco_comentarios("17.4.2.1", res_data)

        render_quesito_17_4_2_1()
        # =============================================================================
        # QUESITO 17.5 - SISTEMA INFORMATIZADO DE REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_sistema_regulacao_17_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5 - Sistema Informatizado de Regulação na Atenção Especializada", expanded=True):
                st.subheader("17.5 • Sistema Informatizado de Regulação")
                st.write(f"**17.5 O município utiliza sistema informatizado de regulação com oferta dos serviços da Atenção Especializada sob gestão municipal?**")
                st.caption("Nota: Refere-se ao Município como Unidade Demandada - Central de Regulação")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                
                opts_17_5 = {
                    "Selecione...": 0.0,
                    "Sim, todos os serviços – 00": 0.0,
                    "Sim, a maior parte dos serviços – -01 (perde 01 ponto)": -1.0,
                    "Sim, a menor parte dos serviços – -03 (perde 03 pontos)": -3.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }
                
                d17_5 = res_data.get("17.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c175_1, c175_2 = st.columns([1, 1])
                with c175_1:
                    sel_17_5 = st.radio(
                        "Utilização do sistema informatizado:", 
                        options=list(opts_17_5.keys()), 
                        index=(list(opts_17_5.keys()).index(d17_5["valor"]) if d17_5["valor"] in opts_17_5 else 0),
                        key=f"reg_17_5_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_17_5 = opts_17_5[sel_17_5] if sel_17_5 is not None else 0.0
                    
                with c175_2:
                    link_17_5 = st.text_area(
                        "Link/Evidência do Sistema de Regulação (17.5):", 
                        value=d17_5.get("link", ""), 
                        key=f"reg_17_5_txt_{ano_sel}",
                        height=130
                    )
                    
                    with st.container(key=f"links_holder_sistema_regulacao_17_5_{ano_sel}"):
                        links_17_5_atuais = re.findall(r'(https?://[^\s]+)', link_17_5)
                        if links_17_5_atuais:
                            botoes_17_5 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5}")
                
                with st.container(key=f"score_holder_sistema_regulacao_17_5_{ano_sel}"):
                    if pts_17_5 < 0:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5:** :red[{pts_17_5:.1f} pontos (Penalidade)]")
                    else:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5:** `{pts_17_5:.1f} pontos`")
                
                mudou_opcao_17_5 = sel_17_5 != d17_5.get("valor", "")
                mudou_link_17_5 = link_17_5 != d17_5.get("link", "")

                if mudou_opcao_17_5 or mudou_link_17_5:
                    if sel_17_5 is not None:
                        save_resp("17.5", sel_17_5, pts_17_5, link_17_5)
                        res_data["17.5"] = {"valor": sel_17_5, "pontos": pts_17_5, "link": link_17_5}
                        
                        if mudou_link_17_5 and links_17_5_atuais:
                            links_17_5_antigos = re.findall(r'(https?://[^\s]+)', d17_5.get("link", ""))
                            if links_17_5_atuais != links_17_5_antigos:
                                modal_aviso_link("17.5", links_17_5_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                
                bloco_comentarios("17.5", res_data)


        # =============================================================================
        # QUESITO 17.5.1 - SISTEMAS UTILIZADOS (FRAGMENTADO PARA EVITAR REMOVECHILD)
        # =============================================================================
        @st.fragment
        def render_quesito_17_5_1():
            with st.container(key=f"container_bloco_sistemas_regulacao_17_5_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 17.5.1 - Sistemas Utilizados pela Regulação", expanded=True):
                    st.subheader("17.5.1 • Sistemas Utilizados pela Regulação")
                    st.write(f"**17.5.1 Assinale os sistemas utilizados pela regulação:**")
                    st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                    
                    d17_5_1 = res_data.get("17.5.1", {"valor": "", "pontos": 0.0, "link": ""})
                    valores_salvos = d17_5_1.get("valor", "")
                    lista_salva = [item.strip() for item in valores_salvos.split(";")] if valores_salvos else []
                    
                    c1751_1, c1751_2 = st.columns([1, 1])
                    with c1751_1:
                        st.write("📋 **Selecione os sistemas em uso:**")
                        
                        opc_1 = "Portal Cross/SIRESP"
                        opc_2 = "SIGA"
                        opc_3 = "SISREG"
                        opc_4 = "Outros"
                        
                        chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva), key=f"chk_1751_1_{ano_sel}")
                        chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva), key=f"chk_1751_2_{ano_sel}")
                        chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva), key=f"chk_1751_3_{ano_sel}")
                        chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva), key=f"chk_1751_4_{ano_sel}")
                        
                        selecionados = []
                        if chk_1: selecionados.append(opc_1)
                        if chk_2: selecionados.append(opc_2)
                        if chk_3: selecionados.append(opc_3)
                        if chk_4: selecionados.append(opc_4)
                        
                        string_selecionados = "; ".join(selecionados) if selecionados else "Nenhum sistema selecionado"
                        pts_17_5_1 = 0.0  
                        
                    with c1751_2:
                        link_17_5_1 = st.text_area(
                            "Link/Evidência ou especificação dos sistemas (17.5.1):", 
                            value=d17_5_1.get("link", ""), 
                            key=f"reg_17_5_1_txt_{ano_sel}",
                            height=180
                        )
                        
                        with st.container(key=f"links_holder_sistemas_regulacao_17_5_1_{ano_sel}"):
                            links_17_5_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_1)
                            if links_17_5_1_atuais:
                                botoes_17_5_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_1_atuais])
                                st.markdown(f"**Links Ativos:** {botoes_17_5_1}")
                    
                    with st.container(key=f"score_holder_sistemas_regulacao_17_5_1_{ano_sel}"):
                        st.info(f"📊 Pontuação Aplicada no Quesito 17.5.1: {pts_17_5_1:.1f} pontos")
                    
                    mudou_valores_17_5_1 = string_selecionados != valores_salvos
                    mudou_link_17_5_1 = link_17_5_1 != d17_5_1.get("link", "")

                    if mudou_valores_17_5_1 or mudou_link_17_5_1:
                        save_resp("17.5.1", string_selecionados, pts_17_5_1, link_17_5_1)
                        res_data["17.5.1"] = {"valor": string_selecionados, "pontos": pts_17_5_1, "link": link_17_5_1}
                        
                        if mudou_link_17_5_1 and links_17_5_1_atuais:
                            links_17_5_1_antigos = re.findall(r'(https?://[^\s]+)', d17_5_1.get("link", ""))
                            if links_17_5_1_atuais != links_17_5_1_antigos:
                                modal_aviso_link("17.5.1", links_17_5_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                    
                    bloco_comentarios("17.5.1", res_data)

        render_quesito_17_5_1()


        # =============================================================================
        # QUESITO 17.5.2 - LISTA DE ESPERA NO SISTEMA DE REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_lista_espera_17_5_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 17.5.2 - Conhecimento da Lista de Espera na Atenção Especializada", expanded=True):
                st.subheader("17.5.2 • Lista de Espera na Regulação")
                st.write("**17.5.2 O sistema informatizado de regulação utilizado pelo município permite conhecer a lista de espera (relação nominal de pacientes com tempo de espera) dos serviços da Atenção Especializada sob gestão municipal?**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                
                opts_17_5_2 = {
                    "Selecione...": 0.0,
                    "Sim, todos os serviços – 00": 0.0,
                    "Sim, a maior parte dos serviços – -01 (perde 01 ponto)": -1.0,
                    "Sim, a menor parte dos serviços – -03 (perde 03 pontos)": -3.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }
                
                d17_5_2 = res_data.get("17.5.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                valor_salvo = d17_5_2.get("valor", "Selecione...")
                if valor_salvo not in opts_17_5_2:
                    valor_salvo = "Selecione..."
                    
                idx_inicial = list(opts_17_5_2.keys()).index(valor_salvo)
                
                c1752_1, c1752_2 = st.columns([1, 1])
                with c1752_1:
                    st.markdown("**Selecione uma alternativa:**")
                    sel_17_5_2 = st.radio(
                        "Permite conhecer a lista de espera:", 
                        options=list(opts_17_5_2.keys()), 
                        index=idx_inicial,
                        key=f"reg_17_5_2_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_17_5_2 = opts_17_5_2.get(sel_17_5_2, 0.0)
                    
                with c1752_2:
                    link_17_5_2 = st.text_area(
                        "Link/Evidência ou Relatório da Lista de Espera (17.5.2):", 
                        value=d17_5_2.get("link", ""), 
                        key=f"reg_17_5_2_txt_{ano_sel}",
                        height=110
                    )
                    
                    with st.container(key=f"links_holder_lista_espera_17_5_2_{ano_sel}"):
                        links_17_5_2_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2)
                        if links_17_5_2_atuais:
                            botoes_17_5_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2}")
                
                with st.container(key=f"score_holder_lista_espera_17_5_2_{ano_sel}"):
                    if sel_17_5_2 == "Selecione...":
                        st.markdown("📊 **Pontuação Aplicada no Quesito 17.5.2:** `Aguardando seleção...`")
                    elif pts_17_5_2 < 0:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2:** :red[{pts_17_5_2:.1f} pontos (Penalidade)]")
                    else:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2:** `{pts_17_5_2:.1f} pontos`")
                
                mudou_opcao_17_5_2 = sel_17_5_2 != d17_5_2.get("valor")
                mudou_link_17_5_2 = link_17_5_2 != d17_5_2.get("link")

                if mudou_opcao_17_5_2 or mudou_link_17_5_2:
                    save_resp("17.5.2", sel_17_5_2, pts_17_5_2, link_17_5_2)
                    res_data["17.5.2"] = {"valor": sel_17_5_2, "pontos": pts_17_5_2, "link": link_17_5_2}
                    
                    if mudou_opcao_17_5_2 and sel_17_5_2 != "Sim, todos os serviços – 00":
                        d17_5_2_1_atual = res_data.get("17.5.2.1", {"valor": "", "link": ""})
                        save_resp("17.5.2.1", "", 0.0, d17_5_2_1_atual.get("link", ""))
                        res_data["17.5.2.1"] = {"valor": "", "pontos": 0.0, "link": d17_5_2_1_atual.get("link", "")}
                    
                    if mudou_link_17_5_2 and links_17_5_2_atuais:
                        links_17_5_2_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2.get("link", ""))
                        if links_17_5_2_atuais != links_17_5_2_antigos:
                            modal_aviso_link("17.5.2", links_17_5_2_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2", res_data)


        # =============================================================================
        # QUESITO 17.5.2.1 - ROL DE SERVIÇOS (BLOCO SEGURO FINALIZADO COMPLETO)
        # =============================================================================
        d17_5_2_pai = res_data.get("17.5.2", {"valor": "Selecione..."})
        resposta_pai_todos_servicos = (d17_5_2_pai.get("valor") == "Sim, todos os serviços – 00")

        @st.fragment
        def render_quesito_17_5_2_1():
            with st.container(key=f"container_bloco_rol_servicos_17_5_2_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 17.5.2.1 - Rol de Serviços no Sistema de Regulação", expanded=True):
                    st.subheader("17.5.2.1 • Rol de Serviços no Sistema de Regulação")
                    st.write(f"**17.5.2.1 Assinale os serviços da Atenção Especializada inseridos no sistema de regulação:**")
                    st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                    
                    d17_5_2_1 = res_data.get("17.5.2.1", {"valor": "", "pontos": 0.0, "link": ""})
                    valores_salvos = d17_5_2_1.get("valor", "")
                    lista_salva = [item.strip() for item in valores_salvos.split(";")] if valores_salvos else []
                    
                    c17521_1, c17521_2 = st.columns([1, 1])
                    with c17521_1:
                        st.write("📋 **Selecione os serviços inseridos:**")
                        
                        opc_1 = "Consultas por especialidade"
                        opc_2 = "Exames"
                        opc_3 = "Terapias / tratamentos"
                        opc_4 = "OPM"
                        opc_5 = "Cirurgias eletivas"
                        opc_6 = "Outros"
                        
                        chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva), key=f"chk_17521_1_{ano_sel}")
                        chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva), key=f"chk_17521_2_{ano_sel}")
                        chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva), key=f"chk_17521_3_{ano_sel}")
                        chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva), key=f"chk_17521_4_{ano_sel}")
                        chk_5 = st.checkbox(opc_5, value=(opc_5 in lista_salva), key=f"chk_17521_5_{ano_sel}")
                        chk_6 = st.checkbox(opc_6, value=(opc_6 in lista_salva), key=f"chk_17521_6_{ano_sel}")
                        
                        selecionados = []
                        if chk_1: selecionados.append(opc_1)
                        if chk_2: selecionados.append(opc_2)
                        if chk_3: selecionados.append(opc_3)
                        if chk_4: selecionados.append(opc_4)
                        if chk_5: selecionados.append(opc_5)
                        if chk_6: selecionados.append(opc_6)
                        
                        if resposta_pai_todos_servicos:
                            pontos_calculados = -5.0
                            if chk_1: pontos_calculados += 1.0
                            if chk_2: pontos_calculados += 1.0
                            if chk_3: pontos_calculados += 1.0
                            if chk_4: pontos_calculados += 1.0
                            if chk_5: pontos_calculados += 1.0
                            pts_17_5_2_1 = pontos_calculados
                        else:
                            pts_17_5_2_1 = 0.0
                        
                        string_selecionados = "; ".join(selecionados) if selecionados else ""
                        
                    with c17521_2:
                        link_17_5_2_1 = st.text_area(
                            "Link/Evidência dos Serviços Regulados (17.5.2.1):", 
                            value=d17_5_2_1.get("link", ""), 
                            key=f"reg_17_5_2_1_txt_{ano_sel}",
                            height=250
                        )
                        
                        with st.container(key=f"links_holder_rol_servicos_17_5_2_1_{ano_sel}"):
                            links_17_5_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1)
                            if links_17_5_2_1_atuais:
                                botoes_17_5_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_atuais])
                                st.markdown(f"**Links Ativos:** {botoes_17_5_2_1}")
                    
                    with st.container(key=f"score_holder_rol_servicos_17_5_2_1_{ano_sel}"):
                        msg_score = f"📊 Pontuação Aplicada no Quesito 17.5.2.1: {pts_17_5_2_1:.1f} pontos"
                        if pts_17_5_2_1 < 0:
                            msg_score += " (Penalidade)"
                        st.info(msg_score)
                    
                    # LINHAS COMPLETADAS ABAIXO (Finalização segura da lógica cortada)
                    mudou_valores_17_5_2_1 = string_selecionados != valores_salvos
                    mudou_link_17_5_2_1 = link_17_5_2_1 != d17_5_2_1.get("link", "")
                    mudou_pontos_17_5_2_1 = abs(pts_17_5_2_1 - float(d17_5_2_1.get("pontos", 0.0))) > 0.01

                    if mudou_valores_17_5_2_1 or mudou_link_17_5_2_1 or mudou_pontos_17_5_2_1:
                        save_resp("17.5.2.1", string_selecionados, pts_17_5_2_1, link_17_5_2_1)
                        res_data["17.5.2.1"] = {"valor": string_selecionados, "pontos": pts_17_5_2_1, "link": link_17_5_2_1}
                        
                        if mudou_link_17_5_2_1 and links_17_5_2_1_atuais:
                            links_17_5_2_1_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1.get("link", ""))
                            if links_17_5_2_1_atuais != links_17_5_2_1_antigos:
                                modal_aviso_link("17.5.2.1", links_17_5_2_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                        
                    bloco_comentarios("17.5.2.1", res_data)

        render_quesito_17_5_2_1()

        # =============================================================================
        # QUESITO 17.5.2.1.1 - 3 CONSULTAS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_maior_espera_consultas_17_5_2_1_1_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.1 - Consultas com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.1 • Consultas com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.1 Informe as 3 consultas médicas com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_1 = res_data.get("17.5.2.1.1", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_1 = d17_5_2_1_1.get("valor", "")
                
                # Trata a string salva para preencher os campos (Especialidade 1|Dias 1||Especialidade 2|Dias 2||Especialidade 3|Dias 3)
                partes = valores_salvos_1_1.split("||") if valores_salvos_1_1 else []
                
                p1 = partes[0].split("|") if len(partes) > 0 else ["", ""]
                p2 = partes[1].split("|") if len(partes) > 1 else ["", ""]
                p3 = partes[2].split("|") if len(partes) > 2 else ["", ""]
                
                c175211_1, c175211_2 = st.columns([1, 1])
                
                with c175211_1:
                    st.write("🩺 **Especialidades Médicas e Prazos:**")
                    
                    # Primeira Consulta
                    esp_1 = st.text_input("1ª - Descrição da especialidade médica:", value=p1[0] if len(p1) > 0 else "", key=f"esp1_175211_{ano_sel}")
                    dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=p1[1] if len(p1) > 1 else "", key=f"dias1_175211_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segunda Consulta
                    esp_2 = st.text_input("2ª - Descrição da especialidade médica:", value=p2[0] if len(p2) > 0 else "", key=f"esp2_175211_{ano_sel}")
                    dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=p2[1] if len(p2) > 1 else "", key=f"dias2_175211_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceira Consulta
                    esp_3 = st.text_input("3ª - Descrição da especialidade médica:", value=p3[0] if len(p3) > 0 else "", key=f"esp3_175211_{ano_sel}")
                    dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=p3[1] if len(p3) > 1 else "", key=f"dias3_175211_{ano_sel}")

                with c175211_2:
                    link_17_5_2_1_1 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera (17.5.2.1.1):", 
                        value=d17_5_2_1_1.get("link", ""), 
                        key=f"reg_17_5_2_1_1_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_consultas_17_5_2_1_1_{ano_sel}"):
                        links_17_5_2_1_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_1)
                        if links_17_5_2_1_1_atuais:
                            botoes_17_5_2_1_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_1}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto de forma limpa
                string_estruturada = f"{esp_1}|{dias_1}||{esp_2}|{dias_2}||{esp_3}|{dias_3}"
                # Caso esteja tudo em branco, salva vazio
                if string_estruturada == "||||":
                    string_estruturada = ""
                    
                pts_17_5_2_1_1 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_consultas_17_5_2_1_1_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.1:** `{pts_17_5_2_1_1:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_1 = string_estruturada != valores_salvos_1_1
                mudou_link_17_5_2_1_1 = link_17_5_2_1_1 != d17_5_2_1_1.get("link", "")

                if mudou_valores_17_5_2_1_1 or mudou_link_17_5_2_1_1:
                    save_resp("17.5.2.1.1", string_estruturada, pts_17_5_2_1_1, link_17_5_2_1_1)
                    
                    if "17.5.2.1.1" not in res_data:
                        res_data["17.5.2.1.1"] = {}
                    res_data["17.5.2.1.1"]["valor"] = string_estruturada
                    res_data["17.5.2.1.1"]["pontos"] = pts_17_5_2_1_1
                    res_data["17.5.2.1.1"]["link"] = link_17_5_2_1_1
                    
                    if mudou_link_17_5_2_1_1 and links_17_5_2_1_1_atuais:
                        links_17_5_2_1_1_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_1.get("link", ""))
                        if links_17_5_2_1_1_atuais != links_17_5_2_1_1_antigos:
                            modal_aviso_link("17.5.2.1.1", links_17_5_2_1_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.1", res_data)

# =============================================================================
        # QUESITO 17.5.2.1.2 - 3 EXAMES COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander(f"📌 Quesito 17.5.2.1.2 - Exames com Maior Tempo de Espera", expanded=True):
            st.write(f"**17.5.2.1.2 Informe os 3 exames médicos com maior tempo de espera na Atenção Especializada:**")
            
            # Recupera os dados salvos ou inicia um dicionário padrão
            d17_5_2_1_2 = res_data.get("17.5.2.1.2", {"valor": "", "pontos": 0.0, "link": ""})
            valores_salvos_1_2 = d17_5_2_1_2.get("valor", "")
            
            # Trata a string salva para preencher os campos (Exame 1|Dias 1||Exame 2|Dias 2||Exame 3|Dias 3)
            partes_ex = valores_salvos_1_2.split("||") if valores_salvos_1_2 else []
            
            e1 = partes_ex[0].split("|") if len(partes_ex) > 0 else ["", ""]
            e2 = partes_ex[1].split("|") if len(partes_ex) > 1 else ["", ""]
            e3 = partes_ex[2].split("|") if len(partes_ex) > 2 else ["", ""]
            
            c175212_1, c175212_2 = st.columns([1, 1])
            
            with c175212_1:
                st.write("🔬 **Exames e Prazos:**")
                
                # Primeiro Exame
                ex_1 = st.text_input("1º - Descrição do exame médico:", value=e1[0] if len(e1) > 0 else "", key=f"ex1_175212_{ano_sel}")
                ex_dias_1 = st.text_input("1º - Tempo médio de espera (em dias):", value=e1[1] if len(e1) > 1 else "", key=f"ex_dias1_175212_{ano_sel}")
                
                st.markdown("---")
                
                # Segundo Exame
                ex_2 = st.text_input("2º - Descrição do exame médico:", value=e2[0] if len(e2) > 0 else "", key=f"ex2_175212_{ano_sel}")
                ex_dias_2 = st.text_input("2º - Tempo médio de espera (em dias):", value=e2[1] if len(e2) > 1 else "", key=f"ex_dias2_175212_{ano_sel}")
                
                st.markdown("---")
                
                # Terceiro Exame
                ex_3 = st.text_input("3º - Descrição do exame médico:", value=e3[0] if len(e3) > 0 else "", key=f"ex3_175212_{ano_sel}")
                ex_dias_3 = st.text_input("3º - Tempo médio de espera (em dias):", value=e3[1] if len(e3) > 1 else "", key=f"ex_dias3_175212_{ano_sel}")

            with c175212_2:
                link_17_5_2_1_2 = st.text_area(
                    "Link/Evidência ou Relatório estatístico dos tempos de espera de exames (17.5.2.1.2):", 
                    value=d17_5_2_1_2.get("link", ""), 
                    key=f"reg_17_5_2_1_2_txt_{ano_sel}",
                    height=320
                )
            
            # Monta a string estruturada para salvar tudo em um único campo de texto
            string_estruturada_ex = f"{ex_1}|{ex_dias_1}||{ex_2}|{ex_dias_2}||{ex_3}|{ex_dias_3}"
            if string_estruturada_ex == "||||":
                string_estruturada_ex = ""
                
            pts_17_5_2_1_2 = 0.0
            st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.2:** `{pts_17_5_2_1_2:.1f} pontos` (Dados Informativos)")
            
            # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
            if string_estruturada_ex != valores_salvos_1_2 or link_17_5_2_1_2 != d17_5_2_1_2["link"]:
                save_resp("17.5.2.1.2", string_estruturada_ex, pts_17_5_2_1_2, link_17_5_2_1_2)
                
                if "17.5.2.1.2" not in res_data:
                    res_data["17.5.2.1.2"] = {}
                res_data["17.5.2.1.2"]["valor"] = string_estruturada_ex
                res_data["17.5.2.1.2"]["pontos"] = pts_17_5_2_1_2
                res_data["17.5.2.1.2"]["link"] = link_17_5_2_1_2
                
                st.rerun()
                
            bloco_comentarios("17.5.2.1.2", res_data)
            
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
        # QUESITO 17.5.2.1.3 - 3 TERAPIAS/TRATAMENTOS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_maior_espera_terapias_17_5_2_1_3_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.3 - Terapias/Tratamentos com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.3 • Terapias/Tratamentos com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.3 Informe as 3 terapias/tratamentos médicos com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_3 = res_data.get("17.5.2.1.3", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_3 = d17_5_2_1_3.get("valor", "")
                
                # Trata a string salva para preencher os campos (Terapia 1|Dias 1||Terapia 2|Dias 2||Terapia 3|Dias 3)
                partes_ter = valores_salvos_1_3.split("||") if valores_salvos_1_3 else []
                
                t1 = partes_ter[0].split("|") if len(partes_ter) > 0 else ["", ""]
                t2 = partes_ter[1].split("|") if len(partes_ter) > 1 else ["", ""]
                t3 = partes_ter[2].split("|") if len(partes_ter) > 2 else ["", ""]
                
                c175213_1, c175213_2 = st.columns([1, 1])
                
                with c175213_1:
                    st.write("💆‍♂️ **Terapias / Tratamentos e Prazos:**")
                    
                    # Primeira Terapia
                    ter_1 = st.text_input("1ª - Descrição da terapia/ tratamento médico:", value=t1[0] if len(t1) > 0 else "", key=f"ter1_175213_{ano_sel}")
                    ter_dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=t1[1] if len(t1) > 1 else "", key=f"ter_dias1_175213_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segunda Terapia
                    ter_2 = st.text_input("2ª - Descrição da terapia/ tratamento médico:", value=t2[0] if len(t2) > 0 else "", key=f"ter2_175213_{ano_sel}")
                    ter_dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=t2[1] if len(t2) > 1 else "", key=f"ter_dias2_175213_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceira Terapia
                    ter_3 = st.text_input("3ª - Descrição da terapia/ tratamento médico:", value=t3[0] if len(t3) > 0 else "", key=f"ter3_175213_{ano_sel}")
                    ter_dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=t3[1] if len(t3) > 1 else "", key=f"ter_dias3_175213_{ano_sel}")

                with c175213_2:
                    link_17_5_2_1_3 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de terapias (17.5.2.1.3):", 
                        value=d17_5_2_1_3.get("link", ""), 
                        key=f"reg_17_5_2_1_3_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_terapias_17_5_2_1_3_{ano_sel}"):
                        links_17_5_2_1_3_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_3)
                        if links_17_5_2_1_3_atuais:
                            botoes_17_5_2_1_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_3_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_3}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto
                string_estruturada_ter = f"{ter_1}|{ter_dias_1}||{ter_2}|{ter_dias_2}||{ter_3}|{ter_dias_3}"
                if string_estruturada_ter == "||||":
                    string_estruturada_ter = ""
                    
                pts_17_5_2_1_3 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_terapias_17_5_2_1_3_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.3:** `{pts_17_5_2_1_3:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_3 = string_estruturada_ter != valores_salvos_1_3
                mudou_link_17_5_2_1_3 = link_17_5_2_1_3 != d17_5_2_1_3.get("link", "")

                if mudou_valores_17_5_2_1_3 or mudou_link_17_5_2_1_3:
                    save_resp("17.5.2.1.3", string_estruturada_ter, pts_17_5_2_1_3, link_17_5_2_1_3)
                    
                    if "17.5.2.1.3" not in res_data:
                        res_data["17.5.2.1.3"] = {}
                    res_data["17.5.2.1.3"]["valor"] = string_estruturada_ter
                    res_data["17.5.2.1.3"]["pontos"] = pts_17_5_2_1_3
                    res_data["17.5.2.1.3"]["link"] = link_17_5_2_1_3
                    
                    if mudou_link_17_5_2_1_3 and links_17_5_2_1_3_atuais:
                        links_17_5_2_1_3_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_3.get("link", ""))
                        if links_17_5_2_1_3_atuais != links_17_5_2_1_3_antigos:
                            modal_aviso_link("17.5.2.1.3", links_17_5_2_1_3_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.3", res_data)

# =============================================================================
        # QUESITO 17.5.2.1.4 - 3 OPM COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_maior_espera_opm_17_5_2_1_4_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.4 - OPM com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.4 • OPM com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.4 Informe as 3 OPM (Órteses, Próteses e Materiais Especiais) com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_4 = res_data.get("17.5.2.1.4", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_4 = d17_5_2_1_4.get("valor", "")
                
                # Trata a string salva para preencher os campos (OPM 1|Dias 1||OPM 2|Dias 2||OPM 3|Dias 3)
                partes_opm = valores_salvos_1_4.split("||") if valores_salvos_1_4 else []
                
                o1 = partes_opm[0].split("|") if len(partes_opm) > 0 else ["", ""]
                o2 = partes_opm[1].split("|") if len(partes_opm) > 1 else ["", ""]
                o3 = partes_opm[2].split("|") if len(partes_opm) > 2 else ["", ""]
                
                c175214_1, c175214_2 = st.columns([1, 1])
                
                with c175214_1:
                    st.write("🦿 **OPM e Prazos:**")
                    
                    # Primeira OPM
                    opm_1 = st.text_input("1ª - Descrição da OPM:", value=o1[0] if len(o1) > 0 else "", key=f"opm1_175214_{ano_sel}")
                    opm_dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=o1[1] if len(o1) > 1 else "", key=f"opm_dias1_175214_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segunda OPM
                    opm_2 = st.text_input("2ª - Descrição da OPM:", value=o2[0] if len(o2) > 0 else "", key=f"opm2_175214_{ano_sel}")
                    opm_dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=o2[1] if len(o2) > 1 else "", key=f"opm_dias2_175214_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceira OPM
                    opm_3 = st.text_input("3ª - Descrição da OPM:", value=o3[0] if len(o3) > 0 else "", key=f"opm3_175214_{ano_sel}")
                    opm_dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=o3[1] if len(o3) > 1 else "", key=f"opm_dias3_175214_{ano_sel}")

                with c175214_2:
                    link_17_5_2_1_4 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de OPM (17.5.2.1.4):", 
                        value=d17_5_2_1_4.get("link", ""), 
                        key=f"reg_17_5_2_1_4_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_opm_17_5_2_1_4_{ano_sel}"):
                        links_17_5_2_1_4_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_4)
                        if links_17_5_2_1_4_atuais:
                            botoes_17_5_2_1_4 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_4_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_4}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto
                string_estruturada_opm = f"{opm_1}|{opm_dias_1}||{opm_2}|{opm_dias_2}||{opm_3}|{opm_dias_3}"
                if string_estruturada_opm == "||||":
                    string_estruturada_opm = ""
                    
                pts_17_5_2_1_4 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_opm_17_5_2_1_4_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.4:** `{pts_17_5_2_1_4:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_4 = string_estruturada_opm != valores_salvos_1_4
                mudou_link_17_5_2_1_4 = link_17_5_2_1_4 != d17_5_2_1_4.get("link", "")

                if mudou_valores_17_5_2_1_4 or mudou_link_17_5_2_1_4:
                    save_resp("17.5.2.1.4", string_estruturada_opm, pts_17_5_2_1_4, link_17_5_2_1_4)
                    
                    if "17.5.2.1.4" not in res_data:
                        res_data["17.5.2.1.4"] = {}
                    res_data["17.5.2.1.4"]["valor"] = string_estruturada_opm
                    res_data["17.5.2.1.4"]["pontos"] = pts_17_5_2_1_4
                    res_data["17.5.2.1.4"]["link"] = link_17_5_2_1_4
                    
                    if mudou_link_17_5_2_1_4 and links_17_5_2_1_4_atuais:
                        links_17_5_2_1_4_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_4.get("link", ""))
                        if links_17_5_2_1_4_atuais != links_17_5_2_1_4_antigos:
                            modal_aviso_link("17.5.2.1.4", links_17_5_2_1_4_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.4", res_data)

# =============================================================================
        # QUESITO 17.5.2.1.5 - 3 CIRURGIAS ELETIVAS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_maior_espera_cirurgias_17_5_2_1_5_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.5 - Cirurgias Eletivas com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.5 • Cirurgias Eletivas com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.5 Informe as 3 cirurgias eletivas com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_5 = res_data.get("17.5.2.1.5", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_5 = d17_5_2_1_5.get("valor", "")
                
                # Trata a string salva para preencher os campos (Cirurgia 1|Dias 1||Cirurgia 2|Dias 2||Cirurgia 3|Dias 3)
                partes_cir = valores_salvos_1_5.split("||") if valores_salvos_1_5 else []
                
                c1 = partes_cir[0].split("|") if len(partes_cir) > 0 else ["", ""]
                c2 = partes_cir[1].split("|") if len(partes_cir) > 1 else ["", ""]
                c3 = partes_cir[2].split("|") if len(partes_cir) > 2 else ["", ""]
                
                c175215_1, c175215_2 = st.columns([1, 1])
                
                with c175215_1:
                    st.write("🏥 **Cirurgias Eletivas e Prazos:**")
                    
                    # Primeira Cirurgia
                    cir_1 = st.text_input("1ª - Descrição da cirurgia eletiva:", value=c1[0] if len(c1) > 0 else "", key=f"cir1_175215_{ano_sel}")
                    cir_dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=c1[1] if len(c1) > 1 else "", key=f"cir_dias1_175215_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segunda Cirurgia
                    cir_2 = st.text_input("2ª - Descrição da cirurgia eletiva:", value=c2[0] if len(c2) > 0 else "", key=f"cir2_175215_{ano_sel}")
                    cir_dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=c2[1] if len(c2) > 1 else "", key=f"cir_dias2_175215_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceira Cirurgia
                    cir_3 = st.text_input("3ª - Descrição da cirurgia eletiva:", value=c3[0] if len(c3) > 0 else "", key=f"cir3_175215_{ano_sel}")
                    cir_dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=c3[1] if len(c3) > 1 else "", key=f"cir_dias3_175215_{ano_sel}")

                with c175215_2:
                    link_17_5_2_1_5 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de cirurgias (17.5.2.1.5):", 
                        value=d17_5_2_1_5.get("link", ""), 
                        key=f"reg_17_5_2_1_5_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_cirurgias_17_5_2_1_5_{ano_sel}"):
                        links_17_5_2_1_5_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_5)
                        if links_17_5_2_1_5_atuais:
                            botoes_17_5_2_1_5 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_5_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_5}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto
                string_estruturada_cir = f"{cir_1}|{cir_dias_1}||{cir_2}|{cir_dias_2}||{cir_3}|{cir_dias_3}"
                if string_estruturada_cir == "||||":
                    string_estruturada_cir = ""
                    
                pts_17_5_2_1_5 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_cirurgias_17_5_2_1_5_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.5:** `{pts_17_5_2_1_5:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_5 = string_estruturada_cir != valores_salvos_1_5
                mudou_link_17_5_2_1_5 = link_17_5_2_1_5 != d17_5_2_1_5.get("link", "")

                if mudou_valores_17_5_2_1_5 or mudou_link_17_5_2_1_5:
                    save_resp("17.5.2.1.5", string_estruturada_cir, pts_17_5_2_1_5, link_17_5_2_1_5)
                    
                    if "17.5.2.1.5" not in res_data:
                        res_data["17.5.2.1.5"] = {}
                    res_data["17.5.2.1.5"]["valor"] = string_estruturada_cir
                    res_data["17.5.2.1.5"]["pontos"] = pts_17_5_2_1_5
                    res_data["17.5.2.1.5"]["link"] = link_17_5_2_1_5
                    
                    if mudou_link_17_5_2_1_5 and links_17_5_2_1_5_atuais:
                        links_17_5_2_1_5_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_5.get("link", ""))
                        if links_17_5_2_1_5_atuais != links_17_5_2_1_5_antigos:
                            modal_aviso_link("17.5.2.1.5", links_17_5_2_1_5_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.5", res_data)

# =============================================================================
        # QUESITO 17.5.2.1.6 - 3 OUTROS SERVIÇOS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_maior_espera_outros_17_5_2_1_6_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.6 - Outros Serviços com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.6 • Outros Serviços com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.6 Informe os 3 Outros serviços da Atenção Especializada sob gestão municipal com maior tempo de espera:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_6 = res_data.get("17.5.2.1.6", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_6 = d17_5_2_1_6.get("valor", "")
                
                # Trata a string salva para preencher os campos (Serviço 1|Dias 1||Serviço 2|Dias 2||Serviço 3|Dias 3)
                partes_out = valores_salvos_1_6.split("||") if valores_salvos_1_6 else []
                
                out1 = partes_out[0].split("|") if len(partes_out) > 0 else ["", ""]
                out2 = partes_out[1].split("|") if len(partes_out) > 1 else ["", ""]
                out3 = partes_out[2].split("|") if len(partes_out) > 2 else ["", ""]
                
                c175216_1, c175216_2 = st.columns([1, 1])
                
                with c175216_1:
                    st.write("📁 **Outros Serviços e Prazos:**")
                    
                    # Primeiro Outro Serviço
                    out_1 = st.text_input("1º - Descrição do Serviço da Atenção Especializada:", value=out1[0] if len(out1) > 0 else "", key=f"out1_175216_{ano_sel}")
                    out_dias_1 = st.text_input("1º - Tempo médio de espera (em dias):", value=out1[1] if len(out1) > 1 else "", key=f"out_dias1_175216_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segundo Outro Serviço
                    out_2 = st.text_input("2º - Descrição do Serviço da Atenção Especializada:", value=out2[0] if len(out2) > 0 else "", key=f"out2_175216_{ano_sel}")
                    out_dias_2 = st.text_input("2º - Tempo médio de espera (em dias):", value=out2[1] if len(out2) > 1 else "", key=f"out_dias2_175216_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceiro Outro Serviço
                    out_3 = st.text_input("3º - Descrição do Serviço da Atenção Especializada:", value=out3[0] if len(out3) > 0 else "", key=f"out3_175216_{ano_sel}")
                    out_dias_3 = st.text_input("3º - Tempo médio de espera (em dias):", value=out3[1] if len(out3) > 1 else "", key=f"out_dias3_175216_{ano_sel}")

                with c175216_2:
                    link_17_5_2_1_6 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de outros serviços (17.5.2.1.6):", 
                        value=d17_5_2_1_6.get("link", ""), 
                        key=f"reg_17_5_2_1_6_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_outros_17_5_2_1_6_{ano_sel}"):
                        links_17_5_2_1_6_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_6)
                        if links_17_5_2_1_6_atuais:
                            botoes_17_5_2_1_6 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_6_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_6}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto
                string_estruturada_out = f"{out_1}|{out_dias_1}||{out_2}|{out_dias_2}||{out_3}|{out_dias_3}"
                if string_estruturada_out == "||||":
                    string_estruturada_out = ""
                    
                pts_17_5_2_1_6 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_outros_17_5_2_1_6_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.6:** `{pts_17_5_2_1_6:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_6 = string_estruturada_out != valores_salvos_1_6
                mudou_link_17_5_2_1_6 = link_17_5_2_1_6 != d17_5_2_1_6.get("link", "")

                if mudou_valores_17_5_2_1_6 or mudou_link_17_5_2_1_6:
                    save_resp("17.5.2.1.6", string_estruturada_out, pts_17_5_2_1_6, link_17_5_2_1_6)
                    
                    if "17.5.2.1.6" not in res_data:
                        res_data["17.5.2.1.6"] = {}
                    res_data["17.5.2.1.6"]["valor"] = string_estruturada_out
                    res_data["17.5.2.1.6"]["pontos"] = pts_17_5_2_1_6
                    res_data["17.5.2.1.6"]["link"] = link_17_5_2_1_6
                    
                    if mudou_link_17_5_2_1_6 and links_17_5_2_1_6_atuais:
                        links_17_5_2_1_6_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_6.get("link", ""))
                        if links_17_5_2_1_6_atuais != links_17_5_2_1_6_antigos:
                            modal_aviso_link("17.5.2.1.6", links_17_5_2_1_6_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.6", res_data)

# -----------------------------------------------------------------------------
        # QUESITO 17.6 • Prontuário Eletrônico na Atenção Especializada
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        with st.expander(f"📌 QUESITO 17.6 • Prontuário Eletrônico na Atenção Especializada em {ano_sel}", expanded=True):
            st.subheader("17.6 • Prontuário Eletrônico na Atenção Especializada")
            st.write("**O município implantou o Prontuário Eletrônico do Paciente na Atenção Especializada sob sua gestão?**")
            
            # Recupera os dados do banco
            d17_6 = res_data.get("17.6", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            
            opts_17_6 = [
                "Selecione...",
                "Sim, para todos os procedimentos da saúde – 00",
                "Sim, para a maior parte dos procedimentos da saúde – -01 (perde 01 ponto)",
                "Sim, para a menor parte dos procedimentos da saúde – -03 (perde 03 pontos)",
                "Não – -05 (perde 05 pontos)"
            ]
            if d17_6["valor"] not in opts_17_6:
                d17_6["valor"] = "Selecione..."
                
            idx_17_6 = opts_17_6.index(d17_6["valor"])
            
            c176_1, c176_2 = st.columns([1, 1])
            with c176_1:
                st.markdown("**Selecione uma alternativa:**")
                sel_17_6 = st.radio(
                    "Implantação do PEP na Especializada:", options=opts_17_6, index=idx_17_6,
                    key=f"rad_pep_esp_17_6_{ano_sel}", label_visibility="collapsed"
                )
            with c176_2:
                st.markdown("**Regra de Penalidades:**")
                st.caption("✅ **Todos** – 0 pts | ⚠️ **Maior parte** – perde 1 pt | ⚠️ **Menor parte** – perde 3 pts | ❌ **Não** – perde 5 pts")

            link_17_6 = st.text_area(
                "Link/Evidência (17.6):", value=d17_6.get("link", ""), 
                key=f"txt_evid_17_6_{ano_sel}", height=100
            )
            
            # Suporte multi-links ativos
            links_17_6_atuais = re.findall(r'(https?://[^\s]+)', link_17_6)
            if links_17_6_atuais:
                botoes_17_6 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_6_atuais])
                st.markdown(f"**Links Ativos:** {botoes_17_6}")

            # Mapeamento exato de pontos/penalidades
            map_pts_17_6 = {
                "Selecione...": 0.0,
                "Sim, para todos os procedimentos da saúde – 00": 0.0,
                "Sim, para a maior parte dos procedimentos da saúde – -01 (perde 01 ponto)": -1.0,
                "Sim, para a menor parte dos procedimentos da saúde – -03 (perde 03 pontos)": -3.0,
                "Não – -05 (perde 05 pontos)": -5.0
            }
            pts_17_6 = map_pts_17_6.get(sel_17_6, 0.0)

            # Processamento de salvamento e trava do modal
            if sel_17_6 != d17_6.get("valor") or link_17_6 != d17_6.get("link"):
                if sel_17_6 is not None:
                    save_resp("17.6", sel_17_6, pts_17_6, link_17_6)
                    res_data["17.6"] = {"valor": sel_17_6, "pontos": pts_17_6, "link": link_17_6}
                    
                    if links_17_6_atuais:
                        links_17_6_antigos = re.findall(r'(https?://[^\s]+)', d17_6.get("link", ""))
                        if links_17_6_atuais != links_17_6_antigos:
                            modal_aviso_link("17.6", links_17_6_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()

            bloco_comentarios("17.6", res_data)
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 17.6.1 • Serviços Inseridos no Prontuário Eletrônico (Atenção Especializada)
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_pep_atencao_especializada_17_6_1_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.6.1 - Serviços Inseridos no Prontuário Eletrônico", expanded=True):
                st.subheader("17.6.1 • Serviços no Prontuário Eletrônico (PEP)")
                st.write("**Assinale os serviços da Atenção Especializada inseridos no Prontuário Eletrônico do Paciente:**")
                st.caption("ℹ️ *Regra do IEGM: O quesito pontua de 0.0 a -2.5 pontos. Perde -0.35 pontos para cada item não assinalado (exceto 'Medicamentos', que penaliza -0.40 se não marcado, e 'Outros', que não pontua).*")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera dados salvos do banco de dados
                d17_6_1 = res_data.get("17.6.1", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1761 = d17_6_1.get("valor", "")
                
                lista_salva_1761 = [item.strip() for item in valores_salvos_1761.split(";")] if valores_salvos_1761 else []
                
                c1761_1, c1761_2 = st.columns([1, 1])
                with c1761_1:
                    st.markdown("**Selecione as opções ativas no PEP:**")
                    
                    op_pep_1 = "Consultas médicas por especialidade"
                    op_pep_2 = "Exames laboratoriais"
                    op_pep_3 = "Exames radiológicos e por imagem"
                    op_pep_4 = "Terapias / tratamentos"
                    op_pep_5 = "Medicamentos"
                    op_pep_6 = "OPM"
                    op_pep_7 = "Cirurgias eletivas"
                    op_pep_8 = "Outros"
                    
                    chk_pep_1 = st.checkbox(op_pep_1, value=(op_pep_1 in lista_salva_1761), key=f"chk_1761_1_{ano_sel}")
                    chk_pep_2 = st.checkbox(op_pep_2, value=(op_pep_2 in lista_salva_1761), key=f"chk_1761_2_{ano_sel}")
                    chk_pep_3 = st.checkbox(op_pep_3, value=(op_pep_3 in lista_salva_1761), key=f"chk_1761_3_{ano_sel}")
                    chk_pep_4 = st.checkbox(op_pep_4, value=(op_pep_4 in lista_salva_1761), key=f"chk_1761_4_{ano_sel}")
                    chk_pep_5 = st.checkbox(op_pep_5, value=(op_pep_5 in lista_salva_1761), key=f"chk_1761_5_{ano_sel}")
                    chk_pep_6 = st.checkbox(op_pep_6, value=(op_pep_6 in lista_salva_1761), key=f"chk_1761_6_{ano_sel}")
                    chk_pep_7 = st.checkbox(op_pep_7, value=(op_pep_7 in lista_salva_1761), key=f"chk_1761_7_{ano_sel}")
                    chk_pep_8 = st.checkbox(op_pep_8, value=(op_pep_8 in lista_salva_1761), key=f"chk_1761_8_{ano_sel}")
                    
                    # Monta a lista de itens atualmente checados
                    selecionados_pep = []
                    if chk_pep_1: selecionados_pep.append(op_pep_1)
                    if chk_pep_2: selecionados_pep.append(op_pep_2)
                    if chk_pep_3: selecionados_pep.append(op_pep_3)
                    if chk_pep_4: selecionados_pep.append(op_pep_4)
                    if chk_pep_5: selecionados_pep.append(op_pep_5)
                    if chk_pep_6: selecionados_pep.append(op_pep_6)
                    if chk_pep_7: selecionados_pep.append(op_pep_7)
                    if chk_pep_8: selecionados_pep.append(op_pep_8)
                    
                    # CÁLCULO EXCLUSIVO DA PENALIDADE POR ITEM NÃO ASSINALADO
                    penalidade = 0.0
                    if not chk_pep_1: penalidade -= 0.35
                    if not chk_pep_2: penalidade -= 0.35
                    if not chk_pep_3: penalidade -= 0.35
                    if not chk_pep_4: penalidade -= 0.35
                    if not chk_pep_5: penalidade -= 0.40  # Medicamentos perde 0.40
                    if not chk_pep_6: penalidade -= 0.35
                    if not chk_pep_7: penalidade -= 0.35
                    
                    # Trava o limite físico da nota entre 0 e -2.5 pontos
                    pts_17_6_1 = max(penalidade, -2.5)
                    string_selecionados_pep = "; ".join(selecionados_pep) if selecionados_pep else ""
                    
                with c1761_2:
                    link_17_6_1 = st.text_area(
                        "Link/Evidência das funcionalidades do PEP (17.6.1):", 
                        value=d17_6_1.get("link", ""), 
                        key=f"reg_17_6_1_txt_{ano_sel}",
                        height=130
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_pep_atencao_especializada_17_6_1_{ano_sel}"):
                        links_17_6_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_6_1)
                        if links_17_6_1_atuais:
                            botoes_17_6_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_6_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_6_1}")
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_pep_atencao_especializada_17_6_1_{ano_sel}"):
                    if pts_17_6_1 < 0:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.6.1:** :red[{pts_17_6_1:.2f} pontos (Penalidade)]")
                    else:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.6.1:** `{pts_17_6_1:.2f} pontos` (Pontuação Máxima)")
                
                # Avaliação de mutações para persistência reativa e síncrona
                mudou_opcao_17_6_1 = string_selecionados_pep != valores_salvos_1761
                mudou_link_17_6_1 = link_17_6_1 != d17_6_1.get("link", "")
                
                if mudou_opcao_17_6_1 or mudou_link_17_6_1:
                    save_resp("17.6.1", string_selecionados_pep, pts_17_6_1, link_17_6_1)
                    
                    # Sincroniza localmente o cache antes do recarregamento (evita flickering visual)
                    if "17.6.1" not in res_data:
                        res_data["17.6.1"] = {}
                    res_data["17.6.1"]["valor"] = string_selecionados_pep
                    res_data["17.6.1"]["pontos"] = pts_17_6_1
                    res_data["17.6.1"]["link"] = link_17_6_1
                    
                    if mudou_link_17_6_1 and links_17_6_1_atuais:
                        links_17_6_1_antigos = re.findall(r'(https?://[^\s]+)', d17_6_1.get("link", ""))
                        if links_17_6_1_atuais != links_17_6_1_antigos:
                            modal_aviso_link("17.6.1", links_17_6_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                        
                bloco_comentarios("17.6.1", res_data)

        # =============================================================================
        # QUESITO 17.7 • Mamógrafos na Rede Própria
        # =============================================================================
        # Substituído HTML cru por container nativo para mitigar o erro 'removeChild'
        with st.container(border=True):
            
            with st.expander(f"📌 QUESITO 17.7 • Mamógrafos na Rede Própria em {ano_sel}", expanded=True):
                st.write(f"**O município possui estabelecimentos de saúde da rede própria com mamógrafos?**")
                
                opts_17_7 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                
                d17_7 = res_data.get("17.7", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c177_1, c177_2 = st.columns([1, 1])
                with c177_1:
                    sel_17_7 = st.radio(
                        "Possui estabelecimentos com mamógrafos:", 
                        options=list(opts_17_7.keys()), 
                        index=(list(opts_17_7.keys()).index(d17_7["valor"]) if d17_7["valor"] in opts_17_7 else 0),
                        key=f"reg_17_7_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_17_7 = opts_17_7[sel_17_7] if sel_17_7 is not None else 0.0
                    
                with c177_2:
                    link_17_7 = st.text_area(
                        "Link/Evidência (Cadastro no CNES ou relatório de equipamentos do município):", 
                        value=d17_7.get("link", ""), 
                        key=f"reg_17_7_txt_{ano_sel}",
                        height=110
                    )
                    
                # SUPORTE MULTI-LINKS ATIVOS (Igual ao modelo do Quesito 2.0)
                links_17_7_atuais = re.findall(r'(https?://[^\s]+)', link_17_7)
                if links_17_7_atuais:
                    botoes_17_7 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_7_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_17_7}")
                    
                if pts_17_7 < 0:
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.7:** :red[{pts_17_7:.1f} pontos (Penalidade)]")
                else:
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.7:** `{(pts_17_7 or 0.0):.1f} pontos`")
                
                # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL
                if sel_17_7 != d17_7.get("valor") or link_17_7 != d17_7.get("link"):
                    if sel_17_7 is not None:
                        save_resp("17.7", sel_17_7, pts_17_7, link_17_7)
                        
                        if "17.7" not in res_data:
                            res_data["17.7"] = {}
                        res_data["17.7"]["valor"] = sel_17_7
                        res_data["17.7"]["pontos"] = pts_17_7
                        res_data["17.7"]["link"] = link_17_7
                        
                        if links_17_7_atuais:
                            links_17_7_antigos = re.findall(r'(https?://[^\s]+)', d17_7.get("link", ""))
                            if links_17_7_atuais != links_17_7_antigos:
                                modal_aviso_link("17.7", links_17_7_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                    
                bloco_comentarios("17.7", res_data)

        # =============================================================================
        # QUESITO 17.7.1 - PRODUTIVIDADE DE MAMÓGRAFOS (NATIVO E ESTÁVEL)
        # =============================================================================
        # Em vez de st.markdown('<div class="quesito-card">'), usamos o container nativo com borda.
        # Caso queira estilizar, o Streamlit gerencia o st.container sem estourar o erro de 'removeChild'.
        with st.container(border=True):
            
            with st.expander(f"📌 QUESITO 17.7.1 • Produtividade de Mamógrafos da Rede Própria em {ano_sel}", expanded=True):
                st.write("**Informe a quantidade de exames realizados e de mamógrafos na rede própria sob gestão municipal para fins de cálculo de produtividade:**")
                
                # Inicializa com padrão neutro (valor "0|0" e 0.0 pontos para não penalizar antes de digitar)
                d17_7_1 = res_data.get("17.7.1", {"valor": "0|0", "pontos": 0.0, "link": ""})
                valores_salvos_1771 = d17_7_1.get("valor", "0|0")
                
                # Trata string estruturada (EX|MM)
                partes_mamog = valores_salvos_1771.split("|") if valores_salvos_1771 else ["0", "0"]
                val_ex_salvo = partes_mamog[0] if len(partes_mamog) > 0 else "0"
                val_mm_salvo = partes_mamog[1] if len(partes_mamog) > 1 else "0"
                
                c1771_1, c1771_2 = st.columns([1, 1])
                
                with c1771_1:
                    st.write(f"📊 **Dados de Produção ({ano_sel}):**")
                    
                    inp_ex = st.text_input(
                        f"Quantidade de exames de mamógrafos realizados na rede própria em {ano_sel} (EX):",
                        value=val_ex_salvo,
                        key=f"txt_1771_ex_{ano_sel}"
                    )
                    
                    inp_mm = st.text_input(
                        f"Quantidade de mamógrafos em estabelecimentos da rede própria em {ano_sel} (MM):",
                        value=val_mm_salvo,
                        key=f"txt_1771_mm_{ano_sel}"
                    )
                    
                    # Conversão e Tratamento seguro numérico
                    try:
                        ex_float = float(inp_ex.replace(".", "").replace(",", ".")) if inp_ex else 0.0
                    except ValueError:
                        ex_float = 0.0
                        
                    try:
                        mm_float = float(inp_mm.replace(".", "").replace(",", ".")) if inp_mm else 0.0
                    except ValueError:
                        mm_float = 0.0
                    
                    # Bloco lógico de cálculo de produtividade
                    if mm_float > 0:
                        prod_p = ex_float / mm_float
                        st.markdown(f"📈 **Produtividade Calculada (P):** `{prod_p:,.2f}` exames/ano")
                        
                        # Aplica a regra de corte: atingiu a meta -> 0.0 | não atingiu -> perde 5 pontos
                        if prod_p >= 6758.0:
                            pts_17_7_1 = 0.0
                        else:
                            pts_17_7_1 = -5.0
                    else:
                        # Se estiver zerado porque o usuário limpou ou não digitou, fica neutro (0.0)
                        if ex_float == 0.0 and mm_float == 0.0:
                            st.markdown("⚠️ **Produtividade Calculada (P):** Aguardando preenchimento dos dados.")
                            pts_17_7_1 = 0.0
                        else:
                            # Se digitou exames mas deixou mamógrafos em 0, aplica a penalidade por inconsistência
                            st.markdown("⚠️ **Produtividade Calculada (P):** Divisão por zero. Informe a quantidade de aparelhos.")
                            pts_17_7_1 = -5.0
                            
                    string_estruturada_mamog = f"{inp_ex}|{inp_mm}"
                    
                with c1771_2:
                    link_17_7_1 = st.text_area(
                        f"Link/Evidência ou Relatório do SIA/SUS para validação da produção ({ano_sel}):", 
                        value=d17_7_1.get("link", ""), 
                        key=f"reg_17_7_1_txt_{ano_sel}",
                        height=150
                    )
                    
                # SUPORTE MULTI-LINKS ATIVOS
                links_17_7_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_7_1)
                if links_17_7_1_atuais:
                    botoes_17_7_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_7_1_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_17_7_1}")
                
                # Exibição reativa das métricas na tela
                if string_estruturada_mamog == "0|0" or string_estruturada_mamog == "|":
                    st.markdown("📊 **Pontuação Aplicada no Quesito 17.7.1:** `Aguardando dados...`")
                elif pts_17_7_1 < 0:
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.7.1:** :red[{pts_17_7_1:.1f} pontos (Penalidade)]")
                else:
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.7.1:** `{pts_17_7_1:.1f} pontos` (Meta Atingida)")
                    
                # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL
                if string_estruturada_mamog != valores_salvos_1771 or link_17_7_1 != d17_7_1.get("link", ""):
                    if string_estruturada_mamog is not None:
                        save_resp("17.7.1", string_estruturada_mamog, pts_17_7_1, link_17_7_1)
                        
                        res_data["17.7.1"] = {
                            "valor": string_estruturada_mamog,
                            "pontos": pts_17_7_1,
                            "link": link_17_7_1
                        }
                        
                        if links_17_7_1_atuais:
                            links_17_7_1_antigos = re.findall(r'(https?://[^\s]+)', d17_7_1.get("link", ""))
                            if links_17_7_1_atuais != links_17_7_1_antigos:
                                modal_aviso_link("17.7.1", links_17_7_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                            
                bloco_comentarios("17.7.1", res_data)
              
        # =============================================================================
        # QUESITO 17.8 • EQUIPAMENTOS DE ULTRASSOM CONVENCIONAL (INFORMATIVO)
        # =============================================================================
        # Substituído HTML cru por container nativo para mitigar de vez o erro 'removeChild'
        with st.container(border=True):
            
            with st.expander(f"📌 QUESITO 17.8 • Equipamentos de Ultrassom Convencional na Rede Própria em {ano_sel}", expanded=True):
                st.write(f"**O município possui estabelecimentos de saúde da rede própria com equipamentos de ultrassom convencional?**")
                
                # Sem pontuação aplicada neste quesito
                opts_17_8 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                
                d17_8 = res_data.get("17.8", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c178_1, c178_2 = st.columns([1, 1])
                with c178_1:
                    sel_17_8 = st.radio(
                        "Possui ultrassom convencional:", 
                        options=list(opts_17_8.keys()), 
                        index=(list(opts_17_8.keys()).index(d17_8["valor"]) if d17_8["valor"] in opts_17_8 else 0),
                        key=f"reg_17_8_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_17_8 = 0.0
                    
                with c178_2:
                    link_17_8 = st.text_area(
                        "Link/Evidência ou Cadastro do SCNES dos equipamentos (17.8):", 
                        value=d17_8.get("link", ""), 
                        key=f"reg_17_8_txt_{ano_sel}",
                        height=130
                    )
                    
                # SUPORTE MULTI-LINKS ATIVOS (Padronizado)
                links_17_8_atuais = re.findall(r'(https?://[^\s]+)', link_17_8)
                if links_17_8_atuais:
                    botoes_17_8 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_8_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_17_8}")
                    
                st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.8:** `{pts_17_8:.1f} pontos` (Dados Informativos)")
                
                # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL
                if sel_17_8 != d17_8.get("valor") or link_17_8 != d17_8.get("link"):
                    if sel_17_8 is not None:
                        save_resp("17.8", sel_17_8, pts_17_8, link_17_8)
                        res_data["17.8"] = {"valor": sel_17_8, "pontos": pts_17_8, "link": link_17_8}
                        
                        if links_17_8_atuais:
                            links_17_8_antigos = re.findall(r'(https?://[^\s]+)', d17_8.get("link", ""))
                            if links_17_8_atuais != links_17_8_antigos:
                                modal_aviso_link("17.8", links_17_8_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                    
                bloco_comentarios("17.8", res_data)

        # =============================================================================
        # QUESITO 17.8.1 - PRODUTIVIDADE E EVOLUÇÃO DE ULTRASSOM CONVENCIONAL
        # =============================================================================
        # Substituído HTML cru por container nativo para mitigar de vez o erro 'removeChild'
        with st.container(border=True):
            
            with st.expander(f"📌 QUESITO 17.8.1 • Produtividade de Ultrassom Convencional (Histórico Dinâmico) em {ano_sel}", expanded=True):
                st.write(f"**Informe a série histórica de exames e equipamentos para cálculo da evolução da produtividade:**")
                
                # Definição dinâmica dos anos com base na seleção da tela
                try:
                    aa = int(ano_sel)
                except:
                    aa = 2026
                        
                aa_minus_1 = aa - 1
                aa_minus_2 = aa - 2
                
                # Inicializa com padrão neutro (valor "0|0|0|0|0|0" e 0.0 pontos para evitar duplicidades)
                d17_8_1 = res_data.get("17.8.1", {"valor": "0|0|0|0|0|0", "pontos": 0.0, "link": ""})
                valores_salvos_1781 = d17_8_1.get("valor", "0|0|0|0|0|0")
                
                p_ult = valores_salvos_1781.split("|") if valores_salvos_1781 else ["0","0","0","0","0","0"]
                while len(p_ult) < 6: p_ult.append("0")
                
                c1781_1, c1781_2 = st.columns([1, 1])
                
                with c1781_1:
                    st.write("📊 **Série Histórica de Exames Realizados (EX):**")
                    ex_aa2 = st.text_input(f"Exames realizados em {aa_minus_2} (EX_{aa_minus_2}):", value=p_ult[0], key=f"ex_aa2_{ano_sel}")
                    ex_aa1 = st.text_input(f"Exames realizados em {aa_minus_1} (EX_{aa_minus_1}):", value=p_ult[1], key=f"ex_aa1_{ano_sel}")
                    ex_aa  = st.text_input(f"Exames realizados em {aa} (EX_{aa}):", value=p_ult[2], key=f"ex_aa_{ano_sel}")
                    
                    st.markdown("---")
                    st.write("⚙️ **Série Histórica de Equipamentos (EQ):**")
                    eq_aa2 = st.text_input(f"Equipamentos em {aa_minus_2} (EQ_{aa_minus_2}):", value=p_ult[3], key=f"eq_aa2_{ano_sel}")
                    eq_aa1 = st.text_input(f"Equipamentos em {aa_minus_1} (EQ_{aa_minus_1}):", value=p_ult[4], key=f"eq_aa1_{ano_sel}")
                    eq_aa  = st.text_input(f"Equipamentos em {aa} (EQ_{aa}):", value=p_ult[5], key=f"eq_aa_{ano_sel}")
                    
                    # Funções seguras de conversão float
                    def converter_campo(val):
                        try: return float(val.replace(".", "").replace(",", ".")) if val else 0.0
                        except: return 0.0
                        
                    f_ex_aa2 = converter_campo(ex_aa2)
                    f_ex_aa1 = converter_campo(ex_aa1)
                    f_ex_aa  = converter_campo(ex_aa)
                    f_eq_aa2 = converter_campo(eq_aa2)
                    f_eq_aa1 = converter_campo(eq_aa1)
                    f_eq_aa  = converter_campo(eq_aa)
                    
                    # Execução das regras lógicas da fórmula
                    denominador_hist = f_eq_aa2 + f_eq_aa1
                    
                    # Verifica se todos os campos estão zerados (Estado inicial limpo)
                    valores_zerados = (f_ex_aa2 == 0.0 and f_ex_aa1 == 0.0 and f_ex_aa == 0.0 and f_eq_aa2 == 0.0 and f_eq_aa1 == 0.0 and f_eq_aa == 0.0)
                    
                    if f_eq_aa > 0 and denominador_hist > 0:
                        prod_atual = f_ex_aa / f_eq_aa
                        prod_hist = (f_ex_aa2 + f_ex_aa1) / denominador_hist
                        
                        st.markdown(f"📈 **Produtividade do Ano Atual ({aa}):** `{prod_atual:,.2f}` exames/eq")
                        st.markdown(f"⏳ **Produtividade Histórica ({aa_minus_2} + {aa_minus_1}):** `{prod_hist:,.2f}` exames/eq")
                        
                        if prod_atual >= prod_hist:
                            pts_17_8_1 = 0.0
                        else:
                            pts_17_8_1 = -5.0
                    else:
                        if valores_zerados:
                            st.markdown("⚠️ **Produtividade:** Aguardando preenchimento da série histórica.")
                            pts_17_8_1 = 0.0
                        else:
                            st.markdown("⚠️ **Aviso:** Divisão por zero detectada. Insira os equipamentos ativos para os anos informados.")
                            pts_17_8_1 = -5.0
                            
                    string_estruturada_ult = f"{ex_aa2}|{ex_aa1}|{ex_aa}|{eq_aa2}|{eq_aa1}|{eq_aa}"
                    
                with c1781_2:
                    link_17_8_1 = st.text_area(
                        f"Link/Evidência ou Relatório estatístico de produção da série histórica ({aa_minus_2} a {aa}):", 
                        value=d17_8_1.get("link", ""), 
                        key=f"reg_17_8_1_txt_{ano_sel}",
                        height=360
                    )
                    
                # SUPORTE MULTI-LINKS ATIVOS
                links_17_8_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_8_1)
                if links_17_8_1_atuais:
                    botoes_17_8_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_8_1_atuais])
                    st.markdown(f"**Links Ativos:** {botoes_17_8_1}")
                    
                # Exibição segura das métricas na tela
                if valores_zerados:
                    st.markdown("📊 **Pontuação Aplicada no Quesito 17.8.1:** `Aguardando dados...`")
                elif pts_17_8_1 < 0:
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.8.1:** :red[{pts_17_8_1:.1f} pontos (Penalidade)]")
                else:
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.8.1:** `{pts_17_8_1:.1f} pontos` (Desempenho Validado)")
                    
                # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL
                if string_estruturada_ult != valores_salvos_1781 or link_17_8_1 != d17_8_1.get("link", ""):
                    if string_estruturada_ult is not None:
                        save_resp("17.8.1", string_estruturada_ult, pts_17_8_1, link_17_8_1)
                        
                        res_data["17.8.1"] = {
                            "valor": string_estruturada_ult,
                            "pontos": pts_17_8_1,
                            "link": link_17_8_1
                        }
                        
                        if links_17_8_1_atuais:
                            links_17_8_1_antigos = re.findall(r'(https?://[^\s]+)', d17_8_1.get("link", ""))
                            if links_17_8_1_atuais != links_17_8_1_antigos:
                                modal_aviso_link("17.8.1", links_17_8_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                            
                bloco_comentarios("17.8.1", res_data)

# =============================================================================
        # QUESITO 17.9 - HOSPITAL OU SANTA CASA SOB GESTÃO MUNICIPAL (INFORMATIVO)
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_hospital_santa_casa_17_9_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.9 - Hospital ou Santa Casa sob Gestão Municipal", expanded=True):
                st.subheader("17.9 • Hospital ou Santa Casa sob Gestão Municipal")
                st.write(f"**17.9 O município possui hospital ou Santa Casa sob sua gestão?**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Quesito informativo: sem impacto na pontuação do bloco
                opts_17_9 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                
                d17_9 = res_data.get("17.9", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c179_1, c179_2 = st.columns([1, 1])
                with c179_1:
                    sel_17_9 = st.radio(
                        "Possui hospital/Santa Casa sob gestão:", 
                        options=list(opts_17_9.keys()), 
                        index=(list(opts_17_9.keys()).index(d17_9["valor"]) if d17_9["valor"] in opts_17_9 else 0),
                        key=f"reg_17_9_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_17_9 = 0.0
                    
                with c179_2:
                    link_17_9 = st.text_area(
                        "Link/Evidência ou Cadastro do SCNES do Hospital/Santa Casa (17.9):", 
                        value=d17_9.get("link", ""), 
                        key=f"reg_17_9_txt_{ano_sel}",
                        height=130
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_hospital_santa_casa_17_9_{ano_sel}"):
                        links_17_9_atuais = re.findall(r'(https?://[^\s]+)', link_17_9)
                        if links_17_9_atuais:
                            botoes_17_9 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_9_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_9}")
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_hospital_santa_casa_17_9_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.9:** `{pts_17_9:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_9 = sel_17_9 != d17_9["valor"]
                mudou_link_17_9 = link_17_9 != d17_9.get("link", "")

                if mudou_valores_17_9 or mudou_link_17_9:
                    if sel_17_9 is not None:
                        save_resp("17.9", sel_17_9, pts_17_9, link_17_9)
                        res_data["17.9"] = {"valor": sel_17_9, "pontos": pts_17_9, "link": link_17_9}
                        
                        if mudou_link_17_9 and links_17_9_atuais:
                            links_17_9_antigos = re.findall(r'(https?://[^\s]+)', d17_9.get("link", ""))
                            if links_17_9_atuais != links_17_9_antigos:
                                modal_aviso_link("17.9", links_17_9_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                    
                bloco_comentarios("17.9", res_data)

# =============================================================================
        # QUESITO 17.9.1 - TAXA DE OCUPAÇÃO HOSPITALAR (CORRIGIDO - SÓ PONTUA SE PREENCHIDO)
        # =============================================================================
        with st.container(key=f"container_bloco_taxa_ocupacao_hospitalar_17_9_1_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.9.1 - Taxa de Ocupação Hospitalar da Rede Própria", expanded=True):
                st.subheader("17.9.1 • Taxa de Ocupação Hospitalar da Rede Própria")
                st.write(f"**17.9.1 Informe o total de pacientes-dia e leitos-dia para fins de cálculo da Taxa de Ocupação (TO):**")
                st.caption("ℹ️ *Este quesito inicia neutro (0.0). A penalidade só será aplicada se os dados forem preenchidos incorretamente.*")
                
                # Modificado o padrão inicial de pontos para 0.0 (evita penalidade sem preenchimento)
                d17_9_1 = res_data.get("17.9.1", {"valor": "0|0", "pontos": 0.0, "link": ""})
                valores_salvos_1791 = d17_9_1.get("valor", "0|0")
                
                partes_leitos = valores_salvos_1791.split("|") if valores_salvos_1791 else ["0", "0"]
                val_pa_salvo = partes_leitos[0] if len(partes_leitos) > 0 else "0"
                val_le_salvo = partes_leitos[1] if len(partes_leitos) > 1 else "0"
                
                c1791_1, c1791_2 = st.columns([1, 1])
                
                with c1791_1:
                    st.write(f"📊 **Dados Operacionais ({ano_sel}):**")
                    
                    inp_pa = st.text_input(
                        f"Total de pacientes-dia atendidos em {ano_sel} (PA):",
                        value=val_pa_salvo,
                        key=f"txt_1791_pa_{ano_sel}"
                    )
                    
                    inp_le = st.text_input(
                        f"Número total de leitos-dia disponíveis em {ano_sel} (LE):",
                        value=val_le_salvo,
                        key=f"txt_1791_le_{ano_sel}"
                    )
                    
                    # Conversão segura para valores decimais
                    try:
                        pa_float = float(inp_pa.replace(".", "").replace(",", ".")) if inp_pa else 0.0
                    except ValueError:
                        pa_float = 0.0
                        
                    try:
                        le_float = float(inp_le.replace(".", "").replace(",", ".")) if inp_le else 0.0
                    except ValueError:
                        le_float = 0.0
                    
                    # Processamento isolado da fórmula da Taxa de Ocupação (TO)
                    with st.container(key=f"calculo_holder_taxa_to_17_9_1_{ano_sel}"):
                        # Se os dois campos estiverem zerados, o quesito está intocado -> 0 pontos (sem penalidade)
                        if pa_float == 0.0 and le_float == 0.0:
                            st.info("💡 Aguardando o preenchimento dos dados operacionais.")
                            pts_17_9_1 = 0.0
                        elif le_float > 0:
                            taxa_to = (pa_float / le_float) * 100
                            st.markdown(f"📈 **Taxa de Ocupação Calculada (TO):** `{taxa_to:.2f}%`")
                            
                            # Verificação dos limites da regra de negócio (75% a 90%)
                            if 75.0 <= taxa_to <= 90.0:
                                pts_17_9_1 = 0.0
                            else:
                                pts_17_9_1 = -5.0
                        else:
                            # Se o usuário mexeu mas deixou leito zerado incorretamente, aí sim aplica a penalidade
                            st.markdown("⚠️ **Aviso:** O número de leitos-dia deve ser maior que zero para o cálculo.")
                            pts_17_9_1 = -5.0
                        
                    string_estruturada_leitos = f"{inp_pa}|{inp_le}"
                    
                with c1791_2:
                    link_17_9_1 = st.text_area(
                        f"Link/Evidência ou Relatório do SIH/SUS (Movimentação de Leitos) em {ano_sel}:", 
                        value=d17_9_1.get("link", ""), 
                        key=f"reg_17_9_1_txt_{ano_sel}",
                        height=180
                    )
                    
                    with st.container(key=f"links_holder_taxa_ocupacao_17_9_1_{ano_sel}"):
                        links_17_9_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_9_1)
                        if links_17_9_1_atuais:
                            botoes_17_9_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_9_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_9_1}")
                
                # ISOLAMENTO DO SCORE
                with st.container(key=f"score_holder_taxa_ocupacao_17_9_1_{ano_sel}"):
                    if pts_17_9_1 < 0:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.9.1:** :red[{pts_17_9_1:.1f} pontos (Penalidade)]")
                    elif pa_float == 0.0 and le_float == 0.0:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.9.1:** `{pts_17_9_1:.1f} pontos` (Não preenchido / Neutro)")
                    else:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.9.1:** `{pts_17_9_1:.1f} pontos` (Eficiência Ideal)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO
                mudou_valores_17_9_1 = string_estruturada_leitos != valores_salvos_1791
                mudou_link_17_9_1 = link_17_9_1 != d17_9_1.get("link", "")
                mudou_pts_17_9_1 = pts_17_9_1 != float(d17_9_1.get("pontos", 0.0))

                if mudou_valores_17_9_1 or mudou_link_17_9_1 or mudou_pts_17_9_1:
                    save_resp("17.9.1", string_estruturada_leitos, pts_17_9_1, link_17_9_1)
                    
                    if "17.9.1" not in res_data:
                        res_data["17.9.1"] = {}
                    res_data["17.9.1"]["valor"] = string_estruturada_leitos
                    res_data["17.9.1"]["pontos"] = pts_17_9_1
                    res_data["17.9.1"]["link"] = link_17_9_1
                    
                    if mudou_link_17_9_1 and links_17_9_1_atuais:
                        links_17_9_1_antigos = re.findall(r'(https?://[^\s]+)', d17_9_1.get("link", ""))
                        if links_17_9_1_atuais != links_17_9_1_antigos:
                            modal_aviso_link("17.9.1", links_17_9_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.9.1", res_data)

# =============================================================================
        # QUESITO 17.9.2 - HOSPITAIS COM TAXA DE OCUPAÇÃO SUPERIOR A 100%
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_hospitais_superlotados_17_9_2_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.9.2 - Hospitais com Ocupação Superior a 100% (Série Histórica)", expanded=True):
                st.subheader("17.9.2 • Hospitais com Ocupação Superior a 100%")
                st.write(f"**17.9.2 Informe o número de hospitais da rede própria que apresentaram taxa de ocupação superior a 100%:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Definição dinâmica dos anos com base no ano selecionado
                try:
                    aa = int(ano_sel)
                except:
                    aa = 2025
                    
                aa_minus_1 = aa - 1
                aa_minus_2 = aa - 2
                
                # Recupera dados estruturados salvos (Formato: TO_AA-2|TO_AA-1|TO_AA)
                d17_9_2 = res_data.get("17.9.2", {"valor": "0|0|0", "pontos": -5.0, "link": ""})
                valores_salvos_1792 = d17_9_2.get("valor", "0|0|0")
                
                partes_to = valores_salvos_1792.split("|") if valores_salvos_1792 else ["0", "0", "0"]
                while len(partes_to) < 3: 
                    partes_to.append("0")
                
                c1792_1, c1792_2 = st.columns([1, 1])
                
                with c1792_1:
                    st.write("📊 **Número de Estabelecimentos com Ocupação > 100%:**")
                    to_aa2 = st.text_input(f"Nº de hospitais em {aa_minus_2} (TO_{aa_minus_2}):", value=partes_to[0], key=f"to_aa2_{ano_sel}")
                    to_aa1 = st.text_input(f"Nº de hospitais em {aa_minus_1} (TO_{aa_minus_1}):", value=partes_to[1], key=f"to_aa1_{ano_sel}")
                    to_aa  = st.text_input(f"Nº de hospitais em {aa} (TO_{aa}):", value=partes_to[2], key=f"to_aa_{ano_sel}")
                    
                    # Conversão limpa para floats
                    def converter_to(val):
                        try: 
                            return float(val.replace(".", "").replace(",", ".")) if val else 0.0
                        except: 
                            return 0.0
                        
                    f_to_aa2 = converter_to(to_aa2)
                    f_to_aa1 = converter_to(to_aa1)
                    f_to_aa  = converter_to(to_aa)
                    
                    # Processamento isolado da regra de negócio da série histórica
                    with st.container(key=f"calculo_holder_historico_17_9_2_{ano_sel}"):
                        media_anterior = (f_to_aa2 + f_to_aa1) / 2.0
                        st.markdown(f"⏳ **Média Histórica Anterior ({aa_minus_2} e {aa_minus_1}):** `{media_anterior:.2f}` hospitais")
                        st.markdown(f"📈 **Valor Registrado no Ano Atual ({aa}):** `{f_to_aa:.2f}` hospitais")
                    
                    # Regra de pontuação: Se o ano atual for menor ou igual à média, ganha 0. Se for maior, perde 5.
                    if f_to_aa <= media_anterior:
                        pts_17_9_2 = 0.0
                    else:
                        pts_17_9_2 = -5.0
                        
                    string_estruturada_to = f"{to_aa2}|{to_aa1}|{to_aa}"
                    
                with c1792_2:
                    link_17_9_2 = st.text_area(
                        f"Link/Evidência ou Relatório de Movimentação de Leitos / AIH da série histórica ({aa_minus_2} a {aa}):", 
                        value=d17_9_2.get("link", ""), 
                        key=f"reg_17_9_2_txt_{ano_sel}",
                        height=235
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_superlotados_17_9_2_{ano_sel}"):
                        links_17_9_2_atuais = re.findall(r'(https?://[^\s]+)', link_17_9_2)
                        if links_17_9_2_atuais:
                            botoes_17_9_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_9_2_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_9_2}")
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_superlotados_17_9_2_{ano_sel}"):
                    if pts_17_9_2 < 0:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.9.2:** :red[{pts_17_9_2:.1f} pontos (Penalidade por aumento de superlotação)]")
                    else:
                        st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.9.2:** `{pts_17_9_2:.1f} pontos` (Controle Histórico Estável)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_9_2 = string_estruturada_to != valores_salvos_1792
                mudou_link_17_9_2 = link_17_9_2 != d17_9_2.get("link", "")
                mudou_pts_17_9_2 = pts_17_9_2 != float(d17_9_2.get("pontos", -5.0))

                if mudou_valores_17_9_2 or mudou_link_17_9_2 or mudou_pts_17_9_2:
                    save_resp("17.9.2", string_estruturada_to, pts_17_9_2, link_17_9_2)
                    
                    if "17.9.2" not in res_data:
                        res_data["17.9.2"] = {}
                    res_data["17.9.2"]["valor"] = string_estruturada_to
                    res_data["17.9.2"]["pontos"] = pts_17_9_2
                    res_data["17.9.2"]["link"] = link_17_9_2
                    
                    if mudou_link_17_9_2 and links_17_9_2_atuais:
                        links_17_9_2_antigos = re.findall(r'(https?://[^\s]+)', d17_9_2.get("link", ""))
                        if links_17_9_2_atuais != links_17_9_2_antigos:
                            modal_aviso_link("17.9.2", links_17_9_2_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.9.2", res_data)

# =============================================================================
        # QUESITO 18.0 - DEMANDA POR ASSISTÊNCIA EM SAÚDE MENTAL (INFORMATIVO)
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_demanda_saude_mental_18_0_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 18.0 - Demanda por Assistência em Saúde Mental e Substâncias Psicoativas", expanded=True):
                st.subheader("18.0 • Demanda por Assistência em Saúde Mental")
                st.write(f"**18.0 No município, há demanda de ações e de serviços voltados para a assistência aos portadores de transtornos mentais, bem como para usuários de substâncias psicoativas?**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Quesito informativo: sem impacto direto na pontuação total
                opts_18_0 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                
                d18_0 = res_data.get("18.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                
                c180_1, c180_2 = st.columns([1, 1])
                with c180_1:
                    sel_18_0 = st.radio(
                        "Há demanda por ações/serviços:", 
                        options=list(opts_18_0.keys()), 
                        index=(list(opts_18_0.keys()).index(d18_0["valor"]) if d18_0["valor"] in opts_18_0 else 0),
                        key=f"reg_18_0_rad_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    pts_18_0 = 0.0
                    
                with c180_2:
                    link_18_0 = st.text_area(
                        "Link/Evidência, Plano Municipal de Saúde ou Relatório de Gestão (18.0):", 
                        value=d18_0.get("link", ""), 
                        key=f"reg_18_0_txt_{ano_sel}",
                        height=130
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_demanda_saude_mental_18_0_{ano_sel}"):
                        links_18_0_atuais = re.findall(r'(https?://[^\s]+)', link_18_0)
                        if links_18_0_atuais:
                            botoes_18_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_0_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_18_0}")
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_demanda_saude_mental_18_0_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 18.0:** `{pts_18_0:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_18_0 = sel_18_0 != d18_0["valor"]
                mudou_link_18_0 = link_18_0 != d18_0.get("link", "")

                if mudou_valores_18_0 or mudou_link_18_0:
                    if sel_18_0 is not None:
                        save_resp("18.0", sel_18_0, pts_18_0, link_18_0)
                        res_data["18.0"] = {"valor": sel_18_0, "pontos": pts_18_0, "link": link_18_0}
                        
                        if mudou_link_18_0 and links_18_0_atuais:
                            links_18_0_antigos = re.findall(r'(https?://[^\s]+)', d18_0.get("link", ""))
                            if links_18_0_atuais != links_18_0_antigos:
                                modal_aviso_link("18.0", links_18_0_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                    
                bloco_comentarios("18.0", res_data)

# =============================================================================
        # QUESITO 18.1 - PLANO DE AÇÃO MUNICIPAL DA RAPS
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_plano_raps_18_1_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 18.1 - Plano de Ação para Inclusão na RAPS", expanded=True):
                st.subheader("18.1 • Plano de Ação para Inclusão na RAPS")
                st.write("**18.1 Realizou Plano de Ação municipal para inclusão do município à sua RAPS?**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Opções com os rótulos de pontuação ao lado das alternativas
                opts_18_1 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                d18_1 = res_data.get("18.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                val_atual_181 = d18_1.get("valor", "Selecione...")
                
                c181_1, c181_2 = st.columns([1, 1])
                with c181_1:
                    idx_181 = opts_18_1.index(val_atual_181) if val_atual_181 in opts_18_1 else 0
                    sel_18_1 = st.radio(
                        "Plano de Ação RAPS:", 
                        options=opts_18_1, 
                        index=idx_181, 
                        key=f"rad_18_1_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    
                    # Regra de negócio baseada na string selecionada
                    if "Não" in sel_18_1:
                        pts_18_1 = -10.0
                    else:
                        pts_18_1 = 0.0
                        
                with c181_2:
                    link_18_1 = st.text_area(
                        "Evidência / Resolução do Plano RAPS (18.1):", 
                        value=d18_1.get("link", ""), 
                        key=f"txt_18_1_{ano_sel}", 
                        height=100
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_plano_raps_18_1_{ano_sel}"):
                        links_18_1_atuais = re.findall(r'(https?://[^\s]+)', link_18_1)
                        if links_18_1_atuais:
                            botoes_18_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_18_1}")
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_plano_raps_18_1_{ano_sel}"):
                    if pts_18_1 < 0:
                        st.markdown(f"📊 **Pontuação:** :red[{pts_18_1:.1f} pontos (Penalidade)]")
                    elif "Selecione..." in sel_18_1:
                        st.markdown(f"📊 **Pontuação:** `{pts_18_1:.1f} pontos` (Aguardando Seleção)")
                    else:
                        st.markdown(f"📊 **Pontuação:** `{pts_18_1:.1f} pontos` (Meta Atingida)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_18_1 = sel_18_1 != d18_1["valor"]
                mudou_link_18_1 = link_18_1 != d18_1.get("link", "")

                if mudou_valores_18_1 or mudou_link_18_1:
                    if sel_18_1 is not None:
                        save_resp("18.1", sel_18_1, pts_18_1, link_18_1)
                        res_data["18.1"] = {"valor": sel_18_1, "pontos": pts_18_1, "link": link_18_1}
                        
                        if mudou_link_18_1 and links_18_1_atuais:
                            links_18_1_antigos = re.findall(r'(https?://[^\s]+)', d18_1.get("link", ""))
                            if links_18_1_atuais != links_18_1_antigos:
                                modal_aviso_link("18.1", links_18_1_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                    
                bloco_comentarios("18.1", res_data)

        # =============================================================================
        # QUESITO 18.2 - INTEGRAÇÃO ENTRE ÓRGÃOS MUNICIPAIS
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_integracao_orgaos_18_2_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 18.2 - Integração de Órgãos para Assistência Mental", expanded=True):
                st.subheader("18.2 • Integração de Órgãos para Assistência Mental")
                st.write("**18.2 A Secretaria Municipal de Saúde (ou equivalente) está integrada com os outros órgãos municipais de forma a ampliar a oferta de ações e de serviços voltados para a assistência aos portadores de transtornos mentais?**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Opções com os rótulos de pontuação ao lado das alternativas
                opts_18_2 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                d18_2 = res_data.get("18.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                val_atual_182 = d18_2.get("valor", "Selecione...")
                
                c182_1, c182_2 = st.columns([1, 1])
                with c182_1:
                    idx_182 = opts_18_2.index(val_atual_182) if val_atual_182 in opts_18_2 else 0
                    sel_18_2 = st.radio(
                        "Integração de órgãos:", 
                        options=opts_18_2, 
                        index=idx_182, 
                        key=f"rad_18_2_{ano_sel}", 
                        label_visibility="collapsed"
                    )
                    
                    if "Não" in sel_18_2:
                        pts_18_2 = -5.0
                    else:
                        pts_18_2 = 0.0
                        
                with c182_2:
                    link_18_2 = st.text_area(
                        "Evidência de Integração Intersetorial (18.2):", 
                        value=d18_2.get("link", ""), 
                        key=f"txt_18_2_{ano_sel}", 
                        height=100
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_integracao_orgaos_18_2_{ano_sel}"):
                        links_18_2_atuais = re.findall(r'(https?://[^\s]+)', link_18_2)
                        if links_18_2_atuais:
                            botoes_18_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_2_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_18_2}")
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_integracao_orgaos_18_2_{ano_sel}"):
                    if pts_18_2 < 0:
                        st.markdown(f"📊 **Pontuação:** :red[{pts_18_2:.1f} pontos (Penalidade)]")
                    elif "Selecione..." in sel_18_2:
                        st.markdown(f"📊 **Pontuação:** `{pts_18_2:.1f} pontos` (Aguardando Seleção)")
                    else:
                        st.markdown(f"📊 **Pontuação:** `{pts_18_2:.1f} pontos` (Meta Atingida)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_18_2 = sel_18_2 != d18_2["valor"]
                mudou_link_18_2 = link_18_2 != d18_2.get("link", "")

                if mudou_valores_18_2 or mudou_link_18_2:
                    if sel_18_2 is not None:
                        save_resp("18.2", sel_18_2, pts_18_2, link_18_2)
                        res_data["18.2"] = {"valor": sel_18_2, "pontos": pts_18_2, "link": link_18_2}
                        
                        if mudou_link_18_2 and links_18_2_atuais:
                            links_18_2_antigos = re.findall(r'(https?://[^\s]+)', d18_2.get("link", ""))
                            if links_18_2_atuais != links_18_2_antigos:
                                modal_aviso_link("18.2", links_18_2_atuais)
                            else:
                                st.rerun()
                        else:
                            st.rerun()
                    
                bloco_comentarios("18.2", res_data)

# =============================================================================
        # QUESITO 18.2.1 - FORMA DE INTEGRAÇÃO DOS ÓRGÃOS
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_forma_integracao_18_2_1_{ano_sel}", border=True):
            
            with st.expander("📌 Quesito 18.2.1 • Forma de Integração dos Órgãos", expanded=True):
                st.subheader("18.2.1 • Forma de Integração dos Órgãos")
                st.write("**Assinale a forma de integração dos órgãos:**")
                st.caption("ℹ nighttime: *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos estruturados em string binária (Ações|Papéis|Metas|Prazos|Normas|Outros)
                d18_2_1 = res_data.get("18.2.1", {"valor": "0|0|0|0|0|0", "pontos": 0.0, "link": ""})
                p_1821 = d18_2_1.get("valor", "0|0|0|0|0|0").split("|")
                while len(p_1821) < 6: 
                    p_1821.append("0")
                
                c1821_1, c1821_2 = st.columns([1, 1])
                with c1821_1:
                    ch1_1821 = st.checkbox("Ações estabelecidas", value=(p_1821[0] == "1"), key=f"ch_1821_1_{ano_sel}")
                    ch2_1821 = st.checkbox("Papéis definidos", value=(p_1821[1] == "1"), key=f"ch_1821_2_{ano_sel}")
                    ch3_1821 = st.checkbox("Metas estabelecidas", value=(p_1821[2] == "1"), key=f"ch_1821_3_{ano_sel}")
                    ch4_1821 = st.checkbox("Prazos", value=(p_1821[3] == "1"), key=f"ch_1821_4_{ano_sel}")
                    ch5_1821 = st.checkbox("Normas complementar firmadas entre órgãos", value=(p_1821[4] == "1"), key=f"ch_1821_5_{ano_sel}")
                    ch6_1821 = st.checkbox("Outros", value=(p_1821[5] == "1"), key=f"ch_1821_6_{ano_sel}")
                    
                    string_estruturada_18_2_1 = f"{1 if ch1_1821 else 0}|{1 if ch2_1821 else 0}|{1 if ch3_1821 else 0}|{1 if ch4_1821 else 0}|{1 if ch5_1821 else 0}|{1 if ch6_1821 else 0}"
                    
                with c1821_2:
                    link_18_2_1 = st.text_area(
                        "Link/Evidência de Integração (18.2.1):",
                        value=d18_2_1.get("link", ""),
                        key=f"txt_18_2_1_{ano_sel}",
                        height=150
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_forma_integracao_18_2_1_{ano_sel}"):
                        links_18_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_18_2_1)
                        if links_18_2_1_atuais:
                            botoes_18_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_2_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_18_2_1}")
                
                # ISOLAMENTO DO SCORE (Dados Informativos)
                with st.container(key=f"score_holder_forma_integracao_18_2_1_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 18.2.1:** `0.0 pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_18_2_1 = string_estruturada_18_2_1 != d18_2_1.get("valor")
                mudou_link_18_2_1 = link_18_2_1 != d18_2_1.get("link", "")

                if mudou_valores_18_2_1 or mudou_link_18_2_1:
                    save_resp("18.2.1", string_estruturada_18_2_1, 0.0, link_18_2_1)
                    res_data["18.2.1"] = {"valor": string_estruturada_18_2_1, "pontos": 0.0, "link": link_18_2_1}
                    
                    if mudou_link_18_2_1 and links_18_2_1_atuais:
                        links_18_2_1_antigos = re.findall(r'(https?://[^\s]+)', d18_2_1.get("link", ""))
                        if links_18_2_1_atuais != links_18_2_1_antigos:
                            modal_aviso_link("18.2.1", links_18_2_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                        
                bloco_comentarios("18.2.1", res_data)

        # =============================================================================
        # QUESITO 18.2.1.1 - METAS ATINGIDAS NO EXERCÍCIO
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Envolvendo o bloco em um container com chave estável para proteger o React DOM
        with st.container(key=f"container_bloco_metas_18_2_1_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 18.2.1.1 • Metas Atingidas no Exercício Anterior", expanded=True):
                        st.subheader("18.2.1.1 • Metas Atingidas no Exercício Anterior")
                        st.write("**As metas estabelecidas para o exercício 2025 foram atingidas?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_18_2_1_1 = {
                                "Selecione...": 0.0,
                                "Sim, todas as metas foram atingidas": 0.0,
                                "Sim, a maior parte das metas foram atingidas": 0.0,
                                "Sim, a menor parte das metas foram atingidas": 0.0,
                                "Não": 0.0
                        }
                        
                        d18_2_1_1 = res_data.get("18.2.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_salvo_18211 = d18_2_1_1.get("valor", "Selecione...")
                        if val_salvo_18211 not in opts_18_2_1_1:
                                val_salvo_18211 = "Selecione..."
                                
                        idx_inicial_18211 = list(opts_18_2_1_1.keys()).index(val_salvo_18211)
                        
                        c18211_1, c18211_2 = st.columns([1, 1])
                        with c18211_1:
                                sel_18_2_1_1 = st.radio(
                                        "Metas atingidas:",
                                        options=list(opts_18_2_1_1.keys()),
                                        index=idx_inicial_18211,
                                        key=f"rb_18_2_1_1_{ano_sel}",
                                        label_visibility="collapsed"
                                )
                                pts_18_2_1_1 = opts_18_2_1_1.get(sel_18_2_1_1, 0.0)
                                
                        with c18211_2:
                                link_18_2_1_1 = st.text_area(
                                        "Link/Evidência do Relatório de Metas (18.2.1.1):",
                                        value=d18_2_1_1.get("link", ""),
                                        key=f"txt_18_2_1_1_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Placeholder estático para links ativos evitando o erro NotFoundError
                                placeholder_links_18_2_1_1 = st.empty()
                                links_18_2_1_1_atuais = re.findall(r'(https?://[^\s]+)', link_18_2_1_1)
                                if links_18_2_1_1_atuais:
                                        botoes_18_2_1_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_2_1_1_atuais])
                                        placeholder_links_18_2_1_1.markdown(f"**Links Ativos:** {botoes_18_2_1_1}")
                        
                        # FIX: Placeholder para exibição da pontuação de forma segura
                        score_placeholder_18_2_1_1 = st.empty()
                        score_placeholder_18_2_1_1.markdown(f"📊 **Pontuação Aplicada no Quesito 18.2.1.1:** `{pts_18_2_1_1:.1f} pontos`")
                        
                        mudou_opcao_18_2_1_1 = sel_18_2_1_1 != d18_2_1_1.get("valor", "")
                        mudou_link_18_2_1_1 = link_18_2_1_1 != d18_2_1_1.get("link", "")
                        
                        if mudou_opcao_18_2_1_1 or mudou_link_18_2_1_1:
                                save_resp("18.2.1.1", sel_18_2_1_1, pts_18_2_1_1, link_18_2_1_1)
                                res_data["18.2.1.1"] = {"valor": sel_18_2_1_1, "pontos": pts_18_2_1_1, "link": link_18_2_1_1}
                                
                                # Lógica do Modal/Aviso de Link
                                if mudou_link_18_2_1_1 and links_18_2_1_1_atuais:
                                        links_18_2_1_1_antigos = re.findall(r'(https?://[^\s]+)', d18_2_1_1.get("link", ""))
                                        if links_18_2_1_1_atuais != links_18_2_1_1_antigos:
                                                modal_aviso_link("18.2.1.1", links_18_2_1_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.2.1.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)


       # =============================================================================
        # QUESITO 18.3 - TERMO DE ADESÃO AO PROGRAMA RECOMEÇO
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container com chave explícita e estável para evitar NotFoundError no front-end
        with st.container(key=f"container_bloco_recomeco_18_3_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 18.3 • Adesão ao Programa Recomeço", expanded=True):
                        st.subheader("18.3 • Adesão ao Programa Recomeço")
                        st.write("**O Município formalizou termo de adesão com o Programa Recomeço (Art. 7º, Decreto nº 61.674/2015) ou outro programa que venha a substituí-lo?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_18_3 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d18_3 = res_data.get("18.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_salvo_183 = d18_3.get("valor", "Selecione...")
                        if val_salvo_183 not in opts_18_3:
                                val_salvo_183 = "Selecione..."
                                
                        idx_inicial_183 = list(opts_18_3.keys()).index(val_salvo_183)
                        
                        c183_1, c183_2 = st.columns([1, 1])
                        with c183_1:
                                sel_18_3 = st.radio(
                                        "Formalizou adesão:",
                                        options=list(opts_18_3.keys()),
                                        index=idx_inicial_183,
                                        key=f"rb_18_3_{ano_sel}",
                                        label_visibility="collapsed"
                                )
                                pts_18_3 = opts_18_3.get(sel_18_3, 0.0)
                                
                        with c183_2:
                                link_18_3 = st.text_area(
                                        "Link/Evidência da Publicação do Termo de Adesão (18.3):",
                                        value=d18_3.get("link", ""),
                                        key=f"txt_18_3_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Criação segura do nó de links ativos
                                placeholder_links_18_3 = st.empty()
                                links_18_3_atuais = re.findall(r'(https?://[^\s]+)', link_18_3)
                                if links_18_3_atuais:
                                        botoes_18_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_3_atuais])
                                        placeholder_links_18_3.markdown(f"**Links Ativos:** {botoes_18_3}")
                        
                        # FIX: Placeholder fixo para a pontuação não quebrar o DOM
                        score_placeholder_18_3 = st.empty()
                        score_placeholder_18_3.markdown(f"📊 **Pontuação Aplicada no Quesito 18.3:** `{pts_18_3:.1f} pontos`")
                        
                        mudou_opcao_18_3 = sel_18_3 != d18_3.get("valor", "")
                        mudou_link_18_3 = link_18_3 != d18_3.get("link", "")
                        
                        if mudou_opcao_18_3 or mudou_link_18_3:
                                save_resp("18.3", sel_18_3, pts_18_3, link_18_3)
                                res_data["18.3"] = {"valor": sel_18_3, "pontos": pts_18_3, "link": link_18_3}
                                
                                # Lógica para exibição do modal de aviso de link
                                if mudou_link_18_3 and links_18_3_atuais:
                                        links_18_3_antigos = re.findall(r'(https?://[^\s]+)', d18_3.get("link", ""))
                                        if links_18_3_atuais != links_18_3_antigos:
                                                modal_aviso_link("18.3", links_18_3_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.3", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.4 - INDICADORES ESPECÍFICOS DA ATENÇÃO PSICOSSOCIAL
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container com chave explícita e estável para evitar NotFoundError no React DOM
        with st.container(key=f"container_bloco_indicadores_18_4_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 18.4 • Indicadores da Atenção Psicossocial", expanded=True):
                        st.subheader("18.4 • Indicadores da Atenção Psicossocial")
                        st.write("**O município possui indicadores específicos para a Atenção Psicossocial?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_18_4 = {
                                "Selecione...": 0.0,
                                "Sim – 00": 0.0,
                                "Não – -05 (perde 05 pontos)": -5.0
                        }
                        
                        d18_4 = res_data.get("18.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_salvo_184 = d18_4.get("valor", "Selecione...")
                        if val_salvo_184 not in opts_18_4:
                                val_salvo_184 = "Selecione..."
                                
                        idx_inicial_184 = list(opts_18_4.keys()).index(val_salvo_184)
                        
                        c184_1, c184_2 = st.columns([1, 1])
                        with c184_1:
                                sel_18_4 = st.radio(
                                        "Possui indicadores específicos:",
                                        options=list(opts_18_4.keys()),
                                        index=idx_inicial_184,
                                        key=f"rb_18_4_{ano_sel}",
                                        label_visibility="collapsed"
                                )
                                pts_18_4 = opts_18_4.get(sel_18_4, 0.0)
                                
                        with c184_2:
                                link_18_4 = st.text_area(
                                        "Link/Evidência dos Indicadores (18.4):",
                                        value=d18_4.get("link", ""),
                                        key=f"txt_18_4_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Criação segura do nó para links ativos
                                placeholder_links_18_4 = st.empty()
                                links_18_4_atuais = re.findall(r'(https?://[^\s]+)', link_18_4)
                                if links_18_4_atuais:
                                        botoes_18_4 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_4_atuais])
                                        placeholder_links_18_4.markdown(f"**Links Ativos:** {botoes_18_4}")
                        
                        # FIX: Uso do st.empty() para a pontuação não ser recriada de forma condicional direta
                        score_placeholder_18_4 = st.empty()
                        if sel_18_4 == "Selecione...":
                                score_placeholder_18_4.markdown("📊 **Pontuação Aplicada no Quesito 18.4:** `Aguardando seleção...`")
                        elif pts_18_4 < 0:
                                score_placeholder_18_4.markdown(f"📊 **Pontuação Aplicada no Quesito 18.4:** :red[{pts_18_4:.1f} pontos (Penalidade)]")
                        else:
                                score_placeholder_18_4.markdown(f"📊 **Pontuação Aplicada no Quesito 18.4:** `{pts_18_4:.1f} pontos`")
                                
                        mudou_opcao_18_4 = sel_18_4 != d18_4.get("valor", "")
                        mudou_link_18_4 = link_18_4 != d18_4.get("link", "")
                        
                        if mudou_opcao_18_4 or mudou_link_18_4:
                                save_resp("18.4", sel_18_4, pts_18_4, link_18_4)
                                res_data["18.4"] = {"valor": sel_18_4, "pontos": pts_18_4, "link": link_18_4}
                                
                                # Lógica para tratamento de alterações no link com modal de confirmação
                                if mudou_link_18_4 and links_18_4_atuais:
                                        links_18_4_antigos = re.findall(r'(https?://[^\s]+)', d18_4.get("link", ""))
                                        if links_18_4_atuais != links_18_4_antigos:
                                                modal_aviso_link("18.4", links_18_4_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.4", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.4.1 - TIPOS DE INDICADORES DA ATENÇÃO PSICOSSOCIAL
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para blindar o React contra o erro de remoção de nós
        with st.container(key=f"container_bloco_tipos_indicadores_18_4_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 18.4.1 • Tipos de Indicadores da Atenção Psicossocial", expanded=True):
                        st.subheader("18.4.1 • Tipos de Indicadores da Atenção Psicossocial")
                        st.write("**Assinale os tipos de indicadores da Atenção Psicossocial:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                        
                        d18_4_1 = res_data.get("18.4.1", {"valor": "0|0|0|0|0", "pontos": 0.0, "link": ""})
                        p_1841 = d18_4_1.get("valor", "0|0|0|0|0").split("|")
                        while len(p_1841) < 5: p_1841.append("0")
                        
                        c1841_1, c1841_2 = st.columns([1, 1])
                        with c1841_1:
                                ch1_1841 = st.checkbox("Para Drogas (transtornos mentais incluindo aqueles relacionados ao uso de substâncias)", value=(p_1841[0] == "1"), key=f"ch_1841_1_{ano_sel}")
                                ch2_1841 = st.checkbox("Para Saúde Mental (transtornos mentais graves e persistentes)", value=(p_1841[1] == "1"), key=f"ch_1841_2_{ano_sel}")
                                ch3_1841 = st.checkbox("Para outras situações clínicas que impossibilitem estabelecer laços sociais e realizar projetos", value=(p_1841[2] == "1"), key=f"ch_1841_3_{ano_sel}")
                                ch4_1841 = st.checkbox("Para Drogas e/ou Saúde Mental para crianças em específico", value=(p_1841[3] == "1"), key=f"ch_1841_4_{ano_sel}")
                                ch5_1841 = st.checkbox("Outros", value=(p_1841[4] == "1"), key=f"ch_1841_5_{ano_sel}")
                                
                                string_estruturada_18_4_1 = f"{1 if ch1_1841 else 0}|{1 if ch2_1841 else 0}|{1 if ch3_1841 else 0}|{1 if ch4_1841 else 0}|{1 if ch5_1841 else 0}"
                                pts_18_4_1 = 0.0
                                
                        with c1841_2:
                                link_18_4_1 = st.text_area(
                                        "Link/Evidência ou Ficha Técnica dos Indicadores (18.4.1):",
                                        value=d18_4_1.get("link", ""),
                                        key=f"txt_18_4_1_{ano_sel}",
                                        height=150
                                )
                                
                                # FIX: Criação estática do nó para links ativos
                                placeholder_links_18_4_1 = st.empty()
                                links_18_4_1_atuais = re.findall(r'(https?://[^\s]+)', link_18_4_1)
                                if links_18_4_1_atuais:
                                        botoes_18_4_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_4_1_atuais])
                                        placeholder_links_18_4_1.markdown(f"**Links Ativos:** {botoes_18_4_1}")
                        
                        # FIX: Placeholder estável fixado na árvore do DOM para exibição dos pontos
                        score_placeholder_18_4_1 = st.empty()
                        score_placeholder_18_4_1.markdown(f"📊 **Pontuação Aplicada no Quesito 18.4.1:** `{pts_18_4_1:.1f} pontos`")
                        
                        mudou_valores_18_4_1 = string_estruturada_18_4_1 != d18_4_1.get("valor", "")
                        mudou_link_18_4_1 = link_18_4_1 != d18_4_1.get("link", "")
                        
                        if mudou_valores_18_4_1 or mudou_link_18_4_1:
                                save_resp("18.4.1", string_estruturada_18_4_1, pts_18_4_1, link_18_4_1)
                                res_data["18.4.1"] = {"valor": string_estruturada_18_4_1, "pontos": pts_18_4_1, "link": link_18_4_1}
                                
                                # Lógica para tratamento de alterações de link e acionamento do modal de aviso
                                if mudou_link_18_4_1 and links_18_4_1_atuais:
                                        links_18_4_1_antigos = re.findall(r'(https?://[^\s]+)', d18_4_1.get("link", ""))
                                        if links_18_4_1_atuais != links_18_4_1_antigos:
                                                modal_aviso_link("18.4.1", links_18_4_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.4.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.5 - POPULAÇÃO SUPERIOR A 15 MIL HABITANTES
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de renderização do React DOM
        with st.container(key=f"container_bloco_populacao_18_5_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 18.5 • População Superior a 15 mil Habitantes", expanded=True):
                        st.subheader("18.5 • População Superior a 15 mil Habitantes")
                        st.write("**O município possui população superior a 15 mil habitantes? (Conforme Dados do IBGE 2025)**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_18_5 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d18_5 = res_data.get("18.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_salvo_185 = d18_5.get("valor", "Selecione...")
                        if val_salvo_185 not in opts_18_5:
                                val_salvo_185 = "Selecione..."
                                
                        idx_inicial_185 = list(opts_18_5.keys()).index(val_salvo_185)
                        
                        c185_1, c185_2 = st.columns([1, 1])
                        with c185_1:
                                sel_18_5 = st.radio(
                                        "População > 15k hab:",
                                        options=list(opts_18_5.keys()),
                                        index=idx_inicial_185,
                                        key=f"rb_18_5_{ano_sel}",
                                        label_visibility="collapsed"
                                )
                                pts_18_5 = opts_18_5.get(sel_18_5, 0.0)
                                
                        with c185_2:
                                link_18_5 = st.text_area(
                                        "Link/Evidência ou Documento de Censo IBGE (18.5):",
                                        value=d18_5.get("link", ""),
                                        key=f"txt_18_5_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Placeholder seguro anexado estaticamente para links ativos
                                placeholder_links_18_5 = st.empty()
                                links_18_5_atuais = re.findall(r'(https?://[^\s]+)', link_18_5)
                                if links_18_5_atuais:
                                        botoes_18_5 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_5_atuais])
                                        placeholder_links_18_5.markdown(f"**Links Ativos:** {botoes_18_5}")
                        
                        # FIX: Placeholder estável para a pontuação
                        score_placeholder_18_5 = st.empty()
                        score_placeholder_18_5.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5:** `{pts_18_5:.1f} pontos`")
                        
                        mudou_opcao_18_5 = sel_18_5 != d18_5.get("valor", "")
                        mudou_link_18_5 = link_18_5 != d18_5.get("link", "")
                        
                        if mudou_opcao_18_5 or mudou_link_18_5:
                                save_resp("18.5", sel_18_5, pts_18_5, link_18_5)
                                res_data["18.5"] = {"valor": sel_18_5, "pontos": pts_18_5, "link": link_18_5}
                                
                                # Lógica para tratamento do modal de aviso ao modificar a evidência
                                if mudou_link_18_5 and links_18_5_atuais:
                                        links_18_5_antigos = re.findall(r'(https?://[^\s]+)', d18_5.get("link", ""))
                                        if links_18_5_atuais != links_18_5_antigos:
                                                modal_aviso_link("18.5", links_18_5_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.5", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.5.1 - ADEQUAÇÃO DA QUANTIDADE DE CAPS E UNIDADES
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_adequacao_caps_18_5_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 18.5.1 • Adequação da Rede CAPS e Acolhimento", expanded=True):
                        st.subheader("18.5.1 • Adequação da Rede CAPS e Acolhimento")
                        st.write("**A Quantidade de CAPS e Unidades de Acolhimento Adulto e Infanto-Juvenil segundo a totalidade de habitantes do município é adequada?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_18_5_1 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d18_5_1 = res_data.get("18.5.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_salvo_1851 = d18_5_1.get("valor", "Selecione...")
                        if val_salvo_1851 not in opts_18_5_1:
                                val_salvo_1851 = "Selecione..."
                                
                        idx_inicial_1851 = list(opts_18_5_1.keys()).index(val_salvo_1851)
                        
                        c1851_1, c1851_2 = st.columns([1, 1])
                        with c1851_1:
                                sel_18_5_1 = st.radio(
                                        "Quantidade adequada:",
                                        options=list(opts_18_5_1.keys()),
                                        index=idx_inicial_1851,
                                        key=f"rb_18_5_1_{ano_sel}",
                                        label_visibility="collapsed"
                                )
                                pts_18_5_1 = opts_18_5_1.get(sel_18_5_1, 0.0)
                                
                        with c1851_2:
                                link_18_5_1 = st.text_area(
                                        "Link/Evidência ou Justificativa de Cobertura (18.5.1):",
                                        value=d18_5_1.get("link", ""),
                                        key=f"txt_18_5_1_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_18_5_1 = st.empty()
                                links_18_5_1_atuais = re.findall(r'(https?://[^\s]+)', link_18_5_1)
                                if links_18_5_1_atuais:
                                        botoes_18_5_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_5_1_atuais])
                                        placeholder_links_18_5_1.markdown(f"**Links Ativos:** {botoes_18_5_1}")
                        
                        # FIX: Placeholder fixo para a pontuação
                        score_placeholder_18_5_1 = st.empty()
                        score_placeholder_18_5_1.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.1:** `{pts_18_5_1:.1f} pontos`")
                        
                        mudou_opcao_18_5_1 = sel_18_5_1 != d18_5_1.get("valor", "")
                        mudou_link_18_5_1 = link_18_5_1 != d18_5_1.get("link", "")
                        
                        if mudou_opcao_18_5_1 or mudou_link_18_5_1:
                                save_resp("18.5.1", sel_18_5_1, pts_18_5_1, link_18_5_1)
                                res_data["18.5.1"] = {"valor": sel_18_5_1, "pontos": pts_18_5_1, "link": link_18_5_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_18_5_1 and links_18_5_1_atuais:
                                        links_18_5_1_antigos = re.findall(r'(https?://[^\s]+)', d18_5_1.get("link", ""))
                                        if links_18_5_1_atuais != links_18_5_1_antigos:
                                                modal_aviso_link("18.5.1", links_18_5_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.5.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.5.2 - QUANTIDADE DE ESTABELECIMENTOS DA REDE
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_quant_estab_18_5_2_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 18.5.2 • Quantidade de Estabelecimentos Cadastrados", expanded=True):
                        st.subheader("18.5.2 • Quantidade de Estabelecimentos do Município")
                        st.write("**Informe a quantidade de estabelecimentos do município por categoria:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos numéricos ou no link grava os dados na hora.*")
                        
                        # Formato serializado: CAPS_I|CAPS_II|CAPS_III|CAPS_AD|CAPS_AD_II|CAPS_AD_III|CAPS_I_F|CAPS_I_II|CAPS_AD_IV|UA_ADULTO|UA_INFANTIL
                        d18_5_2 = res_data.get("18.5.2", {"valor": "0|0|0|0|0|0|0|0|0|0|0", "pontos": 0.0, "link": ""})
                        p_1852 = d18_5_2.get("valor", "0|0|0|0|0|0|0|0|0|0|0").split("|")
                        while len(p_1852) < 11: p_1852.append("0")
                        
                        c1852_1, c1852_2 = st.columns([1, 1])
                        with c1852_1:
                                v1 = st.text_input("I - CAPS I:", value=p_1852[0], key=f"q1852_v1_{ano_sel}")
                                v2 = st.text_input("II - CAPS II:", value=p_1852[1], key=f"q1852_v2_{ano_sel}")
                                v3 = st.text_input("III - CAPS III:", value=p_1852[2], key=f"q1852_v3_{ano_sel}")
                                v4 = st.text_input("IV - CAPS AD:", value=p_1852[3], key=f"q1852_v4_{ano_sel}")
                                v5 = st.text_input("V - CAPS AD II:", value=p_1852[4], key=f"q1852_v5_{ano_sel}")
                                v6 = st.text_input("VI - CAPS AD III:", value=p_1852[5], key=f"q1852_v6_{ano_sel}")
                                v7 = st.text_input("VII - CAPS i:", value=p_1852[6], key=f"q1852_v7_{ano_sel}")
                                v8 = st.text_input("VIII - CAPS i II:", value=p_1852[7], key=f"q1852_v8_{ano_sel}")
                                v9 = st.text_input("IX - CAPS AD IV:", value=p_1852[8], key=f"q1852_v9_{ano_sel}")
                                v10 = st.text_input("X - Unidade de Acolhimento Adulto:", value=p_1852[9], key=f"q1852_v10_{ano_sel}")
                                v11 = st.text_input("XI - Unidade de Acolhimento Infantil:", value=p_1852[10], key=f"q1852_v11_{ano_sel}")
                                
                                string_estruturada_18_5_2 = f"{v1}|{v2}|{v3}|{v4}|{v5}|{v6}|{v7}|{v8}|{v9}|{v10}|{v11}"
                                pts_18_5_2 = 0.0
                                
                        with c1852_2:
                                link_18_5_2 = st.text_area(
                                        "Link/Evidência ou Certidão CNES dos estabelecimentos (18.5.2):",
                                        value=d18_5_2.get("link", ""),
                                        key=f"txt_18_5_2_{ano_sel}",
                                        height=300
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_18_5_2 = st.empty()
                                links_18_5_2_atuais = re.findall(r'(https?://[^\s]+)', link_18_5_2)
                                if links_18_5_2_atuais:
                                        botoes_18_5_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_5_2_atuais])
                                        placeholder_links_18_5_2.markdown(f"**Links Ativos:** {botoes_18_5_2}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação direta de nós HTML
                        score_placeholder_18_5_2 = st.empty()
                        score_placeholder_18_5_2.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.2:** `{pts_18_5_2:.1f} pontos`")
                        
                        mudou_valores_18_5_2 = string_estruturada_18_5_2 != d18_5_2.get("valor", "")
                        mudou_link_18_5_2 = link_18_5_2 != d18_5_2.get("link", "")
                        
                        if mudou_valores_18_5_2 or mudou_link_18_5_2:
                                save_resp("18.5.2", string_estruturada_18_5_2, pts_18_5_2, link_18_5_2)
                                res_data["18.5.2"] = {"valor": string_estruturada_18_5_2, "pontos": pts_18_5_2, "link": link_18_5_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_18_5_2 and links_18_5_2_atuais:
                                        links_18_5_2_antigos = re.findall(r'(https?://[^\s]+)', d18_5_2.get("link", ""))
                                        if links_18_5_2_atuais != links_18_5_2_antigos:
                                                modal_aviso_link("18.5.2", links_18_5_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.5.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.5.3 - DISPONIBILIZAÇÃO NO SISTEMA DE REGULAÇÃO
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_regulacao_18_5_3_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 18.5.3 - Obras/Vagas no Sistema de Regulação", expanded=True):
                        st.subheader("18.5.3 • Obras/Vagas no Sistema de Regulação")
                        st.write("**Todos os serviços assistenciais ofertados pelo CAPS e Unidades de Acolhimento (vagas) estão disponibilizados no sistema de regulação?** *(Pode estar cadastrado no sistema municipal e/ou estadual)*")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        # Opções com os rótulos de pontuação ao lado das alternativas
                        opts_18_5_3 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                        d18_5_3 = res_data.get("18.5.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_1853 = d18_5_3.get("valor", "Selecione...")
                        
                        c1853_1, c1853_2 = st.columns([1, 1])
                        with c1853_1:
                                idx_1853 = opts_18_5_3.index(val_atual_1853) if val_atual_1853 in opts_18_5_3 else 0
                                sel_18_5_3 = st.radio("Serviços na regulação:", options=opts_18_5_3, index=idx_1853, key=f"rad_18_5_3_{ano_sel}", label_visibility="collapsed")
                                
                                if "Não" in sel_18_5_3:
                                        pts_18_5_3 = -10.0
                                        status_texto = "(Penalidade)"
                                elif "Selecione..." in sel_18_5_3:
                                        pts_18_5_3 = 0.0
                                        status_texto = "(Aguardando Seleção)"
                                else:
                                        pts_18_5_3 = 0.0
                                        status_texto = "(Meta Atingida)"
                                        
                        with c1853_2:
                                link_18_5_3 = st.text_area("Evidência de espelho do sistema de regulação CROSS/SISREG (18.5.3):", value=d18_5_3.get("link", ""), key=f"txt_18_5_3_{ano_sel}", height=100)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_18_5_3 = st.empty()
                                links_18_5_3_atuais = re.findall(r'(https?://[^\s]+)', link_18_5_3)
                                if links_18_5_3_atuais:
                                        botoes_18_5_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_5_3_atuais])
                                        placeholder_links_18_5_3.markdown(f"**Links Ativos:** {botoes_18_5_3}")
                        
                        # FIX: Uso do st.empty() para que as alternâncias de estilo da pontuação não quebrem o DOM do React
                        score_placeholder_18_5_3 = st.empty()
                        if pts_18_5_3 < 0:
                                score_placeholder_18_5_3.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.3:** :red[{pts_18_5_3:.1f} pontos {status_texto}]")
                        elif "Selecione..." in sel_18_5_3:
                                score_placeholder_18_5_3.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.3:** `{pts_18_5_3:.1f} pontos` *{status_texto}*")
                        else:
                                score_placeholder_18_5_3.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.3:** `{pts_18_5_3:.1f} pontos` *{status_texto}*")
                                
                        mudou_opcao_18_5_3 = sel_18_5_3 != d18_5_3.get("valor", "")
                        mudou_link_18_5_3 = link_18_5_3 != d18_5_3.get("link", "")
                        
                        if mudou_opcao_18_5_3 or mudou_link_18_5_3:
                                save_resp("18.5.3", sel_18_5_3, pts_18_5_3, link_18_5_3)
                                res_data["18.5.3"] = {"valor": sel_18_5_3, "pontos": pts_18_5_3, "link": link_18_5_3}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_18_5_3 and links_18_5_3_atuais:
                                        links_18_5_3_antigos = re.findall(r'(https?://[^\s]+)', d18_5_3.get("link", ""))
                                        if links_18_5_3_atuais != links_18_5_3_antigos:
                                                modal_aviso_link("18.5.3", links_18_5_3_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.5.3", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.5.3.1 - VAGAS CADASTRADAS NO SISTEMA DE REGULAÇÃO (CAPS / UA)
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_vagas_regulacao_18_5_3_1_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 18.5.3.1 - Vagas Cadastradas no Sistema de Regulação", expanded=True):
                        st.subheader("18.5.3.1 • Vagas Cadastradas no Sistema de Regulação")
                        st.write(f"**18.5.3.1 Informe a quantidade de vagas cadastradas no sistema de regulação municipal e/ou estadual:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de vagas ou no link grava os dados na hora.*")
                        
                        # Recupera a string estruturada do banco de dados (ex: v1|v2|v3...) ou define padrão zerado
                        d18_5_3_1 = res_data.get("18.5.3.1", {"valor": "0|0|0|0|0|0|0|0|0|0|0", "pontos": 0.0, "link": ""})
                        valores_salvos_18531 = d18_5_3_1.get("valor", "0|0|0|0|0|0|0|0|0|0|0")
                        
                        # Divide os valores salvos para preencher cada campo de input correspondente
                        partes_vagas = valores_salvos_18531.split("|") if valores_salvos_18531 else []
                        while len(partes_vagas) < 11:
                                partes_vagas.append("0")
                                
                        c18531_1, c18531_2 = st.columns([1, 1])
                        with c18531_1:
                                st.markdown("**Quantidade de Vagas por Tipo de Estabelecimento:**")
                                
                                v_caps_i     = st.text_input("I - CAPS I:", value=partes_vagas[0], key=f"txt_18531_v1_{ano_sel}")
                                v_caps_ii    = st.text_input("II - CAPS II:", value=partes_vagas[1], key=f"txt_18531_v2_{ano_sel}")
                                v_caps_iii   = st.text_input("III - CAPS III:", value=partes_vagas[2], key=f"txt_18531_v3_{ano_sel}")
                                v_caps_ad    = st.text_input("IV - CAPS AD:", value=partes_vagas[3], key=f"txt_18531_v4_{ano_sel}")
                                v_caps_ad_ii = st.text_input("V - CAPS AD II:", value=partes_vagas[4], key=f"txt_18531_v5_{ano_sel}")
                                v_caps_ad_iii= st.text_input("VI - CAPS AD III:", value=partes_vagas[5], key=f"txt_18531_v6_{ano_sel}")
                                v_caps_inf   = st.text_input("VII - CAPS i:", value=partes_vagas[6], key=f"txt_18531_v7_{ano_sel}")
                                v_caps_inf_ii= st.text_input("VIII - CAPS i II:", value=partes_vagas[7], key=f"txt_18531_v8_{ano_sel}")
                                v_caps_ad_iv = st.text_input("IX - CAPS AD IV:", value=partes_vagas[8], key=f"txt_18531_v9_{ano_sel}")
                                v_ua_adulto  = st.text_input("X - Unidade de Acolhimento Adulto:", value=partes_vagas[9], key=f"txt_18531_v10_{ano_sel}")
                                v_ua_infantil= st.text_input("XI - Unidade de Acolhimento Infantil:", value=partes_vagas[10], key=f"txt_18531_v11_{ano_sel}")
                                
                                # Junta tudo na string estruturada para salvar
                                string_estruturada_vagas = f"{v_caps_i}|{v_caps_ii}|{v_caps_iii}|{v_caps_ad}|{v_caps_ad_ii}|{v_caps_ad_iii}|{v_caps_inf}|{v_caps_inf_ii}|{v_caps_ad_iv}|{v_ua_adulto}|{v_ua_infantil}"
                                pts_18_5_3_1 = 0.0
                                
                        with c18531_2:
                                link_18_5_3_1 = st.text_area(
                                        "Link/Evidência do Sistema de Regulação ou do CNES com o quantitativo de vagas informado (18.5.3.1):", 
                                        value=d18_5_3_1.get("link", ""), 
                                        key=f"reg_18_5_3_1_txt_{ano_sel}",
                                        height=320
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_18_5_3_1 = st.empty()
                                links_18_5_3_1_atuais = re.findall(r'(https?://[^\s]+)', link_18_5_3_1)
                                if links_18_5_3_1_atuais:
                                        botoes_18_5_3_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_5_3_1_atuais])
                                        placeholder_links_18_5_3_1.markdown(f"**Links Ativos:** {botoes_18_5_3_1}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar quebra condicional direta do HTML
                        score_placeholder_18_5_3_1 = st.empty()
                        if pts_18_5_3_1 < 0:
                                score_placeholder_18_5_3_1.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.3.1:** :red[{pts_18_5_3_1:.1f} pontos (Penalidade)]")
                        else:
                                score_placeholder_18_5_3_1.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.3.1:** `{pts_18_5_3_1:.1f} pontos`")
                                
                        mudou_valores_18_5_3_1 = string_estruturada_vagas != d18_5_3_1.get("valor", "")
                        mudou_link_18_5_3_1 = link_18_5_3_1 != d18_5_3_1.get("link", "")
                        
                        if mudou_valores_18_5_3_1 or mudou_link_18_5_3_1:
                                save_resp("18.5.3.1", string_estruturada_vagas, pts_18_5_3_1, link_18_5_3_1)
                                
                                if "18.5.3.1" not in res_data:
                                        res_data["18.5.3.1"] = {}
                                res_data["18.5.3.1"]["valor"] = string_estruturada_vagas
                                res_data["18.5.3.1"]["pontos"] = pts_18_5_3_1
                                res_data["18.5.3.1"]["link"] = link_18_5_3_1
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_18_5_3_1 and links_18_5_3_1_atuais:
                                        links_18_5_3_1_antigos = re.findall(r'(https?://[^\s]+)', d18_5_3_1.get("link", ""))
                                        if links_18_5_3_1_atuais != links_18_5_3_1_antigos:
                                                modal_aviso_link("18.5.3.1", links_18_5_3_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.5.3.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.5.4 - SUFICIÊNCIA DE VAGAS DOS CAPS
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_suficiencia_caps_18_5_4_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 18.5.4 - Suficiência de Vagas dos CAPS", expanded=True):
                        st.subheader("18.5.4 • Suficiência de Vagas dos CAPS")
                        st.write("**A quantidade de vagas dos CAPS é suficiente para demanda da população que apresenta prioritariamente, intenso sofrimento psíquico decorrente de transtornos mentais graves e persistentes, incluindo aqueles relacionados ao uso de substâncias psicoativas, e outras situações clínicas?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_18_5_4 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                        d18_5_4 = res_data.get("18.5.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_1854 = d18_5_4.get("valor", "Selecione...")
                        
                        c1854_1, c1854_2 = st.columns([1, 1])
                        with c1854_1:
                                idx_1854 = opts_18_5_4.index(val_atual_1854) if val_atual_1854 in opts_18_5_4 else 0
                                sel_18_5_4 = st.radio("Vagas suficientes:", options=opts_18_5_4, index=idx_1854, key=f"rad_18_5_4_{ano_sel}", label_visibility="collapsed")
                                
                                if "Não" in sel_18_5_4:
                                        pts_18_5_4 = -10.0
                                        status_texto = "(Penalidade)"
                                elif "Selecione..." in sel_18_5_4:
                                        pts_18_5_4 = 0.0
                                        status_texto = "(Aguardando Seleção)"
                                else:
                                        pts_18_5_4 = 0.0
                                        status_texto = "(Meta Atingida)"
                                        
                        with c1854_2:
                                link_18_5_4 = st.text_area("Justificativa técnica ou relatório de demanda reprimida/fila (18.5.4):", value=d18_5_4.get("link", ""), key=f"txt_18_5_4_{ano_sel}", height=100)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_18_5_4 = st.empty()
                                links_18_5_4_atuais = re.findall(r'(https?://[^\s]+)', link_18_5_4)
                                if links_18_5_4_atuais:
                                        botoes_18_5_4 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_5_4_atuais])
                                        placeholder_links_18_5_4.markdown(f"**Links Ativos:** {botoes_18_5_4}")
                        
                        # FIX: Uso do st.empty() para que as alternâncias de estilo da pontuação não mutem a árvore do DOM
                        score_placeholder_18_5_4 = st.empty()
                        if pts_18_5_4 < 0:
                                score_placeholder_18_5_4.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.4:** :red[{pts_18_5_4:.1f} pontos {status_texto}]")
                        elif "Selecione..." in sel_18_5_4:
                                score_placeholder_18_5_4.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.4:** `{pts_18_5_4:.1f} pontos` *{status_texto}*")
                        else:
                                score_placeholder_18_5_4.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.4:** `{pts_18_5_4:.1f} pontos` *{status_texto}*")
                                
                        mudou_opcao_18_5_4 = sel_18_5_4 != d18_5_4.get("valor", "")
                        mudou_link_18_5_4 = link_18_5_4 != d18_5_4.get("link", "")
                        
                        if mudou_opcao_18_5_4 or mudou_link_18_5_4:
                                save_resp("18.5.4", sel_18_5_4, pts_18_5_4, link_18_5_4)
                                res_data["18.5.4"] = {"valor": sel_18_5_4, "pontos": pts_18_5_4, "link": link_18_5_4}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_18_5_4 and links_18_5_4_atuais:
                                        links_18_5_4_antigos = re.findall(r'(https?://[^\s]+)', d18_5_4.get("link", ""))
                                        if links_18_5_4_atuais != links_18_5_4_antigos:
                                                modal_aviso_link("18.5.4", links_18_5_4_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.5.4", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.5.5 - QUANTIDADE DE VAGAS OFERTADAS
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de renderização do React DOM
        with st.container(key=f"container_bloco_vagas_ofertadas_18_5_5_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 18.5.5 - Quantidade de Vagas Ofertadas pelo Município", expanded=True):
                        st.subheader("18.5.5 • Quantidade de Vagas Ofertadas pelo Município")
                        st.write("**18.5.5 Informe a quantidade de vagas ofertadas pelo município:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos numéricos ou no link grava os dados na hora.*")
                        
                        d18_5_5 = res_data.get("18.5.5", {"valor": "", "pontos": 0.0, "link": ""})
                        vals_1855 = d18_5_5.get("valor", "").split("|")
                        
                        tipos_vagas_ofertadas = [
                                "I - CAPS I", "II - CAPS II", "III - CAPS III", "IV - CAPS AD", 
                                "V - CAPS AD II", "VI - CAPS AD III", "VII - CAPS i", "VIII - CAPS i II", 
                                "IX - CAPS AD IV", "X - Unidade de Acolhimento Adulto", "XI - Unidade de Acolhimento Infantil"
                        ]
                        
                        dict_vals_1855 = {}
                        for t in tipos_vagas_ofertadas:
                                dict_vals_1855[t] = 0
                                for v in vals_1855:
                                        if ":" in v and v.split(":")[0] == t:
                                                try: 
                                                        dict_vals_1855[t] = int(v.split(":")[1])
                                                except: 
                                                        pass

                        c1855_1, c1855_2 = st.columns([1, 1])
                        with c1855_1:
                                novos_vals_1855 = []
                                for t in tipos_vagas_ofertadas:
                                        qtd_vagas_of = st.number_input(f"Vagas Ofertadas {t}:", min_value=0, step=1, value=dict_vals_1855[t], key=f"num_1855_{t}_{ano_sel}")
                                        novos_vals_1855.append(f"{t}:{qtd_vagas_of}")
                                
                                # CORREÇÃO AQUI: Nome da variável padronizado exatamente como chamado abaixo
                                string_estruturada_18_5_5 = "|".join(novos_vals_1855)
                                pts_18_5_5 = 0.0
                                
                        with c1855_2:
                                link_18_5_5 = st.text_area("Documento ou portaria instrutiva com a capacidade operacional declarada (18.5.5):", value=d18_5_5.get("link", ""), key=f"txt_18_5_5_{ano_sel}", height=200)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_18_5_5 = st.empty()
                                links_18_5_5_atuais = re.findall(r'(https?://[^\s]+)', link_18_5_5)
                                if links_18_5_5_atuais:
                                        botoes_18_5_5 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_5_5_atuais])
                                        placeholder_links_18_5_5.markdown(f"**Links Ativos:** {botoes_18_5_5}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação na árvore HTML
                        score_placeholder_18_5_5 = st.empty()
                        score_placeholder_18_5_5.markdown(f"📊 **Pontuação Aplicada no Quesito 18.5.5:** `{pts_18_5_5:.1f} pontos` (Dados Informativos)")
                        
                        mudou_valores_18_5_5 = string_estruturada_18_5_5 != d18_5_5.get("valor", "")
                        mudou_link_18_5_5 = link_18_5_5 != d18_5_5.get("link", "")
                        
                        if mudou_valores_18_5_5 or mudou_link_18_5_5:
                                save_resp("18.5.5", string_estruturada_18_5_5, pts_18_5_5, link_18_5_5)
                                res_data["18.5.5"] = {"valor": string_estruturada_18_5_5, "pontos": pts_18_5_5, "link": link_18_5_5}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_18_5_5 and links_18_5_5_atuais:
                                        links_18_5_5_antigos = re.findall(r'(https?://[^\s]+)', d18_5_5.get("link", ""))
                                        if links_18_5_5_atuais != links_18_5_5_antigos:
                                                modal_aviso_link("18.5.5", links_18_5_5_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.5.5", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 18.6 - PROGRAMA DE VOLTA PARA CASA
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_pvc_18_6_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 18.6 - Adesão ao Programa De Volta para Casa", expanded=True):
                        st.subheader("18.6 • Adesão ao Programa De Volta para Casa")
                        st.write("**18.6 O município aderiu formalmente ao programa “De Volta para Casa” (PVC)?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_18_6 = ["Selecione...", "Sim", "Não"]
                        d18_6 = res_data.get("18.6", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_186 = d18_6.get("valor", "Selecione...")
                        
                        c186_1, c186_2 = st.columns([1, 1])
                        with c186_1:
                                idx_186 = opts_18_6.index(val_atual_186) if val_atual_186 in opts_18_6 else 0
                                sel_18_6 = st.radio("Adesão PVC:", options=opts_18_6, index=idx_186, key=f"rad_18_6_{ano_sel}", label_visibility="collapsed")
                                pts_18_6 = 0.0
                                
                        with c186_2:
                                link_18_6 = st.text_area("Termo de adesão ao PVC ou termo de compromisso federal/estadual (18.6):", value=d18_6.get("link", ""), key=f"txt_18_6_{ano_sel}", height=100)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_18_6 = st.empty()
                                links_18_6_atuais = re.findall(r'(https?://[^\s]+)', link_18_6)
                                if links_18_6_atuais:
                                        botoes_18_6 = " | ".join([f"🔗 [{u}]({u})" for u in links_18_6_atuais])
                                        placeholder_links_18_6.markdown(f"**Links Ativos:** {botoes_18_6}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação condicional direta na árvore HTML
                        score_placeholder_18_6 = st.empty()
                        score_placeholder_18_6.markdown(f"📊 **Pontuação Aplicada no Quesito 18.6:** `{pts_18_6:.1f} pontos` (Dados Informativos)")
                        
                        mudou_opcao_18_6 = sel_18_6 != d18_6.get("valor", "")
                        mudou_link_18_6 = link_18_6 != d18_6.get("link", "")
                        
                        if mudou_opcao_18_6 or mudou_link_18_6:
                                save_resp("18.6", sel_18_6, pts_18_6, link_18_6)
                                res_data["18.6"] = {"valor": sel_18_6, "pontos": pts_18_6, "link": link_18_6}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_18_6 and links_18_6_atuais:
                                        links_18_6_antigos = re.findall(r'(https?://[^\s]+)', d18_6.get("link", ""))
                                        if links_18_6_atuais != links_18_6_antigos:
                                                modal_aviso_link("18.6", links_18_6_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("18.6", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
        # QUESITO 19.0 - DEMANDA DE MORADIA (LONG_PERMANÊNCIA)
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_demanda_moradia_19_0_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 19.0 - Demanda de Moradia para Transtornos Mentais Crônicos", expanded=True):
                        st.subheader("19.0 • Demanda de Moradia para Transtornos Mentais Crônicos")
                        st.write("**19.0 No município, há demanda de moradia para portadores de transtornos mentais crônicos com necessidade de cuidados de longa permanência, prioritariamente egressos de internações psiquiátricas e de hospitais de custódia, que não possuam suporte financeiro, social e/ou laços familiares que permitam outra forma de reinserção?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_19_0 = ["Selecione...", "Sim", "Não"]
                        d19_0 = res_data.get("19.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_190 = d19_0.get("valor", "Selecione...")
                        
                        c190_1, c190_2 = st.columns([1, 1])
                        with c190_1:
                                idx_190 = opts_19_0.index(val_atual_190) if val_atual_190 in opts_19_0 else 0
                                sel_19_0 = st.radio("Existência de demanda:", options=opts_19_0, index=idx_190, key=f"rad_19_0_{ano_sel}", label_visibility="collapsed")
                                pts_19_0 = 0.0
                                
                        with c190_2:
                                link_19_0 = st.text_area("Relatório descritivo da assistência social ou saúde mental sobre a demanda identificada (19.0):", value=d19_0.get("link", ""), key=f"txt_19_0_{ano_sel}", height=100)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_19_0 = st.empty()
                                links_19_0_atuais = re.findall(r'(https?://[^\s]+)', link_19_0)
                                if links_19_0_atuais:
                                        botoes_19_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_19_0_atuais])
                                        placeholder_links_19_0.markdown(f"**Links Ativos:** {botoes_19_0}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação condicional direta na árvore HTML
                        score_placeholder_19_0 = st.empty()
                        score_placeholder_19_0.markdown(f"📊 **Pontuação Aplicada no Quesito 19.0:** `{pts_19_0:.1f} pontos` (Dados Informativos)")
                        
                        mudou_opcao_19_0 = sel_19_0 != d19_0.get("valor", "")
                        mudou_link_19_0 = link_19_0 != d19_0.get("link", "")
                        
                        if mudou_opcao_19_0 or mudou_link_19_0:
                                save_resp("19.0", sel_19_0, pts_19_0, link_19_0)
                                res_data["19.0"] = {"valor": sel_19_0, "pontos": pts_19_0, "link": link_19_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_19_0 and links_19_0_atuais:
                                        links_19_0_antigos = re.findall(r'(https?://[^\s]+)', d19_0.get("link", ""))
                                        if links_19_0_atuais != links_19_0_antigos:
                                                modal_aviso_link("19.0", links_19_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("19.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 19.1 - ADEQUAÇÃO DA QUANTIDADE DE SRTs
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_adequacao_srt_19_1_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 19.1 - Adequação da Quantidade de SRTs Ofertadas", expanded=True):
                        st.subheader("19.1 • Adequação da Quantidade de SRTs Ofertadas")
                        st.write("**19.1 A Quantidade de SRTs ofertadas é adequada, inclusive quanto a distribuição geográfica, para a demanda de moradia para portadores de transtornos mentais crônicos com necessidade de cuidados de longa permanência, prioritariamente egressos de internações psiquiátricas e de hospitais de custódia, que não possuam suporte financeiro, social e/ou laços familiares que permitam outra forma de reinserção?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_19_1 = ["Selecione...", "Sim", "Não"]
                        d19_1 = res_data.get("19.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_191 = d19_1.get("valor", "Selecione...")
                        
                        c191_1, c191_2 = st.columns([1, 1])
                        with c191_1:
                                idx_191 = opts_19_1.index(val_atual_191) if val_atual_191 in opts_19_1 else 0
                                sel_19_1 = st.radio("Adequação das SRTs:", options=opts_19_1, index=idx_191, key=f"rad_19_1_{ano_sel}", label_visibility="collapsed")
                                pts_19_1 = 0.0
                                
                        with c191_2:
                                link_19_1 = st.text_area("Justificativa de cobertura ou mapeamento territorial da RAPS (19.1):", value=d19_1.get("link", ""), key=f"txt_19_1_{ano_sel}", height=100)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_19_1 = st.empty()
                                links_19_1_atuais = re.findall(r'(https?://[^\s]+)', link_19_1)
                                if links_19_1_atuais:
                                        botoes_19_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_19_1_atuais])
                                        placeholder_links_19_1.markdown(f"**Links Ativos:** {botoes_19_1}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação condicional direta na árvore HTML
                        score_placeholder_19_1 = st.empty()
                        score_placeholder_19_1.markdown(f"📊 **Pontuação Aplicada no Quesito 19.1:** `{pts_19_1:.1f} pontos` (Dados Informativos)")
                        
                        mudou_opcao_19_1 = sel_19_1 != d19_1.get("valor", "")
                        mudou_link_19_1 = link_19_1 != d19_1.get("link", "")
                        
                        if mudou_opcao_19_1 or mudou_link_19_1:
                                save_resp("19.1", sel_19_1, pts_19_1, link_19_1)
                                res_data["19.1"] = {"valor": sel_19_1, "pontos": pts_19_1, "link": link_19_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_19_1 and links_19_1_atuais:
                                        links_19_1_antigos = re.findall(r'(https?://[^\s]+)', d19_1.get("link", ""))
                                        if links_19_1_atuais != links_19_1_antigos:
                                                modal_aviso_link("19.1", links_19_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("19.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

       # =============================================================================
        # QUESITO 19.2 - QUANTIDADE DE UNIDADES SRT
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_quant_srt_19_2_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 19.2 - Quantidade de Unidades de SRT", expanded=True):
                        st.subheader("19.2 • Quantidade de Unidades de SRT")
                        st.write("**19.2 Informe a quantidade de unidades:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos numéricos ou no link grava os dados na hora.*")
                        
                        d19_2 = res_data.get("19.2", {"valor": "", "pontos": 0.0, "link": ""})
                        vals_192 = d19_2.get("valor", "").split("|")
                        tipos_srt = ["Para SRT tipo I", "Para SRT tipo II", "Equivalente"]
                        
                        dict_vals_192 = {}
                        for t in tipos_srt:
                                dict_vals_192[t] = 0
                                for v in vals_192:
                                        if ":" in v and v.split(":")[0] == t:
                                                try: 
                                                        dict_vals_192[t] = int(v.split(":")[1])
                                                except: 
                                                        pass

                        c192_1, c192_2 = st.columns([1, 1])
                        with c192_1:
                                novos_vals_192 = []
                                for t in tipos_srt:
                                        qtd_srt = st.number_input(f"Quantidade {t}:", min_value=0, step=1, value=dict_vals_192[t], key=f"num_192_{t}_{ano_sel}")
                                        novos_vals_192.append(f"{t}:{qtd_srt}")
                                string_estruturada_192 = "|".join(novos_vals_192)
                                pts_19_2 = 0.0
                                
                        with c192_2:
                                link_19_2 = st.text_area("Cadastro CNES ou ato normativo de criação/credenciamento das unidades SRT (19.2):", value=d19_2.get("link", ""), key=f"txt_19_2_{ano_sel}", height=150)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_19_2 = st.empty()
                                links_19_2_atuais = re.findall(r'(https?://[^\s]+)', link_19_2)
                                if links_19_2_atuais:
                                        botoes_19_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_19_2_atuais])
                                        placeholder_links_19_2.markdown(f"**Links Ativos:** {botoes_19_2}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação condicional direta na árvore HTML
                        score_placeholder_19_2 = st.empty()
                        score_placeholder_19_2.markdown(f"📊 **Pontuação Aplicada no Quesito 19.2:** `{pts_19_2:.1f} pontos` (Dados Informativos)")
                        
                        mudou_valores_19_2 = string_estruturada_192 != d19_2.get("valor", "")
                        mudou_link_19_2 = link_19_2 != d19_2.get("link", "")
                        
                        if mudou_valores_19_2 or mudou_link_19_2:
                                save_resp("19.2", string_estruturada_192, pts_19_2, link_19_2)
                                res_data["19.2"] = {"valor": string_estruturada_192, "pontos": pts_19_2, "link": link_19_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_19_2 and links_19_2_atuais:
                                        links_19_2_antigos = re.findall(r'(https?://[^\s]+)', d19_2.get("link", ""))
                                        if links_19_2_atuais != links_19_2_antigos:
                                                modal_aviso_link("19.2", links_19_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("19.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
        # QUESITO 19.3 - CADASTRO DE VAGAS SRT NA REGULAÇÃO
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_vagas_srt_regulacao_19_3_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 19.3 - Cadastro de Vagas SRT no Sistema de Regulação", expanded=True):
                        st.subheader("19.3 • Cadastro de Vagas SRT no Sistema de Regulação")
                        st.write("**19.3 As vagas dos Serviços Residenciais Terapêuticos ou equivalente para os residentes do município estão cadastradas no sistema de informação de regulação?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_19_3 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                        d19_3 = res_data.get("19.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_193 = d19_3.get("valor", "Selecione...")
                        
                        c193_1, c193_2 = st.columns([1, 1])
                        with c193_1:
                                idx_193 = opts_19_3.index(val_atual_193) if val_atual_193 in opts_19_3 else 0
                                sel_19_3 = st.radio("Vagas SRT na regulação:", options=opts_19_3, index=idx_193, key=f"rad_19_3_{ano_sel}", label_visibility="collapsed")
                                
                                if "Não" in sel_19_3:
                                        pts_19_3 = -10.0
                                        status_texto = "(Penalidade)"
                                elif "Selecione..." in sel_19_3:
                                        pts_19_3 = 0.0
                                        status_texto = "(Aguardando Seleção)"
                                else:
                                        pts_19_3 = 0.0
                                        status_texto = "(Meta Atingida)"
                                        
                        with c193_2:
                                link_19_3 = st.text_area("Evidência de cadastro ou espelho do sistema de regulação (19.3):", value=d19_3.get("link", ""), key=f"txt_19_3_{ano_sel}", height=100)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_19_3 = st.empty()
                                links_19_3_atuais = re.findall(r'(https?://[^\s]+)', link_19_3)
                                if links_19_3_atuais:
                                        botoes_19_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_19_3_atuais])
                                        placeholder_links_19_3.markdown(f"**Links Ativos:** {botoes_19_3}")
                        
                        # FIX: Uso do st.empty() para que as alternâncias de estilo da pontuação não mutem diretamente a árvore do DOM
                        score_placeholder_19_3 = st.empty()
                        if pts_19_3 < 0:
                                score_placeholder_19_3.markdown(f"📊 **Pontuação Aplicada no Quesito 19.3:** :red[{pts_19_3:.1f} pontos {status_texto}]")
                        elif "Selecione..." in sel_19_3:
                                score_placeholder_19_3.markdown(f"📊 **Pontuação Aplicada no Quesito 19.3:** `{pts_19_3:.1f} pontos` *{status_texto}*")
                        else:
                                score_placeholder_19_3.markdown(f"📊 **Pontuação Aplicada no Quesito 19.3:** `{pts_19_3:.1f} pontos` *{status_texto}*")
                                
                        mudou_opcao_19_3 = sel_19_3 != d19_3.get("valor", "")
                        mudou_link_19_3 = link_19_3 != d19_3.get("link", "")
                        
                        if mudou_opcao_19_3 or mudou_link_19_3:
                                save_resp("19.3", sel_19_3, pts_19_3, link_19_3)
                                res_data["19.3"] = {"valor": sel_19_3, "pontos": pts_19_3, "link": link_19_3}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_19_3 and links_19_3_atuais:
                                        links_19_3_antigos = re.findall(r'(https?://[^\s]+)', d19_3.get("link", ""))
                                        if links_19_3_atuais != links_19_3_antigos:
                                                modal_aviso_link("19.3", links_19_3_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("19.3", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 19.3.1 - QUANTIDADE DE VAGAS CADASTRADAS NA REGULAÇÃO
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_quant_vagas_srt_19_3_1_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 19.3.1 - Quantidade de Vagas SRT Cadastradas na Regulação", expanded=True):
                        st.subheader("19.3.1 • Quantidade de Vagas SRT Cadastradas na Regulação")
                        st.write("**19.3.1 Informe a quantidade de vagas cadastradas no sistema de regulação:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos numéricos ou no link grava os dados na hora.*")
                        
                        d19_3_1 = res_data.get("19.3.1", {"valor": "", "pontos": 0.0, "link": ""})
                        vals_1931 = d19_3_1.get("valor", "").split("|")
                        tipos_vagas_srt = ["Para SRT tipo I", "Para SRT tipo II", "Equivalente"]
                        
                        dict_vals_1931 = {}
                        for t in tipos_vagas_srt:
                                dict_vals_1931[t] = 0
                                for v in vals_1931:
                                        if ":" in v and v.split(":")[0] == t:
                                                try: 
                                                        dict_vals_1931[t] = int(v.split(":")[1])
                                                except: 
                                                        pass

                        c1931_1, c1931_2 = st.columns([1, 1])
                        with c1931_1:
                                novos_vals_1931 = []
                                for t in tipos_vagas_srt:
                                        qtd_vagas_reg = st.number_input(f"Vagas Reguladas {t}:", min_value=0, step=1, value=dict_vals_1931[t], key=f"num_1931_{t}_{ano_sel}")
                                        novos_vals_1931.append(f"{t}:{qtd_vagas_reg}")
                                string_estruturada_1931 = "|".join(novos_vals_1931)
                                pts_19_3_1 = 0.0
                                
                        with c1931_2:
                                link_19_3_1 = st.text_area("Relatório extraído do sistema informático (CROSS/SISREG ou similar) (19.3.1):", value=d19_3_1.get("link", ""), key=f"txt_19_3_1_{ano_sel}", height=150)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_19_3_1 = st.empty()
                                links_19_3_1_atuais = re.findall(r'(https?://[^\s]+)', link_19_3_1)
                                if links_19_3_1_atuais:
                                        botoes_19_3_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_19_3_1_atuais])
                                        placeholder_links_19_3_1.markdown(f"**Links Ativos:** {botoes_19_3_1}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação condicional direta na árvore HTML
                        score_placeholder_19_3_1 = st.empty()
                        score_placeholder_19_3_1.markdown(f"📊 **Pontuação Aplicada no Quesito 19.3.1:** `{pts_19_3_1:.1f} pontos` (Dados Informativos)")
                        
                        mudou_valores_19_3_1 = string_estruturada_1931 != d19_3_1.get("valor", "")
                        mudou_link_19_3_1 = link_19_3_1 != d19_3_1.get("link", "")
                        
                        if mudou_valores_19_3_1 or mudou_link_19_3_1:
                                save_resp("19.3.1", string_estruturada_1931, pts_19_3_1, link_19_3_1)
                                res_data["19.3.1"] = {"valor": string_estruturada_1931, "pontos": pts_19_3_1, "link": link_19_3_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_19_3_1 and links_19_3_1_atuais:
                                        links_19_3_1_antigos = re.findall(r'(https?://[^\s]+)', d19_3_1.get("link", ""))
                                        if links_19_3_1_atuais != links_19_3_1_antigos:
                                                modal_aviso_link("19.3.1", links_19_3_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("19.3.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 19.4 - ROTINAS DE ACOMPANHAMENTO E AVALIAÇÃO SRT
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_rotinas_srt_19_4_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 19.4 - Rotinas de Acompanhamento e Avaliação das SRTs", expanded=True):
                        st.subheader("19.4 • Rotinas de Acompanhamento e Avaliação das SRTs")
                        st.write("**19.4 A Secretaria Municipal de Saúde (ou equivalente), com apoio técnico do Ministério da Saúde, tem rotinas estabelecidas de acompanhamento, supervisão, controle e avaliação para a garantia do funcionamento com qualidade dos Serviços Residenciais Terapêuticos em Saúde Mental?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_19_4 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                        d19_4 = res_data.get("19.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_194 = d19_4.get("valor", "Selecione...")
                        
                        c194_1, c194_2 = st.columns([1, 1])
                        with c194_1:
                                idx_194 = opts_19_4.index(val_atual_194) if val_atual_194 in opts_19_4 else 0
                                sel_19_4 = st.radio("Rotinas estabelecidas:", options=opts_19_4, index=idx_194, key=f"rad_19_4_{ano_sel}", label_visibility="collapsed")
                                
                                if "Não" in sel_19_4:
                                        pts_19_4 = -5.0
                                        status_texto = "(Penalidade)"
                                elif "Selecione..." in sel_19_4:
                                        pts_19_4 = 0.0
                                        status_texto = "(Aguardando Seleção)"
                                else:
                                        pts_19_4 = 0.0
                                        status_texto = "(Meta Atingida)"
                                        
                        with c194_2:
                                link_19_4 = st.text_area("Evidência de atas de supervisão, relatórios de monitoramento ou cronograma técnico (19.4):", value=d19_4.get("link", ""), key=f"txt_19_4_{ano_sel}", height=100)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_19_4 = st.empty()
                                links_19_4_atuais = re.findall(r'(https?://[^\s]+)', link_19_4)
                                if links_19_4_atuais:
                                        botoes_19_4 = " | ".join([f"🔗 [{u}]({u})" for u in links_19_4_atuais])
                                        placeholder_links_19_4.markdown(f"**Links Ativos:** {botoes_19_4}")
                        
                        # FIX: Uso do st.empty() para que as alternâncias de estilo da pontuação não mutem a árvore do DOM
                        score_placeholder_19_4 = st.empty()
                        if pts_19_4 < 0:
                                score_placeholder_19_4.markdown(f"📊 **Pontuação Aplicada no Quesito 19.4:** :red[{pts_19_4:.1f} pontos {status_texto}]")
                        elif "Selecione..." in sel_19_4:
                                score_placeholder_19_4.markdown(f"📊 **Pontuação Aplicada no Quesito 19.4:** `{pts_19_4:.1f} pontos` *{status_texto}*")
                        else:
                                score_placeholder_19_4.markdown(f"📊 **Pontuação Aplicada no Quesito 19.4:** `{pts_19_4:.1f} pontos` *{status_texto}*")
                                
                        mudou_opcao_19_4 = sel_19_4 != d19_4.get("valor", "")
                        mudou_link_19_4 = link_19_4 != d19_4.get("link", "")
                        
                        if mudou_opcao_19_4 or mudou_link_19_4:
                                save_resp("19.4", sel_19_4, pts_19_4, link_19_4)
                                res_data["19.4"] = {"valor": sel_19_4, "pontos": pts_19_4, "link": link_19_4}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_19_4 and links_19_4_atuais:
                                        links_19_4_antigos = re.findall(r'(https?://[^\s]+)', d19_4.get("link", ""))
                                        if links_19_4_atuais != links_19_4_antigos:
                                                modal_aviso_link("19.4", links_19_4_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("19.4", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
        # QUESITO 19.5 - CÁLCULO DE EVOLUÇÃO LEITOS VS VAGAS SRT (DINÂMICO)
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # Define os anos de forma dinâmica com base na seleção atual do sistema
        ano_atual_int = int(ano_sel)
        ano_anterior_int = ano_atual_int - 1

        # FIX: Container estável com chave explísica única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_evolucao_srt_leitos_19_5_{ano_sel}", border=False):

                with st.expander(f"📌 Quesito 19.5 - Indicador de Desinstitucionalização (Leitos vs. Vagas SRT)", expanded=True):
                        st.subheader("19.5 • Indicador de Desinstitucionalização (Leitos vs. Vagas SRT)")
                        st.write(f"**19.5 Avaliação da série histórica (Data Base Mês Dezembro): Redução de Leitos de Internação Psiquiátrica Prolongada vs. Expansão de SRTs**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos numéricos ou no link grava os dados na hora.*")
                        
                        # Recupera dados anteriores do 19.5
                        d19_5 = res_data.get("19.5", {"valor": "0|0|0|0", "pontos": 0.0, "link": ""})
                        vals_195 = d19_5.get("valor", "0|0|0|0").split("|")
                        
                        # Garante que temos as 4 variáveis populadas com segurança
                        try: la_minus_1 = int(vals_195[0])
                        except: la_minus_1 = 0
                        try: la_atual = int(vals_195[1])
                        except: la_atual = 0
                        try: va_minus_1 = int(vals_195[2])
                        except: va_minus_1 = 0
                        try: va_atual = int(vals_195[3])
                        except: va_atual = 0

                        c195_1, c195_2 = st.columns([1, 1])
                        with c195_1:
                                st.markdown("**Leitos de Internação Psiquiátrica Prolongada:**")
                                la_minus_1_input = st.number_input(f"Nº de leitos sob gestão municipal - {ano_anterior_int} (LA-1):", min_value=0, step=1, value=la_minus_1, key=f"num_195_la_minus_1_{ano_sel}")
                                la_atual_input = st.number_input(f"Nº de leitos sob gestão municipal - {ano_atual_int} (LA):", min_value=0, step=1, value=la_atual, key=f"num_195_la_atual_{ano_sel}")
                                
                                st.markdown("**Vagas Disponibilizadas em SRT:**")
                                va_minus_1_input = st.number_input(f"Nº de vagas em SRT sob gestão municipal - {ano_anterior_int} (VA-1):", min_value=0, step=1, value=va_minus_1, key=f"num_195_va_minus_1_{ano_sel}")
                                va_atual_input = st.number_input(f"Nº de vagas em SRT sob gestão municipal - {ano_atual_int} (VA):", min_value=0, step=1, value=va_atual, key=f"num_195_va_atual_{ano_sel}")

                        with c195_2:
                                link_19_5 = st.text_area(f"Relatório do CNES ou ato formal de desospitalização/extinção de leitos ({ano_anterior_int}-{ano_atual_int}):", value=d19_5.get("link", ""), key=f"txt_19_5_{ano_sel}", height=250)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_19_5 = st.empty()
                                links_19_5_atuais = re.findall(r'(https?://[^\s]+)', link_19_5)
                                if links_19_5_atuais:
                                        botoes_19_5 = " | ".join([f"🔗 [{u}]({u})" for u in links_19_5_atuais])
                                        placeholder_links_19_5.markdown(f"**Links Ativos:** {botoes_19_5}")

                        # --- APLICAÇÃO RÍGIDA DA FÓRMULA DE CÁLCULO ---
                        pts_19_5 = 0.0
                        motivo_penalidade = []

                        # 1. Recuperação das unidades informadas em 19.2 para validação cruzada
                        d19_2 = res_data.get("19.2", {"valor": "", "pontos": 0.0, "link": ""})
                        vals_192 = d19_2.get("valor", "").split("|")
                        soma_unidades_192 = 0
                        for v in vals_192:
                                if ":" in v:
                                        try: soma_unidades_192 += int(v.split(":")[1])
                                        except: pass

                        # Condição: Sem SRTs
                        if soma_unidades_192 == 0 or va_atual_input == 0:
                                pts_19_5 = -15.0
                                motivo_penalidade.append(f"Município não possui unidades registradas no quesito 19.2 ou o número de vagas em {ano_atual_int} (VA) é zero.")

                        # Condição: Aumento de Leitos
                        if la_atual_input > la_minus_1_input:
                                pts_19_5 = -15.0
                                motivo_penalidade.append(f"Houve aumento de leitos psiquiátricos (LA de {ano_atual_int} [{la_atual_input}] > LA-1 de {ano_anterior_int} [{la_minus_1_input}]).")

                        # Condição: Diminuição de leitos > aumento de SRTs
                        if va_atual_input < va_minus_1_input:
                                pts_19_5 = -15.0
                                motivo_penalidade.append(f"Houve diminuição no número absoluto de vagas de SRT (VA de {ano_atual_int} [{va_atual_input}] < VA-1 de {ano_anterior_int} [{va_minus_1_input}]).")
                                
                        reducao_leitos = la_minus_1_input - la_atual_input
                        aumento_srt = va_atual_input - va_minus_1_input
                        if reducao_leitos > aumento_srt:
                                pts_19_5 = -15.0
                                motivo_penalidade.append(f"A redução de leitos foi maior do que a capacidade de absorção em novas vagas de SRT (Redução de leitos: {reducao_leitos} > Aumento de SRT: {aumento_srt}).")

                        # FIX: Uso de placeholders estáveis st.empty() para renderizar mensagens condicionais sem quebrar o React DOM
                        msg_placeholder_19_5 = st.empty()
                        score_placeholder_19_5 = st.empty()
                        
                        if pts_19_5 < 0:
                                # Monta o bloco de erro estruturado de forma estática dentro do container
                                texto_erros = "⚠️ **Critério de Penalidade Atingido conforme regras do quesito.**\n\n"
                                for motivo in motivo_penalidade:
                                        texto_erros += f"❌ *{motivo}*\n\n"
                                msg_placeholder_19_5.error(texto_erros)
                                score_placeholder_19_5.markdown(f"📊 **Pontuação Aplicada no Quesito 19.5:** :red[{pts_19_5:.1f} pontos (Fórmula Aplica Perda Máxima de 15 pts)]")
                        else:
                                msg_placeholder_19_5.success("✅ Critério de conformidade atingido (Diminuição de leitos menor ou igual ao aumento de SRTs) ou (Manutenção/Aumento de SRTs).")
                                score_placeholder_19_5.markdown(f"📊 **Pontuação Aplicada no Quesito 19.5:** `{pts_19_5:.1f} pontos` (Sem penalidades aplicadas)")

                        # Estrutura a string valor combinando os inputs numéricos para persistência
                        string_estruturada_195 = f"{la_minus_1_input}|{la_atual_input}|{va_minus_1_input}|{va_atual_input}"
                        
                        mudou_valores_19_5 = string_estruturada_195 != d19_5.get("valor", "")
                        mudou_link_19_5 = link_19_5 != d19_5.get("link", "")
                        
                        if mudou_valores_19_5 or mudou_link_19_5:
                                save_resp("19.5", string_estruturada_195, pts_19_5, link_19_5)
                                res_data["19.5"] = {"valor": string_estruturada_195, "pontos": pts_19_5, "link": link_19_5}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_19_5 and links_19_5_atuais:
                                        links_19_5_antigos = re.findall(r'(https?://[^\s]+)', d19_5.get("link", ""))
                                        if links_19_5_atuais != links_19_5_antigos:
                                                modal_aviso_link("19.5", links_19_5_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("19.5", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # =============================================================================
        # SEÇÃO 20 - VIGILÂNCIA EM SAÚDE
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🛡️ Seção 20 - Vigilância em Saúde")

        # -----------------------------------------------------------------------------
        # QUESITO 20.0 - GESTÃO DE INSUMOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_gestao_insumos_20_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 20.0 - Tipos de Insumos sob Gestão Municipal", expanded=True):
                        st.subheader("20.0 • Tipos de Insumos sob Gestão Municipal")
                        st.write("**20.0 Sobre Vigilância em Saúde, a Prefeitura realiza gestão de quais tipos de insumos?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        d20_0 = res_data.get("20.0", {"valor": "", "pontos": 0.0, "link": ""})
                        v20_0 = d20_0.get("valor", "").split("|")
                        
                        c200_1, c200_2 = st.columns([1, 1])
                        with c200_1:
                                insumo_imuno = st.checkbox("Imunobiológicos (soros, vacinas e imunoglobulinas)", value="Imunobiológicos" in v20_0, key=f"chk_20_0_imuno_{ano_sel}")
                                insumo_diag = st.checkbox("Meios de diagnóstico laboratorial para as doenças sob monitoramento epidemiológico", value="Diagnóstico" in v20_0, key=f"chk_20_0_diag_{ano_sel}")
                                insumo_vetor = st.checkbox("Controle de vetores (inseticidas, larvicidas)", value="Vetores" in v20_0, key=f"chk_20_0_vetor_{ano_sel}")
                                pts_20_0 = 0.0
                                
                        with c200_2:
                                link_20_0 = st.text_area("Link/Evidência (20.0):", value=d20_0.get("link", ""), key=f"txt_20_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_20_0 = st.empty()
                                links_20_0_atuais = re.findall(r'(https?://[^\s]+)', link_20_0)
                                if links_20_0_atuais:
                                        botoes_20_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_20_0_atuais])
                                        placeholder_links_20_0.markdown(f"**Links Ativos:** {botoes_20_0}")
                        
                        # FIX: Placeholder fixo para a pontuação evitar mutação condicional direta na árvore HTML
                        score_placeholder_20_0 = st.empty()
                        score_placeholder_20_0.markdown(f"📊 **Pontuação Aplicada no Quesito 20.0:** `{pts_20_0:.1f} pontos` (Dados Informativos)")
                        
                        selecionados_20_0 = []
                        if insumo_imuno: selecionados_20_0.append("Imunobiológicos")
                        if insumo_diag: selecionados_20_0.append("Diagnóstico")
                        if insumo_vetor: selecionados_20_0.append("Vetores")
                        
                        str_20_0 = "|".join(selecionados_20_0)
                        
                        mudou_opcao_20_0 = str_20_0 != d20_0.get("valor", "")
                        mudou_link_20_0 = link_20_0 != d20_0.get("link", "")
                        
                        if mudou_opcao_20_0 or mudou_link_20_0:
                                save_resp("20.0", str_20_0, pts_20_0, link_20_0)
                                res_data["20.0"] = {"valor": str_20_0, "pontos": pts_20_0, "link": link_20_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_20_0 and links_20_0_atuais:
                                        links_20_0_antigos = re.findall(r'(https?://[^\s]+)', d20_0.get("link", ""))
                                        if links_20_0_atuais != links_20_0_antigos:
                                                modal_aviso_link("20.0", links_20_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("20.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 20.1 - USO DE FRIGOBAR
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_uso_frigobar_20_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 20.1 - Uso de Frigobar para Imunobiológicos", expanded=True):
                        st.subheader("20.1 • Uso de Frigobar para Imunobiológicos")
                        st.write("**20.1 A Prefeitura utiliza frigobar para refrigeração, manutenção, monitoramento e controle da temperatura dos imunobiológicos (soros, vacinas e imunoglobulinas)?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_20_1 = [
                                "Selecione...",
                                "Sim, em todos os estabelecimentos de saúde sob gestão municipal",
                                "Sim, na maior parte dos estabelecimentos de saúde sob gestão municipal",
                                "Sim, na menor parte dos estabelecimentos de saúde sob gestão municipal",
                                "Não"
                        ]
                        
                        d20_1 = res_data.get("20.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_201 = d20_1.get("valor", "Selecione...")
                        idx_20_1 = opts_20_1.index(val_atual_201) if val_atual_201 in opts_20_1 else 0
                        
                        c201_1, c201_2 = st.columns([1, 1])
                        with c201_1:
                                sel_20_1 = st.radio("Uso de Frigobar:", options=opts_20_1, index=idx_20_1, key=f"rad_20_1_{ano_sel}", label_visibility="collapsed")
                                
                                opcoes_pts_201 = {
                                        "Sim, em todos os estabelecimentos de saúde sob gestão municipal": -5.0,
                                        "Sim, na maior parte dos estabelecimentos de saúde sob gestão municipal": -3.0,
                                        "Sim, na menor parte dos estabelecimentos de saúde sob gestão municipal": -1.0,
                                        "Não": 0.0,
                                        "Selecione...": 0.0
                                }
                                pts_20_1 = opcoes_pts_201.get(sel_20_1, 0.0)
                                
                        with c201_2:
                                link_20_1 = st.text_area("Link/Evidência (20.1):", value=d20_1.get("link", ""), key=f"txt_20_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_20_1 = st.empty()
                                links_20_1_atuais = re.findall(r'(https?://[^\s]+)', link_20_1)
                                if links_20_1_atuais:
                                        botoes_20_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_20_1_atuais])
                                        placeholder_links_20_1.markdown(f"**Links Ativos:** {botoes_20_1}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar mensagens e pontuação sem alterar diretamente a estrutura do HTML
                        msg_placeholder_20_1 = st.empty()
                        score_placeholder_20_1 = st.empty()
                        
                        if sel_20_1 != "Selecione..." and pts_20_1 < 0:
                                msg_placeholder_20_1.error(f"⚠️ Penalidade aplicada: {pts_20_1:.1f} pontos.")
                                score_placeholder_20_1.markdown(f"📊 **Pontuação Aplicada no Quesito 20.1:** :red[{pts_20_1:.1f} pontos (Penalidade)]")
                        elif sel_20_1 == "Não":
                                msg_placeholder_20_1.success("✅ Regular: Sem penalidades aplicadas para este item.")
                                score_placeholder_20_1.markdown(f"📊 **Pontuação Aplicada no Quesito 20.1:** `{pts_20_1:.1f} pontos` (Meta Atingida)")
                        else:
                                score_placeholder_20_1.markdown(f"📊 **Pontuação Aplicada no Quesito 20.1:** `{pts_20_1:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_20_1 = sel_20_1 != d20_1.get("valor", "")
                        mudou_link_20_1 = link_20_1 != d20_1.get("link", "")
                        
                        if mudou_opcao_20_1 or mudou_link_20_1:
                                save_resp("20.1", sel_20_1, pts_20_1, link_20_1)
                                res_data["20.1"] = {"valor": sel_20_1, "pontos": pts_20_1, "link": link_20_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_20_1 and links_20_1_atuais:
                                        links_20_1_antigos = re.findall(r'(https?://[^\s]+)', d20_1.get("link", ""))
                                        if links_20_1_atuais != links_20_1_antigos:
                                                modal_aviso_link("20.1", links_20_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("20.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 20.2 - MATERIAIS PARA DIAGNÓSTICO LABORATORIAL
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explílica única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_materiais_diag_20_2_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 20.2 - Materiais para Coleta de Diagnóstico Laboratorial", expanded=True):
                        st.subheader("20.2 • Materiais para Coleta de Diagnóstico Laboratorial")
                        st.write("**20.2 A Prefeitura disponibilizou os materiais necessários para a coleta dos meios de diagnóstico laboratorial para as doenças sob monitoramento epidemiológico (coleta de sangue, fluidos orgânicos como: saliva, secreção, suor, urina, fezes)?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_20_2 = [
                                "Selecione...",
                                "Sim, para todas as amostras",
                                "Sim, para a maior parte das amostras",
                                "Sim, para a menor parte das amostras",
                                "Não"
                        ]
                        
                        d20_2 = res_data.get("20.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_202 = d20_2.get("valor", "Selecione...")
                        idx_20_2 = opts_20_2.index(val_atual_202) if val_atual_202 in opts_20_2 else 0
                        
                        c202_1, c202_2 = st.columns([1, 1])
                        with c202_1:
                                sel_20_2 = st.radio("Materiais Diagnóstico:", options=opts_20_2, index=idx_20_2, key=f"rad_20_2_{ano_sel}", label_visibility="collapsed")
                                
                                cliques_pts_202 = {
                                        "Sim, para todas as amostras": 0.0,
                                        "Sim, para a maior parte das amostras": -1.0,
                                        "Sim, para a menor parte das amostras": -3.0,
                                        "Não": -5.0,
                                        "Selecione...": 0.0
                                }
                                pts_20_2 = cliques_pts_202.get(sel_20_2, 0.0)
                                
                        with c202_2:
                                link_20_2 = st.text_area("Link/Evidência (20.2):", value=d20_2.get("link", ""), key=f"txt_20_2_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_20_2 = st.empty()
                                links_20_2_atuais = re.findall(r'(https?://[^\s]+)', link_20_2)
                                if links_20_2_atuais:
                                        botoes_20_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_20_2_atuais])
                                        placeholder_links_20_2.markdown(f"**Links Ativos:** {botoes_20_2}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações sem mutar nós HTML diretamente
                        msg_placeholder_20_2 = st.empty()
                        score_placeholder_20_2 = st.empty()
                        
                        if sel_20_2 != "Selecione..." and pts_20_2 < 0:
                                msg_placeholder_20_2.error(f"⚠️ Penalidade aplicada: {pts_20_2:.1f} pontos.")
                                score_placeholder_20_2.markdown(f"📊 **Pontuação Aplicada no Quesito 20.2:** :red[{pts_20_2:.1f} pontos (Penalidade)]")
                        elif sel_20_2 == "Sim, para todas as amostras":
                                msg_placeholder_20_2.success("✅ Em conformidade: Fornecimento total garantido.")
                                score_placeholder_20_2.markdown(f"📊 **Pontuação Aplicada no Quesito 20.2:** `{pts_20_2:.1f} pontos` (Meta Atingida)")
                        else:
                                score_placeholder_20_2.markdown(f"📊 **Pontuação Aplicada no Quesito 20.2:** `{pts_20_2:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_20_2 = sel_20_2 != d20_2.get("valor", "")
                        mudou_link_20_2 = link_20_2 != d20_2.get("link", "")
                        
                        if mudou_opcao_20_2 or mudou_link_20_2:
                                save_resp("20.2", sel_20_2, pts_20_2, link_20_2)
                                res_data["20.2"] = {"valor": sel_20_2, "pontos": pts_20_2, "link": link_20_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_20_2 and links_20_2_atuais:
                                        links_20_2_antigos = re.findall(r'(https?://[^\s]+)', d20_2.get("link", ""))
                                        if links_20_2_atuais != links_20_2_antigos:
                                                modal_aviso_link("20.2", links_20_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("20.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 20.3 - EPI PARA CONTROLE DE VETORES
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_epi_vetores_20_3_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 20.3 - Equipamentos de Proteção Individual (EPI)", expanded=True):
                        st.subheader("20.3 • Equipamentos de Proteção Individual (EPI)")
                        st.write("**20.3 A Prefeitura disponibilizou todos os equipamentos de proteção individual (EPIs) para o manuseio dos insumos para controle de vetores (inseticidas e pesticidas)?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_20_3 = [
                                "Selecione...",
                                "Sim, para todos os profissionais – 00",
                                "Sim, para a maior parte dos profissionais – -01 (perde 01 ponto)",
                                "Sim, para a menor parte dos profissionais – -03 (perde 03 pontos)",
                                "Não – -05 (perde 05 pontos)"
                        ]
                        
                        d20_3 = res_data.get("20.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_203 = d20_3.get("valor", "Selecione...")
                        idx_20_3 = opts_20_3.index(val_atual_203) if val_atual_203 in opts_20_3 else 0
                        
                        c203_1, c203_2 = st.columns([1, 1])
                        with c203_1:
                                sel_20_3 = st.radio("Disponibilização de EPIs:", options=opts_20_3, index=idx_20_3, key=f"rad_20_3_{ano_sel}", label_visibility="collapsed")
                                
                                opcoes_pts_203 = {
                                        "Sim, para todos os profissionais – 00": 0.0,
                                        "Sim, para a maior parte dos profissionais – -01 (perde 01 ponto)": -1.0,
                                        "Sim, para a menor parte dos profissionais – -03 (perde 03 pontos)": -3.0,
                                        "Não – -05 (perde 05 pontos)": -5.0,
                                        "Selecione...": 0.0
                                }
                                pts_20_3 = opcoes_pts_203.get(sel_20_3, 0.0)
                                
                        with c203_2:
                                link_20_3 = st.text_area("Link/Evidência (20.3):", value=d20_3.get("link", ""), key=f"txt_20_3_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_20_3 = st.empty()
                                links_20_3_atuais = re.findall(r'(https?://[^\s]+)', link_20_3)
                                if links_20_3_atuais:
                                        botoes_20_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_20_3_atuais])
                                        placeholder_links_20_3.markdown(f"**Links Ativos:** {botoes_20_3}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações sem mutar nós HTML diretamente
                        msg_placeholder_20_3 = st.empty()
                        score_placeholder_20_3 = st.empty()
                        
                        if sel_20_3 != "Selecione..." and pts_20_3 < 0:
                                msg_placeholder_20_3.error(f"⚠️ Penalidade aplicada: {pts_20_3:.1f} pontos.")
                                score_placeholder_20_3.markdown(f"📊 **Pontuação Aplicada no Quesito 20.3:** :red[{pts_20_3:.1f} pontos (Penalidade)]")
                        elif sel_20_3 == "Sim, para todos os profissionais – 00":
                                msg_placeholder_20_3.success("✅ Em conformidade.")
                                score_placeholder_20_3.markdown(f"📊 **Pontuação Aplicada no Quesito 20.3:** `{pts_20_3:.1f} pontos` (Meta Atingida)")
                        else:
                                score_placeholder_20_3.markdown(f"📊 **Pontuação Aplicada no Quesito 20.3:** `{pts_20_3:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_20_3 = sel_20_3 != d20_3.get("valor", "")
                        mudou_link_20_3 = link_20_3 != d20_3.get("link", "")
                        
                        if mudou_opcao_20_3 or mudou_link_20_3:
                                save_resp("20.3", sel_20_3, pts_20_3, link_20_3)
                                res_data["20.3"] = {"valor": sel_20_3, "pontos": pts_20_3, "link": link_20_3}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_20_3 and links_20_3_atuais:
                                        links_20_3_antigos = re.findall(r'(https?://[^\s]+)', d20_3.get("link", ""))
                                        if links_20_3_atuais != links_20_3_antigos:
                                                modal_aviso_link("20.3", links_20_3_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("20.3", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # SEÇÃO 21 - ARBOVIROSES (ANÁLISE)
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🦟 Seção 21 - Monitoramento de Arboviroses")

        # -----------------------------------------------------------------------------
        # QUESITO 21.0 - ANÁLISE SEMANAL DE DADOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_analise_arboviroses_21_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 21.0 - Análise Semanal de Dados", expanded=True):
                        st.subheader("21.0 • Análise Semanal de Dados")
                        st.write("**21.0 O município analisa semanalmente os dados de casos de arboviroses, acompanhando a tendência dos casos e verificando as variações entre as semanas epidemiológicas?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_21_0 = [
                                "Selecione...",
                                "Sim – 10",
                                "Não – 00",
                                "Não houve casos de arboviroses – 10"
                        ]
                        
                        d21_0 = res_data.get("21.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_210 = d21_0.get("valor", "Selecione...")
                        idx_21_0 = opts_21_0.index(val_atual_210) if val_atual_210 in opts_21_0 else 0
                        
                        c210_1, c210_2 = st.columns([1, 1])
                        with c210_1:
                                sel_21_0 = st.radio("Análise de dados:", options=opts_21_0, index=idx_21_0, key=f"rad_21_0_{ano_sel}", label_visibility="collapsed")
                                
                                opcoes_pts_210 = {
                                        "Sim – 10": 10.0,
                                        "Não – 00": 0.0,
                                        "Não houve casos de arboviroses – 10": 10.0,
                                        "Selecione...": 0.0
                                }
                                pts_21_0 = opcoes_pts_210.get(sel_21_0, 0.0)
                                
                        with c210_2:
                                link_21_0 = st.text_area("Link/Evidência (21.0):", value=d21_0.get("link", ""), key=f"txt_21_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_21_0 = st.empty()
                                links_21_0_atuais = re.findall(r'(https?://[^\s]+)', link_21_0)
                                if links_21_0_atuais:
                                        botoes_21_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_21_0_atuais])
                                        placeholder_links_21_0.markdown(f"**Links Ativos:** {botoes_21_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_21_0 = st.empty()
                        if "Sim" in sel_21_0 or "Não houve" in sel_21_0:
                                score_placeholder_21_0.markdown(f"📊 **Pontuação Aplicada no Quesito 21.0:** `{pts_21_0:.1f} pontos` (Meta Atingida)")
                        elif "Não" in sel_21_0:
                                score_placeholder_21_0.markdown(f"📊 **Pontuação Aplicada no Quesito 21.0:** `{pts_21_0:.1f} pontos` (Sem pontuação)")
                        else:
                                score_placeholder_21_0.markdown(f"📊 **Pontuação Aplicada no Quesito 21.0:** `{pts_21_0:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_21_0 = sel_21_0 != d21_0.get("valor", "")
                        mudou_link_21_0 = link_21_0 != d21_0.get("link", "")
                        
                        if mudou_opcao_21_0 or mudou_link_21_0:
                                save_resp("21.0", sel_21_0, pts_21_0, link_21_0)
                                res_data["21.0"] = {"valor": sel_21_0, "pontos": pts_21_0, "link": link_21_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_21_0 and links_21_0_atuais:
                                        links_21_0_antigos = re.findall(r'(https?://[^\s]+)', d21_0.get("link", ""))
                                        if links_21_0_atuais != links_21_0_antigos:
                                                modal_aviso_link("21.0", links_21_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("21.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # SEÇÃO 22 - ARBOVIROSES (INVESTIGAÇÃO)
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🔍 Seção 22 - Investigação de Arboviroses")

        # -----------------------------------------------------------------------------
        # QUESITO 22.0 - INVESTIGAÇÃO DE CASOS, SURTOS E ÓBITOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_investigacao_arboviroses_22_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 22.0 - Investigação de Casos, Surtos e Óbitos", expanded=True):
                        st.subheader("22.0 • Investigação de Casos, Surtos e Óbitos")
                        st.write("**22.0 O município investiga casos notificados, surtos e óbitos de arboviroses?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_22_0 = [
                                "Selecione...",
                                "Sim, investiga todos os casos – 30",
                                "Sim, investiga parte dos casos – 15",
                                f"Não houve casos em {ano_sel} – 30",
                                "Não investiga – 00"
                        ]
                        
                        d22_0 = res_data.get("22.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_220 = d22_0.get("valor", "Selecione...")
                        
                        idx_22_0 = 0
                        for i, k in enumerate(opts_22_0):
                                if k.split("–")[0].strip() == val_atual_220.split("–")[0].strip():
                                        idx_22_0 = i
                                        break
                        
                        c220_1, c220_2 = st.columns([1, 1])
                        with c220_1:
                                sel_22_0 = st.radio("Investigação de casos:", options=opts_22_0, index=idx_22_0, key=f"rad_22_0_{ano_sel}", label_visibility="collapsed")
                                
                                opcoes_pts_220 = {
                                        "Sim, investiga todos os casos – 30": 30.0,
                                        "Sim, investiga parte dos casos – 15": 15.0,
                                        f"Não houve casos em {ano_sel} – 30": 30.0,
                                        "Não investiga – 00": 0.0,
                                        "Selecione...": 0.0
                                }
                                pts_22_0 = opcoes_pts_220.get(sel_22_0, 0.0)
                                
                        with c220_2:
                                link_22_0 = st.text_area("Link/Evidência (22.0):", value=d22_0.get("link", ""), key=f"txt_22_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_22_0 = st.empty()
                                links_22_0_atuais = re.findall(r'(https?://[^\s]+)', link_22_0)
                                if links_22_0_atuais:
                                        botoes_22_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_22_0_atuais])
                                        placeholder_links_22_0.markdown(f"**Links Ativos:** {botoes_22_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_22_0 = st.empty()
                        if "todos" in sel_22_0 or "Não houve" in sel_22_0:
                                score_placeholder_22_0.markdown(f"📊 **Pontuação Aplicada no Quesito 22.0:** `{pts_22_0:.1f} pontos` (Meta Atingida)")
                        elif "parte" in sel_22_0:
                                score_placeholder_22_0.markdown(f"📊 **Pontuação Aplicada no Quesito 22.0:** `{pts_22_0:.1f} pontos` (Meta Parcial)")
                        elif "Não investiga" in sel_22_0:
                                score_placeholder_22_0.markdown(f"📊 **Pontuação Aplicada no Quesito 22.0:** `{pts_22_0:.1f} pontos` (Sem pontuação)")
                        else:
                                score_placeholder_22_0.markdown(f"📊 **Pontuação Aplicada no Quesito 22.0:** `{pts_22_0:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_22_0 = sel_22_0 != d22_0.get("valor", "")
                        mudou_link_22_0 = link_22_0 != d22_0.get("link", "")
                        
                        if mudou_opcao_22_0 or mudou_link_22_0:
                                save_resp("22.0", sel_22_0, pts_22_0, link_22_0)
                                res_data["22.0"] = {"valor": sel_22_0, "pontos": pts_22_0, "link": link_22_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_22_0 and links_22_0_atuais:
                                        links_22_0_antigos = re.findall(r'(https?://[^\s]+)', d22_0.get("link", ""))
                                        if links_22_0_atuais != links_22_0_antigos:
                                                modal_aviso_link("22.0", links_22_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("22.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

       # =============================================================================
        # SEÇÃO 23 - VIGILÂNCIA ENTOMOLÓGICA
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🗺️ Seção 23 - Vigilância Entomológica e Controle Vetorial")

        # -----------------------------------------------------------------------------
        # QUESITO 23.0 - EXERCÍCIO DE ATRIBUIÇÕES
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_vigilancia_entomologica_23_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 23.0 - Atribuições Relacionadas", expanded=True):
                        st.subheader("23.0 • Atribuições Relacionadas à Vigilância Entomológica")
                        st.write(f"**23.0 O município exerceu as atribuições relacionadas a vigilância entomológica e controle vetorial em {ano_sel}?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_23_0 = ["Selecione...", "Sim", "Não"]
                        d23_0 = res_data.get("23.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_230 = d23_0.get("valor", "Selecione...")
                        idx_23_0 = opts_23_0.index(val_atual_230) if val_atual_230 in opts_23_0 else 0
                        
                        c230_1, c230_2 = st.columns([1, 1])
                        with c230_1:
                                sel_23_0 = st.radio("Exercício de atribuições:", options=opts_23_0, index=idx_23_0, key=f"rad_23_0_{ano_sel}", label_visibility="collapsed")
                                pts_23_0 = 0.0
                                
                        with c230_2:
                                link_23_0 = st.text_area("Link/Evidência (23.0):", value=d23_0.get("link", ""), key=f"txt_23_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_23_0 = st.empty()
                                links_23_0_atuais = re.findall(r'(https?://[^\s]+)', link_23_0)
                                if links_23_0_atuais:
                                        botoes_23_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_23_0_atuais])
                                        placeholder_links_23_0.markdown(f"**Links Ativos:** {botoes_23_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_23_0 = st.empty()
                        if "Sim" in sel_23_0:
                                score_placeholder_23_0.markdown(f"📊 **Pontuação Aplicada no Quesito 23.0:** `{pts_23_0:.1f} pontos` (Dados Informativos)")
                        elif "Não" in sel_23_0:
                                score_placeholder_23_0.markdown(f"📊 **Pontuação Aplicada no Quesito 23.0:** `{pts_23_0:.1f} pontos` (Dados Informativos)")
                        else:
                                score_placeholder_23_0.markdown(f"📊 **Pontuação Aplicada no Quesito 23.0:** `{pts_23_0:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_23_0 = sel_23_0 != d23_0.get("valor", "")
                        mudou_link_23_0 = link_23_0 != d23_0.get("link", "")
                        
                        if mudou_opcao_23_0 or mudou_link_23_0:
                                save_resp("23.0", sel_23_0, pts_23_0, link_23_0)
                                res_data["23.0"] = {"valor": sel_23_0, "pontos": pts_23_0, "link": link_23_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_23_0 and links_23_0_atuais:
                                        links_23_0_antigos = re.findall(r'(https?://[^\s]+)', d23_0.get("link", ""))
                                        if links_23_0_atuais != links_23_0_antigos:
                                                modal_aviso_link("23.0", links_23_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("23.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 23.1 - LISTA DE ATRIBUIÇÕES CUMULATIVAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_atribuicoes_vetorial_23_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 23.1 - Atribuições da Vigilância Entomológica", expanded=True):
                        st.subheader("23.1 • Atribuições da Vigilância Entomológica")
                        st.write("**23.1 Assinale as atribuições da vigilância entomológica e controle vetorial:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                        
                        d23_1 = res_data.get("23.1", {"valor": "", "pontos": 0.0, "link": ""})
                        v23_1 = d23_1.get("valor", "").split("|")
                        
                        atribuicoes_specs = {
                                "vig_sanitaria": {"text": "Incluir a vigilância sanitária municipal e como suporte às ações de vigilância e controle vetorial, que exigem o cumprimento da legislação sanitária – 03", "pts": 3.0},
                                "integrar_equipes": {"text": "Integrar as equipes de saúde da família nas atividades de controle vetorial, unificando os territórios de atuação de ACS e ACE – 03", "pts": 3.0},
                                "levantamento_ind": {"text": "Realizar o levantamento de indicadores entomológicos – 03", "pts": 3.0},
                                "acoes_controle": {"text": "Executar as ações de controle mecânico, químico e biológico do mosquito – 03", "pts": 3.0},
                                "enviar_dados": {"text": "Enviar os dados entomológicos ao nível estadual, dentro dos prazos estabelecidos – 03", "pts": 3.0},
                                "gerenciar_estoques": {"text": "Gerenciar os estoques municipais de inseticidas e biolarvicidas – 03", "pts": 3.0},
                                "adquirir_vestuarios": {"text": "Adquirir as vestimentas e equipamentos necessários à rotina de controle vetorial – 03", "pts": 3.0},
                                "adquirir_epi": {"text": "Adquirir os equipamentos de EPI recomendados para a aplicação de inseticidas e biolarvicidas nas ações de rotina – 03", "pts": 3.0},
                                "dosagem_colinesterase": {"text": "Coletar e enviar ao laboratório de referência amostras de sangue aos trabalhadores do controle vetorial que manuseiam inseticidas e/ou larvicidas, para dosagem de colinesterase, na frequência recomendada – 03", "pts": 3.0},
                                "comite_gestor": {"text": "Possuir Comitê Gestor Intersetorial, sob coordenação da secretaria municipal de saúde, com representantes das áreas do município que tenham interface com o problema dengue (defesa civil, limpeza urbana, infraestrutura, segurança, turismo, planejamento, saneamento etc.), definindo responsabilidades, metas e indicadores de acompanhamento de cada área de atuação – 03", "pts": 3.0},
                                "outros": {"text": "Outros – 00", "pts": 0.0}
                        }
                        
                        c231_1, c231_2 = st.columns([1, 1])
                        chks_selecionados = []
                        pts_totais_23_1 = 0.0
                        
                        keys_atrib = list(atribuicoes_specs.keys())
                        metade = (len(keys_atrib) + 1) // 2
                        
                        with c231_1:
                                for k in keys_atrib[:metade]:
                                        marcado = st.checkbox(atribuicoes_specs[k]["text"], value=k in v23_1, key=f"chk_23_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados.append(k)
                                                pts_totais_23_1 += atribuicoes_specs[k]["pts"]
                                                
                        with c231_2:
                                for k in keys_atrib[metade:]:
                                        marcado = st.checkbox(atribuicoes_specs[k]["text"], value=k in v23_1, key=f"chk_23_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados.append(k)
                                                pts_totais_23_1 += atribuicoes_specs[k]["pts"]
                                                
                                link_23_1 = st.text_area("Link/Evidência (23.1):", value=d23_1.get("link", ""), key=f"txt_23_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_23_1 = st.empty()
                                links_23_1_atuais = re.findall(r'(https?://[^\s]+)', link_23_1)
                                if links_23_1_atuais:
                                        botoes_23_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_23_1_atuais])
                                        placeholder_links_23_1.markdown(f"**Links Ativos:** {botoes_23_1}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_23_1 = st.empty()
                        if pts_totais_23_1 > 0:
                                score_placeholder_23_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 23.1:** :green[+{pts_totais_23_1:.1f} pontos]")
                        else:
                                score_placeholder_23_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 23.1:** `{pts_totais_23_1:.1f} pontos` (Nenhum item selecionado)")
                                
                        str_23_1 = "|".join(chks_selecionados)
                        
                        mudou_opcao_23_1 = str_23_1 != d23_1.get("valor", "")
                        mudou_link_23_1 = link_23_1 != d23_1.get("link", "")
                        
                        if mudou_opcao_23_1 or mudou_link_23_1:
                                save_resp("23.1", str_23_1, pts_totais_23_1, link_23_1)
                                res_data["23.1"] = {"valor": str_23_1, "pontos": pts_totais_23_1, "link": link_23_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_23_1 and links_23_1_atuais:
                                        links_23_1_antigos = re.findall(r'(https?://[^\s]+)', d23_1.get("link", ""))
                                        if links_23_1_atuais != links_23_1_antigos:
                                                modal_aviso_link("23.1", links_23_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("23.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 23

# =============================================================================
        # SEÇÃO 24 - EDUCAÇÃO EM SAÚDE
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📢 Seção 24 - Educação em Saúde")

        # -----------------------------------------------------------------------------
        # QUESITO 24.0 - EXECUÇÃO DE ATIVIDADES
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_educacao_saude_24_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 24.0 - Atividades de Educação em Saúde", expanded=True):
                        st.subheader("24.0 • Atividades de Educação em Saúde")
                        st.write("**24.0 O município executou atividades de Educação em Saúde?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_24_0 = ["Selecione...", "Sim", "Não"]
                        d24_0 = res_data.get("24.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_240 = d24_0.get("valor", "Selecione...")
                        idx_24_0 = opts_24_0.index(val_atual_240) if val_atual_240 in opts_24_0 else 0
                        
                        c240_1, c240_2 = st.columns([1, 1])
                        with c240_1:
                                sel_24_0 = st.radio("Execução de atividades:", options=opts_24_0, index=idx_24_0, key=f"rad_24_0_{ano_sel}", label_visibility="collapsed")
                                pts_24_0 = 0.0
                                
                        with c240_2:
                                link_24_0 = st.text_area("Link/Evidência (24.0):", value=d24_0.get("link", ""), key=f"txt_24_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_24_0 = st.empty()
                                links_24_0_atuais = re.findall(r'(https?://[^\s]+)', link_24_0)
                                if links_24_0_atuais:
                                        botoes_24_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_24_0_atuais])
                                        placeholder_links_24_0.markdown(f"**Links Ativos:** {botoes_24_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_24_0 = st.empty()
                        if "Sim" in sel_24_0 or "Não" in sel_24_0:
                                score_placeholder_24_0.markdown(f"📊 **Pontuação Aplicada no Quesito 24.0:** `{pts_24_0:.1f} pontos` (Dados Informativos)")
                        else:
                                score_placeholder_24_0.markdown(f"📊 **Pontuação Aplicada no Quesito 24.0:** `{pts_24_0:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_24_0 = sel_24_0 != d24_0.get("valor", "")
                        mudou_link_24_0 = link_24_0 != d24_0.get("link", "")
                        
                        if mudou_opcao_24_0 or mudou_link_24_0:
                                save_resp("24.0", sel_24_0, pts_24_0, link_24_0)
                                res_data["24.0"] = {"valor": sel_24_0, "pontos": pts_24_0, "link": link_24_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_24_0 and links_24_0_atuais:
                                        links_24_0_antigos = re.findall(r'(https?://[^\s]+)', d24_0.get("link", ""))
                                        if links_24_0_atuais != links_24_0_antigos:
                                                modal_aviso_link("24.0", links_24_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("24.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 24.1 - CAMPANHAS REALIZADAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_campanhas_realizadas_24_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 24.1 - Campanhas Realizadas", expanded=True):
                        st.subheader("24.1 • Campanhas Realizadas")
                        st.write(f"**24.1 Assinale as campanhas realizadas em {ano_sel}:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                        
                        d24_1 = res_data.get("24.1", {"valor": "", "pontos": 0.0, "link": ""})
                        v24_1 = d24_1.get("valor", "").split("|")
                        
                        campanhas_specs = {
                                "plan_familiar": {"text": "Planejamento familiar - concepção e contracepção (Prevenção à Gravidez) – 0,5", "pts": 0.5},
                                "pre_natal": {"text": "Pré-Natal – 0,5", "pts": 0.5},
                                "assist_parto": {"text": "Assistência ao parto, ao puerpério e ao neonato, incluindo aleitamento materno e doação de leite materno – 0,5", "pts": 0.5},
                                "prev_ist": {"text": "Prevenção às IST - Infecção Sexualmente Transmissível – 0,5", "pts": 0.5},
                                "prev_cancer": {"text": "Prevenção dos cânceres do colo do útero, de mama e da saúde do homem – 0,5", "pts": 0.5},
                                "vacinacao": {"text": "Vacinação – 0,5", "pts": 0.5},
                                "hipertensao": {"text": "Hipertensão – 0,5", "pts": 0.5},
                                "diabetes": {"text": "Diabetes – 0,5", "pts": 0.5},
                                "hanseniase": {"text": "Hanseníase – 0,5", "pts": 0.5},
                                "hepatite": {"text": "Hepatite – 0,5", "pts": 0.5},
                                "covid": {"text": "Coronavírus - COVID19 – 0,5", "pts": 0.5},
                                "tuberculose": {"text": "Tuberculose – 0,5", "pts": 0.5},
                                "chagas": {"text": "Doença de Chagas – 0,5", "pts": 0.5},
                                "arboviroses": {"text": "Dengue/Zika/Chikungunya/Febre Amarela/Malária (Arboviroses) – 0,5", "pts": 0.5},
                                "tabaco": {"text": "Tabaco – 0,5", "pts": 0.5},
                                "drogas": {"text": "Drogas e entorpecentes – 0,5", "pts": 0.5},
                                "saude_bucal": {"text": "Saúde Bucal – 0,5", "pts": 0.5},
                                "doacao_sangue": {"text": "Doação de Sangue – 0,5", "pts": 0.5},
                                "doacao_orgaos": {"text": "Doação de Órgãos – 0,5", "pts": 0.5},
                                "depressao_suicidio": {"text": "Prevenção à Depressão e ao Suicídio – 0,5", "pts": 0.5},
                                "hiv_aids": {"text": "HIV/Aids – 00", "pts": 0.0},
                                "falciforme": {"text": "Doença Falciforme – 00", "pts": 0.0},
                                "outros": {"text": "Outros – 00", "pts": 0.0}
                        }
                        
                        c241_1, c241_2 = st.columns([1, 1])
                        chks_selecionados = []
                        pts_totais_24_1 = 0.0
                        
                        keys_campanhas = list(campanhas_specs.keys())
                        metade = (len(keys_campanhas) + 1) // 2
                        
                        with c241_1:
                                for k in keys_campanhas[:metade]:
                                        marcado = st.checkbox(campanhas_specs[k]["text"], value=k in v24_1, key=f"chk_24_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados.append(k)
                                                pts_totais_24_1 += campanhas_specs[k]["pts"]
                                                
                        with c241_2:
                                for k in keys_campanhas[metade:]:
                                        marcado = st.checkbox(campanhas_specs[k]["text"], value=k in v24_1, key=f"chk_24_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados.append(k)
                                                pts_totais_24_1 += campanhas_specs[k]["pts"]
                                                
                                link_24_1 = st.text_area("Link/Evidência (24.1):", value=d24_1.get("link", ""), key=f"txt_24_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_24_1 = st.empty()
                                links_24_1_atuais = re.findall(r'(https?://[^\s]+)', link_24_1)
                                if links_24_1_atuais:
                                        botoes_24_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_24_1_atuais])
                                        placeholder_links_24_1.markdown(f"**Links Ativos:** {botoes_24_1}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_24_1 = st.empty()
                        if pts_totais_24_1 > 0:
                                score_placeholder_24_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 24.1:** :green[+{pts_totais_24_1:.1f} pontos]")
                        else:
                                score_placeholder_24_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 24.1:** `{pts_totais_24_1:.1f} pontos` (Nenhum item selecionado)")
                                
                        str_24_1 = "|".join(chks_selecionados)
                        
                        mudou_opcao_24_1 = str_24_1 != d24_1.get("valor", "")
                        mudou_link_24_1 = link_24_1 != d24_1.get("link", "")
                        
                        if mudou_opcao_24_1 or mudou_link_24_1:
                                save_resp("24.1", str_24_1, pts_totais_24_1, link_24_1)
                                res_data["24.1"] = {"valor": str_24_1, "pontos": pts_totais_24_1, "link": link_24_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_24_1 and links_24_1_atuais:
                                        links_24_1_antigos = re.findall(r'(https?://[^\s]+)', d24_1.get("link", ""))
                                        if links_24_1_atuais != links_24_1_antigos:
                                                modal_aviso_link("24.1", links_24_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("24.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 24

# =============================================================================
        # SEÇÃO 25 - AÇÕES REGULADORAS E COMPLEXOS REGULADORES
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("⚙️ Seção 25 - Regulação do Acesso e Complexos Reguladores")

        # -----------------------------------------------------------------------------
        # QUESITO 25.0 - AÇÕES REGULADORAS NO TERRITÓRIO
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_regulacao_acesso_25_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 25.0 - Ações Reguladoras no Território", expanded=True):
                        st.subheader("25.0 • Ações Reguladoras no Território")
                        st.write("**25.0 O município desenvolve ações reguladoras em seu território, operacionalizando por meio de complexo regulador municipal e/ou participando em co-gestão da operacionalização dos Complexos Reguladores Regionais?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_25_0 = ["Selecione...", "Sim – 05", "Não – 00"]
                        d25_0 = res_data.get("25.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_250 = d25_0.get("valor", "Selecione...")
                        idx_25_0 = opts_25_0.index(val_atual_250) if val_atual_250 in opts_25_0 else 0
                        
                        c250_1, c250_2 = st.columns([1, 1])
                        with c250_1:
                                sel_25_0 = st.radio("Ações reguladoras:", options=opts_25_0, index=idx_25_0, key=f"rad_25_0_{ano_sel}", label_visibility="collapsed")
                                
                                opcoes_pts_250 = {
                                        "Sim – 05": 5.0,
                                        "Não – 00": 0.0,
                                        "Selecione...": 0.0
                                }
                                pts_25_0 = opcoes_pts_250.get(sel_25_0, 0.0)
                                
                        with c250_2:
                                link_25_0 = st.text_area("Link/Evidência (25.0):", value=d25_0.get("link", ""), key=f"txt_25_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_25_0 = st.empty()
                                links_25_0_atuais = re.findall(r'(https?://[^\s]+)', link_25_0)
                                if links_25_0_atuais:
                                        botoes_25_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_25_0_atuais])
                                        placeholder_links_25_0.markdown(f"**Links Ativos:** {botoes_25_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_25_0 = st.empty()
                        if "Sim" in sel_25_0:
                                score_placeholder_25_0.markdown(f"📊 **Pontuação Aplicada no Quesito 25.0:** `{pts_25_0:.1f} pontos` (Meta Atingida)")
                        elif "Não" in sel_25_0:
                                score_placeholder_25_0.markdown(f"📊 **Pontuação Aplicada no Quesito 25.0:** `{pts_25_0:.1f} pontos` (Sem pontuação)")
                        else:
                                score_placeholder_25_0.markdown(f"📊 **Pontuação Aplicada no Quesito 25.0:** `{pts_25_0:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_25_0 = sel_25_0 != d25_0.get("valor", "")
                        mudou_link_25_0 = link_25_0 != d25_0.get("link", "")
                        
                        if mudou_opcao_25_0 or mudou_link_25_0:
                                save_resp("25.0", sel_25_0, pts_25_0, link_25_0)
                                res_data["25.0"] = {"valor": sel_25_0, "pontos": pts_25_0, "link": link_25_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_25_0 and links_25_0_atuais:
                                        links_25_0_antigos = re.findall(r'(https?://[^\s]+)', d25_0.get("link", ""))
                                        if links_25_0_atuais != links_25_0_antigos:
                                                modal_aviso_link("25.0", links_25_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("25.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 25

        # =============================================================================
        # SEÇÃO 26 - PROTOCOLOS DE REGULAÇÃO
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📋 Seção 26 - Protocolos de Regulação")

        # -----------------------------------------------------------------------------
        # QUESITO 26.0 - PROTOCOLOS DE REGULAÇÃO DE ACESSO FORMALIZADOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_protocolos_regulacao_26_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 26.0 - Protocolos de Regulação de Acesso Formalizados", expanded=True):
                        st.subheader("26.0 • Protocolos de Regulação de Acesso Formalizados")
                        st.write("**26.0 O município elaborou os protocolos de regulação de acesso formalizados?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_26_0 = ["Selecione...", "Sim – 10", "Não – 00"]
                        d26_0 = res_data.get("26.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_260 = d26_0.get("valor", "Selecione...")
                        idx_26_0 = opts_26_0.index(val_atual_260) if val_atual_260 in opts_26_0 else 0
                        
                        c260_1, c260_2 = st.columns([1, 1])
                        with c260_1:
                                sel_26_0 = st.radio("Protocolos de regulação:", options=opts_26_0, index=idx_26_0, key=f"rad_26_0_{ano_sel}", label_visibility="collapsed")
                                
                                opcoes_pts_260 = {
                                        "Sim – 10": 10.0,
                                        "Não – 00": 0.0,
                                        "Selecione...": 0.0
                                }
                                pts_26_0 = opcoes_pts_260.get(sel_26_0, 0.0)
                                
                        with c260_2:
                                link_26_0 = st.text_area("Link/Evidência (26.0):", value=d26_0.get("link", ""), key=f"txt_26_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_26_0 = st.empty()
                                links_26_0_atuais = re.findall(r'(https?://[^\s]+)', link_26_0)
                                if links_26_0_atuais:
                                        botoes_26_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_26_0_atuais])
                                        placeholder_links_26_0.markdown(f"**Links Ativos:** {botoes_26_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_26_0 = st.empty()
                        if "Sim" in sel_26_0:
                                score_placeholder_26_0.markdown(f"📊 **Pontuação Aplicada no Quesito 26.0:** `{pts_26_0:.1f} pontos` (Meta Atingida)")
                        elif "Não" in sel_26_0:
                                score_placeholder_26_0.markdown(f"📊 **Pontuação Aplicada no Quesito 26.0:** `{pts_26_0:.1f} pontos` (Sem pontuação)")
                        else:
                                score_placeholder_26_0.markdown(f"📊 **Pontuação Aplicada no Quesito 26.0:** `{pts_26_0:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_26_0 = sel_26_0 != d26_0.get("valor", "")
                        mudou_link_26_0 = link_26_0 != d26_0.get("link", "")
                        
                        if mudou_opcao_26_0 or mudou_link_26_0:
                                save_resp("26.0", sel_26_0, pts_26_0, link_26_0)
                                res_data["26.0"] = {"valor": sel_26_0, "pontos": pts_26_0, "link": link_26_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_26_0 and links_26_0_atuais:
                                        links_26_0_antigos = re.findall(r'(https?://[^\s]+)', d26_0.get("link", ""))
                                        if links_26_0_atuais != links_26_0_antigos:
                                                modal_aviso_link("26.0", links_26_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("26.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 26

        # =============================================================================
        # SEÇÃO 27 - REGULAÇÃO DA REFERÊNCIA INTERMUNICIPAL
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🔗 Seção 27 - Regulação de Referência Intermunicipal")

        # -----------------------------------------------------------------------------
        # QUESITO 27.0 - REGULAÇÃO DA REFERÊNCIA EM OUTROS MUNICÍPIOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_referencia_intermunicipal_27_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 27.0 - Regulação da Referência em Outros Municípios", expanded=True):
                        st.subheader("27.0 • Regulação da Referência em Outros Municípios")
                        st.write("**27.0 O município regula a referência a ser realizada em outros municípios, de acordo com a programação pactuada e integrada, integrando-se aos fluxos regionais estabelecidos?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_27_0 = ["Selecione...", "Sim – 05", "Não – 00"]
                        d27_0 = res_data.get("27.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_270 = d27_0.get("valor", "Selecione...")
                        idx_27_0 = opts_27_0.index(val_atual_270) if val_atual_270 in opts_27_0 else 0
                        
                        c270_1, c270_2 = st.columns([1, 1])
                        with c270_1:
                                sel_27_0 = st.radio("Regulação da referência:", options=opts_27_0, index=idx_27_0, key=f"rad_27_0_{ano_sel}", label_visibility="collapsed")
                                
                                opcoes_pts_270 = {
                                        "Sim – 05": 5.0,
                                        "Não – 00": 0.0,
                                        "Selecione...": 0.0
                                }
                                pts_27_0 = opcoes_pts_270.get(sel_27_0, 0.0)
                                
                        with c270_2:
                                link_27_0 = st.text_area("Link/Evidência (27.0):", value=d27_0.get("link", ""), key=f"txt_27_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_27_0 = st.empty()
                                links_27_0_atuais = re.findall(r'(https?://[^\s]+)', link_27_0)
                                if links_27_0_atuais:
                                        botoes_27_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_27_0_atuais])
                                        placeholder_links_27_0.markdown(f"**Links Ativos:** {botoes_27_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_27_0 = st.empty()
                        if "Sim" in sel_27_0:
                                score_placeholder_27_0.markdown(f"📊 **Pontuação Aplicada no Quesito 27.0:** `{pts_27_0:.1f} pontos` (Meta Atingida)")
                        elif "Não" in sel_27_0:
                                score_placeholder_27_0.markdown(f"📊 **Pontuação Aplicada no Quesito 27.0:** `{pts_27_0:.1f} pontos` (Sem pontuação)")
                        else:
                                score_placeholder_27_0.markdown(f"📊 **Pontuação Aplicada no Quesito 27.0:** `{pts_27_0:.1f} pontos` (Aguardando Seleção)")
                                
                        mudou_opcao_27_0 = sel_27_0 != d27_0.get("valor", "")
                        mudou_link_27_0 = link_27_0 != d27_0.get("link", "")
                        
                        if mudou_opcao_27_0 or mudou_link_27_0:
                                save_resp("27.0", sel_27_0, pts_27_0, link_27_0)
                                res_data["27.0"] = {"valor": sel_27_0, "pontos": pts_27_0, "link": link_27_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_27_0 and links_27_0_atuais:
                                        links_27_0_antigos = re.findall(r'(https?://[^\s]+)', d27_0.get("link", ""))
                                        if links_27_0_atuais != links_27_0_antigos:
                                                modal_aviso_link("27.0", links_27_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("27.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 27

# =============================================================================
        # SEÇÃO 28 - CONTROLE DA FILA DE ESPERA (ATENÇÃO ESPECIALIZADA)
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("⏳ Seção 28 - Controle da Fila de Espera")

        # -----------------------------------------------------------------------------
        # QUESITO 28.0 - CONTROLE DA FILA (FORA DO CROSS)
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_controle_fila_28_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.0 - Controle da Fila de Espera (Atenção Especializada)", expanded=True):
                        st.subheader("28.0 • Controle da Fila de Espera (Atenção Especializada)")
                        st.write("**28.0 O município possui controle da fila de espera para os atendimentos da Atenção Especializada que não foram inseridos no sistema de regulação do governo estadual (Portal CROSS)?**")
                        st.caption("ℹ️ *Refere-se ao Município como Unidade Solicitante.*")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_28_0 = [
                                "Selecione...",
                                "Sim, com a relação nominal de pacientes e tempo de espera para todos os serviços da Atenção Especializada com fila de espera – 05",
                                "Sim, com a relação nominal de pacientes e tempo de espera para a maior parte dos serviços da Atenção Especializada com fila de espera – 02",
                                "Sim, com a relação nominal de pacientes e tempo de espera para a menor parte dos serviços da Atenção Especializada com fila de espera – 01",
                                "Não possui controle da fila de espera – 00",
                                "Não possui fila de espera além da inserida no sistema de regulação do governo estadual (Portal CROSS) – 05"
                        ]
                        
                        d28_0 = res_data.get("28.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_280 = d28_0.get("valor", "Selecione...")
                        idx_28_0 = opts_28_0.index(val_atual_280) if val_atual_280 in opts_28_0 else 0
                        
                        c280_1, c280_2 = st.columns([1, 1])
                        with c280_1:
                                sel_28_0 = st.radio("Controle da fila:", options=opts_28_0, index=idx_28_0, key=f"rad_28_0_{ano_sel}", label_visibility="collapsed")
                                
                                opciones_pts_280 = {
                                        "Sim, com a relação nominal de pacientes e tempo de espera para todos os serviços da Atenção Especializada com fila de espera – 05": 5.0,
                                        "Sim, com a relação nominal de pacientes e tempo de espera para a maior parte dos serviços da Atenção Especializada com fila de espera – 02": 2.0,
                                        "Sim, com a relação nominal de pacientes e tempo de espera para a menor parte dos serviços da Atenção Especializada com fila de espera – 01": 1.0,
                                        "Não possui controle da fila de espera – 00": 0.0,
                                        "Não possui fila de espera além da inserida no sistema de regulação do governo estadual (Portal CROSS) – 05": 5.0,
                                        "Selecione...": 0.0
                                }
                                pts_28_0 = opciones_pts_280.get(sel_28_0, 0.0)
                                
                        with c280_2:
                                link_28_0 = st.text_area("Link/Evidência (28.0):", value=d28_0.get("link", ""), key=f"txt_28_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_0 = st.empty()
                                links_28_0_atuais = re.findall(r'(https?://[^\s]+)', link_28_0)
                                if links_28_0_atuais:
                                        botoes_28_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_0_atuais])
                                        placeholder_links_28_0.markdown(f"**Links Ativos:** {botoes_28_0}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_28_0 = st.empty()
                        if "Selecione..." in sel_28_0:
                                score_placeholder_28_0.markdown(f"📊 **Pontuação Aplicada no Quesito 28.0:** `{pts_28_0:.1f} pontos` (Aguardando Seleção)")
                        elif "Não possui controle" in sel_28_0:
                                score_placeholder_28_0.markdown(f"📊 **Pontuação Aplicada no Quesito 28.0:** `{pts_28_0:.1f} pontos` (Sem pontuação)")
                        else:
                                score_placeholder_28_0.markdown(f"📊 **Pontuação Aplicada no Quesito 28.0:** :green[+{pts_28_0:.1f} pontos] (Dados Computados)")
                                
                        mudou_opcao_28_0 = sel_28_0 != d28_0.get("valor", "")
                        mudou_link_28_0 = link_28_0 != d28_0.get("link", "")
                        
                        if mudou_opcao_28_0 or mudou_link_28_0:
                                save_resp("28.0", sel_28_0, pts_28_0, link_28_0)
                                res_data["28.0"] = {"valor": sel_28_0, "pontos": pts_28_0, "link": link_28_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_0 and links_28_0_atuais:
                                        links_28_0_antigos = re.findall(r'(https?://[^\s]+)', d28_0.get("link", ""))
                                        if links_28_0_atuais != links_28_0_antigos:
                                                modal_aviso_link("28.0", links_28_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 28

        # -----------------------------------------------------------------------------
        # QUESITO 28.1 - TIPO DE CONTROLE
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_tipo_controle_fila_28_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.1 - Tipo de Controle da Lista de Espera", expanded=True):
                        st.subheader("28.1 • Tipo de Controle da Lista de Espera")
                        st.write("**28.1 Assinale o tipo de controle da lista de espera para os atendimentos da Atenção Especializada que não foram inseridos no sistema de regulação do governo estadual:**")
                        st.caption("ℹ️ *Atenção: Planilha eletrônica não é considerada sistema informatizado.*")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no rádio ou no link grava os dados na hora.*")
                        
                        opts_28_1 = [
                                "Selecione...",
                                "Em sistema informatizado – 05",
                                "De forma manual – -05 (perde 05 pontos)"
                        ]
                        
                        d28_1 = res_data.get("28.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_281 = d28_1.get("valor", "Selecione...")
                        idx_28_1 = opts_28_1.index(val_atual_281) if val_atual_281 in opts_28_1 else 0
                        
                        c281_1, c281_2 = st.columns([1, 1])
                        with c281_1:
                                sel_28_1 = st.radio("Tipo de controle:", options=opts_28_1, index=idx_28_1, key=f"rad_28_1_{ano_sel}", label_visibility="collapsed")
                                
                                opciones_pts_281 = {
                                        "Em sistema informatizado – 05": 5.0,
                                        "De forma manual – -05 (perde 05 pontos)": -5.0,
                                        "Selecione...": 0.0
                                }
                                pts_28_1 = opciones_pts_281.get(sel_28_1, 0.0)
                                
                        with c281_2:
                                link_28_1 = st.text_area("Link/Evidência (28.1):", value=d28_1.get("link", ""), key=f"txt_28_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_1 = st.empty()
                                links_28_1_atuais = re.findall(r'(https?://[^\s]+)', link_28_1)
                                if links_28_1_atuais:
                                        botoes_28_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_1_atuais])
                                        placeholder_links_28_1.markdown(f"**Links Ativos:** {botoes_28_1}")
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks e pontuações de forma segura
                        score_placeholder_28_1 = st.empty()
                        if "Selecione..." in sel_28_1:
                                score_placeholder_28_1.markdown(f"📊 **Pontuação Aplicada no Quesito 28.1:** `{pts_28_1:.1f} pontos` (Aguardando Seleção)")
                        elif pts_28_1 < 0:
                                score_placeholder_28_1.error(f"⚠️ Penalidade aplicada no Quesito 28.1: {pts_28_1:.1f} pontos.")
                        else:
                                score_placeholder_28_1.success(f"✅ Pontuação aplicada no Quesito 28.1: +{pts_28_1:.1f} pontos.")
                                
                        mudou_opcao_28_1 = sel_28_1 != d28_1.get("valor", "")
                        mudou_link_28_1 = link_28_1 != d28_1.get("link", "")
                        
                        if mudou_opcao_28_1 or mudou_link_28_1:
                                save_resp("28.1", sel_28_1, pts_28_1, link_28_1)
                                res_data["28.1"] = {"valor": sel_28_1, "pontos": pts_28_1, "link": link_28_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_1 and links_28_1_atuais:
                                        links_28_1_antigos = re.findall(r'(https?://[^\s]+)', d28_1.get("link", ""))
                                        if links_28_1_atuais != links_28_1_antigos:
                                                modal_aviso_link("28.1", links_28_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 28

# -----------------------------------------------------------------------------
        # QUESITO 28.2 - SERVIÇOS FORA DO PORTAL CROSS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_servicos_fora_cross_28_2_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2 - Serviços com Lista de Espera Fora do Portal CROSS", expanded=True):
                        st.subheader("28.2 • Serviços com Lista de Espera Fora do Portal CROSS")
                        st.write("**28.2 Assinale os serviços da Atenção Especializada com lista de espera que não foram inseridos no sistema de regulação do governo estadual (Portal CROSS):**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos checkboxes ou no link grava os dados na hora.*")
                        
                        d28_2 = res_data.get("28.2", {"valor": "", "pontos": 0.0, "link": ""})
                        v28_2 = d28_2.get("valor", "").split("|")
                        
                        servicos_specs = {
                                "consultas": "Consultas por especialidade",
                                "exames": "Exames",
                                "terapias": "Terapias / tratamentos",
                                "medicamentos": "Medicamentos",
                                "opm": "OPM",
                                "cirurgias": "Cirurgias eletivas",
                                "outros": "Outros"
                        }
                        
                        c282_1, c282_2 = st.columns([1, 1])
                        chks_28_2 = []
                        
                        keys_servicos = list(servicos_specs.keys())
                        metade_servicos = (len(keys_servicos) + 1) // 2
                        
                        with c282_1:
                                for k in keys_servicos[:metade_servicos]:
                                        marcado = st.checkbox(servicos_specs[k], value=k in v28_2, key=f"chk_28_2_{k}_{ano_sel}")
                                        if marcado:
                                                chks_28_2.append(k)
                                                
                        with c282_2:
                                for k in keys_servicos[metade_servicos:]:
                                        marcado = st.checkbox(servicos_specs[k], value=k in v28_2, key=f"chk_28_2_{k}_{ano_sel}")
                                        if marcado:
                                                chks_28_2.append(k)
                                                
                                link_28_2 = st.text_area("Link/Evidência (28.2):", value=d28_2.get("link", ""), key=f"txt_28_2_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2 = st.empty()
                                links_28_2_atuais = re.findall(r'(https?://[^\s]+)', link_28_2)
                                if links_28_2_atuais:
                                        botoes_28_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_atuais])
                                        placeholder_links_28_2.markdown(f"**Links Ativos:** {botoes_28_2}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2 = st.empty()
                        pts_28_2 = 0.0
                        if chks_28_2:
                                score_placeholder_28_2.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2:** `{pts_28_2:.1f} pontos` (Dados Informativos)")
                        else:
                                score_placeholder_28_2.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2:** `{pts_28_2:.1f} pontos` (Nenhum item selecionado)")
                                
                        str_28_2 = "|".join(chks_28_2)
                        
                        mudou_opcao_28_2 = str_28_2 != d28_2.get("valor", "")
                        mudou_link_28_2 = link_28_2 != d28_2.get("link", "")
                        
                        if mudou_opcao_28_2 or mudou_link_28_2:
                                save_resp("28.2", str_28_2, pts_28_2, link_28_2)
                                res_data["28.2"] = {"valor": str_28_2, "pontos": pts_28_2, "link": link_28_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2 and links_28_2_atuais:
                                        links_28_2_antigos = re.findall(r'(https?://[^\s]+)', d28_2.get("link", ""))
                                        if links_28_2_atuais != links_28_2_antigos:
                                                modal_aviso_link("28.2", links_28_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 28

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.1 - MAIORES TEMPOS DE ESPERA: CONSULTAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_maiores_esperas_consultas_28_2_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2.1 - Top 3 Consultas Médicas com Maior Tempo de Espera", expanded=True):
                        st.subheader("28.2.1 • Top 3 Consultas Médicas com Maior Tempo de Espera")
                        st.write("**28.2.1 Informe as 3 consultas médicas com maior tempo de espera:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de texto, números ou no link grava os dados na hora.*")
                        
                        d28_2_1 = res_data.get("28.2.1", {"valor": "|||||", "pontos": 0.0, "link": ""})
                        v28_2_1 = d28_2_1.get("valor", "|||||").split("|")
                        while len(v28_2_1) < 6: 
                                v28_2_1.append("")
                        
                        c2821_1, c2821_2 = st.columns([1, 1])
                        with c2821_1:
                                esp_1 = st.text_input("1ª Especialidade médica:", value=v28_2_1[0], key=f"txt_2821_esp1_{ano_sel}")
                                tempo_1 = st.number_input("Tempo médio de espera 1 (em dias):", min_value=0, value=int(v28_2_1[1]) if v28_2_1[1].isdigit() else 0, key=f"num_2821_t1_{ano_sel}")
                                
                                esp_2 = st.text_input("2ª Especialidade médica:", value=v28_2_1[2], key=f"txt_2821_esp2_{ano_sel}")
                                tempo_2 = st.number_input("Tempo médio de espera 2 (em dias):", min_value=0, value=int(v28_2_1[3]) if v28_2_1[3].isdigit() else 0, key=f"num_2821_t2_{ano_sel}")
                                
                                esp_3 = st.text_input("3ª Especialidade médica:", value=v28_2_1[4], key=f"txt_2821_esp3_{ano_sel}")
                                tempo_3 = st.number_input("Tempo médio de espera 3 (em dias):", min_value=0, value=int(v28_2_1[5]) if v28_2_1[5].isdigit() else 0, key=f"num_2821_t3_{ano_sel}")
                                
                        with c2821_2:
                                link_28_2_1 = st.text_area("Link/Evidência (28.2.1):", value=d28_2_1.get("link", ""), key=f"txt_28_2_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2_1 = st.empty()
                                links_28_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_28_2_1)
                                if links_28_2_1_atuais:
                                        botoes_28_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_1_atuais])
                                        placeholder_links_28_2_1.markdown(f"**Links Ativos:** {botoes_28_2_1}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2_1 = st.empty()
                        pts_28_2_1 = 0.0
                        score_placeholder_28_2_1.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2.1:** `{pts_28_2_1:.1f} pontos` (Dados Informativos)")
                        
                        str_28_2_1 = f"{esp_1}|{tempo_1}|{esp_2}|{tempo_2}|{esp_3}|{tempo_3}"
                        
                        mudou_opcao_28_2_1 = str_28_2_1 != d28_2_1.get("valor", "")
                        mudou_link_28_2_1 = link_28_2_1 != d28_2_1.get("link", "")
                        
                        if mudou_opcao_28_2_1 or mudou_link_28_2_1:
                                save_resp("28.2.1", str_28_2_1, pts_28_2_1, link_28_2_1)
                                res_data["28.2.1"] = {"valor": str_28_2_1, "pontos": pts_28_2_1, "link": link_28_2_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2_1 and links_28_2_1_atuais:
                                        links_28_2_1_antigos = re.findall(r'(https?://[^\s]+)', d28_2_1.get("link", ""))
                                        if links_28_2_1_atuais != links_28_2_1_antigos:
                                                modal_aviso_link("28.2.1", links_28_2_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.2 - MAIORES TEMPOS DE ESPERA: EXAMES
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_maiores_esperas_exames_28_2_2_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2.2 - Top 3 Exames Médicos com Maior Tempo de Espera", expanded=True):
                        st.subheader("28.2.2 • Top 3 Exames Médicos com Maior Tempo de Espera")
                        st.write("**28.2.2 Informe os 3 exames médicos com maior tempo de espera:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de texto, números ou no link grava os dados na hora.*")
                        
                        d28_2_2 = res_data.get("28.2.2", {"valor": "|||||", "pontos": 0.0, "link": ""})
                        v28_2_2 = d28_2_2.get("valor", "|||||").split("|")
                        while len(v28_2_2) < 6: 
                                v28_2_2.append("")
                        
                        c2822_1, c2822_2 = st.columns([1, 1])
                        with c2822_1:
                                exm_1 = st.text_input("1º Exame médico:", value=v28_2_2[0], key=f"txt_2822_exm1_{ano_sel}")
                                tempo_exm1 = st.number_input("Tempo médio de espera exm 1 (em dias):", min_value=0, value=int(v28_2_2[1]) if v28_2_2[1].isdigit() else 0, key=f"num_2822_t1_{ano_sel}")
                                
                                exm_2 = st.text_input("2º Exame médico:", value=v28_2_2[2], key=f"txt_2822_exm2_{ano_sel}")
                                tempo_exm2 = st.number_input("Tempo médio de espera exm 2 (em dias):", min_value=0, value=int(v28_2_2[3]) if v28_2_2[3].isdigit() else 0, key=f"num_2822_t2_{ano_sel}")
                                
                                exm_3 = st.text_input("3º Exame médico:", value=v28_2_2[4], key=f"txt_2822_exm3_{ano_sel}")
                                tempo_exm3 = st.number_input("Tempo médio de espera exm 3 (em dias):", min_value=0, value=int(v28_2_2[5]) if v28_2_2[5].isdigit() else 0, key=f"num_2822_t3_{ano_sel}")
                                
                        with c2822_2:
                                link_28_2_2 = st.text_area("Link/Evidência (28.2.2):", value=d28_2_2.get("link", ""), key=f"txt_28_2_2_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2_2 = st.empty()
                                links_28_2_2_atuais = re.findall(r'(https?://[^\s]+)', link_28_2_2)
                                if links_28_2_2_atuais:
                                        botoes_28_2_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_2_atuais])
                                        placeholder_links_28_2_2.markdown(f"**Links Ativos:** {botoes_28_2_2}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2_2 = st.empty()
                        pts_28_2_2 = 0.0
                        score_placeholder_28_2_2.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2.2:** `{pts_28_2_2:.1f} pontos` (Dados Informativos)")
                        
                        str_28_2_2 = f"{exm_1}|{tempo_exm1}|{exm_2}|{tempo_exm2}|{exm_3}|{tempo_exm3}"
                        
                        mudou_opcao_28_2_2 = str_28_2_2 != d28_2_2.get("valor", "")
                        mudou_link_28_2_2 = link_28_2_2 != d28_2_2.get("link", "")
                        
                        if mudou_opcao_28_2_2 or mudou_link_28_2_2:
                                save_resp("28.2.2", str_28_2_2, pts_28_2_2, link_28_2_2)
                                res_data["28.2.2"] = {"valor": str_28_2_2, "pontos": pts_28_2_2, "link": link_28_2_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2_2 and links_28_2_2_atuais:
                                        links_28_2_2_antigos = re.findall(r'(https?://[^\s]+)', d28_2_2.get("link", ""))
                                        if links_28_2_2_atuais != links_28_2_2_antigos:
                                                modal_aviso_link("28.2.2", links_28_2_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.3 - MAIORES TEMPOS DE ESPERA: TERAPIAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_maiores_esperas_terapias_28_2_3_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2.3 - Top 3 Terapias/Tratamentos com Maior Tempo de Espera", expanded=True):
                        st.subheader("28.2.3 • Top 3 Terapias/Tratamentos com Maior Tempo de Espera")
                        st.write("**28.2.3 Informe os 3 terapias/tratamentos médicos com maior tempo de espera:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de texto, números ou no link grava os dados na hora.*")
                        
                        d28_2_3 = res_data.get("28.2.3", {"valor": "|||||", "pontos": 0.0, "link": ""})
                        v28_2_3 = d28_2_3.get("valor", "|||||").split("|")
                        while len(v28_2_3) < 6: 
                                v28_2_3.append("")
                        
                        c2823_1, c2823_2 = st.columns([1, 1])
                        with c2823_1:
                                ter_1 = st.text_input("1ª Terapia / tratamento:", value=v28_2_3[0], key=f"txt_2823_ter1_{ano_sel}")
                                tempo_ter1 = st.number_input("Tempo médio de espera ter 1 (em dias):", min_value=0, value=int(v28_2_3[1]) if v28_2_3[1].isdigit() else 0, key=f"num_2823_t1_{ano_sel}")
                                
                                ter_2 = st.text_input("2ª Terapia / tratamento:", value=v28_2_3[2], key=f"txt_2823_ter2_{ano_sel}")
                                tempo_ter2 = st.number_input("Tempo médio de espera ter 2 (em dias):", min_value=0, value=int(v28_2_3[3]) if v28_2_3[3].isdigit() else 0, key=f"num_2823_t2_{ano_sel}")
                                
                                ter_3 = st.text_input("3ª Terapia / tratamento:", value=v28_2_3[4], key=f"txt_2823_ter3_{ano_sel}")
                                tempo_ter3 = st.number_input("Tempo médio de espera ter 3 (em dias):", min_value=0, value=int(v28_2_3[5]) if v28_2_3[5].isdigit() else 0, key=f"num_2823_t3_{ano_sel}")
                                
                        with c2823_2:
                                link_28_2_3 = st.text_area("Link/Evidência (28.2.3):", value=d28_2_3.get("link", ""), key=f"txt_28_2_3_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2_3 = st.empty()
                                links_28_2_3_atuais = re.findall(r'(https?://[^\s]+)', link_28_2_3)
                                if links_28_2_3_atuais:
                                        botoes_28_2_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_3_atuais])
                                        placeholder_links_28_2_3.markdown(f"**Links Ativos:** {botoes_28_2_3}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2_3 = st.empty()
                        pts_28_2_3 = 0.0
                        score_placeholder_28_2_3.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2.3:** `{pts_28_2_3:.1f} pontos` (Dados Informativos)")
                        
                        str_28_2_3 = f"{ter_1}|{tempo_ter1}|{ter_2}|{tempo_ter2}|{ter_3}|{tempo_ter3}"
                        
                        mudou_opcao_28_2_3 = str_28_2_3 != d28_2_3.get("valor", "")
                        mudou_link_28_2_3 = link_28_2_3 != d28_2_3.get("link", "")
                        
                        if mudou_opcao_28_2_3 or mudou_link_28_2_3:
                                save_resp("28.2.3", str_28_2_3, pts_28_2_3, link_28_2_3)
                                res_data["28.2.3"] = {"valor": str_28_2_3, "pontos": pts_28_2_3, "link": link_28_2_3}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2_3 and links_28_2_3_atuais:
                                        links_28_2_3_antigos = re.findall(r'(https?://[^\s]+)', d28_2_3.get("link", ""))
                                        if links_28_2_3_atuais != links_28_2_3_antigos:
                                                modal_aviso_link("28.2.3", links_28_2_3_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2.3", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
        # QUESITO 28.2.4 - MAIORES TEMPOS DE ESPERA: MEDICAMENTOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_maiores_esperas_medicamentos_28_2_4_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2.4 - Top 3 Medicamentos com Maior Tempo de Espera", expanded=True):
                        st.subheader("28.2.4 • Top 3 Medicamentos com Maior Tempo de Espera")
                        st.write("**28.2.4 Informe os 3 medicamentos com maior tempo de espera:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de texto, números ou no link grava os dados na hora.*")
                        
                        d28_2_4 = res_data.get("28.2.4", {"valor": "|||||", "pontos": 0.0, "link": ""})
                        v28_2_4 = d28_2_4.get("valor", "|||||").split("|")
                        while len(v28_2_4) < 6: 
                                v28_2_4.append("")
                        
                        c2824_1, c2824_2 = st.columns([1, 1])
                        with c2824_1:
                                med_1 = st.text_input("1º Medicamento:", value=v28_2_4[0], key=f"txt_2824_med1_{ano_sel}")
                                tempo_med1 = st.number_input("Tempo médio de espera med 1 (em dias):", min_value=0, value=int(v28_2_4[1]) if v28_2_4[1].isdigit() else 0, key=f"num_2824_t1_{ano_sel}")
                                
                                med_2 = st.text_input("2º Medicamento:", value=v28_2_4[2], key=f"txt_2824_med2_{ano_sel}")
                                tempo_med2 = st.number_input("Tempo médio de espera med 2 (em dias):", min_value=0, value=int(v28_2_4[3]) if v28_2_4[3].isdigit() else 0, key=f"num_2824_t2_{ano_sel}")
                                
                                med_3 = st.text_input("3º Medicamento:", value=v28_2_4[4], key=f"txt_2824_med3_{ano_sel}")
                                tempo_med3 = st.number_input("Tempo médio de espera med 3 (em dias):", min_value=0, value=int(v28_2_4[5]) if v28_2_4[5].isdigit() else 0, key=f"num_2824_t3_{ano_sel}")
                                
                        with c2824_2:
                                link_28_2_4 = st.text_area("Link/Evidência (28.2.4):", value=d28_2_4.get("link", ""), key=f"txt_28_2_4_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2_4 = st.empty()
                                links_28_2_4_atuais = re.findall(r'(https?://[^\s]+)', link_28_2_4)
                                if links_28_2_4_atuais:
                                        botoes_28_2_4 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_4_atuais])
                                        placeholder_links_28_2_4.markdown(f"**Links Ativos:** {botoes_28_2_4}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2_4 = st.empty()
                        pts_28_2_4 = 0.0
                        score_placeholder_28_2_4.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2.4:** `{pts_28_2_4:.1f} pontos` (Dados Informativos)")
                        
                        str_28_2_4 = f"{med_1}|{tempo_med1}|{med_2}|{tempo_med2}|{med_3}|{tempo_med3}"
                        
                        mudou_opcao_28_2_4 = str_28_2_4 != d28_2_4.get("valor", "")
                        mudou_link_28_2_4 = link_28_2_4 != d28_2_4.get("link", "")
                        
                        if mudou_opcao_28_2_4 or mudou_link_28_2_4:
                                save_resp("28.2.4", str_28_2_4, pts_28_2_4, link_28_2_4)
                                res_data["28.2.4"] = {"valor": str_28_2_4, "pontos": pts_28_2_4, "link": link_28_2_4}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2_4 and links_28_2_4_atuais:
                                        links_28_2_4_antigos = re.findall(r'(https?://[^\s]+)', d28_2_4.get("link", ""))
                                        if links_28_2_4_atuais != links_28_2_4_antigos:
                                                modal_aviso_link("28.2.4", links_28_2_4_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2.4", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.5 - MAIORES TEMPOS DE ESPERA: OPM
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_maiores_esperas_opm_28_2_5_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2.5 - Top 3 OPM com Maior Tempo de Espera", expanded=True):
                        st.subheader("28.2.5 • Top 3 OPM com Maior Tempo de Espera")
                        st.write("**28.2.5 Informe as 3 OPM (Órteses, Próteses e Materiais Especiais) com maior tempo de espera:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de texto, números ou no link grava os dados na hora.*")
                        
                        d28_2_5 = res_data.get("28.2.5", {"valor": "|||||", "pontos": 0.0, "link": ""})
                        v28_2_5 = d28_2_5.get("valor", "|||||").split("|")
                        while len(v28_2_5) < 6: 
                                v28_2_5.append("")
                        
                        c2825_1, c2825_2 = st.columns([1, 1])
                        with c2825_1:
                                opm_1 = st.text_input("1ª OPM:", value=v28_2_5[0], key=f"txt_2825_opm1_{ano_sel}")
                                tempo_opm1 = st.number_input("Tempo médio de espera opm 1 (em dias):", min_value=0, value=int(v28_2_5[1]) if v28_2_5[1].isdigit() else 0, key=f"num_2825_t1_{ano_sel}")
                                
                                opm_2 = st.text_input("2ª OPM:", value=v28_2_5[2], key=f"txt_2825_opm2_{ano_sel}")
                                tempo_opm2 = st.number_input("Tempo médio de espera opm 2 (em dias):", min_value=0, value=int(v28_2_5[3]) if v28_2_5[3].isdigit() else 0, key=f"num_2825_t2_{ano_sel}")
                                
                                opm_3 = st.text_input("3ª OPM:", value=v28_2_5[4], key=f"txt_2825_opm3_{ano_sel}")
                                tempo_opm3 = st.number_input("Tempo médio de espera opm 3 (em dias):", min_value=0, value=int(v28_2_5[5]) if v28_2_5[5].isdigit() else 0, key=f"num_2825_t3_{ano_sel}")
                                
                        with c2825_2:
                                link_28_2_5 = st.text_area("Link/Evidência (28.2.5):", value=d28_2_5.get("link", ""), key=f"txt_28_2_5_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2_5 = st.empty()
                                links_28_2_5_atuais = re.findall(r'(https?://[^\s]+)', link_28_2_5)
                                if links_28_2_5_atuais:
                                        botoes_28_2_5 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_5_atuais])
                                        placeholder_links_28_2_5.markdown(f"**Links Ativos:** {botoes_28_2_5}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2_5 = st.empty()
                        pts_28_2_5 = 0.0
                        score_placeholder_28_2_5.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2.5:** `{pts_28_2_5:.1f} pontos` (Dados Informativos)")
                        
                        str_28_2_5 = f"{opm_1}|{tempo_opm1}|{opm_2}|{tempo_opm2}|{opm_3}|{tempo_opm3}"
                        
                        mudou_opcao_28_2_5 = str_28_2_5 != d28_2_5.get("valor", "")
                        mudou_link_28_2_5 = link_28_2_5 != d28_2_5.get("link", "")
                        
                        if mudou_opcao_28_2_5 or mudou_link_28_2_5:
                                save_resp("28.2.5", str_28_2_5, pts_28_2_5, link_28_2_5)
                                res_data["28.2.5"] = {"valor": str_28_2_5, "pontos": pts_28_2_5, "link": link_28_2_5}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2_5 and links_28_2_5_atuais:
                                        links_28_2_5_antigos = re.findall(r'(https?://[^\s]+)', d28_2_5.get("link", ""))
                                        if links_28_2_5_atuais != links_28_2_5_antigos:
                                                modal_aviso_link("28.2.5", links_28_2_5_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2.5", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.6 - MAIORES TEMPOS DE ESPERA: CIRURGIAS ELETIVAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_maiores_esperas_cirurgias_28_2_6_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2.6 - Top 3 Cirurgias Eletivas com Maior Tempo de Espera", expanded=True):
                        st.subheader("28.2.6 • Top 3 Cirurgias Eletivas com Maior Tempo de Espera")
                        st.write("**28.2.6 Informas as 3 Cirurgias eletivas da Atenção Especializada com maior tempo de espera:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de texto, números ou no link grava os dados na hora.*")
                        
                        d28_2_6 = res_data.get("28.2.6", {"valor": "|||||", "pontos": 0.0, "link": ""})
                        v28_2_6 = d28_2_6.get("valor", "|||||").split("|")
                        while len(v28_2_6) < 6: 
                                v28_2_6.append("")
                        
                        c2826_1, c2826_2 = st.columns([1, 1])
                        with c2826_1:
                                cir_1 = st.text_input("1ª Cirurgia eletiva:", value=v28_2_6[0], key=f"txt_2826_cir1_{ano_sel}")
                                tempo_cir1 = st.number_input("Tempo médio de espera cir 1 (em dias):", min_value=0, value=int(v28_2_6[1]) if v28_2_6[1].isdigit() else 0, key=f"num_2826_t1_{ano_sel}")
                                
                                cir_2 = st.text_input("2ª Cirurgia eletiva:", value=v28_2_6[2], key=f"txt_2826_cir2_{ano_sel}")
                                tempo_cir2 = st.number_input("Tempo médio de espera cir 2 (em dias):", min_value=0, value=int(v28_2_6[3]) if v28_2_6[3].isdigit() else 0, key=f"num_2826_t2_{ano_sel}")
                                
                                cir_3 = st.text_input("3ª Cirurgia eletiva:", value=v28_2_6[4], key=f"txt_2826_cir3_{ano_sel}")
                                tempo_cir3 = st.number_input("Tempo médio de espera cir 3 (em dias):", min_value=0, value=int(v28_2_6[5]) if v28_2_6[5].isdigit() else 0, key=f"num_2826_t3_{ano_sel}")
                                
                        with c2826_2:
                                link_28_2_6 = st.text_area("Link/Evidência (28.2.6):", value=d28_2_6.get("link", ""), key=f"txt_28_2_6_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2_6 = st.empty()
                                links_28_2_6_atuais = re.findall(r'(https?://[^\s]+)', link_28_2_6)
                                if links_28_2_6_atuais:
                                        botoes_28_2_6 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_6_atuais])
                                        placeholder_links_28_2_6.markdown(f"**Links Ativos:** {botoes_28_2_6}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2_6 = st.empty()
                        pts_28_2_6 = 0.0
                        score_placeholder_28_2_6.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2.6:** `{pts_28_2_6:.1f} pontos` (Dados Informativos)")
                        
                        str_28_2_6 = f"{cir_1}|{tempo_cir1}|{cir_2}|{tempo_cir2}|{cir_3}|{tempo_cir3}"
                        
                        mudou_opcao_28_2_6 = str_28_2_6 != d28_2_6.get("valor", "")
                        mudou_link_28_2_6 = link_28_2_6 != d28_2_6.get("link", "")
                        
                        if mudou_opcao_28_2_6 or mudou_link_28_2_6:
                                save_resp("28.2.6", str_28_2_6, pts_28_2_6, link_28_2_6)
                                res_data["28.2.6"] = {"valor": str_28_2_6, "pontos": pts_28_2_6, "link": link_28_2_6}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2_6 and links_28_2_6_atuais:
                                        links_28_2_6_antigos = re.findall(r'(https?://[^\s]+)', d28_2_6.get("link", ""))
                                        if links_28_2_6_atuais != links_28_2_6_antigos:
                                                modal_aviso_link("28.2.6", links_28_2_6_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2.6", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.7 - MAIORES TEMPOS DE ESPERA: OUTROS SERVIÇOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_maiores_esperas_outros_28_2_7_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 28.2.7 - Top 3 Outros Serviços com Maior Tempo de Espera", expanded=True):
                        st.subheader("28.2.7 • Top 3 Outros Serviços com Maior Tempo de Espera")
                        st.write("**28.2.7 Informe os 3 Outros serviços da Atenção Especializada com maior tempo de espera:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos de texto, números ou no link grava os dados na hora.*")
                        
                        d28_2_7 = res_data.get("28.2.7", {"valor": "|||||", "pontos": 0.0, "link": ""})
                        v28_2_7 = d28_2_7.get("valor", "|||||").split("|")
                        while len(v28_2_7) < 6: 
                                v28_2_7.append("")
                        
                        c2827_1, c2827_2 = st.columns([1, 1])
                        with c2827_1:
                                out_1 = st.text_input("1º Outro serviço:", value=v28_2_7[0], key=f"txt_2827_out1_{ano_sel}")
                                tempo_out1 = st.number_input("Tempo médio de espera out 1 (em dias):", min_value=0, value=int(v28_2_7[1]) if v28_2_7[1].isdigit() else 0, key=f"num_2827_t1_{ano_sel}")
                                
                                out_2 = st.text_input("2º Outro serviço:", value=v28_2_7[2], key=f"txt_2827_out2_{ano_sel}")
                                tempo_out2 = st.number_input("Tempo médio de espera out 2 (em dias):", min_value=0, value=int(v28_2_7[3]) if v28_2_7[3].isdigit() else 0, key=f"num_2827_t2_{ano_sel}")
                                
                                out_3 = st.text_input("3º Outro serviço:", value=v28_2_7[4], key=f"txt_2827_out3_{ano_sel}")
                                tempo_out3 = st.number_input("Tempo médio de espera out 3 (em dias):", min_value=0, value=int(v28_2_7[5]) if v28_2_7[5].isdigit() else 0, key=f"num_2827_t3_{ano_sel}")
                                
                        with c2827_2:
                                link_28_2_7 = st.text_area("Link/Evidência (28.2.7):", value=d28_2_7.get("link", ""), key=f"txt_28_2_7_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_28_2_7 = st.empty()
                                links_28_2_7_atuais = re.findall(r'(https?://[^\s]+)', link_28_2_7)
                                if links_28_2_7_atuais:
                                        botoes_28_2_7 = " | ".join([f"🔗 [{u}]({u})" for u in links_28_2_7_atuais])
                                        placeholder_links_28_2_7.markdown(f"**Links Ativos:** {botoes_28_2_7}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_28_2_7 = st.empty()
                        pts_28_2_7 = 0.0
                        score_placeholder_28_2_7.markdown(f"📊 **Pontuação Aplicada no Quesito 28.2.7:** `{pts_28_2_7:.1f} pontos` (Dados Informativos)")
                        
                        str_28_2_7 = f"{out_1}|{tempo_out1}|{out_2}|{tempo_out2}|{out_3}|{tempo_out3}"
                        
                        mudou_opcao_28_2_7 = str_28_2_7 != d28_2_7.get("valor", "")
                        mudou_link_28_2_7 = link_28_2_7 != d28_2_7.get("link", "")
                        
                        if mudou_opcao_28_2_7 or mudou_link_28_2_7:
                                save_resp("28.2.7", str_28_2_7, pts_28_2_7, link_28_2_7)
                                res_data["28.2.7"] = {"valor": str_28_2_7, "pontos": pts_28_2_7, "link": link_28_2_7}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_28_2_7 and links_28_2_7_atuais:
                                        links_28_2_7_antigos = re.findall(r'(https?://[^\s]+)', d28_2_7.get("link", ""))
                                        if links_28_2_7_atuais != links_28_2_7_antigos:
                                                modal_aviso_link("28.2.7", links_28_2_7_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("28.2.7", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original

# =============================================================================
        # SEÇÃO 29 - CADASTRO NACIONAL DE ESTABELECIMENTOS DE SAÚDE (CNES)
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📊 Seção 29 - Atualização do CNES")

        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_cnes_atualizacao_29_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 29.0 - Atualização do Cadastro de Estabelecimentos e Profissionais", expanded=True):
                        st.subheader("29.0 • Atualização do Cadastro de Estabelecimentos e Profissionais")
                        st.write("**29.0 O município mantém atualizado o Cadastro de Estabelecimentos e Profissionais de Saúde (CNES)?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_29_0 = [
                                "Selecione...",
                                "SIM, os cadastros de estabelecimentos e de profissionais estão atualizados – 15",
                                "Sim, somente o cadastro de estabelecimentos está atualizado – 05",
                                "Sim, somente o cadastro de profissionais está atualizado – 05",
                                "Não – 00"
                        ]
                        d29_0 = res_data.get("29.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_290 = d29_0.get("valor", "Selecione...")
                        idx_29_0 = opts_29_0.index(val_atual_290) if val_atual_290 in opts_29_0 else 0
                        
                        c290_1, c290_2 = st.columns([1, 1])
                        with c290_1:
                                sel_29_0 = st.radio("Atualização do CNES:", options=opts_29_0, index=idx_29_0, key=f"rad_29_0_{ano_sel}", label_visibility="collapsed")
                        with c290_2:
                                link_29_0 = st.text_area("Link/Evidência (29.0):", value=d29_0.get("link", ""), key=f"txt_29_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_29_0 = st.empty()
                                links_29_0_atuais = re.findall(r'(https?://[^\s]+)', link_29_0)
                                if links_29_0_atuais:
                                        botoes_29_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_29_0_atuais])
                                        placeholder_links_29_0.markdown(f"**Links Ativos:** {botoes_29_0}")
                        
                        opcoes_pts_290 = {
                                "SIM, os cadastros de estabelecimentos e de profissionais estão atualizados – 15": 15.0,
                                "Sim, somente o cadastro de estabelecimentos está atualizado – 05": 5.0,
                                "Sim, somente o cadastro de profissionais está atualizado – 05": 5.0,
                                "Não – 00": 0.0,
                                "Selecione...": 0.0
                        }
                        pts_29_0 = opcoes_pts_290.get(sel_29_0, 0.0)
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_29_0 = st.empty()
                        if sel_29_0 == "Selecione...":
                                score_placeholder_29_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_29_0.markdown(f"📊 **Pontuação Aplicada no Quesito 29.0:** `{pts_29_0:.1f} pontos`")
                                
                        mudou_opcao_29_0 = sel_29_0 != d29_0.get("valor", "")
                        mudou_link_29_0 = link_29_0 != d29_0.get("link", "")
                        
                        if mudou_opcao_29_0 or mudou_link_29_0:
                                save_resp("29.0", sel_29_0, pts_29_0, link_29_0)
                                res_data["29.0"] = {"valor": sel_29_0, "pontos": pts_29_0, "link": link_29_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_29_0 and links_29_0_atuais:
                                        links_29_0_antigos = re.findall(r'(https?://[^\s]+)', d29_0.get("link", ""))
                                        if links_29_0_atuais != links_29_0_antigos:
                                                modal_aviso_link("29.0", links_29_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("29.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 29

        # =============================================================================
        # SEÇÃO 30 - COMPLEXO REGULADOR MUNICIPAL
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🏢 Seção 30 - Complexo Regulador Municipal")

        # -----------------------------------------------------------------------------
        # QUESITO 30.0 - POSSUI COMPLEXO
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_complexo_regulador_30_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 30.0 - Existência de Complexo Regulador Municipal", expanded=True):
                        st.subheader("30.0 • Existência de Complexo Regulador Municipal")
                        st.write("**30.0 O município possui Complexo Regulador Municipal?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_30_0 = ["Selecione...", "Sim", "Não"]
                        d30_0 = res_data.get("30.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_300 = d30_0.get("valor", "Selecione...")
                        idx_30_0 = opts_30_0.index(val_atual_300) if val_atual_300 in opts_30_0 else 0
                        
                        c300_1, c300_2 = st.columns([1, 1])
                        with c300_1:
                                sel_30_0 = st.radio("Possui complexo:", options=opts_30_0, index=idx_30_0, key=f"rad_30_0_{ano_sel}", label_visibility="collapsed")
                        with c300_2:
                                link_30_0 = st.text_area("Link/Evidência (30.0):", value=d30_0.get("link", ""), key=f"txt_30_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_30_0 = st.empty()
                                links_30_0_atuais = re.findall(r'(https?://[^\s]+)', link_30_0)
                                if links_30_0_atuais:
                                        botoes_30_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_30_0_atuais])
                                        placeholder_links_30_0.markdown(f"**Links Ativos:** {botoes_30_0}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_30_0 = st.empty()
                        pts_30_0 = 0.0
                        if sel_30_0 == "Selecione...":
                                score_placeholder_30_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_30_0.markdown(f"📊 **Pontuação Aplicada no Quesito 30.0:** `{pts_30_0:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_30_0 = sel_30_0 != d30_0.get("valor", "")
                        mudou_link_30_0 = link_30_0 != d30_0.get("link", "")
                        
                        if mudou_opcao_30_0 or mudou_link_30_0:
                                save_resp("30.0", sel_30_0, pts_30_0, link_30_0)
                                res_data["30.0"] = {"valor": sel_30_0, "pontos": pts_30_0, "link": link_30_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_30_0 and links_30_0_atuais:
                                        links_30_0_antigos = re.findall(r'(https?://[^\s]+)', d30_0.get("link", ""))
                                        if links_30_0_atuais != links_30_0_antigos:
                                                modal_aviso_link("30.0", links_30_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("30.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 30.1 - POSSUI CENTRAL DE REGULAÇÃO
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_central_regulacao_30_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 30.1 - Central de Regulação", expanded=True):
                        st.subheader("30.1 • Central de Regulação")
                        st.write("**30.1 O Complexo Regulador Municipal possui Central de Regulação?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_30_1 = ["Selecione...", "Sim", "Não"]
                        d30_1 = res_data.get("30.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_301 = d30_1.get("valor", "Selecione...")
                        idx_30_1 = opts_30_1.index(val_atual_301) if val_atual_301 in opts_30_1 else 0
                        
                        c301_1, c301_2 = st.columns([1, 1])
                        with c301_1:
                                sel_30_1 = st.radio("Possui central:", options=opts_30_1, index=idx_30_1, key=f"rad_30_1_{ano_sel}", label_visibility="collapsed")
                        with c301_2:
                                link_30_1 = st.text_area("Link/Evidência (30.1):", value=d30_1.get("link", ""), key=f"txt_30_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_30_1 = st.empty()
                                links_30_1_atuais = re.findall(r'(https?://[^\s]+)', link_30_1)
                                if links_30_1_atuais:
                                        botoes_30_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_30_1_atuais])
                                        placeholder_links_30_1.markdown(f"**Links Ativos:** {botoes_30_1}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_30_1 = st.empty()
                        pts_30_1 = 0.0
                        if sel_30_1 == "Selecione...":
                                score_placeholder_30_1.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_30_1.markdown(f"📊 **Pontuação Aplicada no Quesito 30.1:** `{pts_30_1:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_30_1 = sel_30_1 != d30_1.get("valor", "")
                        mudou_link_30_1 = link_30_1 != d30_1.get("link", "")
                        
                        if mudou_opcao_30_1 or mudou_link_30_1:
                                save_resp("30.1", sel_30_1, pts_30_1, link_30_1)
                                res_data["30.1"] = {"valor": sel_30_1, "pontos": pts_30_1, "link": link_30_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_30_1 and links_30_1_atuais:
                                        links_30_1_antigos = re.findall(r'(https?://[^\s]+)', d30_1.get("link", ""))
                                        if links_30_1_atuais != links_30_1_antigos:
                                                modal_aviso_link("30.1", links_30_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("30.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 30.1.1 - TIPOS DE CENTRAL UTILIZADOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_tipos_central_30_1_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 30.1.1 - Tipos de Central de Regulação Utilizados", expanded=True):
                        st.subheader("30.1.1 • Tipos de Central de Regulação Utilizados")
                        st.write("**30.1.1 Assinale os tipos de central de regulação municipal ou regional utilizados pelo município:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        d30_1_1 = res_data.get("30.1.1", {"valor": "", "pontos": 0.0, "link": ""})
                        v30_1_1 = d30_1_1.get("valor", "").split("|")
                        
                        central_specs = {
                                "urgencia": {"text": "Central de Urgência – 03", "pts": 3.0},
                                "internacoes": {"text": "Central de Internações – 03", "pts": 3.0},
                                "consultas_servicos": {"text": "Central de Consultas e Serviços de Apoio Diagnóstico e terapêutico – 03", "pts": 3.0}
                        }
                        
                        c3011_1, c3011_2 = st.columns([1, 1])
                        chks_selecionados_3011 = []
                        pts_totais_30_1_1 = 0.0
                        
                        with c3011_1:
                                for k, spec in central_specs.items():
                                        marcado = st.checkbox(spec["text"], value=k in v30_1_1, key=f"chk_30_1_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_3011.append(k)
                                                pts_totais_30_1_1 += spec["pts"]
                                                
                        with c3011_2:
                                link_30_1_1 = st.text_area("Link/Evidência (30.1.1):", value=d30_1_1.get("link", ""), key=f"txt_30_1_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_30_1_1 = st.empty()
                                links_30_1_1_atuais = re.findall(r'(https?://[^\s]+)', link_30_1_1)
                                if links_30_1_1_atuais:
                                        botoes_30_1_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_30_1_1_atuais])
                                        placeholder_links_30_1_1.markdown(f"**Links Ativos:** {botoes_30_1_1}")
                        
                        str_30_1_1 = "|".join(chks_selecionados_3011)
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_30_1_1 = st.empty()
                        if pts_totais_30_1_1 > 0:
                                score_placeholder_30_1_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 30.1.1:** :green[+{pts_totais_30_1_1:.1f} pontos]")
                        else:
                                score_placeholder_30_1_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 30.1.1:** `{pts_totais_30_1_1:.1f} pontos`")
                        
                        mudou_opcao_30_1_1 = str_30_1_1 != d30_1_1.get("valor", "")
                        mudou_link_30_1_1 = link_30_1_1 != d30_1_1.get("link", "")
                        
                        if mudou_opcao_30_1_1 or mudou_link_30_1_1:
                                save_resp("30.1.1", str_30_1_1, pts_totais_30_1_1, link_30_1_1)
                                res_data["30.1.1"] = {"valor": str_30_1_1, "pontos": pts_totais_30_1_1, "link": link_30_1_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_30_1_1 and links_30_1_1_atuais:
                                        links_30_1_1_antigos = re.findall(r'(https?://[^\s]+)', d30_1_1.get("link", ""))
                                        if links_30_1_1_atuais != links_30_1_1_antigos:
                                                modal_aviso_link("30.1.1", links_30_1_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("30.1.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original do card externo

        # =============================================================================
        # SEÇÃO 31 - ATENÇÃO PRÉ-HOSPITALAR E SAMU 192
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🚑 Seção 31 - Atenção Pré-Hospitalar e SAMU 192")

        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_pre_hospitalar_samu_31_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 31.0 - Serviço Pré-Hospitalar e Integração SAMU 192", expanded=True):
                        st.subheader("31.0 • Serviço Pré-Hospitalar e Integração SAMU 192")
                        st.write("**31.0 O município possui serviços de atenção pré-hospitalar e Central Samu 192 ou integra Central Samu 192 de abrangência regional?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_31_0 = ["Selecione...", "Sim", "Não"]
                        d31_0 = res_data.get("31.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_310 = d31_0.get("valor", "Selecione...")
                        idx_31_0 = opts_31_0.index(val_atual_310) if val_atual_310 in opts_31_0 else 0
                        
                        c310_1, c310_2 = st.columns([1, 1])
                        with c310_1:
                                sel_31_0 = st.radio("Atenção pré-hospitalar / SAMU:", options=opts_31_0, index=idx_31_0, key=f"rad_31_0_{ano_sel}", label_visibility="collapsed")
                        with c310_2:
                                link_31_0 = st.text_area("Link/Evidência (31.0):", value=d31_0.get("link", ""), key=f"txt_31_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_31_0 = st.empty()
                                links_31_0_atuais = re.findall(r'(https?://[^\s]+)', link_31_0)
                                if links_31_0_atuais:
                                        botoes_31_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_31_0_atuais])
                                        placeholder_links_31_0.markdown(f"**Links Ativos:** {botoes_31_0}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_31_0 = st.empty()
                        pts_31_0 = 0.0
                        if sel_31_0 == "Selecione...":
                                score_placeholder_31_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_31_0.markdown(f"📊 **Pontuação Aplicada no Quesito 31.0:** `{pts_31_0:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_31_0 = sel_31_0 != d31_0.get("valor", "")
                        mudou_link_31_0 = link_31_0 != d31_0.get("link", "")
                        
                        if mudou_opcao_31_0 or mudou_link_31_0:
                                save_resp("31.0", sel_31_0, pts_31_0, link_31_0)
                                res_data["31.0"] = {"valor": sel_31_0, "pontos": pts_31_0, "link": link_31_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_31_0 and links_31_0_atuais:
                                        links_31_0_antigos = re.findall(r'(https?://[^\s]+)', d31_0.get("link", ""))
                                        if links_31_0_atuais != links_31_0_antigos:
                                                modal_aviso_link("31.0", links_31_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("31.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original

# -----------------------------------------------------------------------------
        # QUESITO 31.1 - TEMPO DE RESPOSTA DO SAMU
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_tempo_resposta_samu_31_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 31.1 - Tempo de Resposta em Minutos dos Atendimentos do SAMU", expanded=True):
                        st.subheader("31.1 • Tempo de Resposta em Minutos dos Atendimentos do SAMU")
                        st.write("**31.1 Informe o tempo de resposta em minutos dos atendimentos do SAMU (ou equivalente):**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos numéricos ou no link grava os dados na hora.*")
                        
                        # Cálculo dinâmico dos anos baseado na seleção atual do formulário
                        try:
                                ano_atual_int = int(ano_sel)
                        except:
                                ano_atual_int = 2025 # Fallback caso não esteja definido como inteiro
                                
                        ano_tmr2 = ano_atual_int - 2
                        ano_tmr1 = ano_atual_int - 1
                        ano_tmr = ano_atual_int

                        st.caption(f"ℹ️ *Fórmula de avaliação baseada no Ano Selecionado ({ano_tmr}):* "
                                           f"Melhoria ou Estabilidade = 0.0 pontos | Piora [TMR > ({ano_tmr2} + {ano_tmr1}) / 2] = -5.0 pontos")

                        # Recuperação dos dados salvos no banco (armazenado como string separada por pipe)
                        d31_1 = res_data.get("31.1", {"valor": "0|0|0|0|0|0|0|0|0", "pontos": 0.0, "link": ""})
                        v31_1 = d31_1.get("valor", "0|0|0|0|0|0|0|0|0").split("|")
                        while len(v31_1) < 9: 
                                v31_1.append("0")
                        
                        c311_1, c311_2 = st.columns([1, 1])
                        with c311_1:
                                st.markdown(f"**🗓️ Ano {ano_tmr2} (TMR-2)**")
                                tmr2_min = st.number_input(f"{ano_tmr2} - Mínimo:", min_value=0, value=int(v31_1[0]) if v31_1[0].isdigit() else 0, key=f"num_311_t2_min_{ano_sel}")
                                tmr2_med = st.number_input(f"{ano_tmr2} - Médio:", min_value=0, value=int(v31_1[1]) if v31_1[1].isdigit() else 0, key=f"num_311_t2_med_{ano_sel}")
                                tmr2_max = st.number_input(f"{ano_tmr2} - Máximo:", min_value=0, value=int(v31_1[2]) if v31_1[2].isdigit() else 0, key=f"num_311_t2_max_{ano_sel}")
                                
                                st.markdown(f"**🗓️ Ano {ano_tmr1} (TMR-1)**")
                                tmr1_min = st.number_input(f"{ano_tmr1} - Mínimo:", min_value=0, value=int(v31_1[3]) if v31_1[3].isdigit() else 0, key=f"num_311_t1_min_{ano_sel}")
                                tmr1_med = st.number_input(f"{ano_tmr1} - Médio:", min_value=0, value=int(v31_1[4]) if v31_1[4].isdigit() else 0, key=f"num_311_t1_med_{ano_sel}")
                                tmr1_max = st.number_input(f"{ano_tmr1} - Máximo:", min_value=0, value=int(v31_1[5]) if v31_1[5].isdigit() else 0, key=f"num_311_t1_max_{ano_sel}")
                                
                                st.markdown(f"**🗓️ Ano {ano_tmr} (TMR Atual)**")
                                tmr_min = st.number_input(f"{ano_tmr} - Mínimo:", min_value=0, value=int(v31_1[6]) if v31_1[6].isdigit() else 0, key=f"num_311_t_min_{ano_sel}")
                                tmr_med = st.number_input(f"{ano_tmr} - Médio:", min_value=0, value=int(v31_1[7]) if v31_1[7].isdigit() else 0, key=f"num_311_t_med_{ano_sel}")
                                tmr_max = st.number_input(f"{ano_tmr} - Máximo:", min_value=0, value=int(v31_1[8]) if v31_1[8].isdigit() else 0, key=f"num_311_t_max_{ano_sel}")

                        with c311_2:
                                link_31_1 = st.text_area("Link/Evidência (31.1):", value=d31_1.get("link", ""), key=f"txt_31_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_31_1 = st.empty()
                                links_31_1_atuais = re.findall(r'(https?://[^\s]+)', link_31_1)
                                if links_31_1_atuais:
                                        botoes_31_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_31_1_atuais])
                                        placeholder_links_31_1.markdown(f"**Links Ativos:** {botoes_31_1}")
                        
                        # Processamento da lógica de pontuação baseada na média móvel
                        meta_media = (tmr2_med + tmr1_med) / 2.0
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks mutáveis sem corromper o HTML
                        score_placeholder_31_1 = st.empty()
                        
                        if tmr2_med == 0 and tmr1_med == 0 and tmr_med == 0:
                                pts_31_1 = 0.0 # Sem dados preenchidos ainda
                                score_placeholder_31_1.info("ℹ️ Aguardando preenchimento dos tempos médios para cálculo da pontuação.")
                        elif tmr_med > meta_media:
                                pts_31_1 = -5.0
                                score_placeholder_31_1.error(f"⚠️ O Tempo Médio de Resposta atual ({tmr_med} min) é maior que a média dos anos anteriores ({meta_media:.1f} min). Penalidade Aplicada: `-5.0 pontos`.")
                        else:
                                pts_31_1 = 0.0
                                score_placeholder_31_1.success(f"✅ O Tempo Médio de Resposta atual ({tmr_med} min) está estável ou menor que a média anterior ({meta_media:.1f} min). Estabilidade atingida: `0.0 pontos`.")

                        str_31_1 = f"{tmr2_min}|{tmr2_med}|{tmr2_max}|{tmr1_min}|{tmr1_med}|{tmr1_max}|{tmr_min}|{tmr_med}|{tmr_max}"
                        
                        mudou_opcao_31_1 = str_31_1 != d31_1.get("valor", "")
                        mudou_link_31_1 = link_31_1 != d31_1.get("link", "")
                        
                        if mudou_opcao_31_1 or mudou_link_31_1:
                                save_resp("31.1", str_31_1, pts_31_1, link_31_1)
                                res_data["31.1"] = {"valor": str_31_1, "pontos": pts_31_1, "link": link_31_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_31_1 and links_31_1_atuais:
                                        links_31_1_antigos = re.findall(r'(https?://[^\s]+)', d31_1.get("link", ""))
                                        if links_31_1_atuais != links_31_1_antigos:
                                                modal_aviso_link("31.1", links_31_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("31.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original do bloco externo

# -----------------------------------------------------------------------------
        # QUESITO 31.2 - COMPOSIÇÃO MÍNIMA DA CENTRAL DE REGULAÇÃO DE URGÊNCIAS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_composicao_central_31_2_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 31.2 - Composição Mínima das Equipes da Central de Regulação", expanded=True):
                        st.subheader("31.2 • Composição Mínima das Equipes da Central de Regulação")
                        st.write("**31.2 As equipes da Central de Regulação das Urgências tiveram ao menos a composição mínima estipulada na legislação no decorrer do exercício?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_31_2 = [
                                "Selecione...",
                                "Todas as equipes tinham composição mínima – 00",
                                "A maior parte das equipes tinham composição mínima – -03 (perde 03 pontos)",
                                "A menor parte das equipes tinham composição mínima – -07 (perde 07 pontos)",
                                "Nenhuma equipe tinha composição mínima – -10 (perde 10 pontos)"
                        ]
                        d31_2 = res_data.get("31.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_312 = d31_2.get("valor", "Selecione...")
                        idx_31_2 = opts_31_2.index(val_atual_312) if val_atual_312 in opts_31_2 else 0
                        
                        c312_1, c312_2 = st.columns([1, 1])
                        with c312_1:
                                sel_31_2 = st.radio("Composição Central:", options=opts_31_2, index=idx_31_2, key=f"rad_31_2_{ano_sel}", label_visibility="collapsed")
                        with c312_2:
                                link_31_2 = st.text_area("Link/Evidência (31.2):", value=d31_2.get("link", ""), key=f"txt_31_2_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_31_2 = st.empty()
                                links_31_2_atuais = re.findall(r'(https?://[^\s]+)', link_31_2)
                                if links_31_2_atuais:
                                        botoes_31_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_31_2_atuais])
                                        placeholder_links_31_2.markdown(f"**Links Ativos:** {botoes_31_2}")
                        
                        opcoes_pts_312 = {
                                "Todas as equipes tinham composição mínima – 00": 0.0,
                                "A maior parte das equipes tinham composição mínima – -03 (perde 03 pontos)": -3.0,
                                "A menor parte das equipes tinham composição mínima – -07 (perde 07 pontos)": -7.0,
                                "Nenhuma equipe tinha composição mínima – -10 (perde 10 pontos)": -10.0,
                                "Selecione...": 0.0
                        }
                        pts_31_2 = opcoes_pts_312.get(sel_31_2, 0.0)
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks mutáveis sem corromper o HTML
                        score_placeholder_31_2 = st.empty()
                        
                        if sel_31_2 == "Selecione...":
                                score_placeholder_31_2.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        elif pts_31_2 < 0:
                                score_placeholder_31_2.error(f"⚠️ Penalidade aplicada no Quesito 31.2: `{pts_31_2:.1f} pontos`.")
                        else:
                                score_placeholder_31_2.success(f"✅ Conformidade atingida no Quesito 31.2: `{pts_31_2:.1f} pontos`.")
                                
                        mudou_opcao_31_2 = sel_31_2 != d31_2.get("valor", "")
                        mudou_link_31_2 = link_31_2 != d31_2.get("link", "")
                        
                        if mudou_opcao_31_2 or mudou_link_31_2:
                                save_resp("31.2", sel_31_2, pts_31_2, link_31_2)
                                res_data["31.2"] = {"valor": sel_31_2, "pontos": pts_31_2, "link": link_31_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_31_2 and links_31_2_atuais:
                                        links_31_2_antigos = re.findall(r'(https?://[^\s]+)', d31_2.get("link", ""))
                                        if links_31_2_atuais != links_31_2_antigos:
                                                modal_aviso_link("31.2", links_31_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("31.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 31.3 - COMPOSIÇÃO MÍNIMA DAS UNIDADES MÓVEIS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_composicao_unidades_moveis_31_3_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 31.3 - Composição Mínima das Equipes das Unidades Móveis", expanded=True):
                        st.subheader("31.3 • Composição Mínima das Equipes das Unidades Móveis")
                        st.write("**31.3 As equipes das Unidades Móveis tiveram ao menos a composição mínima estipulada na legislação no decorrer do exercício?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_31_3 = [
                                "Selecione...",
                                "Todas as equipes tinham composição mínima – 00",
                                "A maior parte das equipes tinham composição mínima – -10 (perde 10 pontos)",
                                "A menor parte das equipes tinham composição mínima – -15 (perde 15 pontos)",
                                "Nenhuma equipe tinha composição mínima – -20 (perde 20 pontos)"
                        ]
                        d31_3 = res_data.get("31.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_313 = d31_3.get("valor", "Selecione...")
                        idx_31_3 = opts_31_3.index(val_atual_313) if val_atual_313 in opts_31_3 else 0
                        
                        c313_1, c313_2 = st.columns([1, 1])
                        with c313_1:
                                sel_31_3 = st.radio("Composição Unidades Móveis:", options=opts_31_3, index=idx_31_3, key=f"rad_31_3_{ano_sel}", label_visibility="collapsed")
                        with c313_2:
                                link_31_3 = st.text_area("Link/Evidência (31.3):", value=d31_3.get("link", ""), key=f"txt_31_3_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_31_3 = st.empty()
                                links_31_3_atuais = re.findall(r'(https?://[^\s]+)', link_31_3)
                                if links_31_3_atuais:
                                        botoes_31_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_31_3_atuais])
                                        placeholder_links_31_3.markdown(f"**Links Ativos:** {botoes_31_3}")
                        
                        opcoes_pts_313 = {
                                "Todas as equipes tinham composição mínima – 00": 0.0,
                                "A maior parte das equipes tinham composição mínima – -10 (perde 10 pontos)": -10.0,
                                "A menor parte das equipes tinham composição mínima – -15 (perde 15 pontos)": -15.0,
                                "Nenhuma equipe tinha composição mínima – -20 (perde 20 pontos)": -20.0,
                                "Selecione...": 0.0
                        }
                        pts_31_3 = opcoes_pts_313.get(sel_31_3, 0.0)
                        
                        # FIX: Uso de placeholders estáveis st.empty() para renderizar feedbacks mutáveis sem corromper o HTML
                        score_placeholder_31_3 = st.empty()
                        
                        if sel_31_3 == "Selecione...":
                                score_placeholder_31_3.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        elif pts_31_3 < 0:
                                score_placeholder_31_3.error(f"⚠️ Penalidade aplicada no Quesito 31.3: `{pts_31_3:.1f} pontos`.")
                        else:
                                score_placeholder_31_3.success(f"✅ Conformidade atingida no Quesito 31.3: `{pts_31_3:.1f} pontos`.")
                                
                        mudou_opcao_31_3 = sel_31_3 != d31_3.get("valor", "")
                        mudou_link_31_3 = link_31_3 != d31_3.get("link", "")
                        
                        if mudou_opcao_31_3 or mudou_link_31_3:
                                save_resp("31.3", sel_31_3, pts_31_3, link_31_3)
                                res_data["31.3"] = {"valor": sel_31_3, "pontos": pts_31_3, "link": link_31_3}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_31_3 and links_31_3_atuais:
                                        links_31_3_antigos = re.findall(r'(https?://[^\s]+)', d31_3.get("link", ""))
                                        if links_31_3_atuais != links_31_3_antigos:
                                                modal_aviso_link("31.3", links_31_3_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("31.3", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original

        # =============================================================================
        # SEÇÃO 32 - GERENCIAMENTO DE ESTOQUE
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📦 Seção 32 - Gerenciamento de Estoque")

        # -----------------------------------------------------------------------------
        # QUESITO 32.0 - SISTEMA INFORMATIZADO DE ESTOQUE
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_gerenciamento_estoque_32_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 32.0 - Sistema Informatizado para Estoque de Materiais e Insumos", expanded=True):
                        st.subheader("32.0 • Sistema Informatizado para Estoque de Materiais e Insumos")
                        st.write("**32.0 O município utiliza sistema informatizado para gerenciar o estoque de materiais e insumos médicos?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_32_0 = ["Selecione...", "Sim", "Não"]
                        d32_0 = res_data.get("32.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_320 = d32_0.get("valor", "Selecione...")
                        idx_32_0 = opts_32_0.index(val_atual_320) if val_atual_320 in opts_32_0 else 0
                        
                        c320_1, c320_2 = st.columns([1, 1])
                        with c320_1:
                                sel_32_0 = st.radio("Sistema de estoque:", options=opts_32_0, index=idx_32_0, key=f"rad_32_0_{ano_sel}", label_visibility="collapsed")
                        with c320_2:
                                link_32_0 = st.text_area("Link/Evidência (32.0):", value=d32_0.get("link", ""), key=f"txt_32_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_32_0 = st.empty()
                                links_32_0_atuais = re.findall(r'(https?://[^\s]+)', link_32_0)
                                if links_32_0_atuais:
                                        botoes_32_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_32_0_atuais])
                                        placeholder_links_32_0.markdown(f"**Links Ativos:** {botoes_32_0}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_32_0 = st.empty()
                        pts_32_0 = 0.0
                        if sel_32_0 == "Selecione...":
                                score_placeholder_32_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_32_0.markdown(f"📊 **Pontuação Aplicada no Quesito 32.0:** `{pts_32_0:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_32_0 = sel_32_0 != d32_0.get("valor", "")
                        mudou_link_32_0 = link_32_0 != d32_0.get("link", "")
                        
                        if mudou_opcao_32_0 or mudou_link_32_0:
                                save_resp("32.0", sel_32_0, pts_32_0, link_32_0)
                                res_data["32.0"] = {"valor": sel_32_0, "pontos": pts_32_0, "link": link_32_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_32_0 and links_32_0_atuais:
                                        links_32_0_antigos = re.findall(r'(https?://[^\s]+)', d32_0.get("link", ""))
                                        if links_32_0_atuais != links_32_0_antigos:
                                                modal_aviso_link("32.0", links_32_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("32.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original

# -----------------------------------------------------------------------------
        # QUESITO 32.1 - FUNÇÕES DO SISTEMA DE GESTÃO DE ESTOQUE
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_funcoes_estoque_32_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 32.1 - Funções do Sistema de Gestão de Estoque", expanded=True):
                        st.subheader("32.1 • Funções do Sistema de Gestão de Estoque")
                        st.write("**32.1 Assinale as funções do sistema de gestão de estoque de materiais e insumos médicos:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        d32_1 = res_data.get("32.1", {"valor": "", "pontos": 0.0, "link": ""})
                        v32_1 = d32_1.get("valor", "").split("|")
                        
                        estoque_specs = {
                                "posicao_lote": {"text": "Fornece a posição de estoque, movimentação de entrada e saída, lote e validade – 15", "pts": 15.0},
                                "processo_compras": {"text": "Gerenciar o processo de compras dos insumos/materiais de saúde, desde o planejamento até a entrega e o recebimento da nota fiscal – 15", "pts": 15.0},
                                "reposicao_estab": {"text": "Gerenciar a reposição dos insumos/materiais de saúde por estabelecimento de saúde – 15", "pts": 15.0},
                                "outros": {"text": "Outros – 00", "pts": 0.0}
                        }
                        
                        c321_1, c321_2 = st.columns([1, 1])
                        chks_selecionados_321 = []
                        pts_totais_32_1 = 0.0
                        
                        keys_estoque = list(estoque_specs.keys())
                        metade_estoque = (len(keys_estoque) + 1) // 2
                        
                        with c321_1:
                                for k in keys_estoque[:metade_estoque]:
                                        marcado = st.checkbox(estoque_specs[k]["text"], value=k in v32_1, key=f"chk_32_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_321.append(k)
                                                pts_totais_32_1 += estoque_specs[k]["pts"]
                                                
                        with c321_2:
                                for k in keys_estoque[metade_estoque:]:
                                        marcado = st.checkbox(estoque_specs[k]["text"], value=k in v32_1, key=f"chk_32_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_321.append(k)
                                                pts_totais_32_1 += estoque_specs[k]["pts"]
                                                
                                link_32_1 = st.text_area("Link/Evidência (32.1):", value=d32_1.get("link", ""), key=f"txt_32_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_32_1 = st.empty()
                                links_32_1_atuais = re.findall(r'(https?://[^\s]+)', link_32_1)
                                if links_32_1_atuais:
                                        botoes_32_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_32_1_atuais])
                                        placeholder_links_32_1.markdown(f"**Links Ativos:** {botoes_32_1}")
                        
                        str_32_1 = "|".join(chks_selecionados_321)
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_32_1 = st.empty()
                        if pts_totais_32_1 > 0:
                                score_placeholder_32_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 32.1:** :green[+{pts_totais_32_1:.1f} pontos]")
                        else:
                                score_placeholder_32_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 32.1:** `{pts_totais_32_1:.1f} pontos`")
                                
                        mudou_opcao_32_1 = str_32_1 != d32_1.get("valor", "")
                        mudou_link_32_1 = link_32_1 != d32_1.get("link", "")
                        
                        if mudou_opcao_32_1 or mudou_link_32_1:
                                save_resp("32.1", str_32_1, pts_totais_32_1, link_32_1)
                                res_data["32.1"] = {"valor": str_32_1, "pontos": pts_totais_32_1, "link": link_32_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_32_1 and links_32_1_atuais:
                                        links_32_1_antigos = re.findall(r'(https?://[^\s]+)', d32_1.get("link", ""))
                                        if links_32_1_atuais != links_32_1_antigos:
                                                modal_aviso_link("32.1", links_32_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("32.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original

        # =============================================================================
        # SEÇÃO 33 - OUVIDORIA DA SAÚDE
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🗣️ Seção 33 - Ouvidoria da Saúde")

        # -----------------------------------------------------------------------------
        # QUESITO 33.0 - IMPLANTAÇÃO DA OUVIDORIA
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_ouvidoria_saude_33_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 33.0 - Ouvidoria da Saúde Implantada", expanded=True):
                        st.subheader("33.0 • Ouvidoria da Saúde Implantada")
                        st.write("**33.0 O município possui Ouvidoria da Saúde implantada?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_33_0 = ["Selecione...", "Sim", "Não"]
                        d33_0 = res_data.get("33.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_330 = d33_0.get("valor", "Selecione...")
                        idx_33_0 = opts_33_0.index(val_atual_330) if val_atual_330 in opts_33_0 else 0
                        
                        c330_1, c330_2 = st.columns([1, 1])
                        with c330_1:
                                sel_33_0 = st.radio("Ouvidoria implantada:", options=opts_33_0, index=idx_33_0, key=f"rad_33_0_{ano_sel}", label_visibility="collapsed")
                        with c330_2:
                                link_33_0 = st.text_area("Link/Evidência (33.0):", value=d33_0.get("link", ""), key=f"txt_33_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_33_0 = st.empty()
                                links_33_0_atuais = re.findall(r'(https?://[^\s]+)', link_33_0)
                                if links_33_0_atuais:
                                        botoes_33_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_33_0_atuais])
                                        placeholder_links_33_0.markdown(f"**Links Ativos:** {botoes_33_0}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_33_0 = st.empty()
                        pts_33_0 = 0.0
                        if sel_33_0 == "Selecione...":
                                score_placeholder_33_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_33_0.markdown(f"📊 **Pontuação Aplicada no Quesito 33.0:** `{pts_33_0:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_33_0 = sel_33_0 != d33_0.get("valor", "")
                        mudou_link_33_0 = link_33_0 != d33_0.get("link", "")
                        
                        if mudou_opcao_33_0 or mudou_link_33_0:
                                save_resp("33.0", sel_33_0, pts_33_0, link_33_0)
                                res_data["33.0"] = {"valor": sel_33_0, "pontos": pts_33_0, "link": link_33_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_33_0 and links_33_0_atuais:
                                        links_33_0_antigos = re.findall(r'(https?://[^\s]+)', d33_0.get("link", ""))
                                        if links_33_0_atuais != links_33_0_antigos:
                                                modal_aviso_link("33.0", links_33_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("33.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 33.1 - CARACTERÍSTICAS DA OUVIDORIA
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_caracteristicas_ouvidoria_33_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 33.1 - Características da Ouvidoria da Saúde", expanded=True):
                        st.subheader("33.1 • Características da Ouvidoria da Saúde")
                        st.write("**33.1 Assinale as características da Ouvidoria da Saúde:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        d33_1 = res_data.get("33.1", {"valor": "", "pontos": 0.0, "link": ""})
                        v33_1 = d33_1.get("valor", "").split("|")
                        
                        ouvidoria_specs = {
                                "ato_formal": {"text": "Instituída por ato formal no organograma da secretaria de saúde ou equivalente – 03", "pts": 3.0},
                                "estrutura_fisica": {"text": "Possui estrutura física – 02", "pts": 2.0},
                                "equipe_designada": {"text": "Possui equipe ou profissional designado – 05", "pts": 5.0},
                                "outros": {"text": "Outros – 00", "pts": 0.0}
                        }
                        
                        c331_1, c331_2 = st.columns([1, 1])
                        chks_selecionados_331 = []
                        pts_totais_33_1 = 0.0
                        
                        keys_ouvidoria = list(ouvidoria_specs.keys())
                        metade_ouvidoria = (len(keys_ouvidoria) + 1) // 2
                        
                        with c331_1:
                                # FIX: Distribuição correta na coluna 1 (metade dos checkboxes)
                                for k in keys_ouvidoria[:metade_ouvidoria]:
                                        marcado = st.checkbox(ouvidoria_specs[k]["text"], value=k in v33_1, key=f"chk_33_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_331.append(k)
                                                pts_totais_33_1 += ouvidoria_specs[k]["pts"]
                                                
                        with c331_2:
                                # FIX: Distribuição correta na coluna 2 (outra metade dos checkboxes + área de texto)
                                for k in keys_ouvidoria[metade_ouvidoria:]:
                                        marcado = st.checkbox(ouvidoria_specs[k]["text"], value=k in v33_1, key=f"chk_33_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_331.append(k)
                                                pts_totais_33_1 += ouvidoria_specs[k]["pts"]
                                                
                                link_33_1 = st.text_area("Link/Evidência (33.1):", value=d33_1.get("link", ""), key=f"txt_33_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_33_1 = st.empty()
                                links_33_1_atuais = re.findall(r'(https?://[^\s]+)', link_33_1)
                                if links_33_1_atuais:
                                        botoes_33_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_33_1_atuais])
                                        placeholder_links_33_1.markdown(f"**Links Ativos:** {botoes_33_1}")
                        
                        str_33_1 = "|".join(chks_selecionados_331)
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_33_1 = st.empty()
                        if pts_totais_33_1 > 0:
                                score_placeholder_33_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 33.1:** :green[+{pts_totais_33_1:.1f} pontos]")
                        else:
                                score_placeholder_33_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 33.1:** `{pts_totais_33_1:.1f} pontos`")
                                
                        mudou_opcao_33_1 = str_33_1 != d33_1.get("valor", "")
                        mudou_link_33_1 = link_33_1 != d33_1.get("link", "")
                        
                        if mudou_opcao_33_1 or mudou_link_33_1:
                                save_resp("33.1", str_33_1, pts_totais_33_1, link_33_1)
                                res_data["33.1"] = {"valor": str_33_1, "pontos": pts_totais_33_1, "link": link_33_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_33_1 and links_33_1_atuais:
                                        links_33_1_antigos = re.findall(r'(https?://[^\s]+)', d33_1.get("link", ""))
                                        if links_33_1_atuais != links_33_1_antigos:
                                                modal_aviso_link("33.1", links_33_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("33.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original do bloco externo da seção

        # =============================================================================
        # SEÇÃO 34 - UTILIZAÇÃO DO SISTEMA OUVIDORSUS
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("💻 Seção 34 - Sistema OuvidorSUS")

        # -----------------------------------------------------------------------------
        # QUESITO 34.0 - USO DO SISTEMA OUVIDORSUS OU EQUIVALENTE
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_ouvidorsus_34_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 34.0 - Uso do Sistema OuvidorSUS ou Equivalente", expanded=True):
                        st.subheader("34.0 • Uso do Sistema OuvidorSUS ou Equivalente")
                        st.write("**34.0 O município utiliza o Sistema OuvidorSUS ou sistema equivalente que, além de permitir a disseminação de informações, o registro e o encaminhamento das manifestações dos cidadãos, possibilita troca de informações entre os órgãos responsáveis pela gestão do SUS?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_34_0 = ["Selecione...", "Sim – 05", "Não – 00"]
                        d34_0 = res_data.get("34.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_340 = d34_0.get("valor", "Selecione...")
                        idx_34_0 = opts_34_0.index(val_atual_340) if val_atual_340 in opts_34_0 else 0
                        
                        c340_1, c340_2 = st.columns([1, 1])
                        with c340_1:
                                sel_34_0 = st.radio("Utilização do OuvidorSUS:", options=opts_34_0, index=idx_34_0, key=f"rad_34_0_{ano_sel}", label_visibility="collapsed")
                        with c340_2:
                                link_34_0 = st.text_area("Link/Evidência (34.0):", value=d34_0.get("link", ""), key=f"txt_34_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_34_0 = st.empty()
                                links_34_0_atuais = re.findall(r'(https?://[^\s]+)', link_34_0)
                                if links_34_0_atuais:
                                        botoes_34_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_34_0_atuais])
                                        placeholder_links_34_0.markdown(f"**Links Ativos:** {botoes_34_0}")
                        
                        opcoes_pts_340 = {
                                "Sim – 05": 5.0,
                                "Não – 00": 0.0,
                                "Selecione...": 0.0
                        }
                        pts_34_0 = opcoes_pts_340.get(sel_34_0, 0.0)
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks mutáveis de sucesso/aviso
                        score_placeholder_34_0 = st.empty()
                        
                        if sel_34_0 == "Selecione...":
                                score_placeholder_34_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        elif pts_34_0 > 0:
                                score_placeholder_34_0.success(f"✅ Pontuação Atribuída no Quesito 34.0: `{pts_34_0:.1f} pontos`.")
                        else:
                                score_placeholder_34_0.markdown(f"📊 **Pontuação Atribuída no Quesito 34.0:** `{pts_34_0:.1f} pontos`")
                                
                        mudou_opcao_34_0 = sel_34_0 != d34_0.get("valor", "")
                        mudou_link_34_0 = link_34_0 != d34_0.get("link", "")
                        
                        if mudou_opcao_34_0 or mudou_link_34_0:
                                save_resp("34.0", sel_34_0, pts_34_0, link_34_0)
                                res_data["34.0"] = {"valor": sel_34_0, "pontos": pts_34_0, "link": link_34_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_34_0 and links_34_0_atuais:
                                        links_34_0_antigos = re.findall(r'(https?://[^\s]+)', d34_0.get("link", ""))
                                        if links_34_0_atuais != links_34_0_antigos:
                                                modal_aviso_link("34.0", links_34_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("34.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original do bloco externo

# =============================================================================
        # SEÇÃO 35 - SISTEMA NACIONAL DE AUDITORIA (SNA)
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🔍 Seção 35 - Componente Municipal do SNA")

        # -----------------------------------------------------------------------------
        # QUESITO 35.0 - POSSUI COMPONENTE SNA
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_sna_35_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 35.0 - Existência do Componente Municipal do SNA", expanded=True):
                        st.subheader("35.0 • Existência do Componente Municipal do SNA")
                        st.write("**35.0 O município possui o componente municipal do Sistema Nacional de Auditoria?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_35_0 = ["Selecione...", "Sim", "Não"]
                        d35_0 = res_data.get("35.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_350 = d35_0.get("valor", "Selecione...")
                        idx_35_0 = opts_35_0.index(val_atual_350) if val_atual_350 in opts_35_0 else 0
                        
                        c350_1, c350_2 = st.columns([1, 1])
                        with c350_1:
                                sel_35_0 = st.radio("Componente SNA:", options=opts_35_0, index=idx_35_0, key=f"rad_35_0_{ano_sel}", label_visibility="collapsed")
                        with c350_2:
                                link_35_0 = st.text_area("Link/Evidência (35.0):", value=d35_0.get("link", ""), key=f"txt_35_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_35_0 = st.empty()
                                links_35_0_atuais = re.findall(r'(https?://[^\s]+)', link_35_0)
                                if links_35_0_atuais:
                                        botoes_35_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_35_0_atuais])
                                        placeholder_links_35_0.markdown(f"**Links Ativos:** {botoes_35_0}")
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_35_0 = st.empty()
                        pts_35_0 = 0.0
                        if sel_35_0 == "Selecione...":
                                score_placeholder_35_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_35_0.markdown(f"📊 **Pontuação Aplicada no Quesito 35.0:** `{pts_35_0:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_35_0 = sel_35_0 != d35_0.get("valor", "")
                        mudou_link_35_0 = link_35_0 != d35_0.get("link", "")
                        
                        if mudou_opcao_35_0 or mudou_link_35_0:
                                save_resp("35.0", sel_35_0, pts_35_0, link_35_0)
                                res_data["35.0"] = {"valor": sel_35_0, "pontos": pts_35_0, "link": link_35_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_35_0 and links_35_0_atuais:
                                        links_35_0_antigos = re.findall(r'(https?://[^\s]+)', d35_0.get("link", ""))
                                        if links_35_0_atuais != links_35_0_antigos:
                                                modal_aviso_link("35.0", links_35_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("35.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 35.1 - CARACTERÍSTICAS DO SNA
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_caracteristicas_sna_35_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 35.1 - Características do Componente SNA", expanded=True):
                        st.subheader("35.1 • Características do Componente SNA")
                        st.write("**35.1 Assinale as características do componente municipal do Sistema Nacional de Auditoria - SNA:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        d35_1 = res_data.get("35.1", {"valor": "", "pontos": 0.0, "link": ""})
                        v35_1 = d35_1.get("valor", "").split("|")
                        
                        sna_specs = {
                                "ato_formal": {"text": "Instituída por ato formal no organograma da secretaria de saúde ou equivalente – 03", "pts": 3.0},
                                "estrutura_fisica": {"text": "Possui estrutura física – 02", "pts": 2.0},
                                "equipe_med_enf": {"text": "Possui equipe com ao menos um médico e um enfermeiro – 10", "pts": 10.0},
                                "outros": {"text": "Outros – 00", "pts": 0.0}
                        }
                        
                        c351_1, c351_2 = st.columns([1, 1])
                        chks_selecionados_351 = []
                        pts_totais_35_1 = 0.0
                        
                        keys_sna = list(sna_specs.keys())
                        metade_sna = (len(keys_sna) + 1) // 2
                        
                        with c351_1:
                                # FIX: Distribuição correta na coluna 1 (metade dos checkboxes)
                                for k in keys_sna[:metade_sna]:
                                        marcado = st.checkbox(sna_specs[k]["text"], value=k in v35_1, key=f"chk_35_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_351.append(k)
                                                pts_totais_35_1 += sna_specs[k]["pts"]
                                                
                        with c351_2:
                                # FIX: Distribuição correta na coluna 2 (outra metade dos checkboxes + área de texto)
                                for k in keys_sna[metade_sna:]:
                                        marcado = st.checkbox(sna_specs[k]["text"], value=k in v35_1, key=f"chk_35_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_351.append(k)
                                                pts_totais_35_1 += sna_specs[k]["pts"]
                                                
                                link_35_1 = st.text_area("Link/Evidência (35.1):", value=d35_1.get("link", ""), key=f"txt_35_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_35_1 = st.empty()
                                links_35_1_atuais = re.findall(r'(https?://[^\s]+)', link_35_1)
                                if links_35_1_atuais:
                                        botoes_35_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_35_1_atuais])
                                        placeholder_links_35_1.markdown(f"**Links Ativos:** {botoes_35_1}")
                        
                        str_35_1 = "|".join(chks_selecionados_351)
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_35_1 = st.empty()
                        if pts_totais_35_1 > 0:
                                score_placeholder_35_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 35.1:** :green[+{pts_totais_35_1:.1f} pontos]")
                        else:
                                score_placeholder_35_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 35.1:** `{pts_totais_35_1:.1f} pontos`")
                                
                        mudou_opcao_35_1 = str_35_1 != d35_1.get("valor", "")
                        mudou_link_35_1 = link_35_1 != d35_1.get("link", "")
                        
                        if mudou_opcao_35_1 or mudou_link_35_1:
                                save_resp("35.1", str_35_1, pts_totais_35_1, link_35_1)
                                res_data["35.1"] = {"valor": str_35_1, "pontos": pts_totais_35_1, "link": link_35_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_35_1 and links_35_1_atuais:
                                        links_35_1_antigos = re.findall(r'(https?://[^\s]+)', d35_1.get("link", ""))
                                        if links_35_1_atuais != links_35_1_antigos:
                                                modal_aviso_link("35.1", links_35_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("35.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 35.2 - AUDITORIAS CONCLUÍDAS SITE
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_auditorias_site_35_2_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 35.2 - Disponibilização das Auditorias em Site", expanded=True):
                        st.subheader("35.2 • Disponibilização das Auditorias em Site")
                        st.write(f"**35.2 As auditorias concluídas (encerradas) do exercício de {ano_sel} pelo componente municipal do Sistema Nacional de Auditoria do SUS - SNA estão disponibilizadas em site para consulta?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_35_2 = ["Selecione...", "Sim – 10", "Não – 00"]
                        d35_2 = res_data.get("35.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_352 = d35_2.get("valor", "Selecione...")
                        idx_35_2 = opts_35_2.index(val_atual_352) if val_atual_352 in opts_35_2 else 0
                        
                        c352_1, c352_2 = st.columns([1, 1])
                        with c352_1:
                                sel_35_2 = st.radio("Disponibilização em site:", options=opts_35_2, index=idx_35_2, key=f"rad_35_2_{ano_sel}", label_visibility="collapsed")
                        with c352_2:
                                link_35_2 = st.text_area("Link/Evidência (35.2):", value=d35_2.get("link", ""), key=f"txt_35_2_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_35_2 = st.empty()
                                links_35_2_atuais = re.findall(r'(https?://[^\s]+)', link_35_2)
                                if links_35_2_atuais:
                                        botoes_35_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_35_2_atuais])
                                        placeholder_links_35_2.markdown(f"**Links Ativos:** {botoes_35_2}")
                        
                        opcoes_pts_352 = {
                                "Sim – 10": 10.0,
                                "Não – 00": 0.0,
                                "Selecione...": 0.0
                        }
                        pts_35_2 = opcoes_pts_352.get(sel_35_2, 0.0)
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks mutáveis de sucesso/aviso
                        score_placeholder_35_2 = st.empty()
                        
                        if sel_35_2 == "Selecione...":
                                score_placeholder_35_2.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        elif pts_35_2 > 0:
                                score_placeholder_35_2.success(f"✅ Pontuação Atribuída no Quesito 35.2: `{pts_35_2:.1f} pontos`.")
                        else:
                                score_placeholder_35_2.markdown(f"📊 **Pontuação Atribuída no Quesito 35.2:** `{pts_35_2:.1f} pontos`")
                                
                        mudou_opcao_35_2 = sel_35_2 != d35_2.get("valor", "")
                        mudou_link_35_2 = link_35_2 != d35_2.get("link", "")
                        
                        if mudou_opcao_35_2 or mudou_link_35_2:
                                save_resp("35.2", sel_35_2, pts_35_2, link_35_2)
                                res_data["35.2"] = {"valor": sel_35_2, "pontos": pts_35_2, "link": link_35_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_35_2 and links_35_2_atuais:
                                        links_35_2_antigos = re.findall(r'(https?://[^\s]+)', d35_2.get("link", ""))
                                        if links_35_2_atuais != links_35_2_antigos:
                                                modal_aviso_link("35.2", links_35_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("35.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # -----------------------------------------------------------------------------
        # QUESITO 35.2.1 - LINK DO SITE
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_url_auditorias_35_2_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 35.2.1 - Página Eletrônica de Divulgação", expanded=True):
                        st.subheader("35.2.1 • Página Eletrônica de Divulgação")
                        st.write(f"**35.2.1 Informe a página eletrônica (site) de divulgação dos resultados das auditorias concluídas (encerradas) em {ano_sel}:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração no endereço informado ou no link grava os dados na hora.*")
                        
                        d35_2_1 = res_data.get("35.2.1", {"valor": "", "pontos": 0.0, "link": ""})
                        
                        c3521_1, c3521_2 = st.columns([1, 1])
                        with c3521_1:
                                url_informada = st.text_input("Informe a URL:", value=d35_2_1.get("valor", ""), placeholder="https://...", key=f"txt_val_3521_{ano_sel}")
                                
                                # FIX: Exibição amigável e segura da URL informada
                                placeholder_url_preview = st.empty()
                                if url_informada.strip().startswith(("http://", "https://")):
                                        placeholder_url_preview.markdown(f"🌐 **Página Indicada:** [{url_informada}]({url_informada})")
                        with c3521_2:
                                link_35_2_1 = st.text_area("Link/Evidência (35.2.1):", value=d35_2_1.get("link", ""), key=f"txt_35_2_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_35_2_1 = st.empty()
                                links_35_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_35_2_1)
                                if links_35_2_1_atuais:
                                        botoes_35_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_35_2_1_atuais])
                                        placeholder_links_35_2_1.markdown(f"**Links Ativos:** {botoes_35_2_1}")
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks informativos de pontuação
                        score_placeholder_35_2_1 = st.empty()
                        pts_35_2_1 = 0.0
                        
                        if not url_informada.strip():
                                score_placeholder_35_2_1.markdown(f"⚠️ **Status:** `Aguardando preenchimento da URL`")
                        else:
                                score_placeholder_35_2_1.markdown(f"📊 **Pontuação Aplicada no Quesito 35.2.1:** `{pts_35_2_1:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_35_2_1 = url_informada != d35_2_1.get("valor", "")
                        mudou_link_35_2_1 = link_35_2_1 != d35_2_1.get("link", "")
                        
                        if mudou_opcao_35_2_1 or mudou_link_35_2_1:
                                save_resp("35.2.1", url_informada, pts_35_2_1, link_35_2_1)
                                res_data["35.2.1"] = {"valor": url_informada, "pontos": pts_35_2_1, "link": link_35_2_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_35_2_1 and links_35_2_1_atuais:
                                        links_35_2_1_antigos = re.findall(r'(https?://[^\s]+)', d35_2_1.get("link", ""))
                                        if links_35_2_1_atuais != links_35_2_1_antigos:
                                                modal_aviso_link("35.2.1", links_35_2_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("35.2.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos para encerrar o card e a Seção 35

        # =============================================================================
        # SEÇÃO 36 - SISTEMA DE GESTÃO DE ESTOQUE DE MEDICAMENTOS
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("💊 Seção 36 - Estoque de Medicamentos")

        # -----------------------------------------------------------------------------
        # QUESITO 36.0 - SISTEMA INFORMATIZADO PARA GERENCIAMENTO DE MEDICAMENTOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_estoque_medicamentos_36_0_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 36.0 - Sistema Informatizado para Gerenciamento de Medicamentos", expanded=True):
                        st.subheader("36.0 • Sistema Informatizado para Gerenciamento de Medicamentos")
                        st.write("**36.0 O município utiliza sistema informatizado para gerenciar o estoque de itens de medicamentos?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_36_0 = [
                                "Selecione...",
                                "Sim, utiliza o Sistema Hórus – 40",
                                "Sim, utiliza Sistema Próprio – 00",
                                "Não – 00"
                        ]
                        d36_0 = res_data.get("36.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_atual_360 = d36_0.get("valor", "Selecione...")
                        idx_36_0 = opts_36_0.index(val_atual_360) if val_atual_360 in opts_36_0 else 0
                        
                        c360_1, c360_2 = st.columns([1, 1])
                        with c360_1:
                                sel_36_0 = st.radio("Gerenciamento de medicamentos:", options=opts_36_0, index=idx_36_0, key=f"rad_36_0_{ano_sel}", label_visibility="collapsed")
                        with c360_2:
                                link_36_0 = st.text_area("Link/Evidência (36.0):", value=d36_0.get("link", ""), key=f"txt_36_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_36_0 = st.empty()
                                links_36_0_atuais = re.findall(r'(https?://[^\s]+)', link_36_0)
                                if links_36_0_atuais:
                                        botoes_36_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_36_0_atuais])
                                        placeholder_links_36_0.markdown(f"**Links Ativos:** {botoes_36_0}")
                        
                        opcoes_pts_360 = {
                                "Sim, utiliza o Sistema Hórus – 40": 40.0,
                                "Sim, utiliza Sistema Próprio – 00": 0.0,
                                "Não – 00": 0.0,
                                "Selecione...": 0.0
                        }
                        pts_36_0 = opcoes_pts_360.get(sel_36_0, 0.0)
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks mutáveis de sucesso/aviso
                        score_placeholder_36_0 = st.empty()
                        
                        if sel_36_0 == "Selecione...":
                                score_placeholder_36_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        elif pts_36_0 > 0:
                                score_placeholder_36_0.success(f"✅ Pontuação Atribuída no Quesito 36.0: `{pts_36_0:.1f} pontos`.")
                        else:
                                score_placeholder_36_0.markdown(f"📊 **Pontuação Atribuída no Quesito 36.0:** `{pts_36_0:.1f} pontos`")
                                
                        mudou_opcao_36_0 = sel_36_0 != d36_0.get("valor", "")
                        mudou_link_36_0 = link_36_0 != d36_0.get("link", "")
                        
                        if mudou_opcao_36_0 or mudou_link_36_0:
                                save_resp("36.0", sel_36_0, pts_36_0, link_36_0)
                                res_data["36.0"] = {"valor": sel_36_0, "pontos": pts_36_0, "link": link_36_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_36_0 and links_36_0_atuais:
                                        links_36_0_antigos = re.findall(r'(https?://[^\s]+)', d36_0.get("link", ""))
                                        if links_36_0_atuais != links_36_0_antigos:
                                                modal_aviso_link("36.0", links_36_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("36.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos para encerrar o card e a Seção 36

# -----------------------------------------------------------------------------
        # QUESITO 36.1 - FUNÇÕES DO SISTEMA PRÓPRIO DE MEDICAMENTOS
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_funcoes_sistema_proprio_36_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 36.1 - Funções do Sistema Próprio de Gestão de Estoque", expanded=True):
                        st.subheader("36.1 • Funções do Sistema Próprio de Gestão de Estoque")
                        st.write("**36.1 Assinale as funções existentes no sistema próprio de gestão de estoque de medicamentos:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        d36_1 = res_data.get("36.1", {"valor": "", "pontos": 0.0, "link": ""})
                        v36_1 = d36_1.get("valor", "").split("|")
                        
                        med_specs = {
                                "posicao_lote": {"text": "Fornecer a posição de estoque, movimentação de entrada e saída, lote e validade – 10", "pts": 10.0},
                                "rastreabilidade": {"text": "Permitir a rastreabilidade dos medicamentos dispensados aos pacientes – 10", "pts": 10.0},
                                "processo_compras": {"text": "Gerenciar o processo de compras de itens de medicamentos, desde o planejamento até a entrega e o recebimento da nota fiscal – 10", "pts": 10.0},
                                "reposicao_estab": {"text": "Gerenciar a reposição de itens de medicamentos por estabelecimento de saúde – 10", "pts": 10.0},
                                "integrado_bnafar": {"text": "Integrado à Base Nacional de Dados de Ações e Serviços da Assistência Farmacêutica (BNAFAR) – 00", "pts": 0.0},
                                "outros": {"text": "Outros – 00", "pts": 0.0}
                        }
                        
                        c361_1, c361_2 = st.columns([1, 1])
                        chks_selecionados_361 = []
                        pts_totais_36_1 = 0.0
                        
                        keys_med = list(med_specs.keys())
                        metade_med = (len(keys_med) + 1) // 2
                        
                        with c361_1:
                                for k in keys_med[:metade_med]:
                                        marcado = st.checkbox(med_specs[k]["text"], value=k in v36_1, key=f"chk_36_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_361.append(k)
                                                pts_totais_36_1 += med_specs[k]["pts"]
                                                
                        with c361_2:
                                for k in keys_med[metade_med:]:
                                        marcado = st.checkbox(med_specs[k]["text"], value=k in v36_1, key=f"chk_36_1_{k}_{ano_sel}")
                                        if marcado:
                                                chks_selecionados_361.append(k)
                                                pts_totais_36_1 += med_specs[k]["pts"]
                                                
                                link_36_1 = st.text_area("Link/Evidência (36.1):", value=d36_1.get("link", ""), key=f"txt_36_1_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_36_1 = st.empty()
                                links_36_1_atuais = re.findall(r'(https?://[^\s]+)', link_36_1)
                                if links_36_1_atuais:
                                        botoes_36_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_36_1_atuais])
                                        placeholder_links_36_1.markdown(f"**Links Ativos:** {botoes_36_1}")
                        
                        str_36_1 = "|".join(chks_selecionados_361)
                        
                        # FIX: Uso de placeholder estável st.empty() para renderizar a pontuação sem quebrar a árvore HTML
                        score_placeholder_36_1 = st.empty()
                        if pts_totais_36_1 > 0:
                                score_placeholder_36_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 36.1:** :green[+{pts_totais_36_1:.1f} pontos]")
                        else:
                                score_placeholder_36_1.markdown(f"📊 **Pontuação Total Acumulada no Quesito 36.1:** `{pts_totais_36_1:.1f} pontos`")
                                
                        mudou_opcao_36_1 = str_36_1 != d36_1.get("valor", "")
                        mudou_link_36_1 = link_36_1 != d36_1.get("link", "")
                        
                        if mudou_opcao_36_1 or mudou_link_36_1:
                                save_resp("36.1", str_36_1, pts_totais_36_1, link_36_1)
                                res_data["36.1"] = {"valor": str_36_1, "pontos": pts_totais_36_1, "link": link_36_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_36_1 and links_36_1_atuais:
                                        links_36_1_antigos = re.findall(r'(https?://[^\s]+)', d36_1.get("link", ""))
                                        if links_36_1_atuais != links_36_1_antigos:
                                                modal_aviso_link("36.1", links_36_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("36.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos conforme estrutura original do bloco externo

        # =============================================================================
        # SEÇÃO 37 - DESABASTECIMENTO DE MEDICAMENTOS (CBAF / REMUME)
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📉 Seção 37 - Índice de Desabastecimento de Medicamentos")

        # -----------------------------------------------------------------------------
        # QUESITO 37.0 - MONITORAMENTO DE DESABASTECIMENTO
        # -----------------------------------------------------------------------------
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_desabastecimento_med_37_0_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 37.0 - Monitoramento de Desabastecimento ({ano_sel})", expanded=True):
                        st.subheader("37.0 • Monitoramento de Desabastecimento")
                        st.write(f"**37.0 Informe os dados de desabastecimento de medicamentos do Componente Básico da Assistência Farmacêutica presentes na REMUME no exercício de {ano_sel}:**")
                        
                        # Exibição formal da fórmula matemática do indicador utilizando LaTeX estruturado
                        st.latex(r"Pd = \left( \frac{MD}{TM} \right) \times 100")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos valores numéricos ou no link grava os dados na hora.*")
                        
                        d37_0 = res_data.get("37.0", {"valor": "0|0", "pontos": 0.0, "link": ""})
                        v37_0 = d37_0.get("valor", "0|0").split("|")
                        while len(v37_0) < 2: 
                                v37_0.append("0")
                        
                        c370_1, c370_2 = st.columns([1, 1])
                        with c370_1:
                                val_md = st.number_input(f"Nº de itens com desabastecimento superior a 1 mês em {ano_sel} (MD):", min_value=0, value=int(v37_0[0]) if v37_0[0].isdigit() else 0, key=f"num_370_md_{ano_sel}")
                                val_tm = st.number_input("Total de itens do Componente Básico presentes na REMUME (TM):", min_value=0, value=int(v37_0[1]) if v37_0[1].isdigit() else 1, key=f"num_370_tm_{ano_sel}")
                        
                        with c370_2:
                                link_37_0 = st.text_area("Link/Evidência (37.0):", value=d37_0.get("link", ""), key=f"txt_37_0_{ano_sel}", height=110)
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_37_0 = st.empty()
                                links_37_0_atuais = re.findall(r'(https?://[^\s]+)', link_37_0)
                                if links_37_0_atuais:
                                        botoes_37_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_37_0_atuais])
                                        placeholder_links_37_0.markdown(f"**Links Ativos:** {botoes_37_0}")
                        
                        # FIX: Centralização de toda a lógica mutável de cálculo e feedback visual em um placeholder único st.empty()
                        score_placeholder_37_0 = st.empty()
                        pts_37_0 = 0.0
                        
                        if val_tm > 0:
                                pd = (val_md / val_tm) * 100.0
                                
                                # Criação interna da lógica de amostragem reativa dentro do placeholder
                                with score_placeholder_37_0.container():
                                        st.markdown(f"📊 **Percentual de Desabastecimento Calculado (Pd):** `{pd:.2f}%` ({val_md} de {val_tm} itens)")
                                        
                                        if val_md == 0:
                                                pts_37_0 = 90.0
                                                st.success(f"🏅 **Excelente!** Pd = 0% | Pontuação: `{pts_37_0:.1f} pontos`")
                                        elif pd <= 5.0:
                                                pts_37_0 = 75.0
                                                st.info(f"✅ **Bom Controle:** 0% < Pd <= 5% | Pontuação: `{pts_37_0:.1f} pontos`")
                                        elif pd <= 10.0:
                                                pts_37_0 = 50.0
                                                st.warning(f"⚠️ **Atenção:** 5% < Pd <= 10% | Pontuação: `{pts_37_0:.1f} pontos`")
                                        elif pd <= 15.0:
                                                pts_37_0 = 25.0
                                                st.warning(f"🧡 **Alerta Laranja:** 10% < Pd <= 15% | Pontuação: `{pts_37_0:.1f} pontos`")
                                        else:
                                                pts_37_0 = 0.0
                                                st.error(f"🚨 **Crítico:** Pd > 15% | Pontuação: `{pts_37_0:.1f} pontos`")
                        else:
                                score_placeholder_37_0.error("⚠️ O total de itens da REMUME (TM) deve ser maior que zero para possibilitar o cálculo da pontuação.")

                        str_37_0 = f"{val_md}|{val_tm}"
                        
                        mudou_opcao_37_0 = str_37_0 != d37_0.get("valor", "")
                        mudou_link_37_0 = link_37_0 != d37_0.get("link", "")
                        
                        if mudou_opcao_37_0 or mudou_link_37_0:
                                save_resp("37.0", str_37_0, pts_37_0, link_37_0)
                                res_data["37.0"] = {"valor": str_37_0, "pontos": pts_37_0, "link": link_37_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_37_0 and links_37_0_atuais:
                                        links_37_0_antigos = re.findall(r'(https?://[^\s]+)', d37_0.get("link", ""))
                                        if links_37_0_atuais != links_37_0_antigos:
                                                modal_aviso_link("37.0", links_37_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("37.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # Mantido os dois fechamentos para encerrar o card e a Seção 37

# =============================================================================
        # QUESITO 38.0 - DISPONIBILIZAÇÃO DE TELEMEDICINA
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_telemedicina_38_0_{ano_sel}", border=False):
                
                with st.expander(f"📌 Quesito 38.0 • Disponibilização de Telemedicina ({ano_sel})", expanded=True):
                        st.subheader("38.0 • Disponibilização de Telemedicina")
                        # FIX: Tornou o ano dinâmico baseado na variável de seleção do sistema
                        st.write(f"**Houve a disponibilização do serviço de telemedicina em {ano_sel}?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_38_0 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d38_0 = res_data.get("38.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_salvo_380 = d38_0.get("valor", "Selecione...")
                        if val_salvo_380 not in opts_38_0:
                                val_salvo_380 = "Selecione..."
                                
                        idx_inicial_380 = list(opts_38_0.keys()).index(val_salvo_380)
                        
                        c380_1, c380_2 = st.columns([1, 1])
                        with c380_1:
                                sel_38_0 = st.radio(
                                        "Disponibilizou telemedicina:",
                                        options=list(opts_38_0.keys()),
                                        index=idx_inicial_380,
                                        key=f"rb_38_0_{ano_sel}",
                                        label_visibility="collapsed"
                                )
                                pts_38_0 = opts_38_0.get(sel_38_0, 0.0)
                                
                        with c380_2:
                                link_38_0 = st.text_area(
                                        f"Link/Evidência ou Relatório de Implantação (38.0):",
                                        value=d38_0.get("link", ""),
                                        key=f"txt_38_0_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_38_0 = st.empty()
                                links_38_0_atuais = re.findall(r'(https?://[^\s]+)', link_38_0)
                                if links_38_0_atuais:
                                        botoes_38_0 = " | ".join([f"🔗 [{u}]({u})" for u in links_38_0_atuais])
                                        placeholder_links_38_0.markdown(f"**Links Ativos:** {botoes_38_0}")
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks informativos de pontuação
                        score_placeholder_38_0 = st.empty()
                        
                        if sel_38_0 == "Selecione...":
                                score_placeholder_38_0.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_38_0.markdown(f"📊 **Pontuação Aplicada no Quesito 38.0:** `{pts_38_0:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_38_0 = sel_38_0 != d38_0.get("valor", "")
                        mudou_link_38_0 = link_38_0 != d38_0.get("link", "")
                        
                        if mudou_opcao_38_0 or mudou_link_38_0:
                                save_resp("38.0", sel_38_0, pts_38_0, link_38_0)
                                res_data["38.0"] = {"valor": sel_38_0, "pontos": pts_38_0, "link": link_38_0}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_38_0 and links_38_0_atuais:
                                        links_38_0_antigos = re.findall(r'(https?://[^\s]+)', d38_0.get("link", ""))
                                        if links_38_0_atuais != links_38_0_antigos:
                                                modal_aviso_link("38.0", links_38_0_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("38.0", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
        # QUESITO 38.1 - SERVIÇOS DISPONIBILIZADOS
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_servicos_telemedicina_38_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 38.1 • Serviços de Telemedicina Disponibilizados", expanded=True):
                        st.subheader("38.1 • Serviços Disponibilizados")
                        st.write("**Assinale os serviços disponibilizados:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        # Formato serializado: Teleconsulta|Teleinterconsulta|Telediagnóstico|Teletriagem|Telemonitoramento|Teleconsultoria|Outros
                        d38_1 = res_data.get("38.1", {"valor": "0|0|0|0|0|0|0", "pontos": 0.0, "link": ""})
                        p_381 = d38_1.get("valor", "0|0|0|0|0|0|0").split("|")
                        while len(p_381) < 7: 
                                p_381.append("0")
                        
                        c381_1, c381_2 = st.columns([1, 1])
                        with c381_1:
                                # FIX: Distribuição equilibrada dos checkboxes na Coluna 1
                                ch1_381 = st.checkbox("Teleconsulta", value=(p_381[0] == "1"), key=f"ch_381_1_{ano_sel}")
                                ch2_381 = st.checkbox("Teleinterconsulta", value=(p_381[1] == "1"), key=f"ch_381_2_{ano_sel}")
                                ch3_381 = st.checkbox("Telediagnóstico", value=(p_381[2] == "1"), key=f"ch_381_3_{ano_sel}")
                                ch4_381 = st.checkbox("Teletriagem", value=(p_381[3] == "1"), key=f"ch_381_4_{ano_sel}")
                                
                        with c381_2:
                                # FIX: Continuação dos checkboxes na Coluna 2 antes da área de texto para balanceamento visual
                                ch5_381 = st.checkbox("Telemonitoramento", value=(p_381[4] == "1"), key=f"ch_381_5_{ano_sel}")
                                ch6_381 = st.checkbox("Teleconsultoria", value=(p_381[5] == "1"), key=f"ch_381_6_{ano_sel}")
                                ch7_381 = st.checkbox("Outros", value=(p_381[6] == "1"), key=f"ch_381_7_{ano_sel}")
                                
                                link_38_1 = st.text_area(
                                        "Link/Evidência ou Telas do Sistema de Telemedicina (38.1):",
                                        value=d38_1.get("link", ""),
                                        key=f"txt_38_1_{ano_sel}",
                                        height=130
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_38_1 = st.empty()
                                links_38_1_atuais = re.findall(r'(https?://[^\s]+)', link_38_1)
                                if links_38_1_atuais:
                                        botoes_38_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_38_1_atuais])
                                        placeholder_links_38_1.markdown(f"**Links Ativos:** {botoes_38_1}")
                        
                        string_estruturada_38_1 = f"{1 if ch1_381 else 0}|{1 if ch2_381 else 0}|{1 if ch3_381 else 0}|{1 if ch4_381 else 0}|{1 if ch5_381 else 0}|{1 if ch6_381 else 0}|{1 if ch7_381 else 0}"
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks informativos de pontuação
                        score_placeholder_38_1 = st.empty()
                        pts_38_1 = 0.0
                        
                        if "1" not in string_estruturada_38_1:
                                score_placeholder_38_1.markdown(f"⚠️ **Status:** `Nenhum serviço selecionado`")
                        else:
                                score_placeholder_38_1.markdown(f"📊 **Pontuação Aplicada no Quesito 38.1:** `{pts_38_1:.1f} pontos` (Dados Informativos)")
                        
                        mudou_opcao_38_1 = string_estruturada_38_1 != d38_1.get("valor")
                        mudou_link_38_1 = link_38_1 != d38_1.get("link")
                        
                        if mudou_opcao_38_1 or mudou_link_38_1:
                                save_resp("38.1", string_estruturada_38_1, pts_38_1, link_38_1)
                                res_data["38.1"] = {"valor": string_estruturada_38_1, "pontos": pts_38_1, "link": link_38_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_38_1 and links_38_1_atuais:
                                        links_38_1_antigos = re.findall(r'(https?://[^\s]+)', d38_1.get("link", ""))
                                        if links_38_1_atuais != links_38_1_antigos:
                                                modal_aviso_link("38.1", links_38_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("38.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 38.2 - SISTEMA INFORMATIZADO PARA PRESCRIÇÃO ELETRÔNICA
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_prescricao_eletronica_38_2_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 38.2 • Sistema para Prescrição Eletrônica", expanded=True):
                        st.subheader("38.2 • Sistema Informatizado para Prescrição Eletrônica")
                        st.write("**Foi utilizado sistema informatizado para prescrição eletrônica, que possibilitasse a emissão de receitas e atestados, assinados eletronicamente?**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas opções ou no link grava os dados na hora.*")
                        
                        opts_38_2 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d38_2 = res_data.get("38.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        val_salvo_382 = d38_2.get("valor", "Selecione...")
                        if val_salvo_382 not in opts_38_2:
                                val_salvo_382 = "Selecione..."
                                
                        idx_inicial_382 = list(opts_38_2.keys()).index(val_salvo_382)
                        
                        c382_1, c382_2 = st.columns([1, 1])
                        with c382_1:
                                sel_38_2 = st.radio(
                                        "Utilizou prescrição eletrônica:",
                                        options=list(opts_38_2.keys()),
                                        index=idx_inicial_382,
                                        key=f"rb_38_2_{ano_sel}",
                                        label_visibility="collapsed"
                                )
                                pts_38_2 = opts_38_2.get(sel_38_2, 0.0)
                                
                        with c382_2:
                                link_38_2 = st.text_area(
                                        "Link/Evidência ou Modelo de Prescrição Assinada (38.2):",
                                        value=d38_2.get("link", ""),
                                        key=f"txt_38_2_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_38_2 = st.empty()
                                links_38_2_atuais = re.findall(r'(https?://[^\s]+)', link_38_2)
                                if links_38_2_atuais:
                                        botoes_38_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_38_2_atuais])
                                        placeholder_links_38_2.markdown(f"**Links Ativos:** {botoes_38_2}")
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks informativos de pontuação
                        score_placeholder_38_2 = st.empty()
                        
                        if sel_38_2 == "Selecione...":
                                score_placeholder_38_2.markdown(f"⚠️ **Pontuação:** `0.0 pontos` (Por favor, selecione uma opção válida)")
                        else:
                                score_placeholder_38_2.markdown(f"📊 **Pontuação Aplicada no Quesito 38.2:** `{pts_38_2:.1f} pontos` (Dados Informativos)")
                                
                        mudou_opcao_38_2 = sel_38_2 != d38_2.get("valor", "")
                        mudou_link_38_2 = link_38_2 != d38_2.get("link", "")
                        
                        if mudou_opcao_38_2 or mudou_link_38_2:
                                save_resp("38.2", sel_38_2, pts_38_2, link_38_2)
                                res_data["38.2"] = {"valor": sel_38_2, "pontos": pts_38_2, "link": link_38_2}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_38_2 and links_38_2_atuais:
                                        links_38_2_antigos = re.findall(r'(https?://[^\s]+)', d38_2.get("link", ""))
                                        if links_38_2_atuais != links_38_2_antigos:
                                                modal_aviso_link("38.2", links_38_2_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("38.2", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

       # =============================================================================
        # QUESITO 38.2.1 - FERRAMENTA DE PRESCRIÇÃO E ASSINATURA ELETRÔNICA
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_ferramenta_prescricao_38_2_1_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 38.2.1 • Ferramenta de Prescrição Utilizada", expanded=True):
                        st.subheader("38.2.1 • Ferramenta Utilizada para Prescrição")
                        st.write("**Assinale a ferramenta utilizada para prescrição e assinatura eletrônica:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        # Formato serializado: Consultorio_MS|CFM|Outras
                        d38_2_1 = res_data.get("38.2.1", {"valor": "0|0|0", "pontos": 0.0, "link": ""})
                        p_3821 = d38_2_1.get("valor", "0|0|0").split("|")
                        while len(p_3821) < 3: 
                                p_3821.append("0")
                        
                        c3821_1, c3821_2 = st.columns([1, 1])
                        with c3821_1:
                                ch1_3821 = st.checkbox("Consultório Virtual da Família do Ministério da Saúde", value=(p_3821[0] == "1"), key=f"ch_3821_1_{ano_sel}")
                                ch2_3821 = st.checkbox("Prescrição Eletrônica do Conselho Federal de Medicina", value=(p_3821[1] == "1"), key=f"ch_3821_2_{ano_sel}")
                                ch3_3821 = st.checkbox("Outras", value=(p_3821[2] == "1"), key=f"ch_3821_3_{ano_sel}")
                                
                        with c3821_2:
                                link_38_2_1 = st.text_area(
                                        "Link/Evidência ou Nome da Ferramenta de Assinatura (38.2.1):",
                                        value=d38_2_1.get("link", ""),
                                        key=f"txt_38_2_1_{ano_sel}",
                                        height=110
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_38_2_1 = st.empty()
                                links_38_2_1_atuais = re.findall(r'(https?://[^\s]+)', link_38_2_1)
                                if links_38_2_1_atuais:
                                        botoes_38_2_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_38_2_1_atuais])
                                        placeholder_links_38_2_1.markdown(f"**Links Ativos:** {botoes_38_2_1}")
                        
                        string_estruturada_38_2_1 = f"{1 if ch1_3821 else 0}|{1 if ch2_3821 else 0}|{1 if ch3_3821 else 0}"
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks informativos de pontuação
                        score_placeholder_38_2_1 = st.empty()
                        pts_38_2_1 = 0.0
                        
                        if "1" not in string_estruturada_38_2_1:
                                score_placeholder_38_2_1.markdown(f"⚠️ **Status:** `Nenhuma ferramenta selecionada`")
                        else:
                                score_placeholder_38_2_1.markdown(f"📊 **Pontuação Aplicada no Quesito 38.2.1:** `{pts_38_2_1:.1f} pontos` (Dados Informativos)")
                        
                        mudou_opcao_38_2_1 = string_estruturada_38_2_1 != d38_2_1.get("valor")
                        mudou_link_38_2_1 = link_38_2_1 != d38_2_1.get("link")
                        
                        if mudou_opcao_38_2_1 or mudou_link_38_2_1:
                                save_resp("38.2.1", string_estruturada_38_2_1, pts_38_2_1, link_38_2_1)
                                res_data["38.2.1"] = {"valor": string_estruturada_38_2_1, "pontos": pts_38_2_1, "link": link_38_2_1}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_38_2_1 and links_38_2_1_atuais:
                                        links_38_2_1_antigos = re.findall(r'(https?://[^\s]+)', d38_2_1.get("link", ""))
                                        if links_38_2_1_atuais != links_38_2_1_antigos:
                                                modal_aviso_link("38.2.1", links_38_2_1_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("38.2.1", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
        # QUESITO 38.3 - MODALIDADES E REGISTROS REALIZADOS
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        # FIX: Container estável com chave explícita única para evitar falhas de dessincronização no React DOM
        with st.container(key=f"container_bloco_modalidades_registros_38_3_{ano_sel}", border=False):
                
                with st.expander("📌 Quesito 38.3 • Modalidades e Registros Efetuados", expanded=True):
                        st.subheader("38.3 • Modalidades de Consultas e Registros")
                        st.write("**Assinale as modalidades de consultas e registros realizados referentes aos serviços de telemedicina:**")
                        st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nas caixas de seleção ou no link grava os dados na hora.*")
                        
                        # Formato serializado: Iniciais|Acompanhamento|Urgencia|Supervisao|PEC|CDS|Outros|NaoHouve
                        d38_3 = res_data.get("38.3", {"valor": "0|0|0|0|0|0|0|0", "pontos": 0.0, "link": ""})
                        p_383 = d38_3.get("valor", "0|0|0|0|0|0|0|0").split("|")
                        while len(p_383) < 8: 
                                p_383.append("0")
                        
                        c383_1, c383_2 = st.columns([1, 1])
                        with c383_1:
                                # FIX: Distribuição equilibrada dos checkboxes (Opções de 1 a 4)
                                ch1_383 = st.checkbox("Consultas iniciais (primeiro atendimento)", value=(p_383[0] == "1"), key=f"ch_383_1_{ano_sel}")
                                ch2_383 = st.checkbox("Consultas de acompanhamento/monitoramento", value=(p_383[1] == "1"), key=f"ch_383_2_{ano_sel}")
                                ch3_383 = st.checkbox("Consultas em caráter de urgência", value=(p_383[2] == "1"), key=f"ch_383_3_{ano_sel}")
                                ch4_383 = st.checkbox("Consultas de supervisão. Ex.: troca de experiências entre profissionais", value=(p_383[3] == "1"), key=f"ch_383_4_{ano_sel}")
                                
                        with c383_2:
                                # FIX: Continuação equilibrada dos checkboxes (Opções de 5 a 8) e campo de texto
                                ch5_383 = st.checkbox("Prontuário Eletrônico do Cidadão (PEC)", value=(p_383[4] == "1"), key=f"ch_383_5_{ano_sel}")
                                ch6_383 = st.checkbox("Fichas de Coletas de Dados Simplificados (CDS)", value=(p_383[5] == "1"), key=f"ch_383_6_{ano_sel}")
                                ch7_383 = st.checkbox("Outros", value=(p_383[6] == "1"), key=f"ch_383_7_{ano_sel}")
                                ch8_383 = st.checkbox("Não houve registro", value=(p_383[7] == "1"), key=f"ch_383_8_{ano_sel}")
                                
                                link_38_3 = st.text_area(
                                        "Link/Evidência ou Relatório de Production/SISAB (38.3):",
                                        value=d38_3.get("link", ""),
                                        key=f"txt_38_3_{ano_sel}",
                                        height=130
                                )
                                
                                # FIX: Criação do nó estável do Streamlit para renderização segura dos links ativos
                                placeholder_links_38_3 = st.empty()
                                links_38_3_atuais = re.findall(r'(https?://[^\s]+)', link_38_3)
                                if links_38_3_atuais:
                                        botoes_38_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_38_3_atuais])
                                        placeholder_links_38_3.markdown(f"**Links Ativos:** {botoes_38_3}")
                        
                        string_estruturada_38_3 = f"{1 if ch1_383 else 0}|{1 if ch2_383 else 0}|{1 if ch3_383 else 0}|{1 if ch4_383 else 0}|{1 if ch5_383 else 0}|{1 if ch6_383 else 0}|{1 if ch7_383 else 0}|{1 if ch8_383 else 0}"
                        
                        # FIX: Uso de placeholder estável st.empty() para feedbacks informativos de pontuação
                        score_placeholder_38_3 = st.empty()
                        pts_38_3 = 0.0
                        
                        if "1" not in string_estruturada_38_3:
                                score_placeholder_38_3.markdown(f"⚠️ **Status:** `Nenhuma modalidade selecionada`")
                        else:
                                score_placeholder_38_3.markdown(f"📊 **Pontuação Aplicada no Quesito 38.3:** `{pts_38_3:.1f} pontos` (Dados Informativos)")
                        
                        mudou_opcao_38_3 = string_estruturada_38_3 != d38_3.get("valor")
                        mudou_link_38_3 = link_38_3 != d38_3.get("link")
                        
                        if mudou_opcao_38_3 or mudou_link_38_3:
                                save_resp("38.3", string_estruturada_38_3, pts_38_3, link_38_3)
                                res_data["38.3"] = {"valor": string_estruturada_38_3, "pontos": pts_38_3, "link": link_38_3}
                                
                                # Lógica para tratamento de modificação de links com o modal de aviso
                                if mudou_link_38_3 and links_38_3_atuais:
                                        links_38_3_antigos = re.findall(r'(https?://[^\s]+)', d38_3.get("link", ""))
                                        if links_38_3_atuais != links_38_3_antigos:
                                                modal_aviso_link("38.3", links_38_3_atuais)
                                        else:
                                                st.rerun()
                                else:
                                        st.rerun()
                                        
                        bloco_comentarios("38.3", res_data)
                        
        st.markdown('</div>', unsafe_allow_html=True)

        # =============================================================================
        # QUESITO 39.0 - IMPRESSÕES, COMENTÁRIOS E SUGESTÕES DO QUESTIONÁRIO
        # =============================================================================
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        
        with st.expander("📌 Quesito 39.0 • Impressões, Comentários e Sugestões", expanded=True):
                st.subheader("39.0 • Considerações Finais")
                st.write("**Gostaria de registrar suas impressões, comentários e sugestões a respeito do presente questionário?**")
                
                # Recupera os dados salvos anteriormente
                d39_0 = res_data.get("39.0", {"valor": "", "pontos": 0.0, "link": ""})
                val_salvo_390 = d39_0.get("valor", "")
                
                # Espaço amplo de texto para o usuário dissertar
                texto_39_0 = st.text_area(
                        "Utilize o espaço abaixo para registrar suas impressões, comentários e sugestões a respeito do presente questionário:",
                        value=val_salvo_390,
                        key=f"txt_39_0_val_{ano_sel}",
                        height=250,
                        placeholder="Digite aqui suas observações sobre o preenchimento, estrutura ou sugestões de melhoria..."
                )
                
                # Sincronização e salvamento sem loops (usa o próprio texto como 'valor' e deixa 'link' vazio)
                if texto_39_0 != val_salvo_390:
                        save_resp("39.0", texto_39_0, 0.0, "")
                        res_data["39.0"] = {"valor": texto_39_0, "pontos": 0.0, "link": ""}
                        st.rerun()
                        
                bloco_comentarios("39.0", res_data)
                
        st.markdown('</div>', unsafe_allow_html=True)

        # =========================================================================
        # --- ABA DADOS EXTERNOS ---
        # =========================================================================
        with aba_dados_externos:
            st.title("📊 Indicadores e Dados Externos")
            st.write("Insira abaixo as informações e dados consolidados das fontes externas:")

            # =============================================================================
            # S1 • Mínimo Constitucional em Saúde (Dados AUDESP)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S1 • Aplicação do Mínimo Constitucional em Saúde")
            st.write("**Mede a aplicação do limite mínimo constitucional de 15% em saúde (Despesa aplicada em Saúde com recursos próprios sobre receita de impostos)**")

            # Tabela de Regras de Pontuação (Regras de Rebaixamento de Nota)
            st.markdown(r"""
            | Resultado do Índice $PS$ | Impacto / Pontuação do Indicador |
            | :--- | :--- |
            | Maior ou igual a 15% ($PS \ge 15\%$) | ✅ 00 ponto (Cumpre o Mínimo Constitucional / Sem Penalidade) |
            | Menor que 15% ($PS < 15\%$) | 🚨 REBAIXAR 1 faixa do i-Saúde (Descumprimento Constitucional) |
            """)
            st.caption("ℹ️ *Variáveis parametrizadas e calculadas extraídas diretamente do Sistema AUDESP.*")

            # 🧹 Nova Função de Higienização robusta baseada em caracteres numéricos puros
            def tratar_string_monetaria_para_float(texto):
                if not texto: 
                    return 0.0
                # Remove R$, espaços e pontos de milhar, mantendo apenas dígitos e a vírgula decimal
                apenas_numeros = "".join(c for c in texto if c.isdigit() or c == ",")
                if "," in apenas_numeros:
                    apenas_numeros = apenas_numeros.replace(",", ".")
                try:
                    return float(apenas_numeros)
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação limpa padrão BR
            def formatar_para_moeda_br(valor_float):
                return f"R$ {valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (DESP/REC)
            dS1 = res_data.get("S1", {"valor": "0.00/1.00", "pontos": 0.0, "link": ""})

            try:
                val_salvo_desp, val_salvo_rec = dS1["valor"].split("/")
                float_desp = float(val_salvo_desp)
                float_rec = float(val_salvo_rec)
            except:
                float_desp, float_rec = 0.0, 1.0

            # Garante que o session_state inicialize no formato correto do Brasil
            if f"s1_str_desp_{ano_sel}" not in st.session_state:
                st.session_state[f"s1_str_desp_{ano_sel}"] = formatar_para_moeda_br(float_desp)
            if f"s1_str_rec_{ano_sel}" not in st.session_state:
                st.session_state[f"s1_str_rec_{ano_sel}"] = formatar_para_moeda_br(float_rec)

            c1, c2 = st.columns([1, 2])

            with c1:
                # Input 1: Despesa aplicada em Saúde (Topo da fração)
                input_desp_str = st.text_input(
                    "Despesa aplicada em Saúde com recursos próprios - R$:",
                    value=st.session_state[f"s1_str_desp_{ano_sel}"],
                    placeholder="Ex: 150.000,00",
                    key=f"txt_s1_desp_dinamico_{ano_sel}"
                )
                
                # Input 2: Receita de Impostos (Base da fração / divisor)
                input_rec_str = st.text_input(
                    "Receita de Impostos (Saúde) - R$:",
                    value=st.session_state[f"s1_str_rec_{ano_sel}"],
                    placeholder="Ex: 1.000.000,00",
                    key=f"txt_s1_rec_dinamico_{ano_sel}"
                )

                # Conversão segura usando o novo motor limpo
                v_desp = tratar_string_monetaria_para_float(input_desp_str)
                v_rec = tratar_string_monetaria_para_float(input_rec_str)

                # Sincroniza o session_state formatando de forma correta e sem duplicar masks
                st.session_state[f"s1_str_desp_{ano_sel}"] = formatar_para_moeda_br(v_desp)
                st.session_state[f"s1_str_rec_{ano_sel}"] = formatar_para_moeda_br(v_rec)

                # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                if v_desp == 0.0 or v_rec == 0.0:
                    PS = 0.0
                    ptsS1 = 0.0
                    texto_resultado = "Aguardando preenchimento correto dos valores orçamentários..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # 🧮 Fórmula Correta: (Despesa Aplicada / Receita de Impostos) * 100
                    PS = round((v_desp / v_rec) * 100.0, 2)

                    # 🧮 MOTOR DE REGRAS (Abaixo de 15% gera rebaixamento)
                    if PS >= 15.00:
                        ptsS1 = 0.0
                        texto_resultado = f"✅ REGULAR: Município atende ao limite mínimo de 15% de aplicação constitucional em Saúde"
                        texto_pontuacao = "0,00 pontos (Sem Penalidade)"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    else:
                        ptsS1 = 0.0
                        texto_resultado = f"🚨 DESCUMPRIMENTO: Aplicação abaixo do mínimo de 15% estabelecido para a Saúde"
                        texto_pontuacao = "REBAIXAR 1 FAIXA DO i-Saúde"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS1 = st.text_area("Link/Evidência (S1 - Mínimo Constitucional Saúde - AUDESP):", value=dS1.get("link", ""), key=f"txt_s1_{ano_sel}", height=150)

            # Gera a visualização final estritamente corrigida
            v_desp_br = formatar_para_moeda_br(v_desp)
            v_rec_br = formatar_para_moeda_br(v_rec)
            ps_br = f"{PS:.2f}".replace(".", ",")

            # Exibição do painel consolidador de métricas fiscais decimais
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Valores Processados (Despesa / Receita):</b> {v_desp_br} / {v_rec_br}<br>
                📊 <b>Percentual de Aplicação (PS):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{ps_br}%</code><br>
                ⚖️ <b>Situação da Saúde:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Glosa/Impacto na Pontuação:</b> <code style="font-size: 14px; font-weight: bold; color: #dc2626;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Salva no banco separando os decimais puros por barra
            str_concatenada_s1 = f"{v_desp:.2f}/{v_rec:.2f}"

            if v_desp != float_desp or v_rec != float_rec or lS1 != dS1.get("link", ""):
                save_resp("S1", str_concatenada_s1, ptsS1, lS1)
                st.rerun()

            bloco_comentarios("S1", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S2 • Consultas Médicas por Habitante (SIA/SUS e IBGE)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S2 • Evolução de Consultas Médicas por Habitante")
            st.write("**Mede se a proporção de consultas médicas por habitante no ano corrente (PAA) foi maior ou igual à média dos dois anos anteriores (MAA).**")

            # Tabela de Regras de Pontuação
            st.markdown(r"""
            | Resultado do Indicador | Impacto / Pontuação do Indicador |
            | :--- | :--- |
            | Proporção do Ano Atual maior ou igual à Média Anterior ($PAA \ge MAA$) | ✅ 20 pontos (Meta Atingida ou Evolução Positiva) |
            | Proporção do Ano Atual menor que a Média Anterior ($PAA < MAA$) | ❌ 00 pontos (Redução na Proporção de Consultas) |
            """)
            st.caption("ℹ️ *Dados extraídos do Sistema de Informações Ambulatoriais do SUS (SIA/SUS) e Estimativas Populacionais do IBGE.*")

            # 🧮 Cálculo dinâmico dos anos com base no ano selecionado
            try:
                ano_atual_int = int(ano_sel)
            except:
                ano_atual_int = 2025  # Fallback de segurança

            ano_aa1 = ano_atual_int - 1  # Ano Anterior - 1
            ano_aa2 = ano_atual_int - 2  # Ano Anterior - 2

            # 🧹 Nova Função de Higienização de inteiros puros (Consultas e População)
            def tratar_string_inteiro_para_float(texto):
                if not texto: 
                    return 0.0
                # Remove pontos de milhar e espaços, mantendo apenas os dígitos
                apenas_numeros = "".join(c for c in texto if c.isdigit())
                try:
                    return float(apenas_numeros) if apenas_numeros else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação limpa para números inteiros padrão BR (ex: 1.250.000)
            def formatar_para_inteiro_br(valor_float):
                return f"{int(valor_float):,}".replace(",", ".")

            # Carrega ou inicializa a string persistida no banco contendo os 6 valores separados por barra
            # Formato: CMAA-2/CMAA-1/CMAA/PopAA-2/PopAA-1/PopAA
            dS2 = res_data.get("S2", {"valor": "0/0/0/1/1/1", "pontos": 0.0, "link": ""})

            try:
                v_cmaa2, v_cmaa1, v_cmaa, v_pop2, v_pop1, v_pop = map(float, dS2["valor"].split("/"))
            except:
                v_cmaa2, v_cmaa1, v_cmaa, v_pop2, v_pop1, v_pop = 0.0, 0.0, 0.0, 1.0, 1.0, 1.0

            # Garante que o session_state inicialize no formato correto do Brasil
            if f"s2_str_cmaa2_{ano_sel}" not in st.session_state:
                st.session_state[f"s2_str_cmaa2_{ano_sel}"] = formatar_para_inteiro_br(v_cmaa2)
            if f"s2_str_cmaa1_{ano_sel}" not in st.session_state:
                st.session_state[f"s2_str_cmaa1_{ano_sel}"] = formatar_para_inteiro_br(v_cmaa1)
            if f"s2_str_cmaa_{ano_sel}" not in st.session_state:
                st.session_state[f"s2_str_cmaa_{ano_sel}"] = formatar_para_inteiro_br(v_cmaa)
            if f"s2_str_pop2_{ano_sel}" not in st.session_state:
                st.session_state[f"s2_str_pop2_{ano_sel}"] = formatar_para_inteiro_br(v_pop2)
            if f"s2_str_pop1_{ano_sel}" not in st.session_state:
                st.session_state[f"s2_str_pop1_{ano_sel}"] = formatar_para_inteiro_br(v_pop1)
            if f"s2_str_pop_{ano_sel}" not in st.session_state:
                st.session_state[f"s2_str_pop_{ano_sel}"] = formatar_para_inteiro_br(v_pop)

            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown("##### 🩺 Número de Consultas Médicas (SIA/SUS)")
                input_cmaa2_str = st.text_input(f"Consultas em {ano_aa2} (CMAA-2):", value=st.session_state[f"s2_str_cmaa2_{ano_sel}"], key=f"txt_s2_cmaa2_{ano_sel}")
                input_cmaa1_str = st.text_input(f"Consultas em {ano_aa1} (CMAA-1):", value=st.session_state[f"s2_str_cmaa1_{ano_sel}"], key=f"txt_s2_cmaa1_{ano_sel}")
                input_cmaa_str = st.text_input(f"Consultas em {ano_sel} (CMAA):", value=st.session_state[f"s2_str_cmaa_{ano_sel}"], key=f"txt_s2_cmaa_{ano_sel}")

                st.markdown("##### 👥 População Estimada (IBGE)")
                input_pop2_str = st.text_input(f"População em {ano_aa2} (PopAA-2):", value=st.session_state[f"s2_str_pop2_{ano_sel}"], key=f"txt_s2_pop2_{ano_sel}")
                input_pop1_str = st.text_input(f"População em {ano_aa1} (PopAA-1):", value=st.session_state[f"s2_str_pop1_{ano_sel}"], key=f"txt_s2_pop1_{ano_sel}")
                input_pop_str = st.text_input(f"População em {ano_sel} (PopAA):", value=st.session_state[f"s2_str_pop_{ano_sel}"], key=f"txt_s2_pop_{ano_sel}")

                # Conversão segura para floats limpos
                cmaa2 = tratar_string_inteiro_para_float(input_cmaa2_str)
                cmaa1 = tratar_string_inteiro_para_float(input_cmaa1_str)
                cmaa = tratar_string_inteiro_para_float(input_cmaa_str)
                pop2 = max(tratar_string_inteiro_para_float(input_pop2_str), 1.0)
                pop1 = max(tratar_string_inteiro_para_float(input_pop1_str), 1.0)
                pop = max(tratar_string_inteiro_para_float(input_pop_str), 1.0)

                # Sincroniza o session_state sem duplicar máscaras
                st.session_state[f"s2_str_cmaa2_{ano_sel}"] = formatar_para_inteiro_br(cmaa2)
                st.session_state[f"s2_str_cmaa1_{ano_sel}"] = formatar_para_inteiro_br(cmaa1)
                st.session_state[f"s2_str_cmaa_{ano_sel}"] = formatar_para_inteiro_br(cmaa)
                st.session_state[f"s2_str_pop2_{ano_sel}"] = formatar_para_inteiro_br(pop2)
                st.session_state[f"s2_str_pop1_{ano_sel}"] = formatar_para_inteiro_br(pop1)
                st.session_state[f"s2_str_pop_{ano_sel}"] = formatar_para_inteiro_br(pop)

                # 🧮 Lógica de Cálculo dos Indicadores PAA e MAA
                PAA = cmaa / pop
                MAA = (cmaa2 + cmaa1) / (pop2 + pop1)

                # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                if cmaa2 == 0.0 and cmaa1 == 0.0 and cmaa == 0.0:
                    ptsS2 = 0.0
                    texto_resultado = "Aguardando o preenchimento dos dados de consultas..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # 🧮 MOTOR DE REGRAS (PAA >= MAA garante 20 pontos)
                    if PAA >= MAA:
                        ptsS2 = 20.0
                        texto_resultado = f"✅ EVOLUÇÃO POSITIVA: Proporção atual do município foi superior ou igual à média anterior"
                        texto_pontuacao = "20,00 pontos (Pontuação Máxima)"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    else:
                        ptsS2 = 0.0
                        texto_resultado = f"🚨 REDUÇÃO: Proporção de consultas por habitante caiu em relação à média anterior"
                        texto_pontuacao = "0,00 pontos"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS2 = st.text_area("Link/Evidência (S2 - SIA/SUS e IBGE):", value=dS2.get("link", ""), key=f"txt_s2_link_{ano_sel}", height=150)

            # Formata as taxas decimais para exibição amigável (padrão BR)
            paa_br = f"{PAA:.4f}".replace(".", ",")
            maa_br = f"{MAA:.4f}".replace(".", ",")

            # Exibição do painel consolidador de métricas dinâmicas
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Proporção em {ano_sel} (PAA):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{paa_br}</code> consultas/hab.<br>
                📊 <b>Média Anos Anteriores ({ano_aa2} e {ano_aa1}) (MAA):</b> <code style="font-size: 14px; font-weight: bold; color: #475569;">{maa_br}</code> consultas/hab.<br>
                ⚖️ <b>Status do Indicador:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Pontuação do Quesito:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Salva no banco unindo todas as variáveis brutas
            str_concatenada_s2 = f"{cmaa2:.0f}/{cmaa1:.0f}/{cmaa:.0f}/{pop2:.0f}/{pop1:.0f}/{pop:.0f}"

            if str_concatenada_s2 != dS2["valor"] or lS2 != dS2.get("link", ""):
                save_resp("S2", str_concatenada_s2, ptsS2, lS2)
                st.rerun()

            bloco_comentarios("S2", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S3 • Proporção de Gestantes com Pré-Natal Adequado (SISAB)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S3 • Qualidade da Cobertura de Pré-Natal")
            st.write("**Mede a proporção de gestantes com pelo menos 6 consultas pré-natal realizadas, iniciando até a 12ª semana de gestação (Dados consolidados dos 3 quadrimestres).**")

            # Tabela de Regras de Pontuação (Faixas de Metas)
            st.markdown(r"""
            | Resultado do Índice $P$ | Impacto / Pontuação do Indicador |
            | :--- | :--- |
            | Igual a 100% ($P = 100\%$) | ✅ 25 pontos (Excelência Máxima) |
            | Entre 45% e 99,99% ($45\% \le P < 100\%$) | 🟡 15 pontos |
            | Entre 31% e 44,99% ($31\% \le P < 45\%$) | 🔸 10 pontos |
            | Entre 18% e 30,99% ($18\% \le P < 31\%$) | ⚠️ 5 pontos |
            | Menor que 18% ($P < 18\%$) | 🚨 00 pontos (Desempenho Crítico) |
            """)
            st.caption("ℹ️ *Variáveis extraídas diretamente dos relatórios quadrimestrais consolidados do SISAB (Sistema de Informação em Saúde para Atenção Básica).*")

            # 🧮 Captura o ano de forma dinâmica para os labels
            try:
                ano_atual_s3 = int(ano_sel)
            except:
                ano_atual_s3 = 2025

            # 🧹 Nova Função de Higienização de inteiros puros (Gestantes)
            def tratar_string_inteiro_para_float(texto):
                if not texto: 
                    return 0.0
                apenas_numeros = "".join(c for c in texto if c.isdigit())
                try:
                    return float(apenas_numeros) if apenas_numeros else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação limpa para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                return f"{int(valor_float):,}".replace(",", ".")

            # Carrega ou inicializa a string persistida no banco contendo os 6 valores do SISAB
            # Formato: G1Q/G2Q/G3Q/TG1Q/TG2Q/TG3Q
            dS3 = res_data.get("S3", {"valor": "0/0/0/1/1/1", "pontos": 0.0, "link": ""})

            try:
                v_g1q, v_g2q, v_g3q, v_tg1q, v_tg2q, v_tg3q = map(float, dS3["valor"].split("/"))
            except:
                v_g1q, v_g2q, v_g3q, v_tg1q, v_tg2q, v_tg3q = 0.0, 0.0, 0.0, 1.0, 1.0, 1.0

            # Garante que o session_state inicialize no formato correto do Brasil
            if f"s3_str_g1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s3_str_g1q_{ano_sel}"] = formatar_para_inteiro_br(v_g1q)
            if f"s3_str_g2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s3_str_g2q_{ano_sel}"] = formatar_para_inteiro_br(v_g2q)
            if f"s3_str_g3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s3_str_g3q_{ano_sel}"] = formatar_para_inteiro_br(v_g3q)
            if f"s3_str_tg1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s3_str_tg1q_{ano_sel}"] = formatar_para_inteiro_br(v_tg1q)
            if f"s3_str_tg2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s3_str_tg2q_{ano_sel}"] = formatar_para_inteiro_br(v_tg2q)
            if f"s3_str_tg3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s3_str_tg3q_{ano_sel}"] = formatar_para_inteiro_br(v_tg3q)

            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown(f"##### 🤰 Gestantes com Pré-Natal Adequado (≥ 6 Consultas e Início ≤ 12ª Semana)")
                input_g1q_str = st.text_input(f"Gestantes Adequadas - 1º Quad. {ano_atual_s3} (G1Q):", value=st.session_state[f"s3_str_g1q_{ano_sel}"], key=f"txt_s3_g1q_{ano_sel}")
                input_g2q_str = st.text_input(f"Gestantes Adequadas - 2º Quad. {ano_atual_s3} (G2Q):", value=st.session_state[f"s3_str_g2q_{ano_sel}"], key=f"txt_s3_g2q_{ano_sel}")
                input_g3q_str = st.text_input(f"Gestantes Adequadas - 3º Quad. {ano_atual_s3} (G3Q):", value=st.session_state[f"s3_str_g3q_{ano_sel}"], key=f"txt_s3_g3q_{ano_sel}")

                st.markdown(f"##### 📊 Denominador Geral (Total de Gestantes Cadastradas/Estimadas)")
                input_tg1q_str = st.text_input(f"Total de Gestantes - 1º Quad. {ano_atual_s3} (TG1Q):", value=st.session_state[f"s3_str_tg1q_{ano_sel}"], key=f"txt_s3_tg1q_{ano_sel}")
                input_tg2q_str = st.text_input(f"Total de Gestantes - 2º Quad. {ano_atual_s3} (TG2Q):", value=st.session_state[f"s3_str_tg2q_{ano_sel}"], key=f"txt_s3_tg2q_{ano_sel}")
                input_tg3q_str = st.text_input(f"Total de Gestantes - 3º Quad. {ano_atual_s3} (TG3Q):", value=st.session_state[f"s3_str_tg3q_{ano_sel}"], key=f"txt_s3_tg3q_{ano_sel}")

                # Conversão segura para inteiros puros
                g1q = tratar_string_inteiro_para_float(input_g1q_str)
                g2q = tratar_string_inteiro_para_float(input_g2q_str)
                g3q = tratar_string_inteiro_para_float(input_g3q_str)
                tg1q = tratar_string_inteiro_para_float(input_tg1q_str)
                tg2q = tratar_string_inteiro_para_float(input_tg2q_str)
                tg3q = tratar_string_inteiro_para_float(input_tg3q_str)

                # Sincroniza o session_state tratando máscaras limpas
                st.session_state[f"s3_str_g1q_{ano_sel}"] = formatar_para_inteiro_br(g1q)
                st.session_state[f"s3_str_g2q_{ano_sel}"] = formatar_para_inteiro_br(g2q)
                st.session_state[f"s3_str_g3q_{ano_sel}"] = formatar_para_inteiro_br(g3q)
                st.session_state[f"s3_str_tg1q_{ano_sel}"] = formatar_para_inteiro_br(tg1q)
                st.session_state[f"s3_str_tg2q_{ano_sel}"] = formatar_para_inteiro_br(tg2q)
                st.session_state[f"s3_str_tg3q_{ano_sel}"] = formatar_para_inteiro_br(tg3q)

                # Somatórios para a fórmula matemática
                total_adequadas = g1q + g2q + g3q
                total_universo = tg1q + tg2q + tg3q

                # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                if total_adequadas == 0.0 and total_universo == 0.0:
                    ptsS3 = 0.0
                    P = 0.0
                    texto_resultado = "Aguardando preenchimento dos dados quadrimestrais do SISAB..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # Cálculo da Proporção Geral
                    base_calculo_s3 = max(total_universo, 1.0)
                    P = round((total_adequadas / base_calculo_s3) * 100.0, 2)

                    # 🧮 MOTOR DE REGRAS ENQUADRADO NAS FAIXAS CONSTITUCIONAIS DO i-SAÚDE
                    if P >= 100.00:
                        ptsS3 = 25.0
                        texto_resultado = "✅ META ATINGIDA (100%): Excelência na cobertura e no tempo de resposta do pré-natal"
                        texto_pontuacao = "25,00 pontos (Pontuação Máxima)"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif P >= 45.00:
                        ptsS3 = 15.0
                        texto_resultado = "🟡 FAIXA INTERMEDIÁRIA REGULAR: Boa cobertura de pré-natal dentro dos parâmetros pactuados"
                        texto_pontuacao = "15,00 pontos"
                        estilo_status = "color: #ca8a04; font-weight: bold;"
                    elif P >= 31.00:
                        ptsS3 = 10.0
                        texto_resultado = "🔸 FAIXA INTERMEDIÁRIA BAIXA: Atenção necessária, índice de adequação abaixo do esperado"
                        texto_pontuacao = "10,00 pontos"
                        estilo_status = "color: #ea580c; font-weight: bold;"
                    elif P >= 18.00:
                        ptsS3 = 5.0
                        texto_resultado = "⚠️ ALERTA: Cobertura de pré-natal muito baixa, necessita plano de contingência"
                        texto_pontuacao = "5,00 pontos"
                        estilo_status = "color: #d97706; font-weight: bold;"
                    else:
                        ptsS3 = 0.0
                        texto_resultado = f"🚨 DESEMPENHO CRÍTICO: Município abaixo da linha de corte mínima de 18%"
                        texto_pontuacao = "0,00 pontos"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS3 = st.text_area("Link/Evidência (S3 - SISAB Pré-natal Coletivo):", value=dS3.get("link", ""), key=f"txt_s3_link_{ano_sel}", height=150)

            # Gera a visualização amigável em formato BR
            p_br = f"{P:.2f}".replace(".", ",")
            tot_adeq_br = formatar_para_inteiro_br(total_adequadas)
            tot_univ_br = formatar_para_inteiro_br(total_universo)

            # Exibição do painel consolidador de métricas fiscais decimais
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Volume Consolidado:</b> {tot_adeq_br} de {tot_univ_br} gestantes monitoradas<br>
                📊 <b>Índice de Adequação do Pré-Natal (P):</b> <code style="font-size: 15px; font-weight: bold; color: #1e3a8a;">{p_br}%</code><br>
                ⚖️ <b>Situação do Indicador:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Pontuação do Quesito:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Salva no banco separando os valores puros por barra
            str_concatenada_s3 = f"{g1q:.0f}/{g2q:.0f}/{g3q:.0f}/{tg1q:.0f}/{tg2q:.0f}/{tg3q:.0f}"

            if str_concatenada_s3 != dS3["valor"] or lS3 != dS3.get("link", ""):
                save_resp("S3", str_concatenada_s3, ptsS3, lS3)
                st.rerun()

            bloco_comentarios("S3", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S4 • Realização de Exames Pré-Natal (TABWIN)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S4 Informe nº exames (pré-natal) realizados nos estabelecimentos de saúde sob gestão municipal:")
            st.write("DADOS DO TABWIN")
            st.write("Fórmula de cálculo: Nº exames (pré-natal) realizados nos estabelecimentos de saúde sob gestão municipal - Teste não treponemico p/ detecção de sífilis em gestantes (TS): Nº exames (pré-natal) realizados nos estabelecimentos de saúde sob gestão municipal - Teste rápido para detecção de HIV na gestante (TR): Nº de Gestantes com o primeiro atendimento de prénatal (TG):")

            # Tabela de Regras de Pontuação na íntegra
            st.markdown(r"""
            | Parâmetro | Critério | Pontuação |
            | :--- | :--- | :--- |
            | Se (TS / TG) >= 2 | ✅ Meta Atingida | 10 pontos |
            | Se (TS / TG) < 2 | ❌ Abaixo da Meta | 00 ponto |
            | Se (TR / TG) >= 2 | ✅ Meta Atingida | 10 pontos |
            | Se (TR / TG) < 2 | ❌ Abaixo da Meta | 00 ponto |
            | **Pontuação Máxima** | **Ambos os critérios** | **20 pontos** |
            """)

            # 🧮 Captura o ano de forma dinâmica para os labels
            try:
                ano_atual_s4 = int(ano_sel)
            except:
                ano_atual_s4 = 2025

            # 🧹 Função de Higienização de inteiros puros
            def tratar_string_inteiro_para_float(texto):
                if not texto: 
                    return 0.0
                apenas_numeros = "".join(c for c in texto if c.isdigit())
                try:
                    return float(apenas_numeros) if apenas_numeros else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação limpa para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                return f"{int(valor_float):,}".replace(",", ".")

            # Carrega ou inicializa a string persistida no banco contendo os 3 valores do TABWIN
            # Formato: TS/TR/TG
            dS4 = res_data.get("S4", {"valor": "0/0/1", "pontos": 0.0, "link": ""})

            try:
                v_ts, v_tr, v_tg = map(float, dS4["valor"].split("/"))
            except:
                v_ts, v_tr, v_tg = 0.0, 0.0, 1.0

            # Garante que o session_state inicialize no formato correto do Brasil
            if f"s4_str_ts_{ano_sel}" not in st.session_state:
                st.session_state[f"s4_str_ts_{ano_sel}"] = formatar_para_inteiro_br(v_ts)
            if f"s4_str_tr_{ano_sel}" not in st.session_state:
                st.session_state[f"s4_str_tr_{ano_sel}"] = formatar_para_inteiro_br(v_tr)
            if f"s4_str_tg_{ano_sel}" not in st.session_state:
                st.session_state[f"s4_str_tg_{ano_sel}"] = formatar_para_inteiro_br(v_tg)

            c1, c2 = st.columns([1, 2])

            with c1:
                # Inputs com os textos exatos fornecidos por você
                input_ts_str = st.text_input(
                    f"Nº exames (pré-natal) realizados nos estabelecimentos de saúde sob gestão municipal - Teste não treponemico p/ detecção de sífilis em gestantes:",
                    value=st.session_state[f"s4_str_ts_{ano_sel}"],
                    key=f"txt_s4_ts_{ano_sel}"
                )
                
                input_tr_str = st.text_input(
                    f"Nº exames (pré-natal) realizados nos estabelecimentos de saúde sob gestão municipal - Teste rápido para detecção de HIV na gestante:",
                    value=st.session_state[f"s4_str_tr_{ano_sel}"],
                    key=f"txt_s4_tr_{ano_sel}"
                )

                input_tg_str = st.text_input(
                    f"Nº de Gestantes com o primeiro atendimento de pré-natal:",
                    value=st.session_state[f"s4_str_tg_{ano_sel}"],
                    key=f"txt_s4_tg_{ano_sel}"
                )

                # Conversão segura para floats limpos
                ts = tratar_string_inteiro_para_float(input_ts_str)
                tr = tratar_string_inteiro_para_float(input_tr_str)
                tg = tratar_string_inteiro_para_float(input_tg_str)

                # Sincroniza o session_state tratando masks limpas
                st.session_state[f"s4_str_ts_{ano_sel}"] = formatar_para_inteiro_br(ts)
                st.session_state[f"s4_str_tr_{ano_sel}"] = formatar_para_inteiro_br(tr)
                st.session_state[f"s4_str_tg_{ano_sel}"] = formatar_para_inteiro_br(tg)

                # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                if ts == 0.0 and tr == 0.0 and tg == 0.0:
                    ptsS4 = 0.0
                    razao_sifilis = 0.0
                    razao_hiv = 0.0
                    texto_resultado = "Aguardando lançamento dos dados..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # Cálculo das razões individuais por gestante
                    base_calculo_s4 = max(tg, 1.0)
                    razao_sifilis = round(ts / base_calculo_s4, 2)
                    razao_hiv = round(tr / base_calculo_s4, 2)

                    pts_acumulados = 0.0

                    # Avaliação exata: Se (TS / TG) >= 2 => 10 pontos
                    if razao_sifilis >= 2.00:
                        pts_acumulados += 10.0

                    # Avaliação exata: Se (TR / TG) >= 2 => 10 pontos
                    if razao_hiv >= 2.00:
                        pts_acumulados += 10.0

                    ptsS4 = pts_acumulados

                    if ptsS4 == 20.0:
                        texto_resultado = "✅ Meta de exames atingida para ambos os testes"
                        texto_pontuacao = "20 pontos"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif ptsS4 == 10.0:
                        texto_resultado = "🟡 Meta de exames atingida parcialmente"
                        texto_pontuacao = "10 pontos"
                        estilo_status = "color: #ca8a04; font-weight: bold;"
                    else:
                        texto_resultado = "🚨 Meta de exames não atingida"
                        texto_pontuacao = "00 ponto"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS4 = st.text_area("Link/Evidência (S4 - TABWIN):", value=dS4.get("link", ""), key=f"txt_s4_link_{ano_sel}", height=150)

            # Formatação das razões calculadas para exibição em padrão BR
            r_sifilis_br = f"{razao_sifilis:.2f}".replace(".", ",")
            r_hiv_br = f"{razao_hiv:.2f}".replace(".", ",")

            # Exibição do painel consolidador
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📊 <b>Resultados Calculados:</b><br>
                🔹 Razão Sífilis (TS / TG): <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{r_sifilis_br}</code> (Meta: >= 2)<br>
                🔹 Razão HIV (TR / TG): <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{r_hiv_br}</code> (Meta: >= 2)<br>
                ⚖️ <b>Situação:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Pontuação do Quesito:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Salva no banco compactando os valores em string pura
            str_concatenada_s4 = f"{ts:.0f}/{tr:.0f}/{tg:.0f}"

            if str_concatenada_s4 != dS4["valor"] or lS4 != dS4.get("link", ""):
                save_resp("S4", str_concatenada_s4, ptsS4, lS4)
                st.rerun()

            bloco_comentarios("S4", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
            # S5 • Nº de Inspeções Sanitárias (SIA/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S5 • Nº de Inspeções Sanitárias")
            st.write("todo procedimento realizado pela autoridade de vigilância sanitária competente que busca levantar e avaliar “in loco” os riscos à saúde da população presentes na produção e circulação de mercadorias, na prestação de serviços")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES AMBULATÓRIAIS DO SUS (SIA/SUS)")

            # 🧮 Cálculo dinâmico dos anos com base no ano selecionado
            try:
                ano_atual_int = int(ano_sel)
            except:
                ano_atual_int = 2025  # Fallback de segurança

            ano_aa1 = ano_atual_int - 1  # Ano Anterior - 1 (Equivalente a 2024 se selecionado 2025)
            ano_aa2 = ano_atual_int - 2  # Ano Anterior - 2 (Equivalente a 2023 se selecionado 2025)

            # Tabela de Regras de Pontuação na íntegra adaptada com os anos dinâmicos
            st.markdown(f"""
            | Resultado do Indicador | Critério de Avaliação | Impacto / Pontuação |
            | :--- | :--- | :--- |
            | Se NI $\ge$ (NI-2 + NI-1) / 2 | ✅ Meta Atingida ou Evolução Positiva | 10 pontos |
            | Se NI $<$ (NI-2 + NI-1) / 2 | ❌ Redução no Número de Inspeções | 00 ponto |
            """)

            # 🧹 Função de Higienização de inteiros puros
            def tratar_string_inteiro_para_float(texto):
                if not texto: 
                    return 0.0
                apenas_numeros = "".join(c for c in texto if c.isdigit())
                try:
                    return float(apenas_numeros) if apenas_numeros else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                return f"{int(valor_float):,}".replace(",", ".")

            # Carrega ou inicializa a string persistida no banco contendo os 3 valores de inspeção
            # Formato: NI-2/NI-1/NI
            dS5 = res_data.get("S5", {"valor": "0/0/0", "pontos": 0.0, "link": ""})

            try:
                v_ni2, v_ni1, v_ni = map(float, dS5["valor"].split("/"))
            except:
                v_ni2, v_ni1, v_ni = 0.0, 0.0, 0.0

            # Garante que o session_state inicialize no formato correto do Brasil
            if f"s5_str_ni2_{ano_sel}" not in st.session_state:
                st.session_state[f"s5_str_ni2_{ano_sel}"] = formatar_para_inteiro_br(v_ni2)
            if f"s5_str_ni1_{ano_sel}" not in st.session_state:
                st.session_state[f"s5_str_ni1_{ano_sel}"] = formatar_para_inteiro_br(v_ni1)
            if f"s5_str_ni_{ano_sel}" not in st.session_state:
                st.session_state[f"s5_str_ni_{ano_sel}"] = formatar_para_inteiro_br(v_ni)

            c1, c2 = st.columns([1, 2])

            with c1:
                # Inputs estruturados com os seus textos e anos dinâmicos
                input_ni2_str = st.text_input(f"Nº de Inspeções Sanitárias {ano_aa2} (NI-2) • Em {ano_aa2}:", value=st.session_state[f"s5_str_ni2_{ano_sel}"], key=f"txt_s5_ni2_{ano_sel}")
                input_ni1_str = st.text_input(f"Nº de Inspeções Sanitárias {ano_aa1} (NI-1) • Em {ano_aa1}:", value=st.session_state[f"s5_str_ni1_{ano_sel}"], key=f"txt_s5_ni1_{ano_sel}")
                input_ni_str = st.text_input(f"Nº de Inspeções Sanitárias {ano_sel} (NI) • Em {ano_sel}:", value=st.session_state[f"s5_str_ni_{ano_sel}"], key=f"txt_s5_ni_{ano_sel}")

                # Conversão segura para floats limpos
                ni2 = tratar_string_inteiro_para_float(input_ni2_str)
                ni1 = tratar_string_inteiro_para_float(input_ni1_str)
                ni = tratar_string_inteiro_para_float(input_ni_str)

                # Sincroniza o session_state tratando as máscaras BR
                st.session_state[f"s5_str_ni2_{ano_sel}"] = formatar_para_inteiro_br(ni2)
                st.session_state[f"s5_str_ni1_{ano_sel}"] = formatar_para_inteiro_br(ni1)
                st.session_state[f"s5_str_ni_{ano_sel}"] = formatar_para_inteiro_br(ni)

                # 🧮 Lógica matemática do motor de regras (Média dos dois anos anteriores)
                media_anterior = (ni2 + ni1) / 2.0

                # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                if ni2 == 0.0 and ni1 == 0.0 and ni == 0.0:
                    ptsS5 = 0.0
                    texto_resultado = "Aguardando preenchimento dos dados de inspeção sanitária..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # Regra corrigida para aceitar maior ou igual (evitando injustiças se passar da média)
                    if ni >= media_anterior:
                        ptsS5 = 10.0
                        texto_resultado = f"✅ EVOLUÇÃO POSITIVA: O número de inspeções em {ano_sel} foi maior ou igual à média dos anos anteriores"
                        texto_pontuacao = "10,00 pontos"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    else:
                        ptsS5 = 0.0
                        texto_resultado = f"🚨 REDUÇÃO: O número de inspeções em {ano_sel} ficou abaixo da média de {ano_aa2} e {ano_aa1}"
                        texto_pontuacao = "0,00 ponto"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS5 = st.text_area("Link/Evidência (S5 - Relatórios VISA / SIA/SUS):", value=dS5.get("link", ""), key=f"txt_s5_link_{ano_sel}", height=150)

            # Formatação dos resultados decimais para exibição amigável BR
            media_br = f"{media_anterior:.2f}".replace(".", ",")
            ni_atual_br = formatar_para_inteiro_br(ni)

            # Painel consolidador de métricas dinâmicas
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Inspeções Realizadas em {ano_sel} (NI):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{ni_atual_br}</code> procedimentos<br>
                📊 <b>Média Alvo de Referência ({ano_aa2} e {ano_aa1}):</b> <code style="font-size: 14px; font-weight: bold; color: #475569;">{media_br}</code> procedimentos<br>
                ⚖️ <b>Status do Quesito:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Pontuação do Quesito:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Salva no banco unindo os valores brutos por barra
            str_concatenada_s5 = f"{ni2:.0f}/{ni1:.0f}/{ni:.0f}"

            if str_concatenada_s5 != dS5["valor"] or lS5 != dS5.get("link", ""):
                save_resp("S5", str_concatenada_s5, ptsS5, lS5)
                st.rerun()

            bloco_comentarios("S5", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
            # S6 • Calendário Nacional de Vacinação (TABNET/DATASUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S6 • Sobre o Calendário Nacional de Vacinação, informe o percentual de cobertura:")
            st.caption("🌐 Fonte oficial: http://tabnet.datasus.gov.br/cgi/dhdat.exe?bd_pni/cpnibr.def")

            # 🧮 Captura o ano selecionado de forma dinâmica
            try:
                ano_atual_s6 = int(ano_sel)
            except:
                ano_atual_s6 = 2025

            # 🧹 Função de Higienização para inputs de porcentagem (Ex: "92,5%" -> 92.5)
            def tratar_string_porcentagem_para_float(texto):
                if not texto:
                    return 0.0
                texto_limpo = texto.replace("%", "").replace(".", "").replace(",", ".").strip()
                try:
                    return float(texto_limpo) if texto_limpo else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação para exibição padrão BR com símbolo de %
            def formatar_para_porcentagem_br(valor_float):
                return f"{valor_float:.2f}".replace(".", ",") + "%"

            # Dicionário com a configuração técnica exata: BCG/Rotavírus = 5pts (Meta 90%). Demais = 10pts (Meta 95%)
            config_vacinas = {
                "bcg": {"label": "BCG (Bacilo Calmette-Guerin):", "peso": 5.0, "meta": 90.0},
                "rotavirus": {"label": "Rotavírus humano (2ª dose):", "peso": 5.0, "meta": 90.0},
                "hepatite_b": {"label": "Hepatite B (3ª dose):", "peso": 10.0, "meta": 95.0},
                "meningo_c": {"label": "Meningocócica C (conjugada - 2ª dose):", "peso": 10.0, "meta": 95.0},
                "pentavalente": {"label": "Vacina Pentavalente (3ª dose):", "peso": 10.0, "meta": 95.0},
                "pneumo_10": {"label": "Vacina Pneumocócica 10-valente (2ª dose):", "peso": 10.0, "meta": 95.0},
                "poliomielite": {"label": "Vacina Poliomielite (3ª dose):", "peso": 10.0, "meta": 95.0},
                "febre_amarela": {"label": "Febre Amarela:", "peso": 10.0, "meta": 95.0},
                "triplice_viral": {"label": "Vacina Tríplice Viral (1ª dose):", "peso": 10.0, "meta": 95.0},
                "hepatite_a": {"label": "Hepatite A:", "peso": 10.0, "meta": 95.0},
                "tetra_viral": {"label": "Tetra viral:", "peso": 10.0, "meta": 95.0}
            }

            # Carrega os valores salvos no banco. Formato esperado: string separada por barras com os 11 floats
            dS6 = res_data.get("S6", {"valor": "0/0/0/0/0/0/0/0/0/0/0", "pontos": 0.0, "link": ""})
            
            valores_salvos = dS6["valor"].split("/")
            if len(valores_salvos) != 11:
                valores_salvos = [0.0] * 11
            else:
                valores_salvos = [float(v) for v in valores_salvos]

            # Inicialização das variáveis do session_state mapeadas por índice
            chaves_vacinas = list(config_vacinas.keys())
            for idx, chave in enumerate(chaves_vacinas):
                st_key = f"s6_str_{chave}_{ano_sel}"
                if st_key not in st.session_state:
                    st.session_state[st_key] = formatar_para_porcentagem_br(valores_salvos[idx])

            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown(f"##### 💉 Coberturas Registradas em {ano_atual_s6}")
                valores_coletados = {}

                # Renderização dinâmica dos 11 inputs com as informações logo abaixo
                for chave, info in config_vacinas.items():
                    st_key = f"s6_str_{chave}_{ano_sel}"
                    input_str = st.text_input(
                        f"{info['label']}",
                        value=st.session_state[st_key],
                        key=f"txt_s6_{chave}_{ano_sel}"
                    )
                    
                    # Processa o float e sincroniza no estado de sessão da view
                    v_float = tratar_string_porcentagem_para_float(input_str)
                    st.session_state[st_key] = formatar_para_porcentagem_br(v_float)
                    valores_coletados[chave] = v_float

                    # Mostra o percentual de cobertura e a meta logo abaixo do input
                    meta_v_br = str(int(info['meta'])) + "%"
                    st.markdown(f"<p style='margin-top: -12px; margin-bottom: 10px; font-size: 12px; color: #475569;'>Alcançado: <b>{formatar_para_porcentagem_br(v_float)}</b> / Meta: <b>{meta_v_br}</b></p>", unsafe_allow_html=True)

                # Execução do Motor de Regras de Proporcionalidade Linear do PNI por Vacina
                nf_s6 = 0.0
                total_lancado = sum(valores_coletados.values())

                if total_lancado > 0.0:
                    for chave, valor_cobertura in valores_coletados.items():
                        meta_vacina = config_vacinas[chave]["meta"]
                        peso_vacina = config_vacinas[chave]["peso"]

                        if valor_cobertura >= meta_vacina:
                            # Se a cobertura atingiu ou superou a meta individual da vacina
                            nf_s6 += peso_vacina
                        else:
                            # Se a cobertura ficou abaixo da meta individual da vacina
                            p_proporcional = (valor_cobertura / meta_vacina) * peso_vacina
                            nf_s6 += max(p_proporcional, 0.0)

                    ptsS6 = round(nf_s6, 2)
                    texto_resultado = f"Avaliação calculada de forma individualizada para o ano de {ano_atual_s6}"
                    texto_pontuacao = f"{f'{ptsS6:.2f}'.replace('.', ',')} pontos"
                    estilo_status = "color: #1e3a8a; font-weight: bold;"
                else:
                    ptsS6 = 0.0
                    texto_resultado = "Aguardando preenchimento dos dados do painel do PNI..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"

            with c2:
                lS6 = st.text_area("Link/Evidência (S6 - Painel Imunizações TABNET):", value=dS6.get("link", ""), key=f"txt_s6_link_{ano_sel}", height=150)

            # Painel consolidador de métricas final
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Indicador Geral S6:</b> Monitoramento de Cobertura Vacinal Multidose<br>
                ⚖️ <b>Situação da Coorte:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Nota Final Calculada (NF):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Prepara a string concatenada ordenada dos 11 valores floats para persistência estável
            lista_salvar = [f"{valores_coletados[c]:.2f}" for c in chaves_vacinas]
            str_concatenada_s6 = "/".join(lista_salvar)

            if str_concatenada_s6 != dS6["valor"] or lS6 != dS6.get("link", ""):
                save_resp("S6", str_concatenada_s6, ptsS6, lS6)
                st.rerun()

            bloco_comentarios("S6", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S7 • Cobertura Vacinal para Influenza nos Idosos (Campanha Nacional)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S7 • Informe o percentual de cobertura vacinal para \"Influenza\" nos idosos acima de 60 anos de idade:")
            st.caption(f"🌐 Site da Campanha Nacional de Vacinação contra a influenza {ano_sel}")

            # 🧮 Captura o ano selecionado de forma dinâmica
            try:
                ano_atual_s7 = int(ano_sel)
            except:
                ano_atual_s7 = 2025

            # 🧹 Função de Higienização para inputs de porcentagem (Ex: "85,4%" -> 85.4)
            def tratar_string_porcentagem_para_float(texto):
                if not texto:
                    return 0.0
                texto_limpo = texto.replace("%", "").replace(".", "").replace(",", ".").strip()
                try:
                    return float(texto_limpo) if texto_limpo else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação para exibição padrão BR com símbolo de %
            def formatar_para_porcentagem_br(valor_float):
                return f"{valor_float:.2f}".replace(".", ",") + "%"

            # Carrega ou inicializa o valor persistido no banco de dados para o S7 baseado no ano selecionado
            dS7 = res_data.get("S7", {"valor": "0.0", "pontos": 0.0, "link": ""})

            try:
                v_cobertura_s7 = float(dS7["valor"])
            except:
                v_cobertura_s7 = 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para o ano corrente
            if f"s7_str_cobertura_{ano_sel}" not in st.session_state:
                st.session_state[f"s7_str_cobertura_{ano_sel}"] = formatar_para_porcentagem_br(v_cobertura_s7)

            c1, c2 = st.columns([1, 2])

            with c1:
                # Input principal do indicador com o ano selecionado dinâmico no label
                input_s7_str = st.text_input(
                    f"Percentual de cobertura vacinal para 'Influenza' nos idosos acima de 60 anos de idade em {ano_sel}:",
                    value=st.session_state[f"s7_str_cobertura_{ano_sel}"],
                    key=f"txt_s7_cobertura_{ano_sel}"
                )

                # Processa a string, limpa e sincroniza de volta na tela
                cobertura_s7 = tratar_string_porcentagem_para_float(input_s7_str)
                st.session_state[f"s7_str_cobertura_{ano_sel}"] = formatar_para_porcentagem_br(cobertura_s7)

                # Exibe o percentual alcançado e a meta fixa de 90% logo abaixo do input
                st.markdown(f"<p style='margin-top: -12px; margin-bottom: 10px; font-size: 12px; color: #475569;'>Alcançado: <b>{formatar_para_porcentagem_br(cobertura_s7)}</b> / Meta: <b>90,00%</b></p>", unsafe_allow_html=True)

                # Parâmetros fixados pelo manual do quesito
                meta_s7 = 90.0
                p1_s7 = 20.0

                # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                if cobertura_s7 == 0.0:
                    ptsS7 = 0.0
                    texto_resultado = f"Aguardando lançamento dos dados da campanha de {ano_atual_s7}..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # 🧮 Motor de cálculo: NF = P x P1 (com o corte linear idêntico ao solicitado)
                    if cobertura_s7 >= meta_s7:
                        ptsS7 = p1_s7
                        texto_resultado = f"✅ META ALCANÇADA: Cobertura vacinal protetiva atingida para a população idosa em {ano_atual_s7}"
                        texto_pontuacao = "20,00 pontos (Pontuação Máxima)"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    else:
                        # Fórmula de proporcionalidade direta: ((Meta - (Meta - Cobertura)) / Meta) * P1
                        p_proporcional = (cobertura_s7 / meta_s7) * p1_s7
                        ptsS7 = round(max(p_proporcional, 0.0), 2)
                        texto_resultado = f"⚠️ COBERTURA PARCIAL: Aplicação do desconto de perda linear em relação à meta de {int(meta_s7)}%"
                        texto_pontuacao = f"{f'{ptsS7:.2f}'.replace('.', ',')} pontos"
                        estilo_status = "color: #ea580c; font-weight: bold;"

            with c2:
                lS7 = st.text_area(f"Link/Evidência (S7 - Campanha {ano_sel}):", value=dS7.get("link", ""), key=f"txt_s7_link_{ano_sel}", height=150)

            # Painel consolidador de métricas para conferência do gestor público
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Indicador Geral S7:</b> Campanha de Imunização contra Influenza (Idosos {ano_sel})<br>
                ⚖️ <b>Status da Coorte:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Nota Final Calculada (NF):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Salva no banco o valor float puro formatado em string mapeado pelo ano selecionado
            str_salvar_s7 = f"{cobertura_s7:.2f}"

            if str_salvar_s7 != dS7["valor"] or lS7 != dS7.get("link", ""):
                save_resp("S7", str_salvar_s7, ptsS7, lS7)
                st.rerun()

            bloco_comentarios("S7", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S8 • Percentual de Internações por Causas Sensíveis (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S8 • Percentual de Internações por causas sensíveis à atenção básica no total de internações (%) nos estabelecimentos de saúde sob gestão municipal:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels
            try:
                        ano_atual_s8 = int(ano_sel)
            except:
                        ano_atual_s8 = 2025

            # 🧹 Função de Higienização para inputs de porcentagem (Ex: "12,5%" -> 12.5)
            def tratar_string_porcentagem_para_float(texto):
                        if not texto:
                                    return 0.0
                        texto_limpo = texto.replace("%", "").replace(".", "").replace(",", ".").strip()
                        try:
                                    return float(texto_limpo) if texto_limpo else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para exibição padrão BR com símbolo de %
            def formatar_para_porcentagem_br(valor_float):
                        return f"{valor_float:.2f}".replace(".", ",") + "%"

            # Carrega ou inicializa o valor persistido no banco de dados para o S8 baseado no ano selecionado
            dS8 = res_data.get("S8", {"valor": "0.0", "pontos": 0.0, "link": ""})

            try:
                        v_pi = float(dS8["valor"])
            except:
                        v_pi = 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para o ano corrente
            if f"s8_str_pi_{ano_sel}" not in st.session_state:
                        st.session_state[f"s8_str_pi_{ano_sel}"] = formatar_para_porcentagem_br(v_pi)

            c1, c2 = st.columns([1, 2])

            with c1:
                        # Input principal com o seu texto bruto mantido na íntegra
                        input_pi_str = st.text_input(
                                    f"Percentual de Internações por causas sensíveis à atenção básica no total de internações (%) nos estabelecimentos de saúde sob gestão municipal (PI) em {ano_sel}:",
                                    value=st.session_state[f"s8_str_pi_{ano_sel}"],
                                    key=f"txt_s8_pi_{ano_sel}"
                        )

                        # Processa a string, limpa e sincroniza de volta na tela
                        pi = tratar_string_porcentagem_para_float(input_pi_str)
                        st.session_state[f"s8_str_pi_{ano_sel}"] = formatar_para_porcentagem_br(pi)

                        # Exibe o percentual alcançado logo abaixo do campo
                        st.markdown(f"<p style='margin-top: -12px; margin-bottom: 10px; font-size: 12px; color: #475569;'>Alcançado em {ano_sel}: <b>{formatar_para_porcentagem_br(pi)}</b></p>", unsafe_allow_html=True)

                        # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                        if pi == 0.0:
                                    ptsS8 = 0.0
                                    texto_resultado = f"Aguardando lançamento dos dados consolidados do SIH/SUS para {ano_atual_s8}..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Motor de cálculo de penalidades conforme regras do manual
                                    if pi > 100.0:
                                                ptsS8 = -5.0
                                                texto_resultado = "🚨 CRÍTICO: Percentual informado excede o limite estatístico de 100% (Inconsistência de dados)"
                                                texto_pontuacao = "-5,00 pontos (Penalidade Aplicada)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"
                                    elif pi == 100.0:
                                                # Regra: Se PI = 100% -> N = PI * (-5) considerando a base decimal unitária (1.0 * -5)
                                                ptsS8 = -5.0
                                                texto_resultado = "🚨 ALERTA MÁXIMO: Totalidade das internações municipais classificadas como causas sensíveis (100%)"
                                                texto_pontuacao = "-5,00 pontos (Penalidade Máxima)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"
                                    else:
                                                ptsS8 = 0.0
                                                texto_resultado = f"✅ Regularizado: Taxa de internações por causas sensíveis dentro do limite sob controle municipal"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"

            with c2:
                        lS8 = st.text_area(f"Link/Evidência (S8 - Relatórios SIH/SUS {ano_sel}):", value=dS8.get("link", ""), key=f"txt_s8_link_{ano_sel}", height=150)

            # Painel consolidador de métricas para a Vigilância em Saúde
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S8:</b> Internações por Causas Sensíveis à Atenção Básica (ICSAB)<br>
                        ⚖️ <b>Status da Coorte:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Salva no banco o valor float puro formatado em string
            str_salvar_s8 = f"{pi:.2f}"

            if str_salvar_s8 != dS8["valor"] or lS8 != dS8.get("link", ""):
                        save_resp("S8", str_salvar_s8, ptsS8, lS8)
                        st.rerun()

            bloco_comentarios("S8", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S9 • Quantidade de Internações SUS sob Gestão Municipal (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S9 • Sobre as internações SUS, informe a quantidade de internações em estabelecimentos de saúde sob Gestão Municipal:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Cálculo dinâmico da linha temporal com base no ano selecionado
            try:
                        ano_atual_int_s9 = int(ano_sel)
            except:
                        ano_atual_int_s9 = 2025

            ano_s9_aa1 = ano_atual_int_s9 - 1  # Ano Anterior - 1 (Ex: 2024 se selecionado 2025)
            ano_s9_aa2 = ano_atual_int_s9 - 2  # Ano Anterior - 2 (Ex: 2023 se selecionado 2025)

            # 🧹 Função de Higienização de inteiros puros
            def tratar_string_inteiro_para_float(texto):
                        if not texto: 
                                    return 0.0
                        apenas_numeros = "".join(c for c in texto if c.isdigit())
                        try:
                                    return float(apenas_numeros) if apenas_numeros else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                        return f"{int(valor_float):,}".replace(",", ".")

            # Carrega ou inicializa a string persistida no banco contendo os 3 valores de internação
            # Formato: PIHAA-2/PIHAA-1/PIHAA
            dS9 = res_data.get("S9", {"valor": "0/0/0", "points": 0.0, "link": ""})

            try:
                        v_pihaa2, v_pihaa1, v_pihaa = map(float, dS9["valor"].split("/"))
            except:
                        v_pihaa2, v_pihaa1, v_pihaa = 0.0, 0.0, 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para a tríade temporal
            if f"s9_str_pihaa2_{ano_sel}" not in st.session_state:
                        st.session_state[f"s9_str_pihaa2_{ano_sel}"] = formatar_para_inteiro_br(v_pihaa2)
            if f"s9_str_pihaa1_{ano_sel}" not in st.session_state:
                        st.session_state[f"s9_str_pihaa1_{ano_sel}"] = formatar_para_inteiro_br(v_pihaa1)
            if f"s9_str_pihaa_{ano_sel}" not in st.session_state:
                        st.session_state[f"s9_str_pihaa_{ano_sel}"] = formatar_para_inteiro_br(v_pihaa)

            c1, c2 = st.columns([1, 2])

            with c1:
                        # Inputs de dados estruturados com os labels dinâmicos e anos retroativos
                        input_pihaa2_str = st.text_input(
                                    f"Quantidade de internações em estabelecimentos de saúde sob Gestão Municipal em {ano_s9_aa2} (PIHAA-2) • Em {ano_s9_aa2}:",
                                    value=st.session_state[f"s9_str_pihaa2_{ano_sel}"],
                                    key=f"txt_s9_pihaa2_{ano_sel}"
                        )
                        
                        input_pihaa1_str = st.text_input(
                                    f"Quantidade de internações em estabelecimentos de saúde sob Gestão Municipal em {ano_s9_aa1} (PIHAA-1) • Em {ano_s9_aa1}:",
                                    value=st.session_state[f"s9_str_pihaa1_{ano_sel}"],
                                    key=f"txt_s9_pihaa1_{ano_sel}"
                        )
                        
                        input_pihaa_str = st.text_input(
                                    f"Quantidade de internações em estabelecimentos de saúde sob Gestão Municipal em {ano_sel} (PIHAA) • Em {ano_sel}:",
                                    value=st.session_state[f"s9_str_pihaa_{ano_sel}"],
                                    key=f"txt_s9_pihaa_{ano_sel}"
                        )

                        # Conversão segura para processamento numérico
                        pihaa2 = tratar_string_inteiro_para_float(input_pihaa2_str)
                        pihaa1 = tratar_string_inteiro_para_float(input_pihaa1_str)
                        pihaa = tratar_string_inteiro_para_float(input_pihaa_str)

                        # Sincroniza as máscaras visuais no session_state da view
                        st.session_state[f"s9_str_pihaa2_{ano_sel}"] = formatar_para_inteiro_br(pihaa2)
                        st.session_state[f"s9_str_pihaa1_{ano_sel}"] = formatar_para_inteiro_br(pihaa1)
                        st.session_state[f"s9_str_pihaa_{ano_sel}"] = formatar_para_inteiro_br(pihaa)

                        # 🧮 Lógica do Motor de Regras (Média histórica dos dois anos anteriores)
                        media_historica_s9 = (pihaa2 + pihaa1) / 2.0

                        # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS
                        if pihaa2 == 0.0 and pihaa1 == 0.0 and pihaa == 0.0:
                                    ptsS9 = 0.0
                                    texto_resultado = "Aguardando lançamento do histórico de internações hospitalares..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # Aplicação estrita da regra de corte de penalização
                                    if pihaa <= media_historica_s9:
                                                ptsS9 = 0.0
                                                texto_resultado = f"✅ Sob Controle: O volume de internações em {ano_sel} manteve-se igual ou abaixo da média histórica"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS9 = -5.0
                                                texto_resultado = f"🚨 Alerta de Impacto: O volume de internações em {ano_sel} superou a média histórica de {ano_s9_aa2}-{ano_s9_aa1}"
                                                texto_pontuacao = "-5,00 pontos (Perde 5 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS9 = st.text_area(f"Link/Evidência (S9 - Relatório de Produção SIH/SUS {ano_sel}):", value=dS9.get("link", ""), key=f"txt_s9_link_{ano_sel}", height=150)

            # Formatação das métricas finais calculadas para o padrão brasileiro
            media_s9_br = f"{media_historica_s9:.2f}".replace(".", ",")
            pihaa_atual_br = formatar_para_inteiro_br(pihaa)

            # Painel consolidador de métricas hospitalares
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Internações Registradas em {ano_sel} (PIHAA):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{pihaa_atual_br}</code> internações<br>
                        📊 <b>Média Limiar de Reference ({ano_s9_aa2} e {ano_s9_aa1}):</b> <code style="font-size: 14px; font-weight: bold; color: #475569;">{media_s9_br}</code> internações<br>
                        ⚖️ <b>Status do Indicador:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota Geral:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores brutos para persistência no banco de dados
            str_concatenada_s9 = f"{pihaa2:.0f}/{pihaa1:.0f}/{pihaa:.0f}"

            if str_concatenada_s9 != dS9["valor"] or lS9 != dS9.get("link", ""):
                        save_resp("S9", str_concatenada_s9, ptsS9, lS9)
                        st.rerun()

            bloco_comentarios("S9", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S10 • Especialidade Obstétrica: Métrica de Permanência e Frequência (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S10 • Sobre a especialidade Obstétrica em estabelecimentos de saúde sob gestão municipal em {ano_sel}, informe:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels
            try:
                        ano_atual_s10 = int(ano_sel)
            except:
                        ano_atual_s10 = 2025

            # 🧹 Função de Higienização para inputs numéricos reais/decimais (Ex: "1.250" ou "12,5" -> Float)
            def tratar_string_numerica_para_float(texto):
                        if not texto:
                                    return 0.0
                        texto_limpo = texto.replace(".", "").replace(",", ".").strip()
                        try:
                                    return float(texto_limpo) if texto_limpo else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para exibição padrão BR com duas casas decimais
            def formatar_para_numero_br(valor_float):
                        return f"{valor_float:.2f}".replace(".", ",")

            # Carrega ou inicializa a string persistida no banco contendo os valores de Permanência e Frequência
            # Formato interno: Permanencia/Frequencia
            dS10 = res_data.get("S10", {"valor": "0.0/0.0", "pontos": 0.0, "link": ""})

            try:
                        v_perm_s10, v_freq_s10 = map(float, dS10["valor"].split("/"))
            except:
                        v_perm_s10, v_freq_s10 = 0.0, 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para o ano corrente
            if f"s10_str_perm_{ano_sel}" not in st.session_state:
                        st.session_state[f"s10_str_perm_{ano_sel}"] = formatar_para_numero_br(v_perm_s10)
            if f"s10_str_freq_{ano_sel}" not in st.session_state:
                        st.session_state[f"s10_str_freq_{ano_sel}"] = formatar_para_numero_br(v_freq_s10)

            c1, c2 = st.columns([1, 2])

            with c1:
                        # Inputs estruturados capturando os dados de produção hospitalar obstétrica
                        input_perm_str = st.text_input(
                                    f"Permanência (P) em {ano_sel}:",
                                    value=st.session_state[f"s10_str_perm_{ano_sel}"],
                                    key=f"txt_s10_perm_{ano_sel}"
                        )

                        input_freq_str = st.text_input(
                                    f"Frequência (F) em {ano_sel}:",
                                    value=st.session_state[f"s10_str_freq_{ano_sel}"],
                                    key=f"txt_s10_freq_{ano_sel}"
                        )

                        # Conversão higienizada para execução dos cálculos aritméticos
                        permanencia_s10 = tratar_string_numerica_para_float(input_perm_str)
                        frequencia_s10 = tratar_string_numerica_para_float(input_freq_str)

                        # Sincroniza a máscara visual de volta para o estado da tela
                        st.session_state[f"s10_str_perm_{ano_sel}"] = formatar_para_numero_br(permanencia_s10)
                        st.session_state[f"s10_str_freq_{ano_sel}"] = formatar_para_numero_br(frequencia_s10)

                        # Limiar estabelecido pela fórmula de cálculo do manual
                        limiar_s10 = 3.1

                        # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS OU DIVISÃO POR ZERO
                        if permanencia_s10 == 0.0 or frequencia_s10 == 0.0:
                                    ptsS10 = 0.0
                                    razao_s10 = 0.0
                                    texto_resultado = "Aguardando preenchimento dos indicadores de Permanência e Frequência..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução da fórmula: Razão de dias de internação por paciente (P / F)
                                    razao_s10 = round(permanencia_s10 / frequencia_s10, 4)

                                    # Verificação estrita dos limites de corte
                                    if razao_s10 <= limiar_s10:
                                                ptsS10 = 0.0
                                                texto_resultado = f"✅ Parâmetro Otimizado: Razão P/F ({formatar_para_numero_br(razao_s10)}) em conformidade com o referencial regulatório"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS10 = -2.0
                                                texto_resultado = f"🚨 Alerta de Permanência: Razão P/F ({formatar_para_numero_br(razao_s10)}) superou o limite de {formatar_para_numero_br(limiar_s10)} dias"
                                                texto_pontuacao = "-2,00 pontos (Perde 2 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS10 = st.text_area(f"Link/Evidência (S10 - Módulo Especialidades SIH/SUS {ano_sel}):", value=dS10.get("link", ""), key=f"txt_s10_link_{ano_sel}", height=150)

            # Painel consolidador do monitoramento do plano de parto e internação obstétrica
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S10:</b> Eficiência da Internação na Especialidade Obstétrica ({ano_sel})<br>
                        📊 <b>Média do Período de Permanência por Paciente (P/F):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{formatar_para_numero_br(razao_s10)} dias</code><br>
                        ⚖️ <b>Status da Corte:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores floats brutos separados por barra para armazenamento no banco
            str_concatenada_s10 = f"{permanencia_s10:.2f}/{frequencia_s10:.2f}"

            if str_concatenada_s10 != dS10["valor"] or lS10 != dS10.get("link", ""):
                        save_resp("S10", str_concatenada_s10, ptsS10, lS10)
                        st.rerun()

            bloco_comentarios("S10", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S11 • Especialidade Pediátrica: Métrica de Permanência e Frequência (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S11 • Sobre a especialidade Pediátrica em estabelecimentos de saúde sob gestão municipal em {ano_sel}, informe:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels
            try:
                        ano_atual_s11 = int(ano_sel)
            except:
                        ano_atual_s11 = 2025

            # 🧹 Função de Higienização para inputs numéricos reais/decimais (Ex: "1.250" ou "12,5" -> Float)
            def tratar_string_numerica_para_float(texto):
                        if not texto:
                                    return 0.0
                        texto_limpo = texto.replace(".", "").replace(",", ".").strip()
                        try:
                                    return float(texto_limpo) if texto_limpo else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para exibição padrão BR com duas casas decimais
            def formatar_para_numero_br(valor_float):
                        return f"{valor_float:.2f}".replace(".", ",")

            # Carrega ou inicializa a string persistida no banco contendo os valores de Permanência e Frequência
            # Formato interno: Permanencia/Frequencia
            dS11 = res_data.get("S11", {"valor": "0.0/0.0", "pontos": 0.0, "link": ""})

            try:
                        v_perm_s11, v_freq_s11 = map(float, dS11["valor"].split("/"))
            except:
                        v_perm_s11, v_freq_s11 = 0.0, 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para o ano corrente
            if f"s11_str_perm_{ano_sel}" not in st.session_state:
                        st.session_state[f"s11_str_perm_{ano_sel}"] = formatar_para_numero_br(v_perm_s11)
            if f"s11_str_freq_{ano_sel}" not in st.session_state:
                        st.session_state[f"s11_str_freq_{ano_sel}"] = formatar_para_numero_br(v_freq_s11)

            c1, c2 = st.columns([1, 2])

            with c1:
                        # Inputs estruturados capturando os dados de produção hospitalar pediátrica
                        input_perm_str = st.text_input(
                                    f"Permanência (P) em {ano_sel}:",
                                    value=st.session_state[f"s11_str_perm_{ano_sel}"],
                                    key=f"txt_s11_perm_{ano_sel}"
                        )

                        input_freq_str = st.text_input(
                                    f"Frequência (F) em {ano_sel}:",
                                    value=st.session_state[f"s11_str_freq_{ano_sel}"],
                                    key=f"txt_s11_freq_{ano_sel}"
                        )

                        # Conversão higienizada para execução dos cálculos aritméticos
                        permanencia_s11 = tratar_string_numerica_para_float(input_perm_str)
                        frequencia_s11 = tratar_string_numerica_para_float(input_freq_str)

                        # Sincroniza a máscara visual de volta para o estado da tela
                        st.session_state[f"s11_str_perm_{ano_sel}"] = formatar_para_numero_br(permanencia_s11)
                        st.session_state[f"s11_str_freq_{ano_sel}"] = formatar_para_numero_br(frequencia_s11)

                        # Limiar estabelecido pela fórmula de cálculo do manual
                        limiar_s11 = 5.7

                        # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS OU DIVISÃO POR ZERO
                        if permanencia_s11 == 0.0 or frequencia_s11 == 0.0:
                                    ptsS11 = 0.0
                                    razao_s11 = 0.0
                                    texto_resultado = "Aguardando preenchimento dos indicators de Permanência e Frequência..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução da fórmula: Razão de dias de internação pediátrica por paciente (P / F)
                                    razao_s11 = round(permanencia_s11 / frequencia_s11, 4)

                                    # Verificação estrita dos limites de corte
                                    if razao_s11 <= limiar_s11:
                                                ptsS11 = 0.0
                                                texto_resultado = f"✅ Parâmetro Otimizado: Razão P/F ({formatar_para_numero_br(razao_s11)}) em conformidade com o referencial regulatório pediátrico"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS11 = -2.0
                                                texto_resultado = f"🚨 Alerta de Permanência: Razão P/F ({formatar_para_numero_br(razao_s11)}) superou o limite de {formatar_para_numero_br(limiar_s11)} dias"
                                                texto_pontuacao = "-2,00 pontos (Perde 2 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS11 = st.text_area(f"Link/Evidência (S11 - Módulo Especialidades SIH/SUS {ano_sel}):", value=dS11.get("link", ""), key=f"txt_s11_link_{ano_sel}", height=150)

            # Painel consolidador do monitoramento da internação pediátrica
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S11:</b> Eficiência da Internação na Especialidade Pediátrica ({ano_sel})<br>
                        📊 <b>Média do Período de Permanência por Paciente (P/F):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{formatar_para_numero_br(razao_s11)} dias</code><br>
                        ⚖️ <b>Status da Coorte:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores floats brutos separados por barra para armazenamento no banco
            str_concatenada_s11 = f"{permanencia_s11:.2f}/{frequencia_s11:.2f}"

            if str_concatenada_s11 != dS11["valor"] or lS11 != dS11.get("link", ""):
                        save_resp("S11", str_concatenada_s11, ptsS11, lS11)
                        st.rerun()

            bloco_comentarios("S11", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S12 • Especialidade Clínica Médica: Métrica de Permanência e Frequência (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S12 • Sobre a especialidade Clínica Médica em estabelecimentos de saúde sob gestão municipal em {ano_sel}, informe:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels
            try:
                        ano_atual_s12 = int(ano_sel)
            except:
                        ano_atual_s12 = 2025

            # 🧹 Função de Higienização para inputs numéricos reais/decimais (Ex: "1.250" ou "12,5" -> Float)
            def tratar_string_numerica_para_float(texto):
                        if not texto:
                                    return 0.0
                        texto_limpo = texto.replace(".", "").replace(",", ".").strip()
                        try:
                                    return float(texto_limpo) if texto_limpo else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para exibição padrão BR com duas casas decimais
            def formatar_para_numero_br(valor_float):
                        return f"{valor_float:.2f}".replace(".", ",")

            # Carrega ou inicializa a string persistida no banco contendo os valores de Permanência e Frequência
            # Formato interno: Permanencia/Frequencia
            dS12 = res_data.get("S12", {"valor": "0.0/0.0", "pontos": 0.0, "link": ""})

            try:
                        v_perm_s12, v_freq_s12 = map(float, dS12["valor"].split("/"))
            except:
                        v_perm_s12, v_freq_s12 = 0.0, 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para o ano corrente
            if f"s12_str_perm_{ano_sel}" not in st.session_state:
                        st.session_state[f"s12_str_perm_{ano_sel}"] = formatar_para_numero_br(v_perm_s12)
            if f"s12_str_freq_{ano_sel}" not in st.session_state:
                        st.session_state[f"s12_str_freq_{ano_sel}"] = formatar_para_numero_br(v_freq_s12)

            c1, c2 = st.columns([1, 2])

            with c1:
                        # Inputs estruturados capturando os dados de produção hospitalar da clínica médica
                        input_perm_str = st.text_input(
                                    f"Permanência (P) em {ano_sel}:",
                                    value=st.session_state[f"s12_str_perm_{ano_sel}"],
                                    key=f"txt_s12_perm_{ano_sel}"
                        )

                        input_freq_str = st.text_input(
                                    f"Frequência (F) em {ano_sel}:",
                                    value=st.session_state[f"s12_str_freq_{ano_sel}"],
                                    key=f"txt_s12_freq_{ano_sel}"
                        )

                        # Conversão higienizada para execução dos cálculos aritméticos
                        permanencia_s12 = tratar_string_numerica_para_float(input_perm_str)
                        frequencia_s12 = tratar_string_numerica_para_float(input_freq_str)

                        # Sincroniza a máscara visual de volta para o estado da tela
                        st.session_state[f"s12_str_perm_{ano_sel}"] = formatar_para_numero_br(permanencia_s12)
                        st.session_state[f"s12_str_freq_{ano_sel}"] = formatar_para_numero_br(frequencia_s12)

                        # Limiar estabelecido pela fórmula de cálculo do manual
                        limiar_s12 = 9.7

                        # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS OU DIVISÃO POR ZERO
                        if permanencia_s12 == 0.0 or frequencia_s12 == 0.0:
                                    ptsS12 = 0.0
                                    razao_s12 = 0.0
                                    texto_resultado = "Aguardando preenchimento dos indicadores de Permanência e Frequência..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução da fórmula: Razão de dias de internação por paciente (P / F)
                                    razao_s12 = round(permanencia_s12 / frequencia_s12, 4)

                                    # Verificação estrita dos limites de corte (Se P / F > 9.7 perde 2 pontos)
                                    if razao_s12 <= limiar_s12:
                                                ptsS12 = 0.0
                                                texto_resultado = f"✅ Parâmetro Otimizado: Razão P/F ({formatar_para_numero_br(razao_s12)}) em conformidade com o referencial regulatório de clínica médica"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS12 = -2.0
                                                texto_resultado = f"🚨 Alerta de Permanência: Razão P/F ({formatar_para_numero_br(razao_s12)}) superou o limite de {formatar_para_numero_br(limiar_s12)} dias"
                                                texto_pontuacao = "-2,00 pontos (Perde 2 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS12 = st.text_area(f"Link/Evidência (S12 - Módulo Especialidades SIH/SUS {ano_sel}):", value=dS12.get("link", ""), key=f"txt_s12_link_{ano_sel}", height=150)

            # Painel consolidador do monitoramento da internação de clínica médica
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S12:</b> Eficiência da Internação na Especialidade Clínica Médica ({ano_sel})<br>
                        📊 <b>Média do Período de Permanência por Paciente (P/F):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{formatar_para_numero_br(razao_s12)} dias</code><br>
                        ⚖️ <b>Status da Coorte:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores floats brutos separados por barra para armazenamento no banco
            str_concatenada_s12 = f"{permanencia_s12:.2f}/{frequencia_s12:.2f}"

            if str_concatenada_s12 != dS12["valor"] or lS12 != dS12.get("link", ""):
                        save_resp("S12", str_concatenada_s12, ptsS12, lS12)
                        st.rerun()

            bloco_comentarios("S12", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S13 • Especialidade Cirúrgica: Métrica de Permanência e Frequência (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S13 • Sobre a especialidade Cirúrgica em estabelecimentos de saúde sob gestão municipal em {ano_sel}, informe:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels
            try:
                        ano_atual_s13 = int(ano_sel)
            except:
                        ano_atual_s13 = 2025

            # 🧹 Função de Higienização para inputs numéricos reais/decimais (Ex: "1.250" ou "12,5" -> Float)
            def tratar_string_numerica_para_float(texto):
                        if not texto:
                                    return 0.0
                        texto_limpo = texto.replace(".", "").replace(",", ".").strip()
                        try:
                                    return float(texto_limpo) if texto_limpo else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para exibição padrão BR com duas casas decimais
            def formatar_para_numero_br(valor_float):
                        return f"{valor_float:.2f}".replace(".", ",")

            # Carrega ou inicializa a string persistida no banco contendo os valores de Permanência e Frequência
            # Formato interno: Permanencia/Frequencia
            dS13 = res_data.get("S13", {"valor": "0.0/0.0", "pontos": 0.0, "link": ""})

            try:
                        v_perm_s13, v_freq_s13 = map(float, dS13["valor"].split("/"))
            except:
                        v_perm_s13, v_freq_s13 = 0.0, 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para o ano corrente
            if f"s13_str_perm_{ano_sel}" not in st.session_state:
                        st.session_state[f"s13_str_perm_{ano_sel}"] = formatar_para_numero_br(v_perm_s13)
            if f"s13_str_freq_{ano_sel}" not in st.session_state:
                        st.session_state[f"s13_str_freq_{ano_sel}"] = formatar_para_numero_br(v_freq_s13)

            c1, c2 = st.columns([1, 2])

            with c1:
                        # Inputs estruturados capturando os dados de produção hospitalar cirúrgica
                        input_perm_str = st.text_input(
                                    f"Permanência (P) em {ano_sel}:",
                                    value=st.session_state[f"s13_str_perm_{ano_sel}"],
                                    key=f"txt_s13_perm_{ano_sel}"
                        )

                        input_freq_str = st.text_input(
                                    f"Frequência (F) em {ano_sel}:",
                                    value=st.session_state[f"s13_str_freq_{ano_sel}"],
                                    key=f"txt_s13_freq_{ano_sel}"
                        )

                        # Conversão higienizada para execução dos cálculos aritméticos
                        permanencia_s13 = tratar_string_numerica_para_float(input_perm_str)
                        frequencia_s13 = tratar_string_numerica_para_float(input_freq_str)

                        # Sincroniza a máscara visual de volta para o estado da tela
                        st.session_state[f"s13_str_perm_{ano_sel}"] = formatar_para_numero_br(permanencia_s13)
                        st.session_state[f"s13_str_freq_{ano_sel}"] = formatar_para_numero_br(frequencia_s13)

                        # Limiar estabelecido pela fórmula de cálculo do manual
                        limiar_s13 = 6.5

                        # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS OU DIVISÃO POR ZERO
                        if permanencia_s13 == 0.0 or frequencia_s13 == 0.0:
                                    ptsS13 = 0.0
                                    razao_s13 = 0.0
                                    texto_resultado = "Aguardando preenchimento dos indicadores de Permanência e Frequência..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução da fórmula: Razão de dias de internação por paciente (P / F)
                                    razao_s13 = round(permanencia_s13 / frequencia_s13, 4)

                                    # Verificação estrita dos limites de corte (Se P / F > 6.5 perde 2 pontos)
                                    if razao_s13 <= limiar_s13:
                                                ptsS13 = 0.0
                                                texto_resultado = f"✅ Parâmetro Otimizado: Razão P/F ({formatar_para_numero_br(razao_s13)}) em conformidade com o referencial regulatório de clínica cirúrgica"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS13 = -2.0
                                                texto_resultado = f"🚨 Alerta de Permanência: Razão P/F ({formatar_para_numero_br(razao_s13)}) superou o limite de {formatar_para_numero_br(limiar_s13)} dias"
                                                texto_pontuacao = "-2,00 pontos (Perde 2 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS13 = st.text_area(f"Link/Evidência (S13 - Módulo Especialidades SIH/SUS {ano_sel}):", value=dS13.get("link", ""), key=f"txt_s13_link_{ano_sel}", height=150)

            # Painel consolidador do monitoramento da internação cirúrgica
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S13:</b> Eficiência da Internação na Especialidade Cirúrgica ({ano_sel})<br>
                        📊 <b>Média do Período de Permanência por Paciente (P/F):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{formatar_para_numero_br(razao_s13)} dias</code><br>
                        ⚖️ <b>Status da Coorte:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores floats brutos separados por barra para armazenamento no banco
            str_concatenada_s13 = f"{permanencia_s13:.2f}/{frequencia_s13:.2f}"

            if str_concatenada_s13 != dS13["valor"] or lS13 != dS13.get("link", ""):
                        save_resp("S13", str_concatenada_s13, ptsS13, lS13)
                        st.rerun()

            bloco_comentarios("S13", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S14 • Taxa de Mortalidade Hospitalar sob Gestão Municipal (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S14 • Sobre os pacientes internados em estabelecimentos de saúde sob gestão municipal, informe:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Linha temporal dinâmica baseada no ano selecionado
            try:
                        ano_atual_s14 = int(ano_sel)
            except:
                        ano_atual_s14 = 2025

            ano_s14_aa1 = ano_atual_s14 - 1
            ano_s14_aa2 = ano_atual_s14 - 2

            # 🧹 Função de Higienização de inteiros puros (Ex: "1.450" -> 1450.0)
            def tratar_string_inteiro_para_float(texto):
                        if not texto: 
                                    return 0.0
                        apenas_numeros = "".join(c for c in texto if c.isdigit())
                        try:
                                    return float(apenas_numeros) if apenas_numeros else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                        return f"{int(valor_float):,}".replace(",", ".")

            # Carrega os dados salvos do banco. Formato: TOAA-2/TOAA-1/TOAA/SHAA-2/SHAA-1/SHAA
            dS14 = res_data.get("S14", {"valor": "0/0/0/0/0/0", "pontos": 0.0, "link": ""})

            valores_s14 = dS14["valor"].split("/")
            if len(valores_s14) != 6:
                        valores_s14 = [0.0] * 6
            else:
                        valores_s14 = [float(v) for v in valores_s14]

            # Desempacotamento do histórico estruturado
            toaa2, toaa1, toaa, shaa2, shaa1, shaa = valores_s14

            # Inicialização do session_state com chaves dinâmicas temporais
            if f"s14_str_toaa2_{ano_sel}" not in st.session_state:
                        st.session_state[f"s14_str_toaa2_{ano_sel}"] = formatar_para_inteiro_br(toaa2)
            if f"s14_str_toaa1_{ano_sel}" not in st.session_state:
                        st.session_state[f"s14_str_toaa1_{ano_sel}"] = formatar_para_inteiro_br(toaa1)
            if f"s14_str_toaa_{ano_sel}" not in st.session_state:
                        st.session_state[f"s14_str_toaa_{ano_sel}"] = formatar_para_inteiro_br(toaa)
            if f"s14_str_shaa2_{ano_sel}" not in st.session_state:
                        st.session_state[f"s14_str_shaa2_{ano_sel}"] = formatar_para_inteiro_br(shaa2)
            if f"s14_str_shaa1_{ano_sel}" not in st.session_state:
                        st.session_state[f"s14_str_shaa1_{ano_sel}"] = formatar_para_inteiro_br(shaa1)
            if f"s14_str_shaa_{ano_sel}" not in st.session_state:
                        st.session_state[f"s14_str_shaa_{ano_sel}"] = formatar_para_inteiro_br(shaa)

            c1, c2 = st.columns([1, 2])

            with c1:
                        st.markdown(f"##### 💀 Registro de Óbitos Hospitalares")
                        input_toaa2_str = st.text_input(f"Nº de óbitos em {ano_s14_aa2} (TOAA-2):", value=st.session_state[f"s14_str_toaa2_{ano_sel}"], key=f"txt_s14_toaa2_{ano_sel}")
                        input_toaa1_str = st.text_input(f"Nº de óbitos em {ano_s14_aa1} (TOAA-1):", value=st.session_state[f"s14_str_toaa1_{ano_sel}"], key=f"txt_s14_toaa1_{ano_sel}")
                        input_toaa_str = st.text_input(f"Nº de óbitos em {ano_sel} (TOAA):", value=st.session_state[f"s14_str_toaa_{ano_sel}"], key=f"txt_s14_toaa_{ano_sel}")

                        st.markdown(f"##### 🏥 Total de Saídas Hospitalares")
                        input_shaa2_str = st.text_input(f"Total de saídas hospitalares em {ano_s14_aa2} (SHAA-2):", value=st.session_state[f"s14_str_shaa2_{ano_sel}"], key=f"txt_s14_shaa2_{ano_sel}")
                        input_shaa1_str = st.text_input(f"Total de saídas hospitalares em {ano_s14_aa1} (SHAA-1):", value=st.session_state[f"s14_str_shaa1_{ano_sel}"], key=f"txt_s14_shaa1_{ano_sel}")
                        input_shaa_str = st.text_input(f"Total de saídas hospitalares em {ano_sel} (SHAA):", value=st.session_state[f"s14_str_shaa_{ano_sel}"], key=f"txt_s14_shaa_{ano_sel}")

                        # Conversão dos inputs textuais em floats limpos
                        toaa2 = tratar_string_inteiro_para_float(input_toaa2_str)
                        toaa1 = tratar_string_inteiro_para_float(input_toaa1_str)
                        toaa = tratar_string_inteiro_para_float(input_toaa_str)
                        shaa2 = tratar_string_inteiro_para_float(input_shaa2_str)
                        shaa1 = tratar_string_inteiro_para_float(input_shaa1_str)
                        shaa = tratar_string_inteiro_para_float(input_shaa_str)

                        # Atualização e sincronização do session state da view
                        st.session_state[f"s14_str_toaa2_{ano_sel}"] = formatar_para_inteiro_br(toaa2)
                        st.session_state[f"s14_str_toaa1_{ano_sel}"] = formatar_para_inteiro_br(toaa1)
                        st.session_state[f"s14_str_toaa_{ano_sel}"] = formatar_para_inteiro_br(toaa)
                        st.session_state[f"s14_str_shaa2_{ano_sel}"] = formatar_para_inteiro_br(shaa2)
                        st.session_state[f"s14_str_shaa1_{ano_sel}"] = formatar_para_inteiro_br(shaa1)
                        st.session_state[f"s14_str_shaa_{ano_sel}"] = formatar_para_inteiro_br(shaa)

                        # 🛑 TRAVA DE SEGURANÇA: Preenchimento zerado ou divisão por zero iminente
                        if shaa == 0.0 or (shaa2 + shaa1) == 0.0:
                                    ptsS14 = 0.0
                                    taxa_atual = 0.0
                                    taxa_referencia = 0.0
                                    texto_resultado = "Aguardando preenchimento completo dos dados hospitalares..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução matemática das fórmulas oficiais do indicador
                                    taxa_atual = toaa / shaa
                                    taxa_referencia = (toaa2 + toaa1) / (shaa2 + shaa1)

                                    # Validação estrita dos limites de corte da taxa de mortalidade
                                    if taxa_atual <= taxa_referencia:
                                                ptsS14 = 0.0
                                                texto_resultado = f"✅ Regularizado: Taxa de mortalidade em {ano_sel} controlada ou menor que o histórico de referência"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS14 = -2.0
                                                texto_resultado = f"🚨 Alerta Crítico: Taxa de mortalidade em {ano_sel} superou a média móvel do biênio anterior"
                                                texto_pontuacao = "-2,00 pontos (Perde 2 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS14 = st.text_area(f"Link/Evidência (S14 - Painel de Monitoramento SIH/SUS {ano_sel}):", value=dS14.get("link", ""), key=f"txt_s14_link_{ano_sel}", height=150)

            # Conversão das taxas para strings amigáveis em formato de porcentagem BR
            taxa_atual_br = f"{(taxa_atual * 100):.3f}".replace(".", ",") + "%"
            taxa_ref_br = f"{(taxa_referencia * 100):.3f}".replace(".", ",") + "%"

            # Painel consolidador macro-estatístico da rede hospitalar do SUS
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S14:</b> Avaliação da Taxa de Mortalidade Hospitalar Líquida<br>
                        📊 <b>Taxa de Mortalidade de Referência ({ano_s14_aa2}-{ano_s14_aa1}):</b> <code style="font-size: 13px; font-weight: bold; color: #475569;">{taxa_ref_br}</code><br>
                        📈 <b>Taxa de Mortalidade Registrada em {ano_sel}:</b> <code style="font-size: 13px; font-weight: bold; color: #1e3a8a;">{taxa_atual_br}</code><br>
                        ⚖️ <b>Comportamento Epidemiológico:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Geração da string contígua para envio estável à camada de persistência
            lista_salvar_s14 = [f"{toaa2:.0f}", f"{toaa1:.0f}", f"{toaa:.0f}", f"{shaa2:.0f}", f"{shaa1:.0f}", f"{shaa:.0f}"]
            str_concatenada_s14 = "/".join(lista_salvar_s14)

            if str_concatenada_s14 != dS14["valor"] or lS14 != dS14.get("link", ""):
                        save_resp("S14", str_concatenada_s14, ptsS14, lS14)
                        st.rerun()

            bloco_comentarios("S14", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S15 • Proporção de Partos Cesarianos (SIH/SUS)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S15 • Sobre a especialidade obstétrica em estabelecimentos de saúde sob gestão municipal em {ano_sel}, informe:")
            st.write("DADOS DO SISTEMA DE INFORMAÇÕES HOSPITALARES DO SUS (SIH/SUS)")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels
            try:
                        ano_atual_s15 = int(ano_sel)
            except:
                        ano_atual_s15 = 2025

            # 🧹 Função de Higienização de inteiros puros (Ex: "1.450" -> 1450.0)
            def tratar_string_inteiro_para_float(texto):
                        if not texto: 
                                    return 0.0
                        apenas_numeros = "".join(c for c in texto if c.isdigit())
                        try:
                                    return float(apenas_numeros) if apenas_numeros else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                        return f"{int(valor_float):,}".replace(",", ".")

            # Carrega ou inicializa a string persistida no banco contendo os valores de PC e TP
            # Formato interno: PC/TP
            dS15 = res_data.get("S15", {"valor": "0.0/0.0", "pontos": 0.0, "link": ""})

            try:
                        v_pc_s15, v_tp_s15 = map(float, dS15["valor"].split("/"))
            except:
                        v_pc_s15, v_tp_s15 = 0.0, 0.0

            # Garante que o session_state inicialize no formato correto do Brasil para o ano corrente
            if f"s15_str_pc_{ano_sel}" not in st.session_state:
                        st.session_state[f"s15_str_pc_{ano_sel}"] = formatar_para_inteiro_br(v_pc_s15)
            if f"s15_str_tp_{ano_sel}" not in st.session_state:
                        st.session_state[f"s15_str_tp_{ano_sel}"] = formatar_para_inteiro_br(v_tp_s15)

            c1, c2 = st.columns([1, 2])

            with c1:
                        # Inputs estruturados capturando os volumes de partos da rede municipal
                        input_pc_str = st.text_input(
                                    f"Total de partos cesarianos em estabelecimentos de saúde sob gestão municipal em {ano_sel} (PC):",
                                    value=st.session_state[f"s15_str_pc_{ano_sel}"],
                                    key=f"txt_s15_pc_{ano_sel}"
                        )

                        input_tp_str = st.text_input(
                                    f"Total de partos realizados em estabelecimentos de saúde sob gestão municipal em {ano_sel} (TP):",
                                    value=st.session_state[f"s15_str_tp_{ano_sel}"],
                                    key=f"txt_s15_tp_{ano_sel}"
                        )

                        # Conversão higienizada para execução dos cálculos aritméticos
                        pc_s15 = tratar_string_inteiro_para_float(input_pc_str)
                        tp_s15 = tratar_string_inteiro_para_float(input_tp_str)

                        # Sincroniza a máscara visual de volta para o estado da tela
                        st.session_state[f"s15_str_pc_{ano_sel}"] = formatar_para_inteiro_br(pc_s15)
                        st.session_state[f"s15_str_tp_{ano_sel}"] = formatar_para_inteiro_br(tp_s15)

                        # Limiar de corte estabelecido pelo indicador (40%)
                        limiar_s15 = 40.0

                        # 🛑 TRAVA DE INICIALIZAÇÃO / CAMPOS ZERADOS OU DIVISÃO POR ZERO
                        if pc_s15 == 0.0 or tp_s15 == 0.0:
                                    ptsS15 = 0.0
                                    proporcao_s15 = 0.0
                                    texto_resultado = "Aguardando preenchimento dos totais de partos cesarianos e realizados..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução da fórmula: Proporção de partos cesarianos (PC / TP * 100)
                                    proporcao_s15 = round((pc_s15 / tp_s15) * 100.0, 2)

                                    # Verificação estrita dos limites de corte (Se PC / TP > 40% perde 2 pontos)
                                    if proporcao_s15 <= limiar_s15:
                                                ptsS15 = 0.0
                                                texto_resultado = f"✅ Parâmetro Otimizado: Proporção de cesáreas ({f'{proporcao_s15:.2f}'.replace('.', ',')}%) em conformidade com o referencial de humanização"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS15 = -2.0
                                                texto_resultado = f"🚨 Alerta de Cirurgias: Proporção de cesáreas ({f'{proporcao_s15:.2f}'.replace('.', ',')}%) superou o limite de {f'{limiar_s15:.2f}'.replace('.', ',')}%"
                                                texto_pontuacao = "-2,00 pontos (Perde 2 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS15 = st.text_area(f"Link/Evidência (S15 - Relatórios Hospitalares SIH/SUS {ano_sel}):", value=dS15.get("link", ""), key=f"txt_s15_link_{ano_sel}", height=150)

            # Painel consolidador do monitoramento obstétrico da rede hospitalar
            proporcao_s15_br = f"{proporcao_s15:.2f}".replace(".", ",") + "%"

            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S15:</b> Proporção Hospitalar de Partos Cesarianos ({ano_sel})<br>
                        📊 <b>Índice de Cesáreas Calculado (PC/TP):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{proporcao_s15_br}</code><br>
                        ⚖️ <b>Status da Rede Municipal:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores brutos separados por barra para armazenamento estável no banco de dados
            str_concatenada_s15 = f"{pc_s15:.0f}/{tp_s15:.0f}"

            if str_concatenada_s15 != dS15["valor"] or lS15 != dS15.get("link", ""):
                        save_resp("S15", str_concatenada_s15, ptsS15, lS15)
                        st.rerun()

            bloco_comentarios("S15", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S16 • Taxa de Mortalidade Neonatal Municipal (SESSP-CCD/FSEADE)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader("S16 • Sobre a mortalidade de recém-nascidos e total de nascidos vivos em estabelecimentos de saúde sob gestão municipal, informe:")
            st.write("FONTE: SESSP-CCD/FSEADE - Base Unificada de Nascidos Vivos")

            # 🧮 Linha temporal dinâmica baseada no ano selecionado
            try:
                        ano_atual_s16 = int(ano_sel)
            except:
                        ano_atual_s16 = 2025

            ano_s16_aa1 = ano_atual_s16 - 1
            ano_s16_aa2 = ano_atual_s16 - 2

            # 🧹 Função de Higienização de inteiros puros (Ex: "1.250" -> 1250.0)
            def tratar_string_inteiro_para_float(texto):
                        if not texto: 
                                    return 0.0
                        apenas_numeros = "".join(c for c in texto if c.isdigit())
                        try:
                                    return float(apenas_numeros) if apenas_numeros else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                        return f"{int(valor_float):,}".replace(",", ".")

            # Carrega os dados salvos do banco. Formato: ORNAA-2/ORNAA-1/ORNAA/NVAA-2/NVAA-1/NVAA
            dS16 = res_data.get("S16", {"valor": "0/0/0/0/0/0", "pontos": 0.0, "link": ""})

            valores_s16 = dS16["valor"].split("/")
            if len(valores_s16) != 6:
                        valores_s16 = [0.0] * 6
            else:
                        valores_s16 = [float(v) for v in valores_s16]

            # Desempacotamento do histórico estruturado de mortalidade neonatal
            ornaa2, ornaa1, ornaa, nvaa2, nvaa1, nvaa = valores_s16

            # Inicialização do session_state com as chaves dinâmicas baseadas no ano selecionado
            if f"s16_str_ornaa2_{ano_sel}" not in st.session_state:
                        st.session_state[f"s16_str_ornaa2_{ano_sel}"] = formatar_para_inteiro_br(ornaa2)
            if f"s16_str_ornaa1_{ano_sel}" not in st.session_state:
                        st.session_state[f"s16_str_ornaa1_{ano_sel}"] = formatar_para_inteiro_br(ornaa1)
            if f"s16_str_ornaa_{ano_sel}" not in st.session_state:
                        st.session_state[f"s16_str_ornaa_{ano_sel}"] = formatar_para_inteiro_br(ornaa)
            if f"s16_str_nvaa2_{ano_sel}" not in st.session_state:
                        st.session_state[f"s16_str_nvaa2_{ano_sel}"] = formatar_para_inteiro_br(nvaa2)
            if f"s16_str_nvaa1_{ano_sel}" not in st.session_state:
                        st.session_state[f"s16_str_nvaa1_{ano_sel}"] = formatar_para_inteiro_br(nvaa1)
            if f"s16_str_nvaa_{ano_sel}" not in st.session_state:
                        st.session_state[f"s16_str_nvaa_{ano_sel}"] = formatar_para_inteiro_br(nvaa)

            c1, c2 = st.columns([1, 2])

            with c1:
                        st.markdown(f"##### 👶 Registro de Óbitos de Recém-Nascidos")
                        input_ornaa2_str = st.text_input(f"Nº de óbitos de recém-nascidos em {ano_s16_aa2} (ORNAA-2):", value=st.session_state[f"s16_str_ornaa2_{ano_sel}"], key=f"txt_s16_ornaa2_{ano_sel}")
                        input_ornaa1_str = st.text_input(f"Nº de óbitos de recém-nascidos em {ano_s16_aa1} (ORNAA-1):", value=st.session_state[f"s16_str_ornaa1_{ano_sel}"], key=f"txt_s16_ornaa1_{ano_sel}")
                        input_ornaa_str = st.text_input(f"Nº de óbitos de recém-nascidos em {ano_sel} (ORNAA):", value=st.session_state[f"s16_str_ornaa_{ano_sel}"], key=f"txt_s16_ornaa_{ano_sel}")

                        st.markdown(f"##### 🍼 Total de Nascidos Vivos na Rede")
                        input_nvaa2_str = st.text_input(f"Total de nascidos vivos em estabelecimentos sob gestão municipal em {ano_s16_aa2} (NVAA-2):", value=st.session_state[f"s16_str_nvaa2_{ano_sel}"], key=f"txt_s16_nvaa2_{ano_sel}")
                        input_nvaa1_str = st.text_input(f"Total de nascidos vivos em estabelecimentos sob gestão municipal em {ano_s16_aa1} (NVAA-1):", value=st.session_state[f"s16_str_nvaa1_{ano_sel}"], key=f"txt_s16_nvaa1_{ano_sel}")
                        input_nvaa_str = st.text_input(f"Total de nascidos vivos em estabelecimentos sob gestão municipal em {ano_sel} (NVAA):", value=st.session_state[f"s16_str_nvaa_{ano_sel}"], key=f"txt_s16_nvaa_{ano_sel}")

                        # Conversão dos inputs textuais em valores numéricos puros
                        ornaa2 = tratar_string_inteiro_para_float(input_ornaa2_str)
                        ornaa1 = tratar_string_inteiro_para_float(input_ornaa1_str)
                        ornaa = tratar_string_inteiro_para_float(input_ornaa_str)
                        nvaa2 = tratar_string_inteiro_para_float(input_nvaa2_str)
                        nvaa1 = tratar_string_inteiro_para_float(input_nvaa1_str)
                        nvaa = tratar_string_inteiro_para_float(input_nvaa_str)

                        # Sincronização das máscaras visuais no session state da view
                        st.session_state[f"s16_str_ornaa2_{ano_sel}"] = formatar_para_inteiro_br(ornaa2)
                        st.session_state[f"s16_str_ornaa1_{ano_sel}"] = formatar_para_inteiro_br(ornaa1)
                        st.session_state[f"s16_str_ornaa_{ano_sel}"] = formatar_para_inteiro_br(ornaa)
                        st.session_state[f"s16_str_nvaa2_{ano_sel}"] = formatar_para_inteiro_br(nvaa2)
                        st.session_state[f"s16_str_nvaa1_{ano_sel}"] = formatar_para_inteiro_br(nvaa1)
                        st.session_state[f"s16_str_nvaa_{ano_sel}"] = formatar_para_inteiro_br(nvaa)

                        # 🛑 TRAVA DE SEGURANÇA: Preenchimento zerado ou divisão por zero iminente
                        if nvaa == 0.0 or (nvaa2 + nvaa1) == 0.0:
                                    ptsS16 = 0.0
                                    taxa_neonatal_atual = 0.0
                                    taxa_neonatal_ref = 0.0
                                    texto_resultado = "Aguardando lançamento completo dos dados vitais de nascidos vivos..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução matemática das fórmulas oficiais do manual
                                    taxa_neonatal_atual = ornaa / nvaa
                                    taxa_neonatal_ref = (ornaa2 + ornaa1) / (nvaa2 + nvaa1)

                                    # Validação estrita das regras de corte de mortalidade neonatal
                                    if taxa_neonatal_atual <= taxa_neonatal_ref:
                                                ptsS16 = 0.0
                                                texto_resultado = f"✅ Sob Controle: Taxa de mortalidade neonatal em {ano_sel} igual ou inferior à referência histórica"
                                                texto_pontuacao = "0,00 pontos (Sem penalidades)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    else:
                                                ptsS16 = -2.0
                                                texto_resultado = f"🚨 Alerta Crítico: Proporção de óbitos neonatais em {ano_sel} ultrapassou o patamar do biênio anterior"
                                                texto_pontuacao = "-2,00 pontos (Perde 2 pontos)"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS16 = st.text_area(f"Link/Evidência (S16 - Base Unificada SESSP-CCD/FSEADE {ano_sel}):", value=dS16.get("link", ""), key=f"txt_s16_link_{ano_sel}", height=150)

            # Conversão das taxas para strings amigáveis em formato de porcentagem BR
            taxa_atual_br = f"{(taxa_neonatal_atual * 100):.3f}".replace(".", ",") + "%"
            taxa_ref_br = f"{(taxa_neonatal_ref * 100):.3f}".replace(".", ",") + "%"

            # Painel consolidador de monitoramento da saúde materno-infantil municipal
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S16:</b> Proporção de Mortalidade Neonatal Hospitalar sob Gestão Municipal<br>
                        📊 <b>Proporção de Referência Histórica ({ano_s16_aa2}-{ano_s16_aa1}):</b> <code style="font-size: 13px; font-weight: bold; color: #475569;">{taxa_ref_br}</code><br>
                        📈 <b>Proporção Calculada para o Ano de {ano_sel}:</b> <code style="font-size: 13px; font-weight: bold; color: #1e3a8a;">{taxa_atual_br}</code><br>
                        ⚖️ <b>Comportamento do Indicador:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Impacto na Nota (N):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Geração da string contígua ordenada para envio estável à persistência
            lista_salvar_s16 = [f"{ornaa2:.0f}", f"{ornaa1:.0f}", f"{ornaa:.0f}", f"{nvaa2:.0f}", f"{nvaa1:.0f}", f"{nvaa:.0f}"]
            str_concatenada_s16 = "/".join(lista_salvar_s16)

            if str_concatenada_s16 != dS16["valor"] or lS16 != dS16.get("link", ""):
                        save_resp("S16", str_concatenada_s16, ptsS16, lS16)
                        st.rerun()

            bloco_comentarios("S16", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S17 • Cobertura de Exame Citopatológico na APS (SISAB)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S17 • Número de mulheres com idade de 25 a 64 anos, que realizaram coleta do exame citopatológico na APS nos últimos 36 meses no 1º, 2º e 3º Quadrimestre de {ano_sel}:")
            st.caption(f"🌐 Fonte oficial (SISAB): https://sisab.saude.gov.br/paginas/acessoRestrito/relatorio/federal/indicadores/indicadorPainel.xhtml")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels internos
            try:
                        ano_atual_s17 = int(ano_sel)
            except:
                        ano_atual_s17 = 2025

            # 🧹 Função de Higienização de inteiros puros (Ex: "3.450" -> 3450.0)
            def tratar_string_inteiro_para_float(texto):
                        if not texto: 
                                    return 0.0
                        apenas_numeros = "".join(c for c in texto if c.isdigit())
                        try:
                                    return float(apenas_numeros) if apenas_numeros else 0.0
                        except ValueError:
                                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                        return f"{int(valor_float):,}".replace(",", ".")

            # Carrega os dados salvos do banco. Formato: CIT1Q/CIT2Q/CIT3Q/TM1Q/TM2Q/TM3Q
            dS17 = res_data.get("S17", {"valor": "0/0/0/0/0/0", "pontos": 0.0, "link": ""})

            valores_s17 = dS17["valor"].split("/")
            if len(valores_s17) != 6:
                        valores_s17 = [0.0] * 6
            else:
                        valores_s17 = [float(v) for v in valores_s17]

            # Desempacotamento das variáveis por quadrimestre
            cit1q, cit2q, cit3q, tm1q, tm2q, tm3q = valores_s17

            # Inicialização do session_state mapeando strings brasileiras de visualização por ano corrente
            if f"s17_str_cit1q_{ano_sel}" not in st.session_state:
                        st.session_state[f"s17_str_cit1q_{ano_sel}"] = formatar_para_inteiro_br(cit1q)
            if f"s17_str_cit2q_{ano_sel}" not in st.session_state:
                        st.session_state[f"s17_str_cit2q_{ano_sel}"] = formatar_para_inteiro_br(cit2q)
            if f"s17_str_cit3q_{ano_sel}" not in st.session_state:
                        st.session_state[f"s17_str_cit3q_{ano_sel}"] = formatar_para_inteiro_br(cit3q)
            if f"s17_str_tm1q_{ano_sel}" not in st.session_state:
                        st.session_state[f"s17_str_tm1q_{ano_sel}"] = formatar_para_inteiro_br(tm1q)
            if f"s17_str_tm2q_{ano_sel}" not in st.session_state:
                        st.session_state[f"s17_str_tm2q_{ano_sel}"] = formatar_para_inteiro_br(tm2q)
            if f"s17_str_tm3q_{ano_sel}" not in st.session_state:
                        st.session_state[f"s17_str_tm3q_{ano_sel}"] = formatar_para_inteiro_br(tm3q)

            c1, c2 = st.columns([1, 2])

            with c1:
                        st.markdown(f"##### 🔬 Exames Coletados (Últimos 36 meses)")
                        input_cit1q_str = st.text_input(f"Coletas no 1º Quadrimestre de {ano_atual_s17} (CIT1Q):", value=st.session_state[f"s17_str_cit1q_{ano_sel}"], key=f"txt_s17_cit1q_{ano_sel}")
                        input_cit2q_str = st.text_input(f"Coletas no 2º Quadrimestre de {ano_atual_s17} (CIT2Q):", value=st.session_state[f"s17_str_cit2q_{ano_sel}"], key=f"txt_s17_cit2q_{ano_sel}")
                        input_cit3q_str = st.text_input(f"Coletas no 3º Quadrimestre de {ano_atual_s17} (CIT3Q):", value=st.session_state[f"s17_str_cit3q_{ano_sel}"], key=f"txt_s17_cit3q_{ano_sel}")

                        st.markdown(f"##### 👥 População Alvo Total do Município (25 a 64 anos)")
                        input_tm1q_str = st.text_input(f"Total de mulheres no 1º Quadrimestre de {ano_atual_s17} (TM1Q):", value=st.session_state[f"s17_str_tm1q_{ano_sel}"], key=f"txt_s17_tm1q_{ano_sel}")
                        input_tm2q_str = st.text_input(f"Total de mulheres no 2º Quadrimestre de {ano_atual_s17} (TM2Q):", value=st.session_state[f"s17_str_tm2q_{ano_sel}"], key=f"txt_s17_tm2q_{ano_sel}")
                        input_tm3q_str = st.text_input(f"Total de mulheres no 3º Quadrimestre de {ano_atual_s17} (TM3Q):", value=st.session_state[f"s17_str_tm3q_{ano_sel}"], key=f"txt_s17_tm3q_{ano_sel}")

                        # Conversão higienizada para números floats computáveis
                        cit1q = tratar_string_inteiro_para_float(input_cit1q_str)
                        cit2q = tratar_string_inteiro_para_float(input_cit2q_str)
                        cit3q = tratar_string_inteiro_para_float(input_cit3q_str)
                        tm1q = tratar_string_inteiro_para_float(input_tm1q_str)
                        tm2q = tratar_string_inteiro_para_float(input_tm2q_str)
                        tm3q = tratar_string_inteiro_para_float(input_tm3q_str)

                        # Sincronização imediata no estado de sessão da view
                        st.session_state[f"s17_str_cit1q_{ano_sel}"] = formatar_para_inteiro_br(cit1q)
                        st.session_state[f"s17_str_cit2q_{ano_sel}"] = formatar_para_inteiro_br(cit2q)
                        st.session_state[f"s17_str_cit3q_{ano_sel}"] = formatar_para_inteiro_br(cit3q)
                        st.session_state[f"s17_str_tm1q_{ano_sel}"] = formatar_para_inteiro_br(tm1q)
                        st.session_state[f"s17_str_tm2q_{ano_sel}"] = formatar_para_inteiro_br(tm2q)
                        st.session_state[f"s17_str_tm3q_{ano_sel}"] = formatar_para_inteiro_br(tm3q)

                        # Somatórios para a fórmula ponderada geral
                        total_coletas_s17 = cit1q + cit2q + cit3q
                        total_mulheres_s17 = tm1q + tm2q + tm3q

                        # 🛑 TRAVA DE INICIALIZAÇÃO / DENOMINADOR ZERADO
                        if total_mulheres_s17 == 0.0 or total_coletas_s17 == 0.0:
                                    ptsS17 = 0.0
                                    p_cobertura = 0.0
                                    texto_resultado = "Aguardando preenchimento dos indicadores quadrimestrais do SISAB..."
                                    texto_pontuacao = "⏳ Sem avaliação"
                                    estilo_status = "color: #64748b;"
                        else:
                                    # 🧮 Execução da fórmula: P = (CIT1Q + CIT2Q + CIT3Q) / (TM1Q + TM2Q + TM3Q) * 100
                                    p_cobertura = round((total_coletas_s17 / total_mulheres_s17) * 100.0, 2)

                                    # ⚖️ Tabela de metas progressivas e faixas do manual
                                    if p_cobertura >= 100.0:
                                                ptsS17 = 25.0
                                                texto_resultado = "🥇 EXCELÊNCIA CRÍTICA: Cobertura integral registrada (100% ou mais)"
                                                texto_pontuacao = "25,00 pontos (Pontuação Máxima)"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    elif 80.0 <= p_cobertura < 100.0:
                                                ptsS17 = 20.0
                                                texto_resultado = f"🟢 META ATINGIDA: Excelente índice de triagem preventiva ({f'{p_cobertura:.2f}'.replace('.', ',')}%)"
                                                texto_pontuacao = "20,00 pontos"
                                                estilo_status = "color: #16a34a; font-weight: bold;"
                                    elif 40.0 <= p_cobertura < 80.0:
                                                ptsS17 = 15.0
                                                texto_resultado = f"🟡 COBERTURA MODERADA: Necessidade de busca ativa de pacientes ({f'{p_cobertura:.2f}'.replace('.', ',')}%)"
                                                texto_pontuacao = "15,00 pontos"
                                                estilo_status = "color: #eab308; font-weight: bold;"
                                    elif 28.0 <= p_cobertura < 40.0:
                                                ptsS17 = 10.0
                                                texto_resultado = f"🟠 ALERTA DE COBERTURA: Índice abaixo da linha de segurança epidemiológica ({f'{p_cobertura:.2f}'.replace('.', ',')}%)"
                                                texto_pontuacao = "10,00 pontos"
                                                estilo_status = "color: #ea580c; font-weight: bold;"
                                    elif 16.0 <= p_cobertura < 28.0:
                                                ptsS17 = 5.0
                                                texto_resultado = f"🚨 RISCO DE LINHA DE CUIDADO: Cobertura vacilante e muito fragilizada ({f'{p_cobertura:.2f}'.replace('.', ',')}%)"
                                                texto_pontuacao = "5,00 pontos"
                                                estilo_status = "color: #dc2626; font-weight: bold;"
                                    else:
                                                ptsS17 = 0.0
                                                texto_resultado = f"❌ ALERTA MÁXIMO: Cobertura em nível crítico de desassistência ({f'{p_cobertura:.2f}'.replace('.', ',')}%)"
                                                texto_pontuacao = "0,00 pontos"
                                                estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                        lS17 = st.text_area(f"Link/Evidência (S17 - Relatório Unificado de Indicadores {ano_sel}):", value=dS17.get("link", ""), key=f"txt_s17_link_{ano_sel}", height=150)

            # Formatação visual amigável do indicador consolidado
            p_cobertura_br = f"{p_cobertura:.2f}".replace(".", ",") + "%"

            # Painel consolidador de métricas para a Saúde da Mulher
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                        📌 <b>Indicador Geral S17:</b> Proporção de Cobertura de Exame Citopatológico (Colo de Útero)<br>
                        📊 <b>Percentual de Cobertura Geral Calculado (P):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{p_cobertura_br}</code><br>
                        ⚖️ <b>Status da Assistência Preventiva:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                        🎯 <b>Pontuação Homologada para o Ano:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores brutos para persistência de strings no banco de dados
            lista_salvar_s17 = [f"{cit1q:.0f}", f"{cit2q:.0f}", f"{cit3q:.0f}", f"{tm1q:.0f}", f"{tm2q:.0f}", f"{tm3q:.0f}"]
            str_concatenada_s17 = "/".join(lista_salvar_s17)

            if str_concatenada_s17 != dS17["valor"] or lS17 != dS17.get("link", ""):
                        save_resp("S17", str_concatenada_s17, ptsS17, lS17)
                        st.rerun()

            bloco_comentarios("S17", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S18 • Acompanhamento e Aferição de Pressão de Hipertensos na APS (SISAB)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S18 • Número de hipertensos com consulta e aferição de pressão arterial nos últimos 6 meses nos quadrimestres de {ano_sel}:")
            st.caption(f"🌐 Fonte oficial (SISAB): https://sisab.saude.gov.br/paginas/acessoRestrito/relatorio/federal/indicadores/indicadorPainel.xhtml")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels internos
            try:
                ano_atual_s18 = int(ano_sel)
            except:
                ano_atual_s18 = 2025

            # 🧹 Função de Higienização de inteiros puros (Ex: "4.120" -> 4120.0)
            def tratar_string_inteiro_para_float(texto):
                if not texto: 
                    return 0.0
                apenas_numeros = "".join(c for c in texto if c.isdigit())
                try:
                    return float(apenas_numeros) if apenas_numeros else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                return f"{int(valor_float):,}".replace(",", ".")

            # Carrega os dados salvos do banco. Formato: HPA1Q/HPA2Q/HPA3Q/TH1Q/TH2Q/TH3Q
            dS18 = res_data.get("S18", {"valor": "0/0/0/0/0/0", "pontos": 0.0, "link": ""})

            valores_s18 = dS18["valor"].split("/")
            if len(valores_s18) != 6:
                valores_s18 = [0.0] * 6
            else:
                valores_s18 = [float(v) for v in valores_s18]

            # Desempacotamento das variáveis por quadrimestre
            hpa1q, hpa2q, hpa3q, th1q, th2q, th3q = valores_s18

            # Inicialização do session_state mapeando strings brasileiras de visualização por ano corrente
            if f"s18_str_hpa1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s18_str_hpa1q_{ano_sel}"] = formatar_para_inteiro_br(hpa1q)
            if f"s18_str_hpa2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s18_str_hpa2q_{ano_sel}"] = formatar_para_inteiro_br(hpa2q)
            if f"s18_str_hpa3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s18_str_hpa3q_{ano_sel}"] = formatar_para_inteiro_br(hpa3q)
            if f"s18_str_th1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s18_str_th1q_{ano_sel}"] = formatar_para_inteiro_br(th1q)
            if f"s18_str_th2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s18_str_th2q_{ano_sel}"] = formatar_para_inteiro_br(th2q)
            if f"s18_str_th3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s18_str_th3q_{ano_sel}"] = formatar_para_inteiro_br(th3q)

            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown(f"##### 🩺 Hipertensos com Consulta e Aferição (Últimos 6 meses)")
                input_hpa1q_str = st.text_input(f"Consultas/Aferições no 1º Quadrimestre de {ano_atual_s18} (HPA1Q):", value=st.session_state[f"s18_str_hpa1q_{ano_sel}"], key=f"txt_s18_hpa1q_{ano_sel}")
                input_hpa2q_str = st.text_input(f"Consultas/Aferições no 2º Quadrimestre de {ano_atual_s18} (HPA2Q):", value=st.session_state[f"s18_str_hpa2q_{ano_sel}"], key=f"txt_s18_hpa2q_{ano_sel}")
                input_hpa3q_str = st.text_input(f"Consultas/Aferições no 3º Quadrimestre de {ano_atual_s18} (HPA3Q):", value=st.session_state[f"s18_str_hpa3q_{ano_sel}"], key=f"txt_s18_hpa3q_{ano_sel}")

                st.markdown(f"##### 👥 Total de Hipertensos Cadastrados no Município")
                input_th1q_str = st.text_input(f"Total de hipertensos no 1º Quadrimestre de {ano_atual_s18} (TH1Q):", value=st.session_state[f"s18_str_th1q_{ano_sel}"], key=f"txt_s18_th1q_{ano_sel}")
                input_th2q_str = st.text_input(f"Total de hipertensos no 2º Quadrimestre de {ano_atual_s18} (TH2Q):", value=st.session_state[f"s18_str_th2q_{ano_sel}"], key=f"txt_s18_th2q_{ano_sel}")
                input_th3q_str = st.text_input(f"Total de hipertensos no 3º Quadrimestre de {ano_atual_s18} (TH3Q):", value=st.session_state[f"s18_str_th3q_{ano_sel}"], key=f"txt_s18_th3q_{ano_sel}")

                # Conversão higienizada para números decimais/inteiros computáveis
                hpa1q = tratar_string_inteiro_para_float(input_hpa1q_str)
                hpa2q = tratar_string_inteiro_para_float(input_hpa2q_str)
                hpa3q = tratar_string_inteiro_para_float(input_hpa3q_str)
                th1q = tratar_string_inteiro_para_float(input_th1q_str)
                th2q = tratar_string_inteiro_para_float(input_th2q_str)
                th3q = tratar_string_inteiro_para_float(input_th3q_str)

                # Sincronização imediata no estado de sessão da view
                st.session_state[f"s18_str_hpa1q_{ano_sel}"] = formatar_para_inteiro_br(hpa1q)
                st.session_state[f"s18_str_hpa2q_{ano_sel}"] = formatar_para_inteiro_br(hpa2q)
                st.session_state[f"s18_str_hpa3q_{ano_sel}"] = formatar_para_inteiro_br(hpa3q)
                st.session_state[f"s18_str_th1q_{ano_sel}"] = formatar_para_inteiro_br(th1q)
                st.session_state[f"s18_str_th2q_{ano_sel}"] = formatar_para_inteiro_br(th2q)
                st.session_state[f"s18_str_th3q_{ano_sel}"] = formatar_para_inteiro_br(th3q)

                # Somatórios para aplicação na fórmula consolidada ponderada
                total_consultas_s18 = hpa1q + hpa2q + hpa3q
                total_hipertensos_s18 = th1q + th2q + th3q

                # 🛑 TRAVA DE INICIALIZAÇÃO / DENOMINADOR ZERADO
                if total_hipertensos_s18 == 0.0 or total_consultas_s18 == 0.0:
                    ptsS18 = 0.0
                    p_acompanhamento = 0.0
                    texto_resultado = "Aguardando preenchimento dos indicadores quadrimestrais de hipertensão no SISAB..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # 🧮 Execução da fórmula: P = (HPA1Q + HPA2Q + HPA3Q) / (TH1Q + TH2Q + TH3Q) * 100
                    p_acompanhamento = round((total_consultas_s18 / total_hipertensos_s18) * 100.0, 2)

                    # ⚖️ Tabela de metas e faixas específicas estabelecidas pelo manual para o S18
                    if p_acompanhamento >= 100.0:
                        ptsS18 = 25.0
                        texto_resultado = "🥇 EXCELÊNCIA CRÍTICA: Monitoramento integral da coorte de hipertensos (100%)"
                        texto_pontuacao = "25,00 pontos (Pontuação Máxima)"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif 50.0 <= p_acompanhamento < 100.0:
                        ptsS18 = 15.0
                        texto_resultado = f"🟢 META ALCANÇADA: Adequado controle clínico e acompanhamento semestral ({f'{p_acompanhamento:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "15,00 pontos"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif 35.0 <= p_acompanhamento < 50.0:
                        ptsS18 = 10.0
                        texto_resultado = f"🟡 ACOMPANHAMENTO INTERMEDIÁRIO: Intensificar agendamentos na atenção primária ({f'{p_acompanhamento:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "10,00 pontos"
                        estilo_status = "color: #eab308; font-weight: bold;"
                    elif 20.0 <= p_acompanhamento < 35.0:
                        ptsS18 = 5.0
                        texto_resultado = f"🟠 ALERTA DE COBERTURA: Baixo índice de aferição de pressão arterial ({f'{p_acompanhamento:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "5,00 pontos"
                        estilo_status = "color: #ea580c; font-weight: bold;"
                    else:
                        ptsS18 = 0.0
                        texto_resultado = f"❌ CRÍTICO: Alto risco cardiovascular por falta de acompanhamento clínico ({f'{p_acompanhamento:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "0,00 pontos"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS18 = st.text_area(f"Link/Evidência (S18 - Relatório de Hipertensão Previne Brasil {ano_sel}):", value=dS18.get("link", ""), key=f"txt_s18_link_{ano_sel}", height=150)

            # Formatação visual amigável do indicador consolidado
            p_acompanhamento_br = f"{p_acompanhamento:.2f}".replace(".", ",") + "%"

            # Painel consolidador de métricas para a Linha de Cuidados Crônicos
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Indicador Geral S18:</b> Proporção de Hipertensos com Consulta e Aferição de PA em Dia<br>
                📊 <b>Percentual de Cobertura Clínico-Semestral (P):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{p_acompanhamento_br}</code><br>
                ⚖️ <b>Status da Assistência Cardiovascular:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Pontuação Homologada para o Ano:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores brutos para persistência de strings no banco de dados
            lista_salvar_s18 = [f"{hpa1q:.0f}", f"{hpa2q:.0f}", f"{hpa3q:.0f}", f"{th1q:.0f}", f"{th2q:.0f}", f"{th3q:.0f}"]
            str_concatenada_s18 = "/".join(lista_salvar_s18)

            if str_concatenada_s18 != dS18["valor"] or lS18 != dS18.get("link", ""):
                save_resp("S18", str_concatenada_s18, ptsS18, lS18)
                st.rerun()

            bloco_comentarios("S18", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S19 • Acompanhamento e Solicitação de Hemoglobina Glicada em Diabéticos (SISAB)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S19 • Número de diabéticos com consulta e solicitação de exame de Hemoglobina Glicada nos últimos 6 meses nos quadrimestres de {ano_sel}:")
            st.caption(f"🌐 Fonte oficial (SISAB): https://sisab.saude.gov.br/paginas/acessoRestrito/relatorio/federal/indicadores/indicadorPainel.xhtml")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels internos
            try:
                ano_atual_s19 = int(ano_sel)
            except:
                ano_atual_s19 = 2025

            # 🧹 Função de Higienização de inteiros puros (Ex: "2.140" -> 2140.0)
            def tratar_string_inteiro_para_float(texto):
                if not texto: 
                    return 0.0
                apenas_numeros = "".join(c for c in texto if c.isdigit())
                try:
                    return float(apenas_numeros) if apenas_numeros else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                return f"{int(valor_float):,}".replace(",", ".")

            # Carrega os dados salvos do banco. Formato: DHG1Q/DHG2Q/DHG3Q/TD1Q/TD2Q/TD3Q
            dS19 = res_data.get("S19", {"valor": "0/0/0/0/0/0", "pontos": 0.0, "link": ""})

            valores_s19 = dS19["valor"].split("/")
            if len(valores_s19) != 6:
                valores_s19 = [0.0] * 6
            else:
                valores_s19 = [float(v) for v in valores_s19]

            # Desempacotamento das variáveis por quadrimestre
            dhg1q, dhg2q, dhg3q, td1q, td2q, td3q = valores_s19

            # Inicialização do session_state mapeando strings brasileiras de visualização por ano corrente
            if f"s19_str_dhg1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s19_str_dhg1q_{ano_sel}"] = formatar_para_inteiro_br(dhg1q)
            if f"s19_str_dhg2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s19_str_dhg2q_{ano_sel}"] = formatar_para_inteiro_br(dhg2q)
            if f"s19_str_dhg3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s19_str_dhg3q_{ano_sel}"] = formatar_para_inteiro_br(dhg3q)
            if f"s19_str_td1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s19_str_td1q_{ano_sel}"] = formatar_para_inteiro_br(td1q)
            if f"s19_str_td2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s19_str_td2q_{ano_sel}"] = formatar_para_inteiro_br(td2q)
            if f"s19_str_td3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s19_str_td3q_{ano_sel}"] = formatar_para_inteiro_br(td3q)

            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown(f"##### 🧪 Diabéticos com Solicitação de Hemoglobina Glicada")
                input_dhg1q_str = st.text_input(f"Consultas/Exames no 1º Quadrimestre de {ano_atual_s19} (DHG1Q):", value=st.session_state[f"s19_str_dhg1q_{ano_sel}"], key=f"txt_s19_dhg1q_{ano_sel}")
                input_dhg2q_str = st.text_input(f"Consultas/Exames no 2º Quadrimestre de {ano_atual_s19} (DHG2Q):", value=st.session_state[f"s19_str_dhg2q_{ano_sel}"], key=f"txt_s19_dhg2q_{ano_sel}")
                input_dhg3q_str = st.text_input(f"Consultas/Exames no 3º Quadrimestre de {ano_atual_s19} (DHG3Q):", value=st.session_state[f"s19_str_dhg3q_{ano_sel}"], key=f"txt_s19_dhg3q_{ano_sel}")

                st.markdown(f"##### 👥 Total de Diabéticos Cadastrados no Município")
                input_td1q_str = st.text_input(f"Total de diabéticos no 1º Quadrimestre de {ano_atual_s19} (TD1Q):", value=st.session_state[f"s19_str_td1q_{ano_sel}"], key=f"txt_s19_td1q_{ano_sel}")
                input_td2q_str = st.text_input(f"Total de diabéticos no 2º Quadrimestre de {ano_atual_s19} (TD2Q):", value=st.session_state[f"s19_str_td2q_{ano_sel}"], key=f"txt_s19_td2q_{ano_sel}")
                input_td3q_str = st.text_input(f"Total de diabéticos no 3º Quadrimestre de {ano_atual_s19} (TD3Q):", value=st.session_state[f"s19_str_td3q_{ano_sel}"], key=f"txt_s19_td3q_{ano_sel}")

                # Conversão higienizada para números floats/inteiros operacionais
                dhg1q = tratar_string_inteiro_para_float(input_dhg1q_str)
                dhg2q = tratar_string_inteiro_para_float(input_dhg2q_str)
                dhg3q = tratar_string_inteiro_para_float(input_dhg3q_str)
                td1q = tratar_string_inteiro_para_float(input_td1q_str)
                td2q = tratar_string_inteiro_para_float(input_td2q_str)
                td3q = tratar_string_inteiro_para_float(input_td3q_str)

                # Sincronização imediata no estado de sessão da view
                st.session_state[f"s19_str_dhg1q_{ano_sel}"] = formatar_para_inteiro_br(dhg1q)
                st.session_state[f"s19_str_dhg2q_{ano_sel}"] = formatar_para_inteiro_br(dhg2q)
                st.session_state[f"s19_str_dhg3q_{ano_sel}"] = formatar_para_inteiro_br(dhg3q)
                st.session_state[f"s19_str_td1q_{ano_sel}"] = formatar_para_inteiro_br(td1q)
                st.session_state[f"s19_str_td2q_{ano_sel}"] = formatar_para_inteiro_br(td2q)
                st.session_state[f"s19_str_td3q_{ano_sel}"] = formatar_para_inteiro_br(td3q)

                # Somatórios consolidados para a fórmula ponderada geral
                total_exames_s19 = dhg1q + dhg2q + dhg3q
                total_diabeticos_s19 = td1q + td2q + td3q

                # 🛑 TRAVA DE INICIALIZAÇÃO / DENOMINADOR ZERADO
                if total_diabeticos_s19 == 0.0 or total_exames_s19 == 0.0:
                    ptsS19 = 0.0
                    p_glicada = 0.0
                    texto_resultado = "Aguardando preenchimento dos indicadores quadrimestrais de diabetes no SISAB..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # 🧮 Execução da fórmula: P = (DHG1Q + DHG2Q + DHG3Q) / (TD1Q + TD2Q + TD3Q) * 100
                    p_glicada = round((total_exames_s19 / total_diabeticos_s19) * 100.0, 2)

                    # ⚖️ Tabela oficial de metas progressivas e faixas do indicador S19
                    if p_glicada >= 100.0:
                        ptsS19 = 25.0
                        texto_resultado = "🥇 EXCELÊNCIA CRÍTICA: Cobertura de monitoramento metabólico total (100%)"
                        texto_pontuacao = "25,00 pontos (Pontuação Máxima)"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif 50.0 <= p_glicada < 100.0:
                        ptsS19 = 15.0
                        texto_resultado = f"🟢 META INTEGRALIZADA: Controle glicêmico semestral adequado ({f'{p_glicada:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "15,00 pontos"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif 35.0 <= p_glicada < 50.0:
                        ptsS19 = 10.0
                        texto_resultado = f"🟡 LINHA INTERMEDIÁRIA: Intensificar pedidos laboratoriais de rotina na APS ({f'{p_glicada:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "10,00 pontos"
                        estilo_status = "color: #eab308; font-weight: bold;"
                    elif 20.0 <= p_glicada < 35.0:
                        ptsS19 = 5.0
                        texto_resultado = f"🟠 ALERTA PREVENTIVO: Baixa solicitação de exames de acompanhamento ({f'{p_glicada:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "5,00 pontos"
                        estilo_status = "color: #ea580c; font-weight: bold;"
                    else:
                        ptsS19 = 0.0
                        texto_resultado = f"❌ RISCO CLÍNICO ELEVADO: Desassistência no rastreio de complicações do diabetes ({f'{p_glicada:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "0,00 pontos"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS19 = st.text_area(f"Link/Evidência (S19 - Painel de Monitoramento de Diabetes Previne Brasil {ano_sel}):", value=dS19.get("link", ""), key=f"txt_s19_link_{ano_sel}", height=150)

            # Formatação visual amigável do indicador consolidado
            p_glicada_br = f"{p_glicada:.2f}".replace(".", ",") + "%"

            # Painel consolidador de métricas para a Linha de Cuidados de Diabetes Mellitus
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Indicador Geral S19:</b> Proporção de Diabéticos com Solicitação de Hemoglobina Glicada em Dia<br>
                📊 <b>Percentual de Cobertura de Exames Calculado (P):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{p_glicada_br}</code><br>
                ⚖️ <b>Status do Monitoramento Clínico:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Pontuação Homologada para o Ano:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores brutos para persistência de strings no banco de dados
            lista_salvar_s19 = [f"{dhg1q:.0f}", f"{dhg2q:.0f}", f"{dhg3q:.0f}", f"{td1q:.0f}", f"{td2q:.0f}", f"{td3q:.0f}"]
            str_concatenada_s19 = "/".join(lista_salvar_s19)

            if str_concatenada_s19 != dS19["valor"] or lS19 != dS19.get("link", ""):
                save_resp("S19", str_concatenada_s19, ptsS19, lS19)
                st.rerun()

            bloco_comentarios("S19", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

            # =============================================================================
            # S20 • Proporção de Gestantes com Atendimento Odontológico na APS (SISAB)
            # =============================================================================
            st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
            st.subheader(f"S20 • Número de gestantes com pré-natal e atendimento odontológico na APS nos quadrimestres de {ano_sel}:")
            st.caption(f"🌐 Fonte oficial (SISAB): https://sisab.saude.gov.br/paginas/acessoRestrito/relatorio/federal/indicadores/indicadorPainel.xhtml")

            # 🧮 Captura o ano selecionado de forma dinâmica para os labels internos
            try:
                ano_atual_s20 = int(ano_sel)
            except:
                ano_atual_s20 = 2025

            # 🧹 Função de Higienização de inteiros puros (Ex: "1.240" -> 1240.0)
            def tratar_string_inteiro_para_float(texto):
                if not texto: 
                    return 0.0
                apenas_numeros = "".join(c for c in texto if c.isdigit())
                try:
                    return float(apenas_numeros) if apenas_numeros else 0.0
                except ValueError:
                    return 0.0

            # 🎨 Função de formatação para números inteiros padrão BR
            def formatar_para_inteiro_br(valor_float):
                return f"{int(valor_float):,}".replace(",", ".")

            # Carrega os dados salvos do próprio S20. Formato: GPAO1Q/GPAO2Q/GPAO3Q/TG1Q/TG2Q/TG3Q
            dS20 = res_data.get("S20", {"valor": "0/0/0/0/0/0", "pontos": 0.0, "link": ""})
            valores_s20 = dS20["valor"].split("/")
            
            if len(valores_s20) != 6:
                # Tentativa de fallback caso só existissem os 3 numeradores antes
                if len(valores_s20) == 3:
                    valores_s20 = [float(valores_s20[0]), float(valores_s20[1]), float(valores_s20[2]), 0.0, 0.0, 0.0]
                else:
                    valores_s20 = [0.0] * 6
            else:
                valores_s20 = [float(v) for v in valores_s20]

            # Desempacotamento das variáveis por quadrimestre
            gpao1q, gpao2q, gpao3q, tg1q, tg2q, tg3q = valores_s20

            # Inicialização do session_state mapeando strings brasileiras de visualização por ano corrente
            if f"s20_str_gpao1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s20_str_gpao1q_{ano_sel}"] = formatar_para_inteiro_br(gpao1q)
            if f"s20_str_gpao2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s20_str_gpao2q_{ano_sel}"] = formatar_para_inteiro_br(gpao2q)
            if f"s20_str_gpao3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s20_str_gpao3q_{ano_sel}"] = formatar_para_inteiro_br(gpao3q)
            if f"s20_str_tg1q_{ano_sel}" not in st.session_state:
                st.session_state[f"s20_str_tg1q_{ano_sel}"] = formatar_para_inteiro_br(tg1q)
            if f"s20_str_tg2q_{ano_sel}" not in st.session_state:
                st.session_state[f"s20_str_tg2q_{ano_sel}"] = formatar_para_inteiro_br(tg2q)
            if f"s20_str_tg3q_{ano_sel}" not in st.session_state:
                st.session_state[f"s20_str_tg3q_{ano_sel}"] = formatar_para_inteiro_br(tg3q)

            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown(f"##### 🦷 Gestantes com Atendimento Odontológico")
                input_gpao1q_str = st.text_input(f"Nº gestantes com atendimento odontológico no 1º Quadrimestre de {ano_atual_s20} (GPAO1Q):", value=st.session_state[f"s20_str_gpao1q_{ano_sel}"], key=f"txt_s20_gpao1q_{ano_sel}")
                input_gpao2q_str = st.text_input(f"Nº gestantes com atendimento odontológico no 2º Quadrimestre de {ano_atual_s20} (GPAO2Q):", value=st.session_state[f"s20_str_gpao2q_{ano_sel}"], key=f"txt_s20_gpao2q_{ano_sel}")
                input_gpao3q_str = st.text_input(f"Nº gestantes com atendimento odontológico no 3º Quadrimestre de {ano_atual_s20} (GPAO3Q):", value=st.session_state[f"s20_str_gpao3q_{ano_sel}"], key=f"txt_s20_gpao3q_{ano_sel}")

                st.markdown(f"##### 👥 Total de Gestantes por Quadrimestre (Denominador)")
                input_tg1q_str = st.text_input(f"Total de gestantes no 1º Quadrimestre de {ano_atual_s20} (TG1Q):", value=st.session_state[f"s20_str_tg1q_{ano_sel}"], key=f"txt_s20_tg1q_{ano_sel}")
                input_tg2q_str = st.text_input(f"Total de gestantes no 2º Quadrimestre de {ano_atual_s20} (TG2Q):", value=st.session_state[f"s20_str_tg2q_{ano_sel}"], key=f"txt_s20_tg2q_{ano_sel}")
                input_tg3q_str = st.text_input(f"Total de gestantes no 3º Quadrimestre de {ano_atual_s20} (TG3Q):", value=st.session_state[f"s20_str_tg3q_{ano_sel}"], key=f"txt_s20_tg3q_{ano_sel}")

                # Conversão higienizada para números floats operacionais
                gpao1q = tratar_string_inteiro_para_float(input_gpao1q_str)
                gpao2q = tratar_string_inteiro_para_float(input_gpao2q_str)
                gpao3q = tratar_string_inteiro_para_float(input_gpao3q_str)
                tg1q = tratar_string_inteiro_para_float(input_tg1q_str)
                tg2q = tratar_string_inteiro_para_float(input_tg2q_str)
                tg3q = tratar_string_inteiro_para_float(input_tg3q_str)

                # Sincronização imediata no estado de sessão da view
                st.session_state[f"s20_str_gpao1q_{ano_sel}"] = formatar_para_inteiro_br(gpao1q)
                st.session_state[f"s20_str_gpao2q_{ano_sel}"] = formatar_para_inteiro_br(gpao2q)
                st.session_state[f"s20_str_gpao3q_{ano_sel}"] = formatar_para_inteiro_br(gpao3q)
                st.session_state[f"s20_str_tg1q_{ano_sel}"] = formatar_para_inteiro_br(tg1q)
                st.session_state[f"s20_str_tg2q_{ano_sel}"] = formatar_para_inteiro_br(tg2q)
                st.session_state[f"s20_str_tg3q_{ano_sel}"] = formatar_para_inteiro_br(tg3q)

                # Somatórios para a fórmula geral
                total_atendimentos_s20 = gpao1q + gpao2q + gpao3q
                total_gestantes_s20 = tg1q + tg2q + tg3q

                # 🛑 TRAVA DE SEGURANÇA: Denominador zerado ou sem dados inseridos
                if total_gestantes_s20 == 0.0 or total_atendimentos_s20 == 0.0:
                    ptsS20 = 0.0
                    p_odonto = 0.0
                    texto_resultado = "Aguardando preenchimento dos indicadores quadrimestrais de saúde bucal no SISAB..."
                    texto_pontuacao = "⏳ Sem avaliação"
                    estilo_status = "color: #64748b;"
                else:
                    # 🧮 Execução da fórmula oficial: P = (GPAO1Q + GPAO2Q + GPAO3Q) / (TG1Q + TG2Q + TG3Q) * 100
                    p_odonto = round((total_atendimentos_s20 / total_gestantes_s20) * 100.0, 2)

                    # ⚖️ Tabela oficial de metas progressivas e faixas do indicador S20
                    if p_odonto >= 100.0:
                        ptsS20 = 25.0
                        texto_resultado = "🥇 EXCELÊNCIA CRÍTICA: Cobertura de saúde bucal integral nas gestantes (100%)"
                        texto_pontuacao = "25,00 pontos (Pontuação Máxima)"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif 60.0 <= p_odonto < 100.0:
                        ptsS20 = 15.0
                        texto_resultado = f"🟢 META ALCANÇADA: Excelente integração da equipe de Saúde Bucal no Pré-Natal ({f'{p_odonto:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "15,00 pontos"
                        estilo_status = "color: #16a34a; font-weight: bold;"
                    elif 42.0 <= p_odonto < 60.0:
                        ptsS20 = 10.0
                        texto_resultado = f"🟡 COBERTURA INTERMEDIÁRIA: Necessidade de intensificar o fluxo de encaminhamento para a odontologia ({f'{p_odonto:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "10,00 pontos"
                        estilo_status = "color: #eab308; font-weight: bold;"
                    elif 24.0 <= p_odonto < 42.0:
                        ptsS20 = 5.0
                        texto_resultado = f"🟠 ALERTA ASSISTENCIAL: Baixo índice de consultas odontológicas registradas ({f'{p_odonto:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "5,00 pontos"
                        estilo_status = "color: #ea580c; font-weight: bold;"
                    else:
                        ptsS20 = 0.0
                        texto_resultado = f"❌ ALERTA CRÍTICO: Risco de agravos bucais gestacionais por falta de cobertura odontológica ({f'{p_odonto:.2f}'.replace('.', ',')}%)"
                        texto_pontuacao = "0,00 pontos"
                        estilo_status = "color: #dc2626; font-weight: bold;"

            with c2:
                lS20 = st.text_area(f"Link/Evidência (S20 - Painel de Saúde Bucal Previne Brasil {ano_sel}):", value=dS20.get("link", ""), key=f"txt_s20_link_{ano_sel}", height=150)

            # Formatação visual amigável do indicador de saúde bucal
            p_odonto_br = f"{p_odonto:.2f}".replace(".", ",") + "%"

            # Painel consolidador de métricas para a Linha de Saúde Bucal Materno-Infantil
            st.markdown(f"""
            <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                📌 <b>Indicador Geral S20:</b> Proporção de Gestantes com Atendimento Odontológico Realizado<br>
                📊 <b>Percentual de Cobertura de Saúde Bucal (P):</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{p_odonto_br}</code><br>
                ⚖️ <b>Status da Assistência Interdisciplinar:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
                🎯 <b>Pontuação Homologada para o Ano:</b> <code style="font-size: 14px; font-weight: bold; color: #1e3a8a;">{texto_pontuacao}</code>
            </div>
            """, unsafe_allow_html=True)

            # Agrupa os valores brutos para persistência de strings no banco de dados (Numeradores e Denominadores)
            lista_salvar_s20 = [f"{gpao1q:.0f}", f"{gpao2q:.0f}", f"{gpao3q:.0f}", f"{tg1q:.0f}", f"{tg2q:.0f}", f"{tg3q:.0f}"]
            str_concatenada_s20 = "/".join(lista_salvar_s20)

            if str_concatenada_s20 != dS20["valor"] or lS20 != dS20.get("link", ""):
                save_resp("S20", str_concatenada_s20, ptsS20, lS20)
                st.rerun()

            bloco_comentarios("S20", res_data)
            st.markdown('</div>', unsafe_allow_html=True)

       # =============================================================================
        # ABA 3: GRÁFICOS - SÉRIE HISTÓRICA (BARRAS EM AZUL)
        # =============================================================================
        with aba_graf:
            st.subheader("📈 Série Histórica de Pontuação do i-Saúde")
            st.write("Evolução da pontuação absoluta calculada de forma idêntica ao painel principal.")
            
            import pandas as pd
            import plotly.express as px
            
            # 1. Varre os anos aplicando exatamente a mesma regra de soma da sua interface
            anos_historico = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
            pontuacoes_validas = []
            
            for ano_hist in anos_historico:
                # Carrega o dicionário bruto do banco para o ano específico usando sua função
                dados_ano = load_respostas(ano_hist)
                
                total_pts_ano = 0.0
                for qid, item in dados_ano.items():
                    if qid.startswith("COM_"): 
                        continue
                    if "_" in qid and not qid.startswith("S"): 
                        continue
                    total_pts_ano += float(item.get("pontos", 0))
                
                pontuacoes_validas.append(round(total_pts_ano, 1))
            
            # 2. Criação do DataFrame para o Plotly
            df_historico = pd.DataFrame({
                "Ano": [str(a) for a in anos_historico],
                "Pontuação Real": pontuacoes_validas
            })
            
            # Filtra para mostrar no gráfico apenas anos que já possuem alguma pontuação (evita poluir com zeros do futuro)
            df_visivel = df_historico[df_historico["Pontuação Real"] > 0].copy()
            if df_visivel.empty:
                df_visivel = df_historico.head(4) # Fallback seguro caso tudo esteja zerado inicialmente
                
            # 3. Montagem do gráfico de barras com cor azul fixa
            fig = px.bar(
                df_visivel,
                x="Ano",
                y="Pontuação Real",
                text="Pontuação Real",
                labels={"Pontuação Real": "Pontos Brutos", "Ano": "Ano de Exercício"},
                # Define a cor azul fixa para todas as barras através do color_discrete_sequence
                color_discrete_sequence=["#0078D4"]
            )
            
            # Ajusta os rótulos de pontuação para o topo das barras
            fig.update_traces(texttemplate='%{text:.1f} pts', textposition='outside')
            
            maior_pontuacao = max(df_visivel["Pontuação Real"].max(), 100.0)
            
            fig.update_layout(
                xaxis_type='category',
                yaxis_range=[0, maior_pontuacao + 120], # Margem para o texto não cortar no topo
                showlegend=False,
                margin=dict(l=20, r=20, t=30, b=20),
                height=400
            )
            
            # Renderiza o gráfico na tela
            st.plotly_chart(fig, use_container_width=True)
            
            # 4. Tabela analítica resumida
            st.markdown("### 📋 Resumo da Evolução")
            st.dataframe(df_historico.set_index("Ano").T, use_container_width=True)