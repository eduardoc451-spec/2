import re
import streamlit as st
import sqlite3
import json
from io import BytesIO
from datetime import datetime, date

# =============================================================================
# BIBLIOTECAS PARA O PDF (ReportLab)
# =============================================================================
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak

# =============================================================================
# BIBLIOTECAS PARA OS GRÁFICOS (Plotly)
# =============================================================================
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# =============================================================================
# CONSTANTES GLOBAIS
# =============================================================================
CATEGORIAS_MAP = {
    "infraestrutura": {"label": "Infraestrutura e Setor", "qids": ["1.0", "1.1", "1.2", "1.3", "1.3.1", "1.4", "1.4.1", "1.4.2"]},
    "planejamento":   {"label": "Planejamento (PDTIC)", "qids": ["2.0", "2.1", "2.2", "2.3"]},
    "seguranca":       {"label": "Segurança da Informação", "qids": ["3.0", "3.1", "3.1.1", "3.1.1.1", "3.2", "3.2.1", "3.3", "3.4", "3.5", "3.6", "3.6.1"]},
    "transparencia":   {"label": "Transparência e LAI", "qids": ["4.0", "4.1", "4.2", "6.0", "6.1", "6.2", "6.3", "6.4", "7.0", "7.1", "7.2", "7.3"]},
    "gov_digital":     {"label": "Governo Digital", "qids": ["5.0", "5.1", "5.2", "5.3", "9.0", "9.1", "9.2"]},
    "sistemas":        {"label": "Sistemas de Gestão", "qids": ["8.0", "8.1", "8.2", "8.2.1", "8.2.2", "8.3", "8.4"]},
    "lgpd":            {"label": "LGPD", "qids": ["10.0", "10.1", "10.2", "10.3", "10.4", "10.5", "10.5.1", "11.0", "11.1"]},
}

PONTUACOES_MAX = {
    "1.0": 30, "1.1": 30, "1.2": 30, "1.3": 30, "1.3.1": 30, "1.4.1": 40, "1.4.2": 20,
    "2.0": 40, "2.1": 20, "2.2": 40, "2.3": 20,
    "3.0": 50, "3.1": 20, "3.1.1": 40, "3.1.1.1": 10, "3.2.1": 10, "3.3": 30, "3.4": 30, "3.5": 30, "3.6": 20,
    "4.0": 40, "6.0": 20, "6.1": 20, "6.2": 20, "6.3": 10, "6.4": 30, "7.0": 25, "7.1": 10, "7.2": 10, "7.3": 5,
    "8.0": 40, "8.2.1": 50, "8.2.2": 30, "9.1": 120
}

FAIXA_CORES = {"C": "#ef4444", "C+": "#f97316", "B": "#eab308", "B+": "#22c55e", "A": "#16a34a"}

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO (CORRIGIDO PARA LINKS CLICÁVEIS)
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link Externo")
def modal_aviso_link(qid, links_encontrados):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    
    for lk in links_encontrados:
        # CORREÇÃO: Removeu as crases e transformou em um link Markdown real e clicável
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")
        
    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
    
    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}"):
        st.rerun()

# =============================================================================
# 1. FUNÇÕES DE APOIO E BANCO DE DADOS
# =============================================================================
import sqlite3
import json
import datetime
import streamlit as st

def get_connection():
    return sqlite3.connect("dados_igov_ti.db", check_same_thread=False)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
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
        try:
            cursor.execute("ALTER TABLE respostas ADD COLUMN comentarios TEXT")
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
        with get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO respostas (id, ano, valor, pontos, link, comentarios, atualizado_em) 
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (qid, ano_sel, str(valor), float(pontos), str(link), comentarios_json))
            conn.commit()
    except Exception as e:
        st.error(f"Erro ao salvar {qid}: {e}")

def bloco_comentarios(questao_id, res_data, sufixo=None):
    """
    Gera um bloco de diálogo direto com histórico retrátil e controle de status.
    A alteração do status grava direto no clique e independe do texto.
    Permite exclusão individual de mensagens e limpa a caixa ao enviar.
    """
    ano_sel = st.session_state.get("ano_referencia_global", datetime.date.today().year)
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
                "data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status_clicado.upper()}**.",
                "status_definido": novo_status_clicado
            }
            historico.append(log_mudanca)
            save_resp(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0),
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
                            pontos=dados_questao.get("pontos", 0),
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
                        "data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "texto": novo_texto.strip(),
                        "status_definido": status_global  # FIX: Chave corrigida de 'status_defined' para 'status_definido'
                    }
                    historico.append(nova_mensagem)
                    save_resp(
                        qid=questao_id, 
                        valor=dados_questao.get("valor", ""), 
                        pontos=dados_questao.get("pontos", 0), 
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
# 2. GERADOR DO RELATÓRIO PDF
# =============================================================================
def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    # Inicializa o buffer na memória e vincula ao SimpleDocTemplate
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=30, 
        leftMargin=30, 
        topMargin=30, 
        bottomMargin=50
    )
    elements = []
    styles = getSampleStyleSheet()

    style_titulo_capa = ParagraphStyle('TituloCapa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=24, leading=28, textColor=colors.HexColor("#1b4f72"), alignment=1)

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
    elements.append(Paragraph("Relatório I-Gov-TI", style_titulo_capa))
    elements.append(Spacer(1, 15))
    
    style_ano_capa = ParagraphStyle('AnoCapa', parent=styles['Normal'], fontName='Helvetica', fontSize=16, textColor=colors.HexColor("#7f8c8d"), alignment=1)
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor("#1b4f72"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030 (ODS)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("6. Série Histórica do I-Gov TI", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
    ]
    
    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7"), 1, (2, 4)), 
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-GOV TI - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    nota_atual = float(total)
    ano_atual = int(str(ano).strip()[:4])
    ano_ant = ano_atual - 1

    def converter_pontos_em_faixa_iegm(pontos):
        pts = float(pontos)
        if pts < 500.0:              return "C"
        elif 500.0 <= pts <= 599.9:  return "C+"
        elif 600.0 <= pts <= 749.9:  return "B"
        elif 750.0 <= pts <= 899.9:  return "B+"
        else:                        return "A"

    # Se all_data não for fornecido, inicializa como dicionário vazio para evitar quebras
    if all_data is None:
        all_data = {}

    dados_ano_anterior = all_data.get(ano_ant, {})
    nota_anterior = 0.0
    if ano_ant in all_data:
        nota_anterior = float(sum(
            info_ant.get("pontos", 0) 
            for qid_ant, info_ant in dados_ano_anterior.items() 
            if isinstance(info_ant, dict) and not qid_ant.startswith("COM_")
        ))

    faixa_anterior = converter_pontos_em_faixa_iegm(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_iegm(nota_atual)

    variacao_pontos = nota_atual - nota_anterior
    if nota_anterior > 0:
        variacao_percentual = (variacao_pontos / nota_anterior) * 100
        texto_percentual = f"{variacao_percentual:+.2f}%"
    else:
        texto_percentual = "0.00%"

    if variacao_pontos > 0:
        cor_variacao = colors.HexColor("#28a745")
        seta_tendencia = "▲"
    elif variacao_pontos < 0:
        cor_variacao = colors.HexColor("#dc3545")
        seta_tendencia = "▼"
    else:
        cor_variacao = colors.HexColor("#6c757d")
        seta_tendencia = "■"

    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=colors.HexColor("#1b4f72"), alignment=1)
    style_td_var = ParagraphStyle('TdVar', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=cor_variacao, alignment=1)

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
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade."

    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # 2. ANÁLISE DE DESEMPENHO POR QUESITO
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): continue
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")
        pts_maximo = float(PONTUACOES_MAX.get(qid, 0)) if 'PONTUACOES_MAX' in globals() else 10.0
        
        if pts_maximo > 0:
            eficiencia = (pts_obtidos / pts_maximo) * 100
            item_data = {"qid": qid, "pts_obtidos": pts_obtidos, "pts_maximo": pts_maximo, "eficiencia": eficiencia, "valor": valor_resposta, "link": link_evidencia}
            if eficiencia >= 100.0: 
                lista_pontos_fortes.append(item_data)
            elif eficiencia < 100.0:
                lista_pontos_fracos.append(item_data)

    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes:</b>", styles["h3"]))
        data_fortes = [["Quesito", "Nota / Teto", "Eficiência", "Resposta / Evidência"]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["pts_obtidos"], reverse=True):
            evidencia = f"<b>{item['valor']}</b><br/>{item['link']}"
            data_fortes.append([item['qid'], f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", f"{item['eficiencia']:.1f}%", Paragraph(evidencia, styles["Normal"])])
        tabela_fortes = Table(data_fortes, colWidths=[65, 75, 65, 285])
        tabela_fortes.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#28a745")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (2, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#28a745")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Fracos Geral:</b>", styles["h3"]))
        data_fracos = [["Quesito", "Nota / Teto", "Eficiência", "Resposta / Evidência"]]
        for item in sorted(lista_pontos_fracos, key=lambda x: x["pts_obtidos"]):
            evidencia = f"<b>{item['valor']}</b><br/>{item['link']}"
            data_fracos.append([item['qid'], f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", f"{item['eficiencia']:.1f}%", Paragraph(evidencia, styles["Normal"])])
        tabela_fracos = Table(data_fracos, colWidths=[65, 75, 65, 285])
        tabela_fracos.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (2, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e67e22")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    PENALIDADES_MAX = {
        "8.3": -51.0,
        "8.4": -51.0
    }

    lista_penalidades = []
    
    for qid, pen_max in PENALIDADES_MAX.items():
        info = dados.get(qid, {}) if isinstance(dados.get(qid), dict) else {"pontos": 0.0, "valor": "Não Respondido", "link": ""}
        
        try:
            nota_real = float(info.get("pontos", 0.0))
        except (ValueError, TypeError):
            nota_real = 0.0
        
        if nota_real < 0:
            eficiencia_preventiva = 0.0
            status_html = "<font color='#dc3545'><b>Impacto Máximo Aplicado</b></font>"
        else:
            eficiencia_preventiva = 100.0
            status_html = "<font color='#28a745'><b>Risco Mitigado (Sem Penalidade)</b></font>"

        lista_penalidades.append({
            "qid": qid,
            "nota_real": nota_real,
            "pen_max": pen_max,
            "eficiencia": eficiencia_preventiva,
            "status": status_html
        })

    data_penalidades = [["Quesito", "Nota Obtida", "Penalidade Máxima", "Eficiência Preventiva", "Status de Risco"]]
    
    for item in sorted(lista_penalidades, key=lambda x: x["eficiencia"]):
        nota_txt = f"{item['nota_real']:.1f} pts"
        teto_txt = f"{item['pen_max']:.1f} pts"
        ef_txt = f"{item['eficiencia']:.1f}%"
        
        data_penalidades.append([
            item['qid'], 
            nota_txt, 
            teto_txt, 
            ef_txt, 
            Paragraph(item['status'], styles["Normal"]) 
        ])
        
    tabela_pen = Table(data_penalidades, colWidths=[65, 100, 110, 115, 150])
    tabela_pen.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1b4f72")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(tabela_pen)
    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS 
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS </b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    reincidencias_detectadas = []
    
    # Dicionário de tetos oficiais para validar apenas quesitos de nota real
    TETOS_VALIDOS = {
        "1.0": 30, "1.1": 30, "1.2": 30, "1.3": 30, "1.3.1": 30, "1.4.1": 40, "1.4.2": 20,
        "2.0": 40, "2.1": 20, "2.2": 40, "2.3": 20,
        "3.0": 50, "3.1": 20, "3.1.1": 40, "3.1.1.1": 10, "3.2.1": 10, "3.3": 30, "3.4": 30, "3.5": 30, "3.6": 20,
        "4.0": 40, "6.0": 20, "6.1": 20, "6.2": 20, "6.3": 10, "6.4": 30, "7.0": 25, "7.1": 10, "7.2": 10, "7.3": 5,
        "8.0": 40, "8.2.1": 50, "8.2.2": 30, "9.1": 120, 
    }
    
    for qid, info_atual in dados.items():
        # Ignora comentários e chaves que não sejam dicionários válidos
        if qid.startswith("COM_") or not isinstance(info_atual, dict): 
            return_val = None
            continue
            
        # CRÍTICO: Só avalia se o quesito pertencer à lista de pontuações oficiais
        if qid not in TETOS_VALIDOS:
            continue
            
        pts_maximo = float(TETOS_VALIDOS[qid])
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0))
        
        # Só analisa se o teto for válido e se houve falha real no ano atual (eficiência < 50%)
        if pts_maximo > 0 and (pts_obtidos_atual / pts_maximo) * 100 < 50.0:
            # Busca o mesmo quesito no ano anterior
            info_ant = dados_ano_anterior.get(qid, {}) if isinstance(dados_ano_anterior, dict) else {}
            pts_obtidos_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) else 0.0
            
            # Se também falhou no ano anterior (eficiência < 50%), temos uma Reincidência Crônica
            if (pts_obtidos_ant / pts_maximo) * 100 < 50.0:
                # Define a categoria dinamicamente com base no prefixo do quesito
                if qid.startswith("1") or qid.startswith("2") or qid.startswith("5"):
                    origem = "Governança de TI"
                elif qid.startswith("6") or qid.startswith("7"):
                    origem = "Transparência Digital"
                else:
                    origem = "Segurança / Operação"
                    
                reincidencias_detectadas.append({
                    "qid": qid,
                    "tipo": origem,
                    "detalhe": "Ineficiência Crônica de Desempenho (Abaixo de 50% por 2 anos)",
                    "ant": f"{pts_obtidos_ant:.1f} pts",
                    "atual": f"{pts_obtidos_atual:.1f} pts"
                })

    if reincidencias_detectadas:
        data_reinc = [["Quesito", "Origem da Falha", "Impacto Histórico", "Exercício Anterior", "Exercício Atual"]]
        # Ordena a tabela pelo ID do quesito para ficar organizado
        for reinc in sorted(reincidencias_detectadas, key=lambda x: [float(i) for i in x["qid"].split('.') if i.isdigit()]): 
            data_reinc.append([
                reinc["qid"], 
                reinc["tipo"], 
                Paragraph(f"<b>{reinc['detalhe']}</b>", styles["Normal"]), 
                reinc["ant"], 
                reinc["atual"]
            ])
            
        tabela_reinc = Table(data_reinc, colWidths=[65, 115, 170, 75, 65])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")), 
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), 
            ("ALIGN", (0, 0), (-1, 0), "CENTER"), 
            ("ALIGN", (0, 1), (1, -1), "CENTER"), 
            ("ALIGN", (3, 1), (-1, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")), 
            ("FONTSIZE", (0, 0), (-1, -1), 9), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_reinc)
    else: 
        elements.append(Paragraph("<font color='#28a745'><b>✅ Nenhuma reincidência ativa detectada. O município corrigiu ou mitigou as falhas do ano anterior.</b></font>", styles["Normal"]))
        
    elements.append(Spacer(1, 15))

# -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)
    # -------------------------------------------------------------------------
    # Importação com apelido isolado para não afetar o escopo global do PDF
    import reportlab.lib.colors as rl_colors

    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    def calcular_percentual_checklist(resposta_bruta, total_itens):
        if not resposta_bruta: 
            return 0.0
        
        # Se a string salva contiver estrutura de lista do Python ['item1', 'item2']
        if str(resposta_bruta).startswith("["):
            try:
                import ast
                itens_lista = ast.literal_eval(str(resposta_bruta))
                if isinstance(itens_lista, list):
                    itens_validos = [str(i).strip().lower() for i in itens_lista if "outros" not in str(i).lower()]
                    return min((len(itens_validos) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0
            except Exception:
                pass
                
        # Fallback limpo caso seja texto puro separado por vírgula
        itens = [i.strip().lower() for i in str(resposta_bruta).split(",") if i.strip()]
        itens_validos = [i for i in itens if "outros" not in i]
        return min((len(itens_validos) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0

    # Dicionário de Metas ODS parametrizado conforme as regras do i-Gov TI
    REGRAS_ODS = {
        "1.0": {"metas": "16.6, 17.8", "total_chk": 0},
        "1.2": {"metas": "9.c", "total_chk": 0},
        "1.3": {"metas": "9.c, 16.6, 17.8", "total_chk": 0},
        "1.4": {"metas": "16.6, 17.8", "total_chk": 0},
        "1.4.2": {"metas": "16.6, 17.8", "total_chk": 0},
        "2.0": {"metas": "16.6, 16.7, 17.8", "total_chk": 0},
        "3.0": {"metas": "16.6, 16.a, 17.8", "total_chk": 0},
        "3.1": {"metas": "16.6", "total_chk": 0},
        "3.1.1": {"metas": "16.6", "total_chk": 0},
        "3.3": {"metas": "16.6, 16.7, 17.8", "total_chk": 0},
        "3.4": {"metas": "9.c, 16.6", "total_chk": 0},
        "3.5": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "3.6": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "4.0": {"metas": "16.5, 16.6, 17.8", "total_chk": 0},
        "5.0": {"metas": "9.4, 16.5, 16.6, 17.14", "total_chk": 0},
        "6.0": {"metas": "16.6, 17.8", "total_chk": 0},
        "6.1": {"metas": "9.c, 16.7, 17.8", "total_chk": 0},
        "6.2": {"metas": "16.6", "total_chk": 0},
        "6.3": {"metas": "16.6, 16.7", "total_chk": 0},
        "6.4": {"metas": "10.2, 16.6, 17.8", "total_chk": 0},
        "7.0": {"metas": "16.5, 16.6, 17.8", "total_chk": 0},
        "7.1": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "7.2": {"metas": "16.5, 16.6, 17.8", "total_chk": 0},
        "7.3": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "8.0": {"metas": "16.5, 16.6, 17.8, 17.14", "total_chk": 0},
        "8.1": {"metas": "16.5, 16.6, 17.8", "total_chk": 17},
        "8.2": {"metas": "16.5, 16.6, 17.8", "total_chk": 17},
        "8.2.1": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "8.4": {"metas": "16.5, 16.6, 17.8", "total_chk": 17},
        "9.0": {"metas": "10.2, 16.6, 17.8", "total_chk": 0},
        "9.1": {"metas": "16.6", "total_chk": 16},
        "10.0": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "10.3": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "10.4": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "10.5": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "11.0": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0}
    }

    analise_ods = []
    
    # Captura dinâmica do DICIONÁRIO DE DADOS para suportar qualquer escopo
    dados_reference = None
    for nome_var in ['dados', 'res_data', 'respostas', 'dados_municipio']:
        if nome_var in locals():
            dados_reference = locals()[nome_var]
            break

    if dados_reference is None:
        try: dados_reference = dados
        except NameError:
            try: dados_reference = res_data
            except NameError: dados_reference = {}

    for qid, config in REGRAS_ODS.items():
        info = dados_reference.get(qid, {}) if isinstance(dados_reference, dict) else {"valor": "Não Respondido"}
        if not isinstance(info, dict):
            info = {"valor": str(info)}
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()
        
        if not resp or resp_l == "não respondido" or resp == "[]": 
            continue
            
        if config["total_chk"] > 0:
            pct = calcular_percentual_checklist(resp, config["total_chk"])
            status = f"{pct:.1f}% Atendido"
        else:
            # Filtros condicionais específicos
            if qid == "6.2":
                status = "Atendido" if "possibilita para todos os relatórios" in resp_l else "Não Atendido"
            elif qid == "7.3":
                status = "Atendido" if "não" in resp_l else "Não Atendido"
            elif qid == "8.2.1":
                status = "Atendido" if "totalmente integrado" in resp_l else "Não Atendido"
            elif qid == "10.3":
                status = "Atendido" if "todos os contratos vigentes" in resp_l else "Não Atendido"
            # Regras genéricas e de fallback padrão do i-Gov TI
            elif "não" in resp_l and qid in ["5.1.2"]: 
                status = "Atendido"
            elif "sim" in resp_l or "parcialmente" in resp_l or "integralmente" in resp_l or "todas" in resp_l or "maior parte" in resp_l:
                status = "Atendido"
            else:
                status = "Não Atendido"

        # Formatação para exibição limpa na tabela removendo colchetes e aspas simples
        exibicao_resp = resp
        if exibicao_resp.startswith("["):
            exibicao_resp = exibicao_resp.replace("[", "").replace("]", "").replace("'", "")

        analise_ods.append({
            "qid": qid,
            "status": status,
            "metas": config["metas"],
            "resp": exibicao_resp[:45] + "..." if len(exibicao_resp) > 45 else exibicao_resp
        })

    if analise_ods:
        data_ods = [["Quesito", "Resposta Informada", "Vínculo Metas ODS", "Status de Cumprimento"]]
        style_td_ods = ParagraphStyle('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        for item in sorted(analise_ods, key=lambda x: [float(i) if i.replace('.','',1).isdigit() else 999 for i in x['qid'].split('.')]):
            st_txt = item["status"]
            
            if "Não Atendido" in st_txt:
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt:
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else:
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
                
            data_ods.append([
                item["qid"], 
                Paragraph(item["resp"], styles["Normal"]), 
                item["metas"], 
                st_p
            ])
            
        tabela_ods = Table(data_ods, colWidths=[60, 200, 115, 110])
        tabela_ods.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#0f9d58")), 
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.whitesmoke), 
            ("ALIGN", (0, 0), (0, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#0f9d58")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 📊 6. SÉRIE HISTÓRICA DO I-GOV TI (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    # IMPORTS LOCAIS SEGUROS (Evita conflitos de escopo global no ReportLab)
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    import reportlab.lib.colors as rl_colors

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>6. SÉRIE HISTÓRICA DO I-GOV TI (CONSOLIDADO FINAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    
    # 🕵️‍♂️ Captura dinâmica do ANO para evitar conflito de nomenclatura
    ano_reference = None
    for nome_var in ['ano_sel', 'ano_atual', 'ano', 'exercicio']:
        if nome_var in locals():
            ano_reference = locals()[nome_var]
            break
    if ano_reference is None:
        ano_reference = 2026

    # 🕵️‍♂️ Captura dinâmica da NOTA ATUAL DO COMPILADOR
    nota_reference = 0.0
    for nome_var in ['total_pts', 'nota_atual', 'pontuacao_final']:
        if nome_var in locals():
            try:
                nota_reference = float(locals()[nome_var])
                break
            except (ValueError, TypeError):
                continue

    # Montagem dos dados do gráfico (Sincronizado com o parâmetro all_data + Fallbacks)
    import streamlit as st

    for a in anos_serie:
        # 1. Se for o ano selecionado atualmente no formulário
        if a == ano_reference: 
            if nota_reference > 0.0:
                valores_serie.append(min(nota_reference, 1000.0))
            elif dados_reference and isinstance(dados_reference, dict):
                nota_recuperada = float(sum(info_h.get("pontos", 0.0) for qid_h, info_h in dados_reference.items() if isinstance(info_h, dict) and not qid_h.startswith("COM_")))
                valores_serie.append(min(nota_recuperada, 1000.0))
            else:
                valores_serie.append(0.0)
                
        # 2. Se o ano estiver salvo no dicionário "all_data" passado por parâmetro
        elif all_data and a in all_data:
            dados_ano = all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(info_h.get("pontos", 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not qid_h.startswith("COM_")))
                valores_serie.append(min(pontos_ano, 1000.0))
            else:
                valores_serie.append(min(float(dados_ano), 1000.0))

        # 3. Fallback: Se o ano estiver salvo no histórico do session_state do Streamlit
        elif hasattr(st, 'session_state') and 'all_data' in st.session_state and a in st.session_state.all_data:
            dados_ano = st.session_state.all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(info_h.get("pontos", 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not qid_h.startswith("COM_")))
                valores_serie.append(min(pontos_ano, 1000.0))
            else:
                valores_serie.append(min(float(dados_ano), 1000.0))
                
        # 4. Se não encontrar o ano em lugar nenhum, deixa zerado
        else: 
            valores_serie.append(0.0)

    # Configuração do Gráfico do i-Gov TI
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
    
    # Escala baseada nas regras de pontuação até 1000
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = 1000
    bc.valueAxis.valueStep = 200
    bc.valueAxis.labels.fontSize = 8
    
    # 🔥 ATIVAÇÃO DOS RÓTULOS (PONTUAÇÃO EM CIMA DA BARRA)
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    # Customização das cores utilizando o padrão institucional estável
    bc.bars[0].fillColor = rl_colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = rl_colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    # Título do Gráfico atualizado para o i-Gov TI
    desenho_grafico.add(String(240, 150, "Série Histórica do I-Gov TI", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=rl_colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))

    # =============================================================================
    # --- FECHAMENTO E RETORNO SEGURO DO RELATÓRIO (FIM DA FUNÇÃO) ---
    # =============================================================================
    doc.build(elements)
    buffer.seek(0)
    return buffer

# =============================================================================
# 3. INTERFACE E FORMULÁRIO (STREAMLIT)
# =============================================================================
def render_sidebar():
    st.sidebar.title("🛠️ Painel i-GOV TI")
    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_global")
    res_data = load_respostas(ano_sel)
    
    total_pts = sum(float(item.get("pontos", 0)) for k, item in res_data.items() if not k.startswith("COM_"))
    
    if total_pts <= 499:   faixa, cor = "C",  "red"
    elif total_pts <= 599: faixa, cor = "C+", "orange"
    elif total_pts <= 749: faixa, cor = "B",  "#d4d400"
    elif total_pts <= 899: faixa, cor = "B+", "lightgreen"
    elif total_pts <= 1000: faixa, cor = "A",  "green"

    st.sidebar.metric("Pontuação Total", f"{total_pts:.1f} pts")
    st.sidebar.markdown(f"**Faixa:** <span style='color:{cor}; font-size:20px; font-weight:bold;'>{faixa}</span>", unsafe_allow_html=True)
    
    # 🔥 Botão de Download do Relatório PDF Integrado na Sidebar (COM HISTÓRICO TRATADO)
    st.sidebar.markdown("---")
    st.sidebar.subheader("📄 Relatórios")
    
    # 1. Busca os dados brutos de todos os anos no banco de dados para a série histórica
    try:
        dados_historicos_brutos = get_all_years_data()
    except Exception:
        dados_historicos_brutos = {}
        
    # 2. TRATAMENTO CRÍTICO: Garante que as chaves dos anos sejam inteiros (ex: converte "2024" para 2024)
    historico_tratado = {}
    if isinstance(dados_historicos_brutos, dict):
        for ano_chave, valor_ano in dados_historicos_brutos.items():
            try:
                ano_int = int(str(ano_chave).strip()[:4])
                historico_tratado[ano_int] = valor_ano
            except (ValueError, TypeError):
                continue

    # 3. Alimenta o session_state como garantia extra para o componente do gráfico
    st.session_state.all_data = historico_tratado

    # 4. Gera o relatório passando o dicionário histórico tratado para o gráfico puxar os dados
    pdf_buffer = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa, historico_tratado)
    
    st.sidebar.download_button(
        label="📥 Baixar Relatório PDF",
        data=pdf_buffer.getvalue(),  # Extrai o valor binário correto
        file_name=f"Relatorio_i-Gov TI_{ano_sel}.pdf",
        mime="application/pdf"
    )
    
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Zerar Questionário"):
        with get_connection() as conn:
            conn.execute("DELETE FROM respostas WHERE ano = ?", (ano_sel,))
            conn.commit()
        st.rerun()
        
    return total_pts, res_data, ano_sel


def mostrar_formulario_gov():
    # =========================================================================
    # CORREÇÃO CRÍTICA PARA CONFLITO DE ESCOPO DO 're' (UNBOUNDLOCALERROR)
    # =========================================================================
    global re
    import sys
    re = sys.modules['re']
    # =========================================================================

    init_db()
    total_pts, res_data, ano_sel = render_sidebar()
    
    st.markdown("""
        <style>
        .quesito-card {
            background-color: #f8f9fa;
            padding: 20px;
            border-left: 6px solid #1e3a5f;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #ddd;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title(f"📊 Auditoria i-Gov TI - {ano_sel}")
    
    aba_quest, aba_graf = st.tabs(["📋 Questionário", "📈 Gráficos"])
    
    with aba_quest:
        # Veja se o seu erro estava aqui para baixo:
        # Se a linha "st.header("1.0 Estrutura de TIC")" estiver aqui dentro, 
        # ela PRECISA ter 8 espaços de recuo (2 tabs) por estar dentro do "with aba_quest:"
        st.write("Conteúdo do questionário aqui...")

        # --- SEÇÃO 1: INFRAESTRUTURA E SETOR ---
        st.header("1.0 Estrutura de TIC")
        
        # =============================================================================
        # QUESITO 1.0 • SETOR DE TIC (100% INDEPENDENTE COM 8 ESPAÇOS DE INDENTAÇÃO)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.0 - Setor de Tecnologia da Informação e Comunicação", expanded=True):
                st.subheader("1.0 • Setor de TIC")
                st.write("**A Prefeitura possui uma área ou setor que cuida de Tecnologia da Informação e Comunicação (TIC)?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes10 = ["Selecione...", "Sim – 30", "Não – 00"]
                
                # Recupera o estado salvo no dicionário de dados históricos
                d10 = res_data.get("1.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d10 is None: d10 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_10 = d10.get("valor", "Selecione...")
                chave_radio_10 = f"r_10_{v_salvo_10}_{ano_sel}"

                def cb_radio_10():
                    val = st.session_state[chave_radio_10]
                    pts = 30.0 if "Sim" in val else 0.0
                    lnk = st.session_state.get(f"l_10_txt_{ano_sel}", d10.get("link", ""))
                    
                    save_resp("1.0", val, pts, lnk)
                    res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_10():
                    lnk = st.session_state[f"l_10_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_10, v_salvo_10)
                    pts = 30.0 if "Sim" in val else 0.0
                    
                    save_resp("1.0", val, pts, lnk)
                    res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d10.get("link", "") or "")]
                    
                    if lnk != d10.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx10 = opcoes10.index(v_salvo_10) if v_salvo_10 in opcoes10 else 0
                    st.radio(
                        "Selecione 1.0:", 
                        options=opcoes10, 
                        index=idx10, 
                        key=chave_radio_10,
                        on_change=cb_radio_10,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_10 = st.text_area(
                        "Link/Evidência (1.0):", 
                        value=d10.get("link", ""), 
                        key=f"l_10_txt_{ano_sel}", 
                        on_change=cb_text_10, 
                        placeholder="Insira o link da lei de estrutura administrativa, organograma oficial ou portaria de nomeação da equipe de TIC...",
                        height=100
                    )
                    placeholder_links_10 = st.empty()
                    links_10_visuais = [u[0] for u in re.findall(regex_pure_url, link_10 or "")]
                    if links_10_visuais:
                        placeholder_links_10.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_10_visuais]))

                pts_atuais_10 = d10.get("pontos", 0.0)
                cor_txt_10 = "#28a745" if pts_atuais_10 == 30.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_10}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.0: +{pts_atuais_10:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.0", res_data, ano_sel)

        # GATILHO DO MODAL 1.0
        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
            modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.1 • QUANTIDADE DA EQUIPE DE TIC (100% INDEPENDENTE VIA CALLBACKS)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.1 - Composição de Recursos Humanos do Setor de TIC", expanded=True):
                st.subheader("1.1 • Recursos Humanos em TIC")
                st.write("**Informe a quantidade da equipe que atua no suporte e atendimento de primeiro nível:**")
                st.caption("ℹ *Regra: (Concursados + Comissionados + Estagiários) > 0 garante +30 pontos. Salvamento via eventos nativos.*")

                # Recupera e trata o estado inicial do dicionário com segurança
                d11 = res_data.get("1.1", {"valor": "0", "pontos": 0.0, "link": ""})
                if d11 is None: d11 = {"valor": "0", "pontos": 0.0, "link": ""}

                v_conc_i, v_comi_i, v_esta_i, v_outr_i = 0, 0, 0, 0
                evidencia_11_salva = ""
                raw_link = d11.get("link", "")

                if raw_link:
                    try:
                        if "|LINK:" in raw_link:
                            contadores_part, evidencia_11_salva = raw_link.split("|LINK:", 1)
                        else:
                            contadores_part = raw_link
                        
                        parts = contadores_part.split(",")
                        v_conc_i = int(parts[0].split(":")[1])
                        v_comi_i = int(parts[1].split(":")[1])
                        v_esta_i = int(parts[2].split(":")[1])
                        v_outr_i = int(parts[3].split(":")[1])
                    except Exception:
                        v_conc_i, v_comi_i, v_esta_i, v_outr_i = 0, 0, 0, 0

                # Definição unificada dos Callbacks do Quesito 1.1 para inputs numéricos e área de texto
                def cb_processa_e_salva_11():
                    c_val = int(st.session_state.get(f"q11_num_conc_{ano_sel}", v_conc_i))
                    co_val = int(st.session_state.get(f"q11_num_comi_{ano_sel}", v_comi_i))
                    e_val = int(st.session_state.get(f"q11_num_esta_{ano_sel}", v_esta_i))
                    o_val = int(st.session_state.get(f"q11_num_outr_{ano_sel}", v_outr_i))
                    lnk_val = st.session_state.get(f"l_11_txt_area_{ano_sel}", evidencia_11_salva)

                    total_p = c_val + co_val + e_val
                    pts_calculados = 30.0 if total_p > 0 else 0.0
                    composite_string = f"C:{c_val},Co:{co_val},E:{e_val},O:{o_val}|LINK:{lnk_val.strip()}"

                    save_resp("1.1", str(total_p), pts_calculados, composite_string)
                    res_data["1.1"] = {"valor": str(total_p), "pontos": pts_calculados, "link": composite_string}

                    # Avaliação do gatilho do modal baseado na alteração da URL limpa
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_11_salva or "")]
                    
                    if lnk_val != evidencia_11_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Concursados:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_conc_i, key=f"q11_num_conc_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")
                with col2:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Comissionados:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_comi_i, key=f"q11_num_comi_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")
                with col3:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Estagiários:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_esta_i, key=f"q11_num_esta_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")
                with col4:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Outros:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_outr_i, key=f"q11_num_outr_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")

                st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)

                link_11 = st.text_area(
                    "Link/Evidência da composição da equipe (1.1):", 
                    value=evidencia_11_salva, 
                    key=f"l_11_txt_area_{ano_sel}", 
                    on_change=cb_processa_e_salva_11,
                    placeholder="Cole aqui o link do decreto de lotação de pessoal, relatório do setor de RH ou folha simplificada da TI...",
                    height=90
                )

                placeholder_links_11 = st.empty()
                links_11_visuais = [u[0] for u in re.findall(regex_pure_url, link_11 or "")]
                if links_11_visuais:
                    placeholder_links_11.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_11_visuais]))

                # Resumo dinâmico e impacto de pontuação
                total_pessoal = int(d11.get("valor", "0"))
                pts_atuais_11 = d11.get("pontos", 0.0)
                cor_txt_11 = "#28a745" if pts_atuais_11 == 30.0 else "#6c757d"
                
                st.info(f"👥 Total de Pessoal Efetivo Computado (C+Co+E): {total_pessoal} funcionário(s)")
                st.markdown(f"<span style='color:{cor_txt_11}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.1: +{pts_atuais_11:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.1", res_data, ano_sel)

        # GATILHO DO MODAL 1.1
        if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
            modal_aviso_link("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = False

            # =============================================================================
        # QUESITO 1.2 • ATRIBUIÇÕES DO SETOR DE TIC (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.2 - Definição de Atribuições Formais da Equipe", expanded=True):
                st.subheader("1.2 • Atribuições Formais")
                st.write("**A prefeitura municipal definiu formalmente as atribuições do pessoal do setor de Tecnologia da Informação e Comunicação (TIC)?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes12 = ["Selecione...", "Sim – 30", "Não – 00"]
                
                # Recupera o estado salvo no dicionário de dados históricos
                d12 = res_data.get("1.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d12 is None: d12 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_12 = d12.get("valor", "Selecione...")
                chave_radio_12 = f"r_12_{v_salvo_12}_{ano_sel}"

                def cb_radio_12():
                    val = st.session_state[chave_radio_12]
                    pts = 30.0 if "Sim" in val else 0.0
                    lnk = st.session_state.get(f"l_12_txt_{ano_sel}", d12.get("link", ""))
                    
                    save_resp("1.2", val, pts, lnk)
                    res_data["1.2"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_12():
                    lnk = st.session_state[f"l_12_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_12, v_salvo_12)
                    pts = 30.0 if "Sim" in val else 0.0
                    
                    save_resp("1.2", val, pts, lnk)
                    res_data["1.2"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d12.get("link", "") or "")]
                    
                    if lnk != d12.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx12 = opcoes12.index(v_salvo_12) if v_salvo_12 in opcoes12 else 0
                    st.radio(
                        "Selecione 1.2:", 
                        options=opcoes12, 
                        index=idx12, 
                        key=chave_radio_12,
                        on_change=cb_radio_12,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_12 = st.text_area(
                        "Link/Evidência (1.2):", 
                        value=d12.get("link", ""), 
                        key=f"l_12_txt_{ano_sel}", 
                        on_change=cb_text_12, 
                        placeholder="Insira o link do manual de cargos, decreto de atribuições de secretarias ou manual interno de procedimentos...",
                        height=100
                    )
                    placeholder_links_12 = st.empty()
                    links_12_visuais = [u[0] for u in re.findall(regex_pure_url, link_12 or "")]
                    if links_12_visuais:
                        placeholder_links_12.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_12_visuais]))

                pts_atuais_12 = d12.get("pontos", 0.0)
                cor_txt_12 = "#28a745" if pts_atuais_12 == 30.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_12}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.2: +{pts_atuais_12:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.2", res_data, ano_sel)

        # GATILHO DO MODAL 1.2
        if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
            modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False

            # =============================================================================
        # QUESITO 1.3 • CAPACITAÇÃO EM TIC (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.3 - Capacitação e Treinamento do Pessoal de TIC", expanded=True):
                st.subheader("1.3 • Capacitação do Setor")
                st.write("**A prefeitura disponibilizou capacitação para o pessoal da área de Tecnologia da Informação e Comunicação (TIC)?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes13 = ["Selecione...", "Sim – 30", "Não – 00"]
                
                # Recupera o estado salvo no dicionário de dados históricos
                d13 = res_data.get("1.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d13 is None: d13 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_13 = d13.get("valor", "Selecione...")
                chave_radio_13 = f"r_13_{v_salvo_13}_{ano_sel}"

                def cb_radio_13():
                    val = st.session_state[chave_radio_13]
                    pts = 30.0 if "Sim" in val else 0.0
                    lnk = st.session_state.get(f"l_13_txt_{ano_sel}", d13.get("link", ""))
                    
                    save_resp("1.3", val, pts, lnk)
                    res_data["1.3"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_13():
                    lnk = st.session_state[f"l_13_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_13, v_salvo_13)
                    pts = 30.0 if "Sim" in val else 0.0
                    
                    save_resp("1.3", val, pts, lnk)
                    res_data["1.3"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d13.get("link", "") or "")]
                    
                    if lnk != d13.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_3_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx13 = opcoes13.index(v_salvo_13) if v_salvo_13 in opcoes13 else 0
                    st.radio(
                        "Selecione 1.3:", 
                        options=opcoes13, 
                        index=idx13, 
                        key=chave_radio_13,
                        on_change=cb_radio_13,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_13 = st.text_area(
                        "Link/Evidência (1.3):", 
                        value=d13.get("link", ""), 
                        key=f"l_13_txt_{ano_sel}", 
                        on_change=cb_text_13, 
                        placeholder="Insira o link de certificados emitidos, notas de empenho de cursos contratados ou plano anual de capacitação...",
                        height=100
                    )
                    placeholder_links_13 = st.empty()
                    links_13_visuais = [u[0] for u in re.findall(regex_pure_url, link_13 or "")]
                    if links_13_visuais:
                        placeholder_links_13.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_13_visuais]))

                pts_atuais_13 = d13.get("pontos", 0.0)
                cor_txt_13 = "#28a745" if pts_atuais_13 == 30.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_13}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.3: +{pts_atuais_13:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.3", res_data, ano_sel)

        # GATILHO DO MODAL 1.3
        if st.session_state.get(f"gatilho_modal_1_3_{ano_sel}", False):
            modal_aviso_link("1.3", st.session_state.get(f"links_pendentes_1_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = False
            
        # =============================================================================
        # QUESITO 1.3.1 • ÁREAS DE CAPACITAÇÃO EM TIC (100% INDEPENDENTE VIA CALLBACKS)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_3_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.3.1 - Detalhamento das Áreas Temáticas de Capacitação", expanded=True):
                st.subheader("1.3.1 • Áreas Temáticas de Treinamento")
                st.write("**Informe em quais áreas houve capacitação para a equipe do setor de TIC e anexe a comprovação:**")
                st.caption("ℹ *Regra: Mínimo 3 áreas (desconsiderando 'Outros') garante +30 pontos. Salvamento automático por eventos.*")

                # Recupera e trata o estado inicial do dicionário com segurança
                d131 = res_data.get("1.3.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d131 is None: d131 = {"valor": "[]", "pontos": 0.0, "link": ""}

                raw_v131 = d131.get("valor", "[]")
                if not raw_v131.startswith("["): raw_v131 = "[]"
                try:
                    lista_salva_131 = eval(raw_v131)
                except:
                    lista_salva_131 = []

                evidencia_131_salva = d131.get("link", "")
                areas = ["Infraestrutura e Redes", "Desenvolvimento e Software", "Análise de Dados", "Gestão e Segurança", "Outros"]

                # Callback exclusivo para processar tanto os checkboxes quanto o campo de texto de evidência
                def cb_processa_e_salva_131():
                    selecionadas = []
                    for area in areas:
                        area_key = area.replace(" ", "_").lower()
                        if st.session_state.get(f"chk_131_{area_key}_{ano_sel}", False):
                            selecionadas.append(area)
                    
                    lnk_val = st.session_state.get(f"l_131_txt_area_{ano_sel}", evidencia_131_salva)
                    
                    # Cálculo de pontos baseado na regra de negócio informada
                    contagem = len([a for a in selecionadas if a != "Outros"])
                    pts131 = 30.0 if contagem >= 3 else (15.0 if contagem == 2 else (5.0 if contagem == 1 else 0.0))
                    val_str = str(selecionadas)

                    save_resp("1.3.1", val_str, pts131, lnk_val)
                    res_data["1.3.1"] = {"valor": val_str, "pontos": pts131, "link": lnk_val}

                    # Avaliação do gatilho do modal baseado na alteração da URL limpa
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_131_salva or "")]
                    
                    if lnk_val != evidencia_131_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_3_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("**Assinale as verticais de treinamento aplicadas:**")
                    # Divisão em duas colunas internas menores para organizar os checkboxes de forma compacta
                    col_sub1, col_sub2 = st.columns([1, 1])
                    for idx, area in enumerate(areas):
                        area_key = area.replace(" ", "_").lower()
                        target_col = col_sub1 if idx % 2 == 0 else col_sub2
                        with target_col:
                            st.checkbox(
                                area,
                                value=area in lista_salva_131,
                                key=f"chk_131_{area_key}_{ano_sel}",
                                on_change=cb_processa_e_salva_131
                            )
                    
                with col2:
                    link_131 = st.text_area(
                        "Link/Evidência das áreas de capacitação (1.3.1):", 
                        value=evidencia_131_salva, 
                        key=f"l_131_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_131,
                        placeholder="Insira o link das ementas dos cursos, certificados de conclusão anexados na transparência ou portarias de fomento ao treino...",
                        height=110
                    )
                    
                    placeholder_links_131 = st.empty()
                    links_131_visuais = [u[0] for u in re.findall(regex_pure_url, link_131 or "")]
                    if links_131_visuais:
                        placeholder_links_131.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_131_visuais]))

                pts_atuais_131 = d131.get("pontos", 0.0)
                cor_txt_131 = "#28a745" if pts_atuais_131 == 30.0 else ("#ffc107" if pts_atuais_131 > 0.0 else "#6c757d")
                
                st.markdown(f"<span style='color:{cor_txt_131}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.3.1: +{pts_atuais_131:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.3.1", res_data, ano_sel)

        # GATILHO DO MODAL 1.3.1
        if st.session_state.get(f"gatilho_modal_1_3_1_{ano_sel}", False):
            modal_aviso_link("1.3.1", st.session_state.get(f"links_pendentes_1_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = False

            # =============================================================================
        # QUESITO 1.4 • PARTICIPAÇÃO EM LICITAÇÕES DE TIC (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.4 - Participação Institucional em Compras de TIC", expanded=True):
                st.subheader("1.4 • Participação em Licitações")
                st.write("**Nas licitações e contratos que tenham como soluções o uso de Tecnologia da Informação e Comunicação, houve participação formalizada do pessoal de TIC? Considerar somente compras com verba municipal**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes14 = ["Selecione...", "Sim", "Não"]
                
                # Recupera o estado salvo no dicionário de dados históricos
                d14 = res_data.get("1.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d14 is None: d14 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_14 = d14.get("valor", "Selecione...")
                chave_radio_14 = f"r_14_{v_salvo_14}_{ano_sel}"

                def cb_radio_14():
                    val = st.session_state[chave_radio_14]
                    lnk = st.session_state.get(f"l_14_txt_{ano_sel}", d14.get("link", ""))
                    
                    save_resp("1.4", val, 0.0, lnk)
                    res_data["1.4"] = {"valor": val, "pontos": 0.0, "link": lnk}

                def cb_text_14():
                    lnk = st.session_state[f"l_14_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_14, v_salvo_14)
                    
                    save_resp("1.4", val, 0.0, lnk)
                    res_data["1.4"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d14.get("link", "") or "")]
                    
                    if lnk != d14.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_4_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx14 = opcoes14.index(v_salvo_14) if v_salvo_14 in opcoes14 else 0
                    st.radio(
                        "Selecione 1.4:", 
                        options=opcoes14, 
                        index=idx14, 
                        key=chave_radio_14,
                        on_change=cb_radio_14,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_14 = st.text_area(
                        "Link/Evidência (1.4):", 
                        value=d14.get("link", ""), 
                        key=f"l_14_txt_{ano_sel}", 
                        on_change=cb_text_14, 
                        placeholder="Insira o link de termos de referência assinados pela TI, pareceres técnicos em editais ou portarias de equipe de apoio...",
                        height=100
                    )
                    placeholder_links_14 = st.empty()
                    links_14_visuais = [u[0] for u in re.findall(regex_pure_url, link_14 or "")]
                    if links_14_visuais:
                        placeholder_links_14.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_14_visuais]))

                st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.4: 0.0 pontos (A pontuação é computada no sub-quesito 1.4.1)</span>", unsafe_allow_html=True)
                bloco_comentarios("1.4", res_data, ano_sel)

        # GATILHO DO MODAL 1.4
        if st.session_state.get(f"gatilho_modal_1_4_{ano_sel}", False):
            modal_aviso_link("1.4", st.session_state.get(f"links_pendentes_1_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.4.1 • ETAPAS DE PARTICIPAÇÃO EM LICITAÇÕES (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_4_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.4.1 - Detalhamento das Etapas de Atuação Institucional", expanded=True):
                st.subheader("1.4.1 • Etapas de Atuação")
                st.write("**Selecione as etapas em que houve participação formalizada da equipe de TIC e anexe a comprovação:**")
                st.caption("ℹ *A pontuação é somada incrementalmente (Até 40 pontos). Salvamento automático por eventos com validação de link.*")

                # Recupera e trata o estado inicial do dicionário com segurança
                d141 = res_data.get("1.4.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d141 is None: d141 = {"valor": "[]", "pontos": 0.0, "link": ""}

                raw_v141 = d141.get("valor", "[]")
                if not raw_v141.startswith("["): raw_v141 = "[]"
                try:
                    lista_salva_141 = eval(raw_v141)
                except:
                    lista_salva_141 = []

                evidencia_141_salva = d141.get("link", "")
                etapas = {
                    "Elaboração do edital / Especificação técnica – 15": 15.0, 
                    "Comissão de Licitação / Equipe de Apoio – 10": 10.0, 
                    "Recebimento / Gestão de Contrato – 15": 15.0
                }

                # Callback exclusivo unificado para processar as caixas de seleção e a área de texto de evidência
                def cb_processa_e_salva_141():
                    sel141 = []
                    pts141 = 0.0
                    for etapa, pts in etapas.items():
                        slug_etapa = etapa.split(" – ")[0].replace(" / ", "_").replace(" ", "_").lower()
                        if st.session_state.get(f"chk_141_{slug_etapa}_{ano_sel}", False):
                            sel141.append(etapa)
                            pts141 += pts
                    
                    lnk_val = st.session_state.get(f"l_141_txt_area_{ano_sel}", evidencia_141_salva)
                    val_str = str(sel141)

                    save_resp("1.4.1", val_str, pts141, lnk_val)
                    res_data["1.4.1"] = {"valor": val_str, "pontos": pts141, "link": lnk_val}

                    # Avaliação do gatilho do modal baseado na alteração da URL limpa
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_141_salva or "")]
                    
                    if lnk_val != evidencia_141_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_4_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_4_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("**Selecione as etapas de atuação comprovadas:**")
                    # Renderização organizada verticalmente das caixas de seleção
                    for etapa, pts in etapas.items():
                        slug_etapa = etapa.split(" – ")[0].replace(" / ", "_").replace(" ", "_").lower()
                        st.checkbox(
                            etapa,
                            value=etapa in lista_salva_141,
                            key=f"chk_141_{slug_etapa}_{ano_sel}",
                            on_change=cb_processa_e_salva_141
                        )
                    
                with col2:
                    link_141 = st.text_area(
                        "Link/Evidência das etapas de participação (1.4.1):", 
                        value=evidencia_141_salva, 
                        key=f"l_141_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_141,
                        placeholder="Insira o link das publicações no Diário Oficial, atas de sessões com assinatura da TI ou relatórios de homologação técnica...",
                        height=110
                    )
                    
                    placeholder_links_141 = st.empty()
                    links_141_visuais = [u[0] for u in re.findall(regex_pure_url, link_141 or "")]
                    if links_141_visuais:
                        placeholder_links_141.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_141_visuais]))

                pts_atuais_141 = d141.get("pontos", 0.0)
                cor_txt_141 = "#28a745" if pts_atuais_141 == 40.0 else ("#ffc107" if pts_atuais_141 > 0.0 else "#6c757d")
                
                st.markdown(f"<span style='color:{cor_txt_141}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.4.1: +{pts_atuais_141:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.4.1", res_data, ano_sel)

        # GATILHO DO MODAL 1.4.1
        if st.session_state.get(f"gatilho_modal_1_4_1_{ano_sel}", False):
            modal_aviso_link("1.4.1", st.session_state.get(f"links_pendentes_1_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.4.2 • ESTUDOS PRELIMINARES DE SOFTWARE (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_4_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.4.2 - Análise de Viabilidade Técnica e Contratações de Software", expanded=True):
                st.subheader("1.4.2 • Estudos de Viabilidade de Software")
                st.write("**Sobre programas de computador (softwares) adquiridos ou licenciados nos últimos 5 anos, foi realizada análise ou estudo antes de sua contratação com a participação do pessoal de Tecnologia da Informação e Comunicação (TIC)?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opc142 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os softwares – 20": 20.0, 
                    "Sim, para a maior parte dos softwares – 15": 15.0, 
                    "Sim, para a menor parte dos softwares – 08": 8.0, 
                    "Não foi realizado – 00": 0.0, 
                    "Não foi adquirido nenhum software nos últimos 5 anos – 20": 20.0
                }
                lista142 = list(opc142.keys())
                
                # Recupera o estado salvo no dicionário de dados históricos
                d142 = res_data.get("1.4.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d142 is None: d142 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_142 = d142.get("valor", "Selecione...")
                chave_radio_142 = f"r_142_{v_salvo_142}_{ano_sel}"

                def cb_radio_142():
                    val = st.session_state[chave_radio_142]
                    pts = float(opc142.get(val, 0.0))
                    lnk = st.session_state.get(f"l_142_txt_{ano_sel}", d142.get("link", ""))
                    
                    save_resp("1.4.2", val, pts, lnk)
                    res_data["1.4.2"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_142():
                    lnk = st.session_state[f"l_142_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_142, v_salvo_142)
                    pts = float(opc142.get(val, 0.0))
                    
                    save_resp("1.4.2", val, pts, lnk)
                    res_data["1.4.2"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d142.get("link", "") or "")]
                    
                    if lnk != d142.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_4_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx142 = lista142.index(v_salvo_142) if v_salvo_142 in lista142 else 0
                    st.radio(
                        "Selecione 1.4.2:", 
                        options=lista142, 
                        index=idx142, 
                        key=chave_radio_142,
                        on_change=cb_radio_142,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_142 = st.text_area(
                        "Link/Evidência (1.4.2):", 
                        value=d142.get("link", ""), 
                        key=f"l_142_txt_{ano_sel}", 
                        on_change=cb_text_142, 
                        placeholder="Insira o link dos Estudos Técnicos Preliminares (ETP), relatórios de análise de aderência ou certidões de inexistência de compras de software...",
                        height=120
                    )
                    placeholder_links_142 = st.empty()
                    links_142_visuais = [u[0] for u in re.findall(regex_pure_url, link_142 or "")]
                    if links_142_visuais:
                        placeholder_links_142.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_142_visuais]))

                pts_atuais_142 = d142.get("pontos", 0.0)
                cor_txt_142 = "#28a745" if pts_atuais_142 > 0.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_142}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.4.2: +{pts_atuais_142:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.4.2", res_data, ano_sel)

        # GATILHO DO MODAL 1.4.2
        if st.session_state.get(f"gatilho_modal_1_4_2_{ano_sel}", False):
            modal_aviso_link("1.4.2", st.session_state.get(f"links_pendentes_1_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = False

        # --- SEÇÃO 2: PLANEJAMENTO (PDTIC) ---
        st.divider()
        st.header("2.0 Planejamento de TIC")

# =============================================================================
        # QUESITO 2.0 • PLANO DIRETOR DE TIC (PDTIC) (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_2_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 2.0 - Plano Diretor de Tecnologia da Informação e Comunicação", expanded=True):
                st.subheader("2.0 • PDTIC")
                st.write("**A prefeitura municipal possui um PDTIC – Plano Diretor de Tecnologia da Informação e Comunicação – vigente que estabeleça diretrizes e metas de atingimento no futuro?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opc20 = {
                    "Selecione...": 0.0,
                    "SIM, com metas acima de 02 anos – 40": 40.0, 
                    "SIM, com metas para até 02 anos – 30": 30.0, 
                    "NÃO POSSUI PDTIC – 00": 0.0
                }
                lista20 = list(opc20.keys())
                
                # Recupera o estado salvo no dicionário de dados históricos
                d20 = res_data.get("2.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d20 is None: d20 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_20 = d20.get("valor", "Selecione...")
                chave_radio_20 = f"r_20_{v_salvo_20}_{ano_sel}"

                def cb_radio_20():
                    val = st.session_state[chave_radio_20]
                    pts = float(opc20.get(val, 0.0))
                    lnk = st.session_state.get(f"l_20_txt_{ano_sel}", d20.get("link", ""))
                    
                    save_resp("2.0", val, pts, lnk)
                    res_data["2.0"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_20():
                    lnk = st.session_state[f"l_20_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_20, v_salvo_20)
                    pts = float(opc20.get(val, 0.0))
                    
                    save_resp("2.0", val, pts, lnk)
                    res_data["2.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d20.get("link", "") or "")]
                    
                    if lnk != d20.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx20 = lista20.index(v_salvo_20) if v_salvo_20 in lista20 else 0
                    st.radio(
                        "Selecione 2.0:", 
                        options=lista20, 
                        index=idx20, 
                        key=chave_radio_20,
                        on_change=cb_radio_20,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_20 = st.text_area(
                        "Link/Evidência (2.0):", 
                        value=d20.get("link", ""), 
                        key=f"l_20_txt_{ano_sel}", 
                        on_change=cb_text_20, 
                        placeholder="Insira o link da publicação do PDTIC no Diário Oficial, decreto de aprovação do plano ou página institucional de governança...",
                        height=100
                    )
                    placeholder_links_20 = st.empty()
                    links_20_visuais = [u[0] for u in re.findall(regex_pure_url, link_20 or "")]
                    if links_20_visuais:
                        placeholder_links_20.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_20_visuais]))

                pts_atuais_20 = d20.get("pontos", 0.0)
                cor_txt_20 = "#28a745" if pts_atuais_20 > 0.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_20}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.0: +{pts_atuais_20:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("2.0", res_data, ano_sel)
              
        # GATILHO DO MODAL 2.0
        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
            modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False
        
   # =============================================================================
        # QUESITO 2.1 • PÁGINA ELETRÔNICA DO PDTIC (ALINHADO AO PADRÃO DO SISTEMA)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_2_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 2.1 - Endereço Eletrônico de Publicação do PDTIC", expanded=True):
                st.subheader("2.1 • Página Eletrônica do PDTIC")
                st.write("**Informe a página eletrônica (link na internet) do PDTIC:**")
                st.caption("ℹ *Salvamento automático por eventos com validação de link via Regex.*")

                # Recupera o estado salvo com consistência
                d21 = res_data.get("2.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d21 is None: d21 = {"valor": "", "pontos": 0.0, "link": ""}

                valor_salvo_21 = d21.get("valor", "")

                # Callback exclusivo para processar a mudança no campo de texto
                def cb_text_21():
                    lnk_val = st.session_state[f"l_21_txt_input_{ano_sel}"].strip()
                    
                    # Regra de pontuação: Se preenchido e diferente de vazio ou XYZ, pontua 20
                    pts_21 = 20.0 if lnk_val != "" and lnk_val.upper() != "XYZ" else 0.0

                    save_resp("2.1", lnk_val, pts_21, lnk_val)
                    res_data["2.1"] = {"valor": lnk_val, "pontos": pts_21, "link": lnk_val}

                    # Avaliação do gatilho do modal baseado na alteração da URL
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d21.get("link", "") or "")]
                    
                    if lnk_val != d21.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_2_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 2])
                with col1:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.info("Insira a URL direta do plano publicado ou digite 'XYZ' caso esteja indisponível.")
                    
                with col2:
                    link_21 = st.text_input(
                        "Página eletrônica (link URL):", 
                        value=valor_salvo_21, 
                        key=f"l_21_txt_input_{ano_sel}", 
                        on_change=cb_text_21,
                        placeholder="https://www.municipio.sp.gov.br/transparencia/pdtic.pdf"
                    )
                    
                    placeholder_links_21 = st.empty()
                    links_21_visuais = [u[0] for u in re.findall(regex_pure_url, link_21 or "")]
                    if links_21_visuais:
                        placeholder_links_21.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_21_visuais]))

                pts_atuais_21 = d21.get("pontos", 0.0)
                cor_txt_21 = "#28a745" if pts_atuais_21 > 0.0 else "#6c757d"
                
                st.markdown(f"<span style='color:{cor_txt_21}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.1: +{pts_atuais_21:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("2.1", res_data, ano_sel)

        # GATILHO DO MODAL 2.1
        if st.session_state.get(f"gatilho_modal_2_1_{ano_sel}", False):
            modal_aviso_link("2.1", st.session_state.get(f"links_pendentes_2_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = False

            # =============================================================================
        # QUESITO 2.2 • ESCOPO DO PLANO DE TIC (100% INDEPENDENTE VIA CALLBACKS)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_2_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 2.2 - Elementos Contemplados no Plano de TIC", expanded=True):
                st.subheader("2.2 • Escopo do Plano de TIC")
                st.write("**O plano de TIC vigente contempla:**")
                st.caption("ℹ *A pontuação é somada incrementalmente (Até 40 pontos). Salvamento automático por eventos com validação de link.*")

                # Recupera e trata o estado inicial do dicionário com segurança
                d22 = res_data.get("2.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d22 is None: d22 = {"valor": "[]", "pontos": 0.0, "link": ""}

                raw_v22 = d22.get("valor", "[]")
                if not raw_v22.startswith("["): raw_v22 = "[]"
                try:
                    lista_salva_22 = eval(raw_v22)
                except:
                    lista_salva_22 = []

                evidencia_22_salva = d22.get("link", "")
                contempla = {
                    "Alocação de recursos orçamentários – 10": 10.0, 
                    "Alocação de recursos humanos – 10": 10.0, 
                    "Alocação de recursos materiais – 10": 10.0, 
                    "Estratégia de execução indireta (terceirização) – 10": 10.0
                }

                # Callback exclusivo unificado para caixas de seleção e área de texto de evidência
                def cb_processa_e_salva_22():
                    sel22 = []
                    pts22 = 0.0
                    for item, pts in contempla.items():
                        slug_item = item.split(" – ")[0].replace(" (", "_").replace(")", "").replace(" ", "_").lower()
                        if st.session_state.get(f"chk_22_{slug_item}_{ano_sel}", False):
                            sel22.append(item)
                            pts22 += pts
                    
                    lnk_val = st.session_state.get(f"l_22_txt_area_{ano_sel}", evidencia_22_salva)
                    val_str = str(sel22)

                    save_resp("2.2", val_str, pts22, lnk_val)
                    res_data["2.2"] = {"valor": val_str, "pontos": pts22, "link": lnk_val}

                    # Avaliação do gatilho do modal baseado na alteração da URL limpa
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_22_salva or "")]
                    
                    if lnk_val != evidencia_22_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_2_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_2_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("**Selecione as metas/estratégias contempladas:**")
                    # Renderização organizada das caixas de seleção
                    for item, pts in contempla.items():
                        slug_item = item.split(" – ")[0].replace(" (", "_").replace(")", "").replace(" ", "_").lower()
                        st.checkbox(
                            item,
                            value=item in lista_salva_22,
                            key=f"chk_22_{slug_item}_{ano_sel}",
                            on_change=cb_processa_e_salva_22
                        )
                    
                with col2:
                    link_22 = st.text_area(
                        "Link/Evidência do escopo do plano (2.2):", 
                        value=evidencia_22_salva, 
                        key=f"l_22_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_22,
                        placeholder="Insira as páginas ou links diretos das seções do PDTIC que comprovam as alocações de recursos e terceirizações...",
                        height=130
                    )
                    
                    placeholder_links_22 = st.empty()
                    links_22_visuais = [u[0] for u in re.findall(regex_pure_url, link_22 or "")]
                    if links_22_visuais:
                        placeholder_links_22.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_22_visuais]))

                pts_atuais_22 = d22.get("pontos", 0.0)
                cor_txt_22 = "#28a745" if pts_atuais_22 == 40.0 else ("#ffc107" if pts_atuais_22 > 0.0 else "#6c757d")
                
                st.markdown(f"<span style='color:{cor_txt_22}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.2: +{pts_atuais_22:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("2.2", res_data, ano_sel)

        # GATILHO DO MODAL 2.2
        if st.session_state.get(f"gatilho_modal_2_2_{ano_sel}", False):
            modal_aviso_link("2.2", st.session_state.get(f"links_pendentes_2_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_2_{ano_sel}"] = False

       # =============================================================================
        # QUESITO 2.3 • ATUALIZAÇÃO DO PDTIC (100% INDEPENDENTE COM EVIDÊNCIA)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_2_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 2.3 - Cronologia de Atualização / Publicação do PDTIC", expanded=True):
                st.subheader("2.3 • Data de Atualização do PDTIC")
                st.write("**Qual a data da última atualização do PDTIC? (Se não foi atualizado, informar a data da publicação)**")
                
                st.info("""
                **Regra de Pontuação:**
                * ✅ **Data de até 5 anos atrás:** 20 pontos.
                * ⚠️ **Data entre 5 e 10 anos atrás:** 10 pontos.
                * 🚫 **Data com mais de 10 anos ou Inexistente:** 00 pontos.
                """)

                # Recupera e trata o estado inicial do dicionário com segurança
                d23 = res_data.get("2.3", {"valor": None, "pontos": 0.0, "link": ""})
                if d23 is None: d23 = {"valor": None, "pontos": 0.0, "link": ""}

                valor_salvo_23 = d23.get("valor", "")
                evidencia_23_salva = d23.get("link", "")

                # Se o valor salvo for lixo, nulo ou a constante "XYZ", define a data padrão como hoje
                try:
                    if valor_salvo_23 and valor_salvo_23 != "XYZ":
                        dt_i = datetime.strptime(valor_salvo_23, '%Y-%m-%d').date()
                    else:
                        dt_i = date.today()
                except:
                    dt_i = date.today()

                chave_date_23 = f"dt23_picker_{ano_sel}"
                chave_switch_23 = f"chk_23_nao_possui_{ano_sel}"

                # Callback único que processa todas as alterações de estado deste quesito
                def cb_processa_e_salva_23():
                    lnk_val = st.session_state.get(f"l_23_txt_area_{ano_sel}", evidencia_23_salva).strip()
                    
                    # Se marcou que o documento está indisponível ou digitou XYZ na evidência
                    if st.session_state.get(chave_switch_23, False) or lnk_val.upper() == "XYZ":
                        data_str = "XYZ"
                        pontos_23 = 0.0
                        if lnk_val.upper() != "XYZ": 
                            lnk_val = "XYZ"
                    else:
                        data_sel = st.session_state.get(chave_date_23, dt_i)
                        ano_documento = data_sel.year
                        ano_contexto = int(ano_sel)
                        idade_anos = ano_contexto - ano_documento

                        if idade_anos <= 5:
                            pontos_23 = 20.0
                        elif 5 < idade_anos <= 10:
                            pontos_23 = 10.0
                        else:
                            pontos_23 = 0.0

                        if idade_anos < 0:
                            pontos_23 = 20.0

                        data_str = data_sel.strftime('%Y-%m-%d')
                        
                    save_resp("2.3", data_str, pontos_23, lnk_val)
                    res_data["2.3"] = {"valor": data_str, "pontos": pontos_23, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_23_salva or "")]

                    if lnk_val != evidencia_23_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_2_3_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_2_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    documento_indisponivel = st.checkbox(
                        "Documento indisponível / Não possui PDTIC", 
                        value=(valor_salvo_23 == "XYZ" or evidencia_23_salva == "XYZ"),
                        key=chave_switch_23,
                        on_change=cb_processa_e_salva_23
                    )

                    st.date_input(
                        "Selecione a data de vigência/publicação:",
                        value=dt_i,
                        key=chave_date_23,
                        on_change=cb_processa_e_salva_23,
                        format="DD/MM/YYYY",
                        disabled=documento_indisponivel
                    )
                    
                    if not st.session_state.get(chave_switch_23, documento_indisponivel):
                        dt_atual_feedback = st.session_state.get(chave_date_23, dt_i)
                        if dt_atual_feedback:
                            idade_calculada = int(ano_sel) - dt_atual_feedback.year
                            st.markdown(f"<div style='padding-top:10px;'><b>Idade calculada:</b> {idade_calculada} ano(s) em relação ao ciclo de {ano_sel}.</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='padding-top:10px; color:#dc3545;'><b>Status:</b> Constante 'XYZ' aplicada.</div>", unsafe_allow_html=True)
                        
                with col2:
                    link_23 = st.text_area(
                        "Link/Evidência da data de publicação (2.3):", 
                        value="" if evidencia_23_salva == "XYZ" else evidencia_23_salva, 
                        key=f"l_23_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_23,
                        placeholder="Insira o link direto da página da publicação ou diário oficial contendo a data...",
                        disabled=documento_indisponivel,
                        height=100
                    )
                    
                    placeholder_links_23 = st.empty()
                    links_23_visuais = [u[0] for u in re.findall(regex_pure_url, link_23 or "")]
                    if links_23_visuais and not documento_indisponivel:
                        placeholder_links_23.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_23_visuais]))

                pts_atuais_23 = d23.get("pontos", 0.0)
                cor_txt_23 = "#28a745" if pts_atuais_23 == 20.0 else ("#ffc107" if pts_atuais_23 == 10.0 else "#6c757d")
                
                st.markdown(f"<span style='color:{cor_txt_23}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.3: +{pts_atuais_23:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("2.3", res_data, ano_sel)

        # GATILHO DO MODAL 2.3
        if st.session_state.get(f"gatilho_modal_2_3_{ano_sel}", False):
            modal_aviso_link("2.3", st.session_state.get(f"links_pendentes_2_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_3_{ano_sel}"] = False

        # --- SEÇÃO 3: SEGURANÇA ---
        st.divider()
        st.header("3.0 Segurança da Informação")
                    
       # =============================================================================
        # QUESITO 3.0 • POLÍTICA DE SEGURANÇA DA INFORMAÇÃO (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_3_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.0 - Política de Segurança da Informação (POSIC)", expanded=True):
                st.subheader("3.0 • Política de Segurança da Informação")
                st.write("**A Prefeitura dispõe de Política de Segurança da informação formalmente instituída e de cumprimento obrigatório?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc30 = {
                    "Selecione...": 0.0,
                    "Sim – 50": 50.0,
                    "Não – 00": 0.0
                }
                lista30 = list(opc30.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d30 = res_data.get("3.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d30 is None: d30 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_30 = d30.get("valor", "Selecione...")
                evidencia_30_salva = d30.get("link", "")
                
                chave_radio_30 = f"r_30_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado deste quesito
                def cb_processa_e_salva_30():
                    lnk_val = st.session_state.get(f"l_30_txt_area_{ano_sel}", evidencia_30_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_30, v_salvo_30)
                    pts_30 = float(opc30.get(val_salvar, 0.0))

                    save_resp("3.0", val_salvar, pts_30, lnk_val)
                    res_data["3.0"] = {"valor": val_salvar, "pontos": pts_30, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_30_salva or "")]

                    if lnk_val != evidencia_30_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx30 = lista30.index(v_salvo_30) if v_salvo_30 in lista30 else 0
                    st.radio(
                        "Selecione o status da POSIC:",
                        options=lista30,
                        index=idx30,
                        key=chave_radio_30,
                        on_change=cb_processa_e_salva_30
                    )

                with col2:
                    link_30 = st.text_area(
                        "Link/Evidência (3.0):",
                        value=evidencia_30_salva,
                        key=f"l_30_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_30,
                        placeholder="Insira o link da publicação do decreto, resolução ou portaria instituindo a POSIC municipal...",
                        height=90
                    )

                    placeholder_links_30 = st.empty()
                    links_30_visuais = [u[0] for u in re.findall(regex_pure_url, link_30 or "")]
                    if links_30_visuais:
                        placeholder_links_30.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_30_visuais]))

                pts_atuais_30 = d30.get("pontos", 0.0)
                cor_txt_30 = "#28a745" if pts_atuais_30 == 50.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_30}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.0: +{pts_atuais_30:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.0", res_data, ano_sel)

        # GATILHO DO MODAL 3.0
        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
            modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.1 • TERMO DE RESPONSABILIDADE (100% INDEPENDENTE / ISOLADO)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_3_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.1 - Termo de Responsabilidade e Compromisso de TI", expanded=True):
                st.subheader("3.1 • Termo de Responsabilidade")
                st.write("**A Prefeitura estabelece procedimentos e responsabilidades quanto ao uso da tecnologia da informação pelos funcionários municipais, conhecido como Termo de Responsabilidade/Compromisso?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")
                
                opc31 = {
                    "Selecione...": 0.0, 
                    "Sim – 20": 20.0, 
                    "Não – 00": 0.0
                }
                lista31 = list(opc31.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d31 = res_data.get("3.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d31 is None: d31 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_31 = d31.get("valor", "Selecione...")
                evidencia_31_salva = d31.get("link", "")
                
                chave_radio_31 = f"r_31_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado deste quesito
                def cb_processa_e_salva_31():
                    lnk_val = st.session_state.get(f"l_31_txt_area_{ano_sel}", evidencia_31_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_31, v_salvo_31)
                    pts_31 = float(opc31.get(val_salvar, 0.0))

                    save_resp("3.1", val_salvar, pts_31, lnk_val)
                    res_data["3.1"] = {"valor": val_salvar, "pontos": pts_31, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_31_salva or "")]

                    if lnk_val != evidencia_31_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx31 = lista31.index(v_salvo_31) if v_salvo_31 in lista31 else 0
                    st.radio(
                        "Selecione o status do Termo:", 
                        options=lista31, 
                        index=idx31, 
                        key=chave_radio_31, 
                        on_change=cb_processa_e_salva_31
                    )
                    
                with col2:
                    link_31 = st.text_area(
                        "Link/Evidência (3.1):", 
                        value=evidencia_31_salva,
                        key=f"l_31_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_31, 
                        placeholder="Insira o link de publicação do decreto, portaria ou regulamento interno do Termo de Responsabilidade...",
                        height=90
                    )
                    
                    placeholder_links_31 = st.empty()
                    links_31_visuais = [u[0] for u in re.findall(regex_pure_url, link_31 or "")]
                    if links_31_visuais:
                        placeholder_links_31.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_31_visuais]))

                pts_atuais_31 = d31.get("pontos", 0.0)
                cor_txt_31 = "#28a745" if pts_atuais_31 == 20.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_31}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.1: +{pts_atuais_31:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.1", res_data, ano_sel)

        # GATILHO DO MODAL 3.1
        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
            modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 3.1.1 • DISPOSIÇÃO SOBRE ASSINATURA ELETRÔNICA (100% INDEPENDENTE / ISOLADO)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_3_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.1.1 - Uso de Assinatura Eletrônica no Termo", expanded=True):
                st.subheader("3.1.1 • Regramento de Assinatura Eletrônica")
                st.write("**O Termo de Responsabilidade/Compromisso dispõe sobre o uso da assinatura eletrônica pelos funcionários municipais?**")
                
                opc311 = {"Selecione...": 0.0, "Sim – 40": 40.0, "Não – 00": 0.0}
                lista311 = list(opc311.keys())

                d311 = res_data.get("3.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d311 is None: d311 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_311 = d311.get("valor", "Selecione...")
                evidencia_311_salva = d311.get("link", "")
                
                chave_radio_311 = f"r_311_select_{ano_sel}"

                def cb_processa_e_salva_311():
                    lnk_val = st.session_state.get(f"l_311_txt_area_{ano_sel}", evidencia_311_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_311, v_salvo_311)
                    pts_311 = float(opc311.get(val_salvar, 0.0))

                    save_resp("3.1.1", val_salvar, pts_311, lnk_val)
                    res_data["3.1.1"] = {"valor": val_salvar, "pontos": pts_311, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_311_salva or "")]
                    if lnk_val != evidencia_311_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx311 = lista311.index(v_salvo_311) if v_salvo_311 in lista311 else 0
                    st.radio(
                        "Selecione o status do regramento:", 
                        options=lista311, 
                        index=idx311, 
                        key=chave_radio_311, 
                        on_change=cb_processa_e_salva_311
                    )
                    
                with col2:
                    link_311 = st.text_area(
                        "Link/Evidência (3.1.1):", 
                        value=evidencia_311_salva,
                        key=f"l_311_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_311, 
                        placeholder="Insira o link ou fragmento do termo explicativo...",
                        height=90
                    )
                    placeholder_links_311 = st.empty()
                    links_311_visuais = [u[0] for u in re.findall(regex_pure_url, link_311 or "")]
                    if links_311_visuais:
                        placeholder_links_311.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_311_visuais]))

                pts_atuais_311 = d311.get("pontos", 0.0)
                cor_txt_311 = "#28a745" if pts_atuais_311 == 40.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_311}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.1.1: +{pts_atuais_311:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_3_1_1_{ano_sel}", False):
            modal_aviso_link("3.1.1", st.session_state.get(f"links_pendentes_3_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_1_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 3.1.1.1 • TIPO DE ASSINATURA ELETRÔNICA (100% INDEPENDENTE / ISOLADO)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_3_1_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.1.1.1 - Tipos de Assinatura Eletrônica Utilizada", expanded=True):
                st.subheader("3.1.1.1 • Modalidades de Assinatura")
                st.write("**Identifique os tipos de assinatura eletrônica aplicados na municipalidade:**")

                d3111 = res_data.get("3.1.1.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d3111 is None: d3111 = {"valor": "[]", "pontos": 0.0, "link": ""}

                raw_v3111 = d3111.get("valor", "[]")
                if not raw_v3111.startswith("["): raw_v3111 = "[]"
                try:
                    lista_salva_3111 = eval(raw_v3111)
                except:
                    lista_salva_3111 = []

                evidencia_3111_salva = d3111.get("link", "")
                tipos_assinatura = {
                    "Assinatura eletrônica de uso gratuito – 10": 10.0, 
                    "Assinatura eletrônica onerosa – 00": 0.0
                }

                def cb_processa_e_salva_3111():
                    lnk_val = st.session_state.get(f"l_3111_txt_area_{ano_sel}", evidencia_311_salva).strip()
                    sel3111 = []
                    pts3111 = 0.0
                    for item, pts in tipos_assinatura.items():
                        slug_item = item.split(" – ")[0].replace(" ", "_").lower()
                        if st.session_state.get(f"chk_3111_{slug_item}_{ano_sel}", False):
                            sel3111.append(item)
                            pts3111 += pts
                    val_str = str(sel3111)

                    save_resp("3.1.1.1", val_str, pts3111, lnk_val)
                    res_data["3.1.1.1"] = {"valor": val_str, "pontos": pts3111, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_3111_salva or "")]
                    if lnk_val != evidencia_3111_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_1_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    for item, pts in tipos_assinatura.items():
                        slug_item = item.split(" – ")[0].replace(" ", "_").lower()
                        st.checkbox(
                            item, 
                            value=item in lista_salva_3111,
                            key=f"chk_3111_{slug_item}_{ano_sel}", 
                            on_change=cb_processa_e_salva_3111
                        )
                    
                with col2:
                    link_3111 = st.text_area(
                        "Link/Evidência das modalidades (3.1.1.1):", 
                        value=evidencia_3111_salva,
                        key=f"l_3111_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_3111, 
                        placeholder="Insira os links comprobatórios...",
                        height=90
                    )
                    placeholder_links_3111 = st.empty()
                    links_3111_visuais = [u[0] for u in re.findall(regex_pure_url, link_3111 or "")]
                    if links_3111_visuais:
                        placeholder_links_3111.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_3111_visuais]))

                pts_atuais_3111 = d3111.get("pontos", 0.0)
                cor_txt_3111 = "#28a745" if pts_atuais_3111 > 0.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_3111}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.1.1.1: +{pts_atuais_3111:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.1.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_3_1_1_1_{ano_sel}", False):
            modal_aviso_link("3.1.1.1", st.session_state.get(f"links_pendentes_3_1_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_1_1_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.2 • IDENTIFICAÇÃO DE RISCOS DE TIC (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_3_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.2 - Identificação de Riscos de TIC (ISO/IEC 27000)", expanded=True):
                st.subheader("3.2 • Riscos de TIC")
                st.write("**Os riscos de TIC são identificados de acordo com as normas brasileiras da família ISO/IEC 27000?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc32 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                lista32 = list(opc32.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d32 = res_data.get("3.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d32 is None: d32 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_32 = d32.get("valor", "Selecione...")
                evidencia_32_salva = d32.get("link", "")
                
                chave_radio_32 = f"r_32_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado deste quesito
                def cb_processa_e_salva_32():
                    lnk_val = st.session_state.get(f"l_32_txt_area_{ano_sel}", evidencia_32_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_32, v_salvo_32)
                    pts_32 = float(opc32.get(val_salvar, 0.0))

                    save_resp("3.2", val_salvar, pts_32, lnk_val)
                    res_data["3.2"] = {"valor": val_salvar, "pontos": pts_32, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_32_salva or "")]

                    if lnk_val != evidencia_32_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx32 = lista32.index(v_salvo_32) if v_salvo_32 in lista32 else 0
                    st.radio(
                        "Selecione o status da identificação:",
                        options=lista32,
                        index=idx32,
                        key=chave_radio_32,
                        on_change=cb_processa_e_salva_32
                    )

                with col2:
                    link_32 = st.text_area(
                        "Link/Evidência (3.2):",
                        value=evidencia_32_salva,
                        key=f"l_32_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_32,
                        placeholder="Insira o link do processo, relatório ou mapeamento de riscos baseado na ISO 27000...",
                        height=90
                    )

                    placeholder_links_32 = st.empty()
                    links_32_visuais = [u[0] for u in re.findall(regex_pure_url, link_32 or "")]
                    if links_32_visuais:
                        placeholder_links_32.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_32_visuais]))

                pts_atuais_32 = d32.get("pontos", 0.0)
                st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.2: +{pts_atuais_32:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.2", res_data, ano_sel)

        # GATILHO DO MODAL 3.2
        if st.session_state.get(f"gatilho_modal_3_2_{ano_sel}", False):
            modal_aviso_link("3.2", st.session_state.get(f"links_pendentes_3_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 3.2.1 • NORMAS ISO APLICADAS (100% INDEPENDENTE E COM EVIDÊNCIA)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_3_2_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.2.1 - Normas da Família ISO/IEC 27000 Utilizadas", expanded=True):
                st.subheader("3.2.1 • Normas Utilizadas e Fiscalização")
                st.write("**As secretarias setoriais realizaram a fiscalização das áreas de risco? Informe quais normas da família ISO/IEC 27000 são utilizadas nos processos de segurança no uso de TIC:**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                # Recupera e trata o estado inicial do dicionário com segurança
                d321 = res_data.get("3.2.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d321 is None: d321 = {"valor": "[]", "pontos": 0.0, "link": ""}

                raw_v321 = d321.get("valor", "[]")
                if not raw_v321.startswith("["): raw_v321 = "[]"
                try:
                    lista_salva_321 = eval(raw_v321)
                except:
                    lista_salva_321 = []

                evidencia_321_salva = d321.get("link", "")
                normas_iso = {
                    "ISO/IEC 27000 – 1,5": 1.5, 
                    "ISO/IEC 27001 – 1,5": 1.5, 
                    "ISO/IEC 27002 – 1,5": 1.5, 
                    "ISO/IEC 27003 – 1,5": 1.5, 
                    "ISO/IEC 27004 – 02": 2.0, 
                    "ISO/IEC 27005 – 02": 2.0
                }

                # Callback único que processa as caixas de seleção e a área de texto de evidência
                def cb_processa_e_salva_321():
                    lnk_val = st.session_state.get(f"l_321_txt_area_{ano_sel}", evidencia_321_salva).strip()
                    sel321 = []
                    pts321 = 0.0
                    
                    for norma, pts in normas_iso.items():
                        slug_norma = norma.split(" – ")[0].replace("/", "_").replace(" ", "_").lower()
                        if st.session_state.get(f"chk_321_{slug_norma}_{ano_sel}", False):
                            sel321.append(norma)
                            pts321 += pts
                    val_str = str(sel321)

                    save_resp("3.2.1", val_str, pts321, lnk_val)
                    res_data["3.2.1"] = {"valor": val_str, "pontos": pts321, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_321_salva or "")]

                    if lnk_val != evidencia_321_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_2_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_2_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    for norma, pts in normas_iso.items():
                        slug_norma = norma.split(" – ")[0].replace("/", "_").replace(" ", "_").lower()
                        st.checkbox(
                            norma, 
                            value=norma in lista_salva_321,
                            key=f"chk_321_{slug_norma}_{ano_sel}", 
                            on_change=cb_processa_e_salva_321
                        )
                    
                with col2:
                    link_321 = st.text_area(
                        "Link/Evidência das normas e fiscalizações (3.2.1):", 
                        value=evidencia_321_salva,
                        key=f"l_321_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_321, 
                        placeholder="Insira os links comprobatórios dos atos, portarias ou relatórios de fiscalização baseados nas ISOs...",
                        height=140
                    )
                    
                    placeholder_links_321 = st.empty()
                    links_321_visuais = [u[0] for u in re.findall(regex_pure_url, link_321 or "")]
                    if links_321_visuais:
                        placeholder_links_321.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_321_visuais]))

                pts_atuais_321 = d321.get("pontos", 0.0)
                cor_txt_321 = "#28a745" if pts_atuais_321 > 0.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_321}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.2.1: +{pts_atuais_321:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.2.1", res_data, ano_sel)

        # GATILHO DO MODAL 3.2.1
        if st.session_state.get(f"gatilho_modal_3_2_1_{ano_sel}", False):
            modal_aviso_link("3.2.1", st.session_state.get(f"links_pendentes_3_2_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_2_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.3 • IDENTIFICAÇÃO DE RISCOS DE TIC (ISO 31000) (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_3_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.3 - Gestão de Riscos de TIC (ABNT NBR ISO/IEC 31000)", expanded=True):
                st.subheader("3.3 • Riscos de TIC (ISO 31000)")
                st.write("**Os riscos de TIC são identificados de acordo com as normas da ABNT NBR ISO/IEC 31000? Se tiver apenas antivírus e firewall, a resposta é NÃO.**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc33 = {
                    "Selecione...": 0.0,
                    "Sim – 30": 30.0,
                    "Não – 00": 0.0
                }
                lista33 = list(opc33.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d33 = res_data.get("3.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d33 is None: d33 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_33 = d33.get("valor", "Selecione...")
                evidencia_33_salva = d33.get("link", "")
                
                chave_radio_33 = f"r_33_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado deste quesito
                def cb_processa_e_salva_33():
                    lnk_val = st.session_state.get(f"l_33_txt_area_{ano_sel}", evidencia_33_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_33, v_salvo_33)
                    pts_33 = float(opc33.get(val_salvar, 0.0))

                    save_resp("3.3", val_salvar, pts_33, lnk_val)
                    res_data["3.3"] = {"valor": val_salvar, "pontos": pts_33, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_33_salva or "")]

                    if lnk_val != evidencia_33_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_3_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx33 = lista33.index(v_salvo_33) if v_salvo_33 in lista33 else 0
                    st.radio(
                        "Selecione o status da conformidade:",
                        options=lista33,
                        index=idx33,
                        key=chave_radio_33,
                        on_change=cb_processa_e_salva_33
                    )

                with col2:
                    link_33 = st.text_area(
                        "Link/Evidência (3.3):",
                        value=evidencia_33_salva,
                        key=f"l_33_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_33,
                        placeholder="Insira o link da política, plano ou matriz institucional de gestão de riscos de TIC corporativos...",
                        height=90
                    )

                    placeholder_links_33 = st.empty()
                    links_33_visuais = [u[0] for u in re.findall(regex_pure_url, link_33 or "")]
                    if links_33_visuais:
                        placeholder_links_33.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_33_visuais]))

                pts_atuais_33 = d33.get("pontos", 0.0)
                cor_txt_33 = "#28a745" if pts_atuais_33 == 30.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_33}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.3: +{pts_atuais_33:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.3", res_data, ano_sel)

        # GATILHO DO MODAL 3.3
        if st.session_state.get(f"gatilho_modal_3_3_{ano_sel}", False):
            modal_aviso_link("3.3", st.session_state.get(f"links_pendentes_3_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_3_{ano_sel}"] = False
        
        # =============================================================================
        # QUESITO 3.4 • PLANO DE CONTINUIDADE DE SERVIÇOS (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_3_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.4 - Plano de Continuidade dos Serviços de TIC", expanded=True):
                st.subheader("3.4 • Plano de Continuidade")
                st.write("**A Prefeitura possui um Plano de Continuidade dos Serviços de Tecnologia da Informação e Comunicação (TIC)? Recomendamos anexar o Plano de continuidade de serviços de TI, conforme Instrução de Preenchimento (IP)**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc34 = {
                    "Selecione...": 0.0,
                    "Sim – 30": 30.0,
                    "Não – 00": 0.0
                }
                lista34 = list(opc34.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d34 = res_data.get("3.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d34 is None: d34 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_34 = d34.get("valor", "Selecione...")
                evidencia_34_salva = d34.get("link", "")
                
                chave_radio_34 = f"r_34_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado deste quesito
                def cb_processa_e_salva_34():
                    lnk_val = st.session_state.get(f"l_34_txt_area_{ano_sel}", evidencia_34_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_34, v_salvo_34)
                    pts_34 = float(opc34.get(val_salvar, 0.0))

                    save_resp("3.4", val_salvar, pts_34, lnk_val)
                    res_data["3.4"] = {"valor": val_salvar, "pontos": pts_34, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_34_salva or "")]

                    if lnk_val != evidencia_34_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_4_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx34 = lista34.index(v_salvo_34) if v_salvo_34 in lista34 else 0
                    st.radio(
                        "Selecione o status da continuidade:",
                        options=lista34,
                        index=idx34,
                        key=chave_radio_34,
                        on_change=cb_processa_e_salva_34
                    )

                with col2:
                    link_34 = st.text_area(
                        "Link/Evidência (3.4):",
                        value=evidencia_34_salva,
                        key=f"l_34_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_34,
                        placeholder="Insira o link para o Plano de Continuidade de Negócios/TI aprovado institucionalmente...",
                        height=90
                    )

                    placeholder_links_34 = st.empty()
                    links_34_visuais = [u[0] for u in re.findall(regex_pure_url, link_34 or "")]
                    if links_34_visuais:
                        placeholder_links_34.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_34_visuais]))

                pts_atuais_34 = d34.get("pontos", 0.0)
                cor_txt_34 = "#28a745" if pts_atuais_34 == 30.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_34}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.4: +{pts_atuais_34:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.4", res_data, ano_sel)

        # GATILHO DO MODAL 3.4
        if st.session_state.get(f"gatilho_modal_3_4_{ano_sel}", False):
            modal_aviso_link("3.4", st.session_state.get(f"links_pendentes_3_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_4_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 3.5 • POLÍTICA DE BACKUP (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_3_5_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.5 - Política de Cópias de Segurança (Backup)", expanded=True):
                st.subheader("3.5 • Política de Backup")
                st.write("**A Prefeitura dispõe de política de cópias de segurança (backup) formalmente instituída como norma de cumprimento obrigatório?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc35 = {
                    "Selecione...": 0.0,
                    "Sim – 30": 30.0,
                    "Não – 00": 0.0
                }
                lista35 = list(opc35.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d35 = res_data.get("3.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d35 is None: d35 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_35 = d35.get("valor", "Selecione...")
                evidencia_35_salva = d35.get("link", "")
                
                chave_radio_35 = f"r_35_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado deste quesito
                def cb_processa_e_salva_35():
                    lnk_val = st.session_state.get(f"l_35_txt_area_{ano_sel}", evidencia_35_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_35, v_salvo_35)
                    pts_35 = float(opc35.get(val_salvar, 0.0))

                    save_resp("3.5", val_salvar, pts_35, lnk_val)
                    res_data["3.5"] = {"valor": val_salvar, "pontos": pts_35, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_35_salva or "")]

                    if lnk_val != evidencia_35_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_5_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_5_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx35 = lista35.index(v_salvo_35) if v_salvo_35 in lista35 else 0
                    st.radio(
                        "Selecione o status da política:",
                        options=lista35,
                        index=idx35,
                        key=chave_radio_35,
                        on_change=cb_processa_e_salva_35
                    )

                with col2:
                    link_35 = st.text_area(
                        "Link/Evidência (3.5):",
                        value=evidencia_35_salva,
                        key=f"l_35_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_35,
                        placeholder="Insira o link do normativo, portaria ou regulamento interno que formaliza a Política de Backup...",
                        height=90
                    )

                    placeholder_links_35 = st.empty()
                    links_35_visuais = [u[0] for u in re.findall(regex_pure_url, link_35 or "")]
                    if links_35_visuais:
                        placeholder_links_35.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_35_visuais]))

                pts_atuais_35 = d35.get("pontos", 0.0)
                cor_txt_35 = "#28a745" if pts_atuais_35 == 30.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_35}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.5: +{pts_atuais_35:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.5", res_data, ano_sel)

        # GATILHO DO MODAL 3.5
        if st.session_state.get(f"gatilho_modal_3_5_{ano_sel}", False):
            modal_aviso_link("3.5", st.session_state.get(f"links_pendentes_3_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_5_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.6 • INVENTÁRIO DE ATIVOS DE TIC (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_3_6_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.6 - Inventário Atualizado de Ativos de TIC", expanded=True):
                st.subheader("3.6 • Inventário de Ativos")
                st.write("**A Prefeitura possui inventário atualizado dos ativos de TIC? Ativos de TIC: switches, roteadores, servidores, firewalls, Sistemas operacionais, carga de processamento, backup, utilização de storages, etc.**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc36 = {
                    "Selecione...": 0.0,
                    "Sim – 20": 20.0,
                    "Não – 00": 0.0
                }
                lista36 = list(opc36.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d36 = res_data.get("3.6", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d36 is None: d36 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_36 = d36.get("valor", "Selecione...")
                evidencia_36_salva = d36.get("link", "")
                
                chave_radio_36 = f"r_36_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado do quesito 3.6
                def cb_processa_e_salva_36():
                    lnk_val = st.session_state.get(f"l_36_txt_area_{ano_sel}", evidencia_36_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_36, v_salvo_36)
                    pts_36 = float(opc36.get(val_salvar, 0.0))

                    save_resp("3.6", val_salvar, pts_36, lnk_val)
                    res_data["3.6"] = {"valor": val_salvar, "pontos": pts_36, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_36_salva or "")]

                    if lnk_val != evidencia_36_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_6_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_6_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx36 = lista36.index(v_salvo_36) if v_salvo_36 in lista36 else 0
                    st.radio(
                        "Selecione o status do inventário:",
                        options=lista36,
                        index=idx36,
                        key=chave_radio_36,
                        on_change=cb_processa_e_salva_36
                    )

                with col2:
                    link_36 = st.text_area(
                        "Link/Evidência (3.6):",
                        value=evidencia_36_salva,
                        key=f"l_36_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_36,
                        placeholder="Insira o link do sistema de inventário, planilha corporativa compartilhada ou relatório de ativos...",
                        height=90
                    )

                    placeholder_links_36 = st.empty()
                    links_36_visuais = [u[0] for u in re.findall(regex_pure_url, link_36 or "")]
                    if links_36_visuais:
                        placeholder_links_36.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_36_visuais]))

                pts_atuais_36 = d36.get("pontos", 0.0)
                cor_txt_36 = "#28a745" if pts_atuais_36 == 20.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_36}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.6: +{pts_atuais_36:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.6", res_data, ano_sel)

        # GATILHO DO MODAL 3.6
        if st.session_state.get(f"gatilho_modal_3_6_{ano_sel}", False):
            modal_aviso_link("3.6", st.session_state.get(f"links_pendentes_3_6_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_6_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 3.6.1 • COMPOSIÇÃO DA BASE DE ATIVOS (100% INDEPENDENTE E ISOLADO)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_3_6_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.6.1 - Composição da Base de Ativos de TIC", expanded=True):
                st.subheader("3.6.1 • Composição da Base de Ativos")
                st.write("**Como é composta a base de ativos mapeada no município?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                # Recupera e trata o estado inicial do dicionário com segurança
                d361 = res_data.get("3.6.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d361 is None: d361 = {"valor": "[]", "pontos": 0.0, "link": ""}

                raw_v361 = d361.get("valor", "[]")
                if not raw_v361.startswith("["): raw_v361 = "[]"
                try:
                    lista_salva_361 = eval(raw_v361)
                except:
                    lista_salva_361 = []

                evidencia_361_salva = d361.get("link", "")
                base_ativos = [
                    "Ativos de informação", 
                    "Ativos de software", 
                    "Ativos físicos", 
                    "Serviços", 
                    "Pessoas e suas qualificações"
                ]

                # Callback único que processa as caixas de seleção e a área de texto de evidência do 3.6.1
                def cb_processa_e_salva_361():
                    lnk_val = st.session_state.get(f"l_361_txt_area_{ano_sel}", evidencia_361_salva).strip()
                    sel361 = []
                    
                    for item in base_ativos:
                        slug_item = item.lower().replace(" ", "_").replace("ç", "c").replace("õ", "o")
                        if st.session_state.get(f"chk_361_{slug_item}_{ano_sel}", False):
                            sel361.append(item)
                    val_str = str(sel361)

                    save_resp("3.6.1", val_str, 0.0, lnk_val)
                    res_data["3.6.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_361_salva or "")]

                    if lnk_val != evidencia_361_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_3_6_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_3_6_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    for item in base_ativos:
                        slug_item = item.lower().replace(" ", "_").replace("ç", "c").replace("õ", "o")
                        st.checkbox(
                            item, 
                            value=item in lista_salva_361,
                            key=f"chk_361_{slug_item}_{ano_sel}", 
                            on_change=cb_processa_e_salva_361
                        )
                    
                with col2:
                    link_361 = st.text_area(
                        "Link/Evidência da base mapeada (3.6.1):", 
                        value=evidencia_361_salva,
                        key=f"l_361_txt_area_{ano_sel}", 
                        on_change=cb_processa_e_salva_361, 
                        placeholder="Insira os links, relatórios ou extratos que comprovem a abrangência do inventário...",
                        height=130
                    )
                    
                    placeholder_links_361 = st.empty()
                    links_361_visuais = [u[0] for u in re.findall(regex_pure_url, link_361 or "")]
                    if links_361_visuais:
                        placeholder_links_361.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_361_visuais]))

                pts_atuais_361 = d361.get("pontos", 0.0)
                st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.6.1: +{pts_atuais_361:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("3.6.1", res_data, ano_sel)

        # GATILHO DO MODAL 3.6.1
        if st.session_state.get(f"gatilho_modal_3_6_1_{ano_sel}", False):
            modal_aviso_link("3.6.1", st.session_state.get(f"links_pendentes_3_6_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_6_1_{ano_sel}"] = False
           
        # --- SEÇÃO 4: LAI ---
        st.divider()
        st.header("4.0 Transparência e LAI")
        
        # =============================================================================
        # QUESITO 4.0 • REGULAMENTAÇÃO DA LAI (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_4_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.0 - Regulamentação da Lei de Acesso à Informação (LAI)", expanded=True):
                st.subheader("4.0 • Regulamentação da LAI")
                st.write("**O município regulamentou a Lei de Acesso à Informação?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc40 = {
                    "Selecione...": 0.0,
                    "Sim – 40": 40.0,
                    "Não – 00": 0.0
                }
                lista40 = list(opc40.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d40 = res_data.get("4.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d40 is None: d40 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_40 = d40.get("valor", "Selecione...")
                evidencia_40_salva = d40.get("link", "")
                
                chave_radio_40 = f"r_40_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado do quesito 4.0
                def cb_processa_e_salva_40():
                    lnk_val = st.session_state.get(f"l_40_txt_area_{ano_sel}", evidencia_40_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_40, v_salvo_40)
                    pts_40 = float(opc40.get(val_salvar, 0.0))

                    save_resp("4.0", val_salvar, pts_40, lnk_val)
                    res_data["4.0"] = {"valor": val_salvar, "pontos": pts_40, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_40_salva or "")]

                    if lnk_val != evidencia_40_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx40 = lista40.index(v_salvo_40) if v_salvo_40 in lista40 else 0
                    st.radio(
                        "Selecione o status da regulamentação:",
                        options=lista40,
                        index=idx40,
                        key=chave_radio_40,
                        on_change=cb_processa_e_salva_40
                    )

                with col2:
                    link_40 = st.text_area(
                        "Link/Evidência (4.0):",
                        value=evidencia_40_salva,
                        key=f"l_40_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_40,
                        placeholder="Insira o link do decreto ou ato normativo municipal que regulamentou a LAI local...",
                        height=90
                    )

                    placeholder_links_40 = st.empty()
                    links_40_visuais = [u[0] for u in re.findall(regex_pure_url, link_40 or "")]
                    if links_40_visuais:
                        placeholder_links_40.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_40_visuais]))

                pts_atuais_40 = d40.get("pontos", 0.0)
                cor_txt_40 = "#28a745" if pts_atuais_40 == 40.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_40}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 4.0: +{pts_atuais_40:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("4.0", res_data, ano_sel)

        # GATILHO DO MODAL 4.0
        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
            modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 4.1 • IDENTIFICAÇÃO DO INSTRUMENTO NORMATIVO (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_4_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.1 - Dados de Identificação da Normativa da LAI", expanded=True):
                st.subheader("4.1 • Dados do Instrumento")
                st.write("**Informe o Instrumento normativo, Número e Data de publicação:**")
                st.caption("ℹ *Salvamento automático por eventos após edição de texto.*")

                # Recupera os dados do 4.1 de forma segura
                d41 = res_data.get("4.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d41 is None: d41 = {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_41 = d41.get("valor", "")

                # Callback para salvar o input de texto do 4.1
                def cb_processa_e_salva_41():
                    txt_normativa = st.session_state.get(f"t_41_input_{ano_sel}", v_salvo_41).strip()
                    save_resp("4.1", txt_normativa, 0.0, "")
                    res_data["4.1"] = {"valor": txt_normativa, "pontos": 0.0, "link": ""}

                st.text_input(
                    "Identificação do Instrumento Normativo:",
                    value=v_salvo_41,
                    key=f"t_41_input_{ano_sel}",
                    placeholder="Ex: Decreto Municipal nº 1.234, de 15 de março de 2018",
                    on_change=cb_processa_e_salva_41
                )
                
                st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 4.1: +0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("4.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 4.2 • LINK DO INSTRUMENTO NORMATIVO (100% INDEPENDENTE E ISOLADO)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_4_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.2 - Endereço Eletrônico do Instrumento Normativo", expanded=True):
                st.subheader("4.2 • Link da Normativa")
                st.write("**Página eletrônica (link) do instrumento oficial de regulamentação:**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                # Recupera os dados do 4.2 de forma isolada
                d42 = res_data.get("4.2", {"valor": "", "pontos": 0.0, "link": ""})
                if d42 is None: d42 = {"valor": "", "pontos": 0.0, "link": ""}
                evidencia_42_salva = d42.get("link", "") if d42.get("link", "") else d42.get("valor", "")
                if evidencia_42_salva == "XYZ": evidencia_42_salva = ""

                # Callback único que processa as alterações de estado exclusivas do 4.2
                def cb_processa_e_salva_42():
                    lnk_val = st.session_state.get(f"l_42_txt_area_{ano_sel}", evidencia_42_salva).strip()

                    save_resp("4.2", lnk_val, 0.0, lnk_val)
                    res_data["4.2"] = {"valor": lnk_val, "pontos": 0.0, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_42_salva or "")]

                    if lnk_val != evidencia_42_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_4_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = True

                link_42 = st.text_area(
                    "Link URL da Normativa (4.2):",
                    value=evidencia_42_salva,
                    key=f"l_42_txt_area_{ano_sel}",
                    placeholder="Insira a URL direta para acesso à publicação oficial do decreto ou ato normativo municipal...",
                    on_change=cb_processa_e_salva_42,
                    height=90
                )

                placeholder_links_42 = st.empty()
                links_42_visuais = [u[0] for u in re.findall(regex_pure_url, link_42 or "")]
                if links_42_visuais:
                    placeholder_links_42.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_42_visuais]))

                st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 4.2: +0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("4.2", res_data, ano_sel)

        # GATILHO DO MODAL 4.2
        if st.session_state.get(f"gatilho_modal_4_2_{ano_sel}", False):
            modal_aviso_link("4.2", st.session_state.get(f"links_pendentes_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = False

        # --- SEÇÃO 5: GOVERNO DIGITAL ---
        st.divider()
        st.header("5.0 Governo Digital")
        
        # =============================================================================
        # QUESITO 5.0 • REGULAMENTAÇÃO DO GOVERNO DIGITAL (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_5_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.0 - Lei sobre Eficiência Pública (Governo Digital)", expanded=True):
                st.subheader("5.0 • Governo Digital")
                st.write("**O município regulamentou a Lei sobre Eficiência Pública (Governo Digital)?**")
                st.caption("ℹ *Lei Federal nº 14.129, de 29 de Março de 2021. Salvamento automático por eventos.*")

                opc50 = {
                    "Selecione...": 0.0,
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0
                }
                lista50 = list(opc50.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d50 = res_data.get("5.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d50 is None: d50 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_50 = d50.get("valor", "Selecione...")
                if v_salvo_50 == "Sim": v_salvo_50 = "Sim – 10"
                if v_salvo_50 == "Não": v_salvo_50 = "Não – 00"
                evidencia_50_salva = d50.get("link", "")
                
                chave_radio_50 = f"r_50_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado do quesito 5.0
                def cb_processa_e_salva_50():
                    lnk_val = st.session_state.get(f"l_50_txt_area_{ano_sel}", evidencia_50_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_50, v_salvo_50)
                    pts_50 = float(opc50.get(val_salvar, 0.0))

                    save_resp("5.0", val_salvar, pts_50, lnk_val)
                    res_data["5.0"] = {"valor": val_salvar, "pontos": pts_50, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_50_salva or "")]

                    if lnk_val != evidencia_50_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx50 = lista50.index(v_salvo_50) if v_salvo_50 in lista50 else 0
                    st.radio(
                        "Selecione o status da regulamentação:",
                        options=lista50,
                        index=idx50,
                        key=chave_radio_50,
                        on_change=cb_processa_e_salva_50
                    )

                with col2:
                    link_50 = st.text_area(
                        "Link/Evidência (5.0):",
                        value=evidencia_50_salva,
                        key=f"l_50_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_50,
                        placeholder="Insira o link do decreto ou ato normativo municipal de Governo Digital...",
                        height=90
                    )

                    placeholder_links_50 = st.empty()
                    links_50_visuais = [u[0] for u in re.findall(regex_pure_url, link_50 or "")]
                    if links_50_visuais:
                        placeholder_links_50.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_50_visuais]))

                pts_atuais_50 = d50.get("pontos", 0.0)
                cor_txt_50 = "#28a745" if pts_atuais_50 == 10.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_50}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.0: +{pts_atuais_50:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("5.0", res_data, ano_sel)

        # GATILHO DO MODAL 5.0
        if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
            modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 5.1 • IDENTIFICAÇÃO DO INSTRUMENTO NORMATIVO (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_5_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.1 - Identificação da Normativa de Governo Digital", expanded=True):
                st.subheader("5.1 • Dados do Instrumento")
                st.write("**Informe o Instrumento normativo, Número e Data da publicação:**")
                st.caption("ℹ *Salvamento automático por eventos após edição de texto.*")

                # Recupera os dados do 5.1 de forma segura
                d51 = res_data.get("5.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d51 is None: d51 = {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_51 = d51.get("valor", "")

                # Callback para salvar o input de texto do 5.1
                def cb_processa_e_salva_51():
                    txt_normativa = st.session_state.get(f"t_51_input_{ano_sel}", v_salvo_51).strip()
                    save_resp("5.1", txt_normativa, 0.0, "")
                    res_data["5.1"] = {"valor": txt_normativa, "pontos": 0.0, "link": ""}

                st.text_input(
                    "Identificação do Instrumento Normativo:",
                    value=v_salvo_51,
                    key=f"t_51_input_{ano_sel}",
                    placeholder="Ex: Decreto Municipal nº 4.321, de 10 de maio de 2022",
                    on_change=cb_processa_e_salva_51
                )
                
                st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.1: +0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("5.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 5.2 • LINK DO INSTRUMENTO NORMATIVO (100% INDEPENDENTE E ISOLADO)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_5_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.2 - Endereço Eletrônico do Instrumento Normativo", expanded=True):
                st.subheader("5.2 • Link da Normativa")
                st.write("**Página eletrônica (link na internet) do instrumento normativo oficial:**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                # Recupera os dados do 5.2 de forma isolada
                d52 = res_data.get("5.2", {"valor": "", "pontos": 0.0, "link": ""})
                if d52 is None: d52 = {"valor": "", "pontos": 0.0, "link": ""}
                evidencia_52_salva = d52.get("link", "") if d52.get("link", "") else d52.get("valor", "")
                if evidencia_52_salva == "XYZ": evidencia_52_salva = ""

                # Callback único que processa as alterações de estado exclusivas do 5.2
                def cb_processa_e_salva_52():
                    lnk_val = st.session_state.get(f"l_52_txt_area_{ano_sel}", evidencia_52_salva).strip()

                    save_resp("5.2", lnk_val, 0.0, lnk_val)
                    res_data["5.2"] = {"valor": lnk_val, "pontos": 0.0, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_52_salva or "")]

                    if lnk_val != evidencia_52_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_5_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = True

                link_52 = st.text_area(
                    "Link URL da Normativa (5.2):",
                    value=evidencia_52_salva,
                    key=f"l_52_txt_area_{ano_sel}",
                    placeholder="Insira a URL direta para o texto publicado da lei de Governo Digital do município...",
                    on_change=cb_processa_e_salva_52,
                    height=90
                )

                placeholder_links_52 = st.empty()
                links_52_visuais = [u[0] for u in re.findall(regex_pure_url, link_52 or "")]
                if links_52_visuais:
                    placeholder_links_52.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_52_visuais]))

                st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.2: +0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("5.2", res_data, ano_sel)

        # GATILHO DO MODAL 5.2
        if st.session_state.get(f"gatilho_modal_5_2_{ano_sel}", False):
            modal_aviso_link("5.2", st.session_state.get(f"links_pendentes_5_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 6.0 • SITE INTERNET ATUALIZADO (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_6_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 6.0 - Manutenção de Site na Internet Atualizado", expanded=True):
                st.subheader("6.0 • Site na Internet")
                st.write("**A prefeitura mantém site na Internet com informações atualizadas?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc60 = {
                    "Selecione...": 0.0,
                    "Sim – 20": 20.0,
                    "Não – 00": 0.0
                }
                lista60 = list(opc60.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d60 = res_data.get("6.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d60 is None: d60 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_60 = d60.get("valor", "Selecione...")
                evidencia_60_salva = d60.get("link", "")
                
                chave_radio_60 = f"r_60_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado do quesito 6.0
                def cb_processa_e_salva_60():
                    lnk_val = st.session_state.get(f"l_60_txt_area_{ano_sel}", evidencia_60_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_60, v_salvo_60)
                    pts_60 = float(opc60.get(val_salvar, 0.0))

                    save_resp("6.0", val_salvar, pts_60, lnk_val)
                    res_data["6.0"] = {"valor": val_salvar, "pontos": pts_60, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_60_salva or "")]

                    if lnk_val != evidencia_60_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx60 = lista60.index(v_salvo_60) if v_salvo_60 in lista60 else 0
                    st.radio(
                        "Selecione o status do site institucional:",
                        options=lista60,
                        index=idx60,
                        key=chave_radio_60,
                        on_change=cb_processa_e_salva_60
                    )

                with col2:
                    link_60 = st.text_area(
                        "Link/Evidência (6.0):",
                        value=evidencia_60_salva,
                        key=f"l_60_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_60,
                        placeholder="Insira a URL principal do portal da prefeitura municipal...",
                        height=90
                    )

                    placeholder_links_60 = st.empty()
                    links_60_visuais = [u[0] for u in re.findall(regex_pure_url, link_60 or "")]
                    if links_60_visuais:
                        placeholder_links_60.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_60_visuais]))

                pts_atuais_60 = d60.get("pontos", 0.0)
                cor_txt_60 = "#28a745" if pts_atuais_60 == 20.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_60}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.0: +{pts_atuais_60:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("6.0", res_data, ano_sel)

        # GATILHO DO MODAL 6.0
        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
            modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 6.1 • FERRAMENTA DE PESQUISA INTERNA (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_6_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 6.1 - Ferramenta de Pesquisa/Busca Interna de Conteúdo", expanded=True):
                st.subheader("6.1 • Ferramenta de Pesquisa")
                st.write("**O site eletrônico da prefeitura continha ferramenta de pesquisa/busca interna de conteúdo? Não considerar a opção de busca do próprio browser (Ctrl + F)**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc61 = {
                    "Selecione...": 0.0,
                    "Sim, para todo o conteúdo – 20": 20.0,
                    "Sim, para a maior parte do conteúdo – 10": 10.0,
                    "Sim, para a menor parte do conteúdo – 05": 5.0,
                    "Não – 00": 0.0
                }
                lista61 = list(opc61.keys())

                d61 = res_data.get("6.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d61 is None: d61 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_61 = d61.get("valor", "Selecione...")
                evidencia_61_salva = d61.get("link", "")
                chave_radio_61 = f"r_61_select_{ano_sel}"

                def cb_processa_e_salva_61():
                    lnk_val = st.session_state.get(f"l_61_txt_area_{ano_sel}", evidencia_61_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_61, v_salvo_61)
                    pts_61 = float(opc61.get(val_salvar, 0.0))

                    save_resp("6.1", val_salvar, pts_61, lnk_val)
                    res_data["6.1"] = {"valor": val_salvar, "pontos": pts_61, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_61_salva or "")]
                    if lnk_val != evidencia_61_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx61 = lista61.index(v_salvo_61) if v_salvo_61 in lista61 else 0
                    st.radio(
                        "Selecione a abrangência do mecanismo de busca:",
                        options=lista61,
                        index=idx61,
                        key=chave_radio_61,
                        on_change=cb_processa_e_salva_61
                    )

                with col2:
                    link_61 = st.text_area(
                        "Link/Evidência (6.1):",
                        value=evidencia_61_salva,
                        key=f"l_61_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_61,
                        placeholder="Insira a URL contendo a barra de pesquisa ou exemplo de tela de resultados de busca...",
                        height=110
                    )
                    placeholder_links_61 = st.empty()
                    links_61_visuais = [u[0] for u in re.findall(regex_pure_url, link_61 or "")]
                    if links_61_visuais:
                        placeholder_links_61.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_61_visuais]))

                pts_atuais_61 = d61.get("pontos", 0.0)
                cor_txt_61 = "#28a745" if pts_atuais_61 > 0.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_61}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.1: +{pts_atuais_61:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("6.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_6_1_{ano_sel}", False):
            modal_aviso_link("6.1", st.session_state.get(f"links_pendentes_6_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 6.2 • FORMATOS ABERTOS E NÃO PROPRIETÁRIOS (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_6_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 6.2 - Disponibilização de Dados em Formatos Abertos", expanded=True):
                st.subheader("6.2 • Formatos Abertos")
                st.write("**O site possibilita o download de dados/informações em formatos abertos e não proprietários? Exemplos de formatos abertos e não proprietários: JSON, XML, CSV, ODS, RDF, etc.**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc62 = {
                    "Selecione...": 0.0,
                    "Possibilita para todos os relatórios – 20": 20.0,
                    "Possibilita para a maior parte dos relatórios – 10": 10.0,
                    "Possibilita para a menor parte dos relatórios – 05": 5.0,
                    "Não – 00": 0.0
                }
                lista62 = list(opc62.keys())

                d62 = res_data.get("6.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d62 is None: d62 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_62 = d62.get("valor", "Selecione...")
                evidencia_62_salva = d62.get("link", "")
                chave_radio_62 = f"r_62_select_{ano_sel}"

                def cb_processa_e_salva_62():
                    lnk_val = st.session_state.get(f"l_62_txt_area_{ano_sel}", evidencia_62_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_62, v_salvo_62)
                    pts_62 = float(opc62.get(val_salvar, 0.0))

                    save_resp("6.2", val_salvar, pts_62, lnk_val)
                    res_data["6.2"] = {"valor": val_salvar, "pontos": pts_62, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_62_salva or "")]
                    if lnk_val != evidencia_62_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx62 = lista62.index(v_salvo_62) if v_salvo_62 in lista62 else 0
                    st.radio(
                        "Selecione a cobertura de formatos abertos:",
                        options=lista62,
                        index=idx62,
                        key=chave_radio_62,
                        on_change=cb_processa_e_salva_62
                    )

                with col2:
                    link_62 = st.text_area(
                        "Link/Evidência (6.2):",
                        value=evidencia_62_salva,
                        key=f"l_62_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_62,
                        placeholder="Insira o link da página de Dados Abertos ou com botões para downloads em CSV, JSON ou ODS...",
                        height=110
                    )
                    placeholder_links_62 = st.empty()
                    links_62_visuais = [u[0] for u in re.findall(regex_pure_url, link_62 or "")]
                    if links_62_visuais:
                        placeholder_links_62.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_62_visuais]))

                pts_atuais_62 = d62.get("pontos", 0.0)
                cor_txt_62 = "#28a745" if pts_atuais_62 > 0.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_62}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.2: +{pts_atuais_62:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("6.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_6_2_{ano_sel}", False):
            modal_aviso_link("6.2", st.session_state.get(f"links_pendentes_6_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_2_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 6.3 • REPOSITÓRIO DE PERGUNTAS FREQUENTES (FAQ) (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_6_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 6.3 - Disponibilização de Perguntas Mais Frequentes (FAQ)", expanded=True):
                st.subheader("6.3 • Perguntas Frequentes (FAQ)")
                st.write("**O site disponibiliza as respostas a perguntas mais frequentes da sociedade?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc63 = {
                    "Selecione...": 0.0,
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0
                }
                lista63 = list(opc63.keys())

                d63 = res_data.get("6.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d63 is None: d63 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_63 = d63.get("valor", "Selecione...")
                if v_salvo_63 == "Sim": v_salvo_63 = "Sim – 10"
                if v_salvo_63 == "Não": v_salvo_63 = "Não – 00"
                evidencia_63_salva = d63.get("link", "")
                chave_radio_63 = f"r_63_select_{ano_sel}"

                def cb_processa_e_salva_63():
                    lnk_val = st.session_state.get(f"l_63_txt_area_{ano_sel}", evidencia_63_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_63, v_salvo_63)
                    pts_63 = float(opc63.get(val_salvar, 0.0))

                    save_resp("6.3", val_salvar, pts_63, lnk_val)
                    res_data["6.3"] = {"valor": val_salvar, "pontos": pts_63, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_63_salva or "")]
                    if lnk_val != evidencia_63_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx63 = lista63.index(v_salvo_63) if v_salvo_63 in lista63 else 0
                    st.radio(
                        "Selecione o status da FAQ:",
                        options=lista63,
                        index=idx63,
                        key=chave_radio_63,
                        on_change=cb_processa_e_salva_63
                    )

                with col2:
                    link_63 = st.text_area(
                        "Link/Evidência (6.3):",
                        value=evidencia_63_salva,
                        key=f"l_63_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_63,
                        placeholder="Insira a URL direta para a página institucional com a base de perguntas frequentes...",
                        height=90
                    )
                    placeholder_links_63 = st.empty()
                    links_63_visuais = [u[0] for u in re.findall(regex_pure_url, link_63 or "")]
                    if links_63_visuais:
                        placeholder_links_63.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_63_visuais]))

                pts_atuais_63 = d63.get("pontos", 0.0)
                cor_txt_63 = "#28a745" if pts_atuais_63 == 10.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_63}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.3: +{pts_atuais_63:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("6.3", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_6_3_{ano_sel}", False):
            modal_aviso_link("6.3", st.session_state.get(f"links_pendentes_6_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_3_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 6.4 • ACESSIBILIDADE DIGITAL DE CONTEÚDO (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_6_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 6.4 - Acessibilidade de Conteúdo para Pessoas com Deficiência", expanded=True):
                st.subheader("6.4 • Acessibilidade Digital")
                st.write("**O site disponibiliza acessibilidade de conteúdo para pessoas com deficiência?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc64 = {
                    "Selecione...": 0.0,
                    "Sim, para todo o conteúdo – 30": 30.0,
                    "Sim, para a maior parte – 15": 15.0,
                    "Sim, para a menor parte – 05": 5.0,
                    "Não – 00": 0.0
                }
                lista64 = list(opc64.keys())

                d64 = res_data.get("6.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d64 is None: d64 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_64 = d64.get("valor", "Selecione...")
                evidencia_64_salva = d64.get("link", "")
                chave_radio_64 = f"r_64_select_{ano_sel}"

                def cb_processa_e_salva_64():
                    lnk_val = st.session_state.get(f"l_64_txt_area_{ano_sel}", evidencia_64_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_64, v_salvo_64)
                    pts_64 = float(opc64.get(val_salvar, 0.0))

                    save_resp("6.4", val_salvar, pts_64, lnk_val)
                    res_data["6.4"] = {"valor": val_salvar, "pontos": pts_64, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_64_salva or "")]
                    if lnk_val != evidencia_64_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx64 = lista64.index(v_salvo_64) if v_salvo_64 in lista64 else 0
                    st.radio(
                        "Selecione o nível de acessibilidade digital implantado:",
                        options=lista64,
                        index=idx64,
                        key=chave_radio_64,
                        on_change=cb_processa_e_salva_64
                    )

                with col2:
                    link_64 = st.text_area(
                        "Link/Evidência (6.4):",
                        value=evidencia_64_salva,
                        key=f"l_64_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_64,
                        placeholder="Insira a URL contendo as ferramentas e atalhos de acessibilidade (Ex: VLibras, Alto Contraste)...",
                        height=110
                    )
                    placeholder_links_64 = st.empty()
                    links_64_visuais = [u[0] for u in re.findall(regex_pure_url, link_64 or "")]
                    if links_64_visuais:
                        placeholder_links_64.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_64_visuais]))

                pts_atuais_64 = d64.get("pontos", 0.0)
                cor_txt_64 = "#28a745" if pts_atuais_64 > 0.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_64}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.4: +{pts_atuais_64:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("6.4", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_6_4_{ano_sel}", False):
            modal_aviso_link("6.4", st.session_state.get(f"links_pendentes_6_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_4_{ano_sel}"] = False

        # --- SEÇÃO 7: e-SIC ---
        st.divider()
        st.header("7.0 Serviço de Informação (e-SIC)")
        
       # =============================================================================
        # QUESITO 7.0 • DISPONIBILIZAÇÃO DO E-SIC (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_7_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 7.0 - Serviço de Informação ao Cidadão (e-SIC)", expanded=True):
                st.subheader("7.0 • Serviço de Informação ao Cidadão (e-SIC)")
                st.write("**A Prefeitura disponibiliza no site o Serviço de Informação ao Cidadão/e-SIC (LF nº 12.527/11)?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc70 = {
                    "Selecione...": 0.0,
                    "Sim – 25": 25.0,
                    "Não – 00": 0.0
                }
                lista70 = list(opc70.keys())

                # Recupera e trata o estado inicial do dicionário com segurança
                d70 = res_data.get("7.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d70 is None: d70 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_70 = d70.get("valor", "Selecione...")
                evidencia_70_salva = d70.get("link", "")
                
                chave_radio_70 = f"r_70_select_{ano_sel}"

                # Callback único que processa todas as alterações de estado do quesito 7.0
                def cb_processa_e_salva_70():
                    lnk_val = st.session_state.get(f"l_70_txt_area_{ano_sel}", evidencia_70_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_70, v_salvo_70)
                    pts_70 = float(opc70.get(val_salvar, 0.0))

                    save_resp("7.0", val_salvar, pts_70, lnk_val)
                    res_data["7.0"] = {"valor": val_salvar, "pontos": pts_70, "link": lnk_val}

                    # Avaliação reativa para o disparo do modal de links novos
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_70_salva or "")]

                    if lnk_val != evidencia_70_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx70 = lista70.index(v_salvo_70) if v_salvo_70 in lista70 else 0
                    st.radio(
                        "Selecione o status do e-SIC:",
                        options=lista70,
                        index=idx70,
                        key=chave_radio_70,
                        on_change=cb_processa_e_salva_70
                    )

                with col2:
                    link_70 = st.text_area(
                        "Link/Evidência (7.0):",
                        value=evidencia_70_salva,
                        key=f"l_70_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_70,
                        placeholder="Insira o link de acesso direto à plataforma do e-SIC do município...",
                        height=90
                    )

                    placeholder_links_70 = st.empty()
                    links_70_visuais = [u[0] for u in re.findall(regex_pure_url, link_70 or "")]
                    if links_70_visuais:
                        placeholder_links_70.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_70_visuais]))

                pts_atuais_70 = d70.get("pontos", 0.0)
                cor_txt_70 = "#28a745" if pts_atuais_70 == 25.0 else "#6c757d"

                st.markdown(f"<span style='color:{cor_txt_70}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.0: +{pts_atuais_70:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("7.0", res_data, ano_sel)

        # GATILHO DO MODAL 7.0
        if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
            modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.1 • SOLICITAÇÃO SIMPLIFICADA NO E-SIC (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_7_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 7.1 - Simplificação de Exigências Cadastrais", expanded=True):
                st.subheader("7.1 • Solicitação Simplificada")
                st.write("**A solicitação por meio do e-SIC é simplificada (sem a exigência de itens de identificação do requerente e demais dados desnecessários à solicitação)?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc71 = {
                    "Selecione...": 0.0,
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0
                }
                lista71 = list(opc71.keys())

                d71 = res_data.get("7.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d71 is None: d71 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_71 = d71.get("valor", "Selecione...")
                if v_salvo_71 == "Sim": v_salvo_71 = "Sim – 10"
                if v_salvo_71 == "Não": v_salvo_71 = "Não – 00"
                evidencia_71_salva = d71.get("link", "")
                chave_radio_71 = f"r_71_select_{ano_sel}"

                def cb_processa_e_salva_71():
                    lnk_val = st.session_state.get(f"l_71_txt_area_{ano_sel}", evidencia_71_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_71, v_salvo_71)
                    pts_71 = float(opc71.get(val_salvar, 0.0))

                    save_resp("7.1", val_salvar, pts_71, lnk_val)
                    res_data["7.1"] = {"valor": val_salvar, "pontos": pts_71, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_71_salva or "")]
                    if lnk_val != evidencia_71_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx71 = lista71.index(v_salvo_71) if v_salvo_71 in lista71 else 0
                    st.radio(
                        "Selecione o status de simplificação do formulário:",
                        options=lista71,
                        index=idx71,
                        key=chave_radio_71,
                        on_change=cb_processa_e_salva_71
                    )

                with col2:
                    link_71 = st.text_area(
                        "Link/Evidência (7.1):",
                        value=evidencia_71_salva,
                        key=f"l_71_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_71,
                        placeholder="Insira o link ou print da tela de cadastro/solicitação demonstrando os campos exigidos...",
                        height=110
                    )
                    placeholder_links_71 = st.empty()
                    links_71_visuais = [u[0] for u in re.findall(regex_pure_url, link_71 or "")]
                    if links_71_visuais:
                        placeholder_links_71.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_71_visuais]))

                pts_atuais_71 = d71.get("pontos", 0.0)
                cor_txt_71 = "#28a745" if pts_atuais_71 == 10.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_71}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.1: +{pts_atuais_71:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("7.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_7_1_{ano_sel}", False):
            modal_aviso_link("7.1", st.session_state.get(f"links_pendentes_7_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.2 • ACOMPANHAMENTO DE SOLICITAÇÃO (100% INDEPENDENTE)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_7_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 7.2 - Mecanismo de Acompanhamento de Pedidos", expanded=True):
                st.subheader("7.2 • Acompanhamento da Solicitação")
                st.write("**O Serviço de Informação ao Cidadão/e-SIC apresentou possibilidade de acompanhamento da solicitação?**")
                st.caption("ℹ *Salvamento automático por eventos com validação reativa de links.*")

                opc72 = {
                    "Selecione...": 0.0,
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0
                }
                lista72 = list(opc72.keys())

                d72 = res_data.get("7.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d72 is None: d72 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_72 = d72.get("valor", "Selecione...")
                if v_salvo_72 == "Sim": v_salvo_72 = "Sim – 10"
                if v_salvo_72 == "Não": v_salvo_72 = "Não – 00"
                evidencia_72_salva = d72.get("link", "")
                chave_radio_72 = f"r_72_select_{ano_sel}"

                def cb_processa_e_salva_72():
                    lnk_val = st.session_state.get(f"l_72_txt_area_{ano_sel}", evidencia_72_salva).strip()
                    val_salvar = st.session_state.get(chave_radio_72, v_salvo_72)
                    pts_72 = float(opc72.get(val_salvar, 0.0))

                    save_resp("7.2", val_salvar, pts_72, lnk_val)
                    res_data["7.2"] = {"valor": val_salvar, "pontos": pts_72, "link": lnk_val}

                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_72_salva or "")]
                    if lnk_val != evidencia_72_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx72 = lista72.index(v_salvo_72) if v_salvo_72 in lista72 else 0
                    st.radio(
                        "Selecione o status do painel de consulta/protocolo:",
                        options=lista72,
                        index=idx72,
                        key=chave_radio_72,
                        on_change=cb_processa_e_salva_72
                    )

                with col2:
                    link_72 = st.text_area(
                        "Link/Evidência (7.2):",
                        value=evidencia_72_salva,
                        key=f"l_72_txt_area_{ano_sel}",
                        on_change=cb_processa_e_salva_72,
                        placeholder="Insira a URL do sistema de consulta de protocolos ou painel de acompanhamento...",
                        height=110
                    )
                    placeholder_links_72 = st.empty()
                    links_72_visuais = [u[0] for u in re.findall(regex_pure_url, link_72 or "")]
                    if links_72_visuais:
                        placeholder_links_72.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_72_visuais]))

                pts_atuais_72 = d72.get("pontos", 0.0)
                cor_txt_72 = "#28a745" if pts_atuais_72 == 10.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_72}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.2: +{pts_atuais_72:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("7.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_7_2_{ano_sel}", False):
            modal_aviso_link("7.2", st.session_state.get(f"links_pendentes_7_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 8.0 • SOFTWARE DE GESTÃO DE PROCESSOS (PADRONIZADO E CORRIGIDO)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_8_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.0 - Softwares para Gestão de Processos", expanded=True):
                        st.subheader("8.0 • Softwares de Gestão")
                        st.write("**A Prefeitura possui programas de computador (softwares) para gestão de processos?**")
                        st.caption("ℹ *Exemplos: Sistema de contabilidade, tributos, dívida ativa, etc. Próprio ou terceirizado.*")

                        opc80 = {
                                "Selecione...": 0.0,
                                "Sim – 40": 40.0,
                                "Não – 00": 0.0
                        }
                        lista80 = list(opc80.keys())

                        d80 = res_data.get("8.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d80 is None: d80 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        # CORREÇÃO ESSENCIAL: Converte "Sim" puro vindo do banco para "Sim – 40"
                        v_salvo_80 = d80.get("valor", "Selecione...")
                        if v_salvo_80 == "Sim": v_salvo_80 = "Sim – 40"
                        if v_salvo_80 == "Não": v_salvo_80 = "Não – 00"
                        
                        evidencia_80_salva = d80.get("link", "")
                        chave_radio_80 = f"r_80_select_{ano_sel}"

                        def cb_processa_e_salva_80():
                                lnk_val = st.session_state.get(f"l_80_txt_area_{ano_sel}", evidencia_80_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_80, v_salvo_80)
                                pts_80 = float(opc80.get(val_salvar, 0.0))

                                save_resp("8.0", val_salvar, pts_80, lnk_val)
                                res_data["8.0"] = {"valor": val_salvar, "pontos": pts_80, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_80_salva or "")]
                                if lnk_val != evidencia_80_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx80 = lista80.index(v_salvo_80) if v_salvo_80 in lista80 else 0
                                st.radio(
                                        "Selecione o status de informatização:",
                                        options=lista80,
                                        index=idx80,
                                        key=chave_radio_80,
                                        on_change=cb_processa_e_salva_80
                                )

                        with col2:
                                link_80 = st.text_area(
                                        "Link/Evidência (8.0):",
                                        value=evidencia_80_salva,
                                        key=f"l_80_txt_area_{ano_sel}",
                                        on_change=cb_processa_e_salva_80,
                                        placeholder="Insira links de portais de sistemas, telas ou contratos públicos dos softwares vigentes...",
                                        height=110
                                )
                                placeholder_links_80 = st.empty()
                                links_80_visuais = [u[0] for u in re.findall(regex_pure_url, link_80 or "")]
                                if links_80_visuais:
                                        placeholder_links_80.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_80_visuais]))

                        # Lógica reativa que lê direto do st.session_state (Igual ao 7.3 que você usa)
                        v_atual_80 = st.session_state.get(chave_radio_80, v_salvo_80)
                        pts_atuais_80 = float(opc80.get(v_atual_80, 0.0))
                                
                        cor_txt_80 = "#28a745" if pts_atuais_80 == 40.0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_80}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.0: +{pts_atuais_80:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_8_0_{ano_sel}", False):
                modal_aviso_link("8.0", st.session_state.get(f"links_pendentes_8_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.1 • PROCESSOS / SETORES ENGLOBADOS (100% INDEPENDENTE E REATIVO)
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_8_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 8.1 - Processos e Setores Englobados pelos Sistemas", expanded=True):
                st.subheader("8.1 • Setores Englobados")
                st.write("**Os programas de computador (softwares) englobam quais processos/setores?**")
                st.caption("ℹ *Salvamento automático por eventos. Marque os setores e inclua os links comprobatórios.*")

                d81 = res_data.get("8.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d81 is None: d81 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    import ast
                    lista_salva_81 = ast.literal_eval(d81.get("valor", "[]"))
                    if not isinstance(lista_salva_81, list): lista_salva_81 = []
                except Exception:
                    lista_salva_81 = []

                evidencia_81_salva = d81.get("link", "")
                chave_link_81 = f"l_81_txt_area_{ano_sel}"

                opcoes_setores = [
                    "Contabilidade", "Gestão de tributos (arrecadação)", "Dívida Ativa", 
                    "Precatórios", "Gestão patrimonial (bens e equipamentos)", 
                    "Gestão de negócios (Business Intelligence)", "Planejamento", 
                    "Recursos humanos / Departamento pessoal", "Almoxarifado", 
                    "Controle de frotas", "Controle Interno", "Saúde", 
                    "Ensino (education)", "Compras, licitações e contratos", 
                    "Certidões e alvarás", "Saneamento", "Cemitérios"
                ]

                # Callback único que sincroniza checkboxes e a área de texto de evidência
                def cb_processa_e_salva_81():
                    sel81_coletado = []
                    for s_nome in opcoes_setores:
                        if st.session_state.get(f"q81_{s_nome}_{ano_sel}", s_nome in lista_salva_81):
                            sel81_coletado.append(s_nome)
                    
                    lnk_val = st.session_state.get(chave_link_81, evidencia_81_salva).strip()
                    string_salvar = str(sel81_coletado)
                    
                    save_resp("8.1", string_salvar, 0.0, lnk_val)
                    res_data["8.1"] = {"valor": string_salvar, "pontos": 0.0, "link": lnk_val}

                    # Avaliação do Modal de Links
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_81_salva or "")]
                    if lnk_val != evidencia_81_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

                col_checks, col_link = st.columns([1.2, 1])
                
                with col_checks:
                    col_setor1, col_setor2 = st.columns(2)
                    for i, setor in enumerate(opcoes_setores):
                        with col_setor1 if i % 2 == 0 else col_setor2:
                            st.checkbox(
                                setor, 
                                value=(setor in lista_salva_81), 
                                key=f"q81_{setor}_{ano_sel}",
                                on_change=cb_processa_e_salva_81
                            )
                
                with col_link:
                    link_81 = st.text_area(
                        "Link/Evidência (8.1):",
                        value=evidencia_81_salva,
                        key=chave_link_81,
                        on_change=cb_processa_e_salva_81,
                        placeholder="Insira links de relatórios ou publicações que comprovem os setores integrados pelos sistemas...",
                        height=160
                    )
                    placeholder_links_81 = st.empty()
                    links_81_visuais = [u[0] for u in re.findall(regex_pure_url, link_81 or "")]
                    if links_81_visuais:
                        placeholder_links_81.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_81_visuais]))
            
                st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.1: +0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("8.1", res_data, ano_sel)

        # GATILHO DO MODAL 8.1
        if st.session_state.get(f"gatilho_modal_8_1_{ano_sel}", False):
            modal_aviso_link("8.1", st.session_state.get(f"links_pendentes_8_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.2 • SISTEMAS INTEGRADOS À CONTABILIDADE
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_8_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.2 - Sistemas Integrados ao Sistema de Contabilidade", expanded=True):
                        st.subheader("8.2 • Integração Contábil")
                        st.write("**Informe quais sistemas encontram-se integrados ao Sistema de Contabilidade do município:**")
                        st.caption("ℹ *Salvamento automático por eventos. Selecione os sistemas e adicione os links comprobatórios.*")

                        d82 = res_data.get("8.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d82 is None: d82 = {"valor": "[]", "pontos": 0.0, "link": ""}
                        
                        try:
                                import ast
                                lista_salva_82 = ast.literal_eval(d82.get("valor", "[]"))
                                if not isinstance(lista_salva_82, list): lista_salva_82 = []
                        except Exception:
                                lista_salva_82 = []

                        evidencia_82_salva = d82.get("link", "")
                        chave_link_82 = f"l_82_txt_area_{ano_sel}"

                        opcoes_integracao = [
                                "Gestão de tributos (arrecadação)", "Dívida Ativa", "Precatórios", 
                                "Gestão patrimonial (bens e equipamentos)", "Gestão de negócios (Business Intelligence)", 
                                "Planejamento", "Recursos humanos / Departamento pessoal", "Almoxarifado", 
                                "Controle de frotas", "Controle Interno", "Saúde", 
                                "Ensino (educação)", "Compras, licitações e contratos", 
                                "Certidões e alvarás", "Saneamento", "Cemitérios"
                        ]

                        def cb_processa_e_salva_82():
                                sel82_coletado = []
                                for s_nome in opcoes_integracao:
                                        if st.session_state.get(f"q82_{s_nome}_{ano_sel}", s_nome in lista_salva_82):
                                                sel82_coletado.append(s_nome)
                                
                                lnk_val = st.session_state.get(chave_link_82, evidencia_82_salva).strip()
                                string_salvar = str(sel82_coletado)
                                
                                save_resp("8.2", string_salvar, 0.0, lnk_val)
                                res_data["8.2"] = {"valor": string_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_82_salva or "")]
                                if lnk_val != evidencia_82_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

                        col_checks, col_link = st.columns([1.2, 1])
                        
                        with col_checks:
                                col_int1, col_int2 = st.columns(2)
                                for i, sistema in enumerate(opcoes_integracao):
                                        with col_int1 if i % 2 == 0 else col_int2:
                                                st.checkbox(
                                                        sistema, 
                                                        value=(sistema in lista_salva_82), 
                                                        key=f"q82_{sistema}_{ano_sel}",
                                                        on_change=cb_processa_e_salva_82
                                                )
                        
                        with col_link:
                                link_82 = st.text_area(
                                        "Link/Evidência (8.2):",
                                        value=evidencia_82_salva,
                                        key=chave_link_82,
                                        on_change=cb_processa_e_salva_82,
                                        placeholder="Insira links de termos, manuais ou relatórios técnicos...",
                                        height=160
                                )
                                placeholder_links_82 = st.empty()
                                links_82_visuais = [u[0] for u in re.findall(regex_pure_url, link_82 or "")]
                                if links_82_visuais:
                                        placeholder_links_82.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_82_visuais]))
                        
                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.2: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.2", res_data, ano_sel)

        # =============================================================================
        # QUESITO 8.2.1 • INTEGRAÇÃO DÍVIDA ATIVA
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_8_2_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.2.1 - Integração Dívida Ativa", expanded=True):
                        st.subheader("8.2.1 • Integração Dívida Ativa")
                        st.write("**Informe o nível de integração entre o Sistema da Dívida Ativa e o de Contabilidade:**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc821 = {
                                "Selecione...": 0.0,
                                "Totalmente integrado (Inscrição / Atualização e Baixa) – 50": 50.0,
                                "Somente as Inscrições / Atualizações estão integrados – 10": 10.0,
                                "Somente as Baixas estão integradas – 10": 10.0
                        }
                        lista821 = list(opc821.keys())

                        d821 = res_data.get("8.2.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d821 is None: d821 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_821 = d821.get("valor", "Selecione...")
                        if v_salvo_821 and "Totalmente" in str(v_salvo_821): v_salvo_821 = "Totalmente integrado (Inscrição / Atualização e Baixa) – 50"
                        elif v_salvo_821 and "Inscrições" in str(v_salvo_821): v_salvo_821 = "Somente as Inscrições / Atualizações estão integrados – 10"
                        elif v_salvo_821 and "Baixas" in str(v_salvo_821): v_salvo_821 = "Somente as Baixas estão integradas – 10"
                        else: v_salvo_821 = "Selecione..."
                        
                        evidencia_821_salva = d821.get("link", "")
                        chave_radio_821 = f"r_821_select_{ano_sel}"

                        def cb_processa_e_salva_821():
                                lnk_val = st.session_state.get(f"l_821_txt_area_{ano_sel}", evidencia_821_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_821, v_salvo_821)
                                pts_821 = float(opc821.get(val_salvar, 0.0))

                                save_resp("8.2.1", val_salvar, pts_821, lnk_val)
                                res_data["8.2.1"] = {"valor": val_salvar, "pontos": pts_821, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_821_salva or "")]
                                if lnk_val != evidencia_821_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_2_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_2_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx821 = lista821.index(v_salvo_821) if v_salvo_821 in lista821 else 0
                                st.radio(
                                        "Selecione o nível de integração:",
                                        options=lista821,
                                        index=idx821,
                                        key=chave_radio_821,
                                        on_change=cb_processa_e_salva_821
                                )

                        with col2:
                                link_821 = st.text_area(
                                        "Link/Evidência (8.2.1):",
                                        value=evidencia_821_salva,
                                        key=f"l_821_txt_area_{ano_sel}",
                                        on_change=cb_processa_e_salva_821,
                                        placeholder="Insira links de relatórios, telas de integração...",
                                        height=110
                                )
                                placeholder_links_821 = st.empty()
                                links_821_visuais = [u[0] for u in re.findall(regex_pure_url, link_821 or "")]
                                if links_821_visuais:
                                        placeholder_links_821.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_821_visuais]))

                        v_atual_821 = st.session_state.get(chave_radio_821, v_salvo_821)
                        pts_atuais_821 = float(opc821.get(v_atual_821, 0.0))
                                
                        cor_txt_821 = "#28a745" if pts_atuais_821 == 50.0 else ("#17a2b8" if pts_atuais_821 == 10.0 else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_821}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.2.1: +{pts_atuais_821:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.2.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 8.2.2 • INTEGRAÇÃO PRECATÓRIOS
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_8_2_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.2.2 - Integração Precatórios", expanded=True):
                        st.subheader("8.2.2 • Integração Precatórios")
                        st.write("**Informe o nível de integração entre o Sistema de Precatórios e o de Contabilidade:**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc822 = {
                                "Selecione...": 0.0,
                                "Totalmente integrado (Provisão e Baixa) – 30": 30.0,
                                "Somente as Provisões estão integradas – 05": 5.0,
                                "Somente as Baixas estão integradas – 05": 5.0
                        }
                        lista822 = list(opc822.keys())

                        d822 = res_data.get("8.2.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d822 is None: d822 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_822 = d822.get("valor", "Selecione...")
                        if v_salvo_822 and "Totalmente" in str(v_salvo_822): v_salvo_822 = "Totalmente integrado (Provisão e Baixa) – 30"
                        elif v_salvo_822 and "Provisões" in str(v_salvo_822): v_salvo_822 = "Somente as Provisões estão integradas – 05"
                        elif v_salvo_822 and "Baixas" in str(v_salvo_822): v_salvo_822 = "Somente as Baixas estão integradas – 05"
                        else: v_salvo_822 = "Selecione..."
                        
                        evidencia_822_salva = d822.get("link", "")
                        chave_radio_822 = f"r_822_select_{ano_sel}"

                        def cb_processa_e_salva_822():
                                lnk_val = st.session_state.get(f"l_822_txt_area_{ano_sel}", evidencia_822_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_822, v_salvo_822)
                                pts_822 = float(opc822.get(val_salvar, 0.0))

                                save_resp("8.2.2", val_salvar, pts_822, lnk_val)
                                res_data["8.2.2"] = {"valor": val_salvar, "pontos": pts_822, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_822_salva or "")]
                                if lnk_val != evidencia_822_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_2_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_2_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx822 = lista822.index(v_salvo_822) if v_salvo_822 in lista822 else 0
                                st.radio(
                                        "Selecione o nível de integração:",
                                        options=lista822,
                                        index=idx822,
                                        key=chave_radio_822,
                                        on_change=cb_processa_e_salva_822
                                )

                        with col2:
                                link_822 = st.text_area(
                                        "Link/Evidência (8.2.2):",
                                        value=evidencia_822_salva,
                                        key=f"l_822_txt_area_{ano_sel}",
                                        on_change=cb_processa_e_salva_822,
                                        placeholder="Insira links de relatórios judiciais, telas...",
                                        height=110
                                )
                                placeholder_links_822 = st.empty()
                                links_822_visuais = [u[0] for u in re.findall(regex_pure_url, link_822 or "")]
                                if links_822_visuais:
                                        placeholder_links_822.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_822_visuais]))

                        v_atual_822 = st.session_state.get(chave_radio_822, v_salvo_822)
                        pts_atuais_822 = float(opc822.get(v_atual_822, 0.0))
                                
                        cor_txt_822 = "#28a745" if pts_atuais_822 == 30.0 else ("#17a2b8" if pts_atuais_822 == 5.0 else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_822}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.2.2: +{pts_atuais_822:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.2.2", res_data, ano_sel)

        # =============================================================================
        # QUESITO 8.3 • GESTÃO DIRETA DE BASES DE DADOS
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_8_3_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.3 - Gestão Direta de Bases de Dados", expanded=True):
                        st.subheader("8.3 • Gestão Direta de Bases de Dados")
                        st.write("**Assinale quais bases de dados encontram-se sob gestão direta da Prefeitura:**")
                        st.caption("ℹ *Gestão Direta = empresa terceira não pode mudar os dados sem o conhecimento da Prefeitura. Salvamento automático.*")

                        opcoes_bases = [
                                "Contabilidade", "Gestão de tributos (arrecadação)", "Dívida Ativa", 
                                "Precatórios", "Gestão patrimonial (bens e equipamentos)", 
                                "Gestão de negócios (Business Intelligence)", "Planejamento", 
                                "Recursos humanos / Departamento pessoal", "Almoxarifado", 
                                "Controle de frotas", "Controle Interno", "Saúde", 
                                "Ensino (educação)", "Compras, licitações e contratos", 
                                "Certidões e alvarás", "Saneamento", "Cemitérios"
                        ]

                        d83 = res_data.get("8.3", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d83 is None: d83 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        val_83_banco = d83.get("valor", "[]")
                        if isinstance(val_83_banco, str):
                                if val_83_banco.strip() in ["", "[]", "None"]:
                                        lista_salva_83 = []
                                else:
                                        try:
                                                import json
                                                lista_salva_83 = json.loads(val_83_banco.replace("'", '"'))
                                        except Exception:
                                                try:
                                                        import ast
                                                        lista_salva_83 = ast.literal_eval(val_83_banco)
                                                except Exception:
                                                        lista_salva_83 = []
                        else:
                                lista_salva_83 = list(val_83_banco)

                        evidencia_83_salva = d83.get("link", "")
                        chave_link_83 = f"l_83_txt_area_{ano_sel}"

                        def cb_processa_e_salva_83():
                                lnk_val = st.session_state.get(chave_link_83, evidencia_83_salva).strip()
                                
                                sel83_atual = []
                                for base in opcoes_bases:
                                        if st.session_state.get(f"ck_83_{base}_{ano_sel}", base in lista_salva_83):
                                                sel83_atual.append(base)
                                sel83_atual = sorted(sel83_atual)

                                v_80_cb = st.session_state.get(f"r_80_select_{ano_sel}", res_data.get("8.0", {}).get("valor", ""))
                                de_penalidade_cb = (v_80_cb and "Sim" in str(v_80_cb))

                                if de_penalidade_cb:
                                        pts_83 = -51.0 + (len(sel83_atual) * 3.0)
                                        if pts_83 > 0.0: pts_83 = 0.0
                                else:
                                        pts_83 = 0.0

                                save_resp("8.3", str(sel83_atual), pts_83, lnk_val)
                                res_data["8.3"] = {"valor": str(sel83_atual), "pontos": pts_83, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_83_salva or "")]
                                if lnk_val != evidencia_83_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_3_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_3_{ano_sel}"] = True

                        sel83 = []
                        col_base1, col_base2 = st.columns(2)
                        for i, base in enumerate(opcoes_bases):
                                with col_base1 if i % 2 == 0 else col_base2:
                                        esta_marcado = base in lista_salva_83
                                        if st.checkbox(
                                                base, 
                                                value=esta_marcado, 
                                                key=f"ck_83_{base}_{ano_sel}",
                                                on_change=cb_processa_e_salva_83
                                        ):
                                                sel83.append(base)
                        sel83 = sorted(sel83)

                        st.markdown("<br>", unsafe_allow_html=True)
                        link_83 = st.text_area(
                                "Link/Evidência (8.3):",
                                value=evidencia_83_salva,
                                key=chave_link_83,
                                on_change=cb_processa_e_salva_83,
                                placeholder="Insira links de termos de auditoria, declarações de TI...",
                                height=90
                        )
                        placeholder_links_83 = st.empty()
                        links_83_visuais = [u[0] for u in re.findall(regex_pure_url, link_83 or "")]
                        if links_83_visuais:
                                placeholder_links_83.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_83_visuais]))

                        v_80_tela = st.session_state.get(f"r_80_select_{ano_sel}", res_data.get("8.0", {}).get("valor", ""))
                        deve_aplicar_penalidade = (v_80_tela and "Sim" in str(v_80_tela))

                        if deve_aplicar_penalidade:
                                pontos_finais_83 = -51.0 + (len(sel83) * 3.0)
                                if pontos_finais_83 > 0.0: pontos_finais_83 = 0.0
                                
                                if pontos_finais_83 < 0.0:
                                        st.warning(f"⚠️ Penalidade aplicada: {pontos_finais_83:.1f} pontos")
                                else:
                                        st.success("✅ Nenhuma penalidade aplicada (Todos os itens preenchidos)!")
                        else:
                                pontos_finais_83 = 0.0
                                st.success("✅ Nenhuma penalidade aplicada (Quesito 8.0 é Não)!")

                        cor_txt_83 = "#28a745" if pontos_finais_83 == 0.0 else "#dc3545"
                        st.markdown(f"<span style='color:{cor_txt_83}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.3: {pontos_finais_83:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.3", res_data, ano_sel)

        # =============================================================================
        # QUESITO 8.4 • CONTROLE DE ACESSO À INFORMAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_compdec_8_4_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4 - Controle de Acesso à Informação", expanded=True):
                        st.subheader("8.4 • Controle de Acesso à Informação")
                        st.write("**Assinale quais sistemas possuem controle de acesso à informação:**")
                        st.caption("ℹ *Controle relativo a histórico, níveis de acesso e logs de eventos. Salvamento automático.*")

                        opcoes_sistemas = [
                                "Contabilidade", "Gestão de tributos (arrecadação)", "Dívida Ativa", 
                                "Precatórios", "Gestão patrimonial (bens e equipamentos)", 
                                "Gestão de negócios (Business Intelligence)", "Planejamento", 
                                "Recursos humanos / Departamento pessoal", "Almoxarifado", 
                                "Controle de frotas", "Controle Interno", "Saúde", 
                                "Ensino (educação)", "Compras, licitações e contratos", 
                                "Certidões e alvarás", "Saneamento", "Cemitérios"
                        ]

                        d84 = res_data.get("8.4", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d84 is None: d84 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        val_84_banco = d84.get("valor", "[]")
                        if isinstance(val_84_banco, str):
                                if val_84_banco.strip() in ["", "[]", "None"]:
                                        lista_salva_84 = []
                                else:
                                        try:
                                                import json
                                                lista_salva_84 = json.loads(val_84_banco.replace("'", '"'))
                                        except Exception:
                                                try:
                                                        import ast
                                                        lista_salva_84 = ast.literal_eval(val_84_banco)
                                                except Exception:
                                                        lista_salva_84 = []
                        else:
                                lista_salva_84 = list(val_84_banco)

                        evidencia_84_salva = d84.get("link", "")
                        chave_link_84 = f"l_84_txt_area_{ano_sel}"

                        def cb_processa_e_salva_84():
                                lnk_val = st.session_state.get(chave_link_84, evidencia_84_salva).strip()
                                
                                sel84_atual = []
                                for sistema in opcoes_sistemas:
                                        if st.session_state.get(f"ck_84_{sistema}_{ano_sel}", sistema in lista_salva_84):
                                                sel84_atual.append(sistema)
                                sel84_atual = sorted(sel84_atual)

                                v_80_cb = st.session_state.get(f"r_80_select_{ano_sel}", res_data.get("8.0", {}).get("valor", ""))
                                de_penalidade_cb = (v_80_cb and "Sim" in str(v_80_cb))

                                if de_penalidade_cb:
                                        pts_84 = -51.0 + (len(sel84_atual) * 3.0)
                                        if pts_84 > 0.0: pts_84 = 0.0
                                else:
                                        pts_84 = 0.0

                                save_resp("8.4", str(sel84_atual), pts_84, lnk_val)
                                res_data["8.4"] = {"valor": str(sel84_atual), "pontos": pts_84, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_84_salva or "")]
                                if lnk_val != evidencia_84_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_4_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_4_{ano_sel}"] = True

                        sel84 = []
                        col_sis1, col_sis2 = st.columns(2)
                        for i, sistema in enumerate(opcoes_sistemas):
                                with col_sis1 if i % 2 == 0 else col_sis2:
                                        esta_marcado = sistema in lista_salva_84
                                        if st.checkbox(
                                                sistema, 
                                                value=esta_marcado, 
                                                key=f"ck_84_{sistema}_{ano_sel}",
                                                on_change=cb_processa_e_salva_84
                                        ):
                                                sel84.append(sistema)
                        sel84 = sorted(sel84)

                        st.markdown("<br>", unsafe_allow_html=True)
                        link_84 = st.text_area(
                                "Link/Evidência (8.4):",
                                value=evidencia_84_salva,
                                key=chave_link_84,
                                on_change=cb_processa_e_salva_84,
                                placeholder="Insira links de manuais de segurança, políticas de senhas...",
                                height=90
                        )
                        placeholder_links_84 = st.empty()
                        links_84_visuais = [u[0] for u in re.findall(regex_pure_url, link_84 or "")]
                        if links_84_visuais:
                                placeholder_links_84.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_84_visuais]))

                        v_80_tela = st.session_state.get(f"r_80_select_{ano_sel}", res_data.get("8.0", {}).get("valor", ""))
                        deve_aplicar_penalidade = (v_80_tela and "Sim" in str(v_80_tela))

                        if deve_aplicar_penalidade:
                                pontos_finais_84 = -51.0 + (len(sel84) * 3.0)
                                if pontos_finais_84 > 0.0: pontos_finais_84 = 0.0
                                
                                if pontos_finais_84 < 0.0:
                                        st.warning(f"⚠️ Penalidade aplicada: {pontos_finais_84:.1f} pontos")
                                else:
                                        st.success("✅ Nenhuma penalidade aplicada (Todos os itens preenchidos)!")
                        else:
                                pontos_finais_84 = 0.0
                                st.success("✅ Nenhuma penalidade aplicada (Quesito 8.0 é Não)!")

                        cor_txt_84 = "#28a745" if pontos_finais_84 == 0.0 else "#dc3545"
                        st.markdown(f"<span style='color:{cor_txt_84}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.4: {pontos_finais_84:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4", res_data, ano_sel)

        # =============================================================================
        # CONTROLADOR CENTRAL DE MODAIS DE AVISO (EVITA ERRO DUPLICATE ELEMENT ID)
        # =============================================================================
        lista_quesitos_modais = ["8.2", "8.2.1", "8.2.2", "8.3", "8.4"]
        for q_id in lista_quesitos_modais:
                chave_limpa = q_id.replace('.', '_')
                if st.session_state.get(f"gatilho_modal_{chave_limpa}_{ano_sel}", False):
                        modal_aviso_link(q_id, st.session_state.get(f"links_pendentes_{chave_limpa}_{ano_sel}", []))
                        st.session_state[f"gatilho_modal_{chave_limpa}_{ano_sel}"] = False
        
# =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (QUESITOS 9.0, 9.1 e 9.2)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_9_0_{ano_sel}", False):
                modal_aviso_link("9.0", st.session_state.get(f"links_pendentes_9_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_9_1_{ano_sel}", False):
                modal_aviso_link("9.1", st.session_state.get(f"links_pendentes_9_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_9_2_{ano_sel}", False):
                modal_aviso_link("9.2", st.session_state.get(f"links_pendentes_9_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 9.0 • SERVIÇOS ONLINE
        # =============================================================================
        with st.container(key=f"container_bloco_serv_9_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.0 - Serviços Oferecidos de Forma Online", expanded=True):
                        st.subheader("9.0 • Serviços Online")
                        st.write("**A Prefeitura ofereceu serviços de forma online?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc90 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        lista90 = list(opc90.keys())

                        d90 = res_data.get("9.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d90 is None: d90 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_90 = d90.get("valor", "Selecione...")
                        if v_salvo_90 and "Sim" in str(v_salvo_90): v_salvo_90 = "Sim"
                        elif v_salvo_90 and "Não" in str(v_salvo_90): v_salvo_90 = "Não"
                        else: v_salvo_90 = "Selecione..."
                        
                        evidencia_90_salva = d90.get("link", "")
                        chave_radio_90 = f"r_90_select_{ano_sel}"
                        chave_link_90 = f"l_90_txt_area_{ano_sel}"

                        def cb_processa_e_salva_90():
                                lnk_val = st.session_state.get(chave_link_90, evidencia_90_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_90, v_salvo_90)
                                pts_90 = float(opc90.get(val_salvar, 0.0))

                                save_resp("9.0", val_salvar, pts_90, lnk_val)
                                res_data["9.0"] = {"valor": val_salvar, "pontos": pts_90, "link": lnk_val}

                                # MODAL AUTOMÁTICO CORRIGIDO (Gatilho idêntico ao 8.2.1)
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_90_salva or "")]
                                if lnk_val != evidencia_90_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx90 = lista90.index(v_salvo_90) if v_salvo_90 in lista90 else 0
                                st.radio(
                                        "Selecione uma opção:",
                                        options=lista90,
                                        index=idx90,
                                        key=chave_radio_90,
                                        on_change=cb_processa_e_salva_90
                                )

                        with col2:
                                link_90 = st.text_area(
                                        "Link/Evidência (9.0):",
                                        value=evidencia_90_salva,
                                        key=chave_link_90,
                                        on_change=cb_processa_e_salva_90,
                                        placeholder="Insira o link principal que comprova o portal de serviços...",
                                        height=110
                                )
                                placeholder_links_90 = st.empty()
                                links_90_visuais = [u[0] for u in re.findall(regex_pure_url, link_90 or "")]
                                if links_90_visuais:
                                        placeholder_links_90.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_90_visuais]))

                        # Resgate do valor atual do state para renderização de cor idêntica ao 8.2.1
                        v_atual_90 = st.session_state.get(chave_radio_90, v_salvo_90)
                        cor_txt_90 = "#28a745" if v_atual_90 == "Sim" else ("#dc3545" if v_atual_90 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_90}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 9.0: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.0", res_data, ano_sel)


        # =============================================================================
        # QUESITO 9.1 • DETALHAMENTO DE SERVIÇOS DIGITAIS
        # =============================================================================
        with st.container(key=f"container_bloco_serv_9_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.1 - Tipos de Serviços Oferecidos Digitalmente", expanded=True):
                        st.subheader("9.1 • Detalhamento de Serviços")
                        st.write("**Quais tipos de serviços são oferecidos de forma digital?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        d91 = res_data.get("9.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d91 is None: d91 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_91 = ast.literal_eval(d91.get("valor", "[]"))
                                if not isinstance(lista_salva_91, list): lista_salva_91 = []
                        except Exception:
                                lista_salva_91 = []

                        evidencia_91_salva = d91.get("link", "")
                        chave_link_91 = f"l_91_txt_area_{ano_sel}"

                        opcoes_servicos = [
                                "Alvarás / licenças de funcionamento", "Certidões", "Licenças / autorizações", 
                                "Ouvidoria", "Consulta de débitos municipais", "Emissão de guias/boletos dos débitos municipais", 
                                "Solicitação de serviços de zeladoria", "Solicitação de obras e serviços de urbanização", 
                                "Inscrições em oficinas, cursos, eventos e vagas", "Nota fiscal eletrônica", 
                                "Canal de denúncias", "Cadastro de fornecedores", 
                                "Agendamento de cookies na rede pública de saúde", 
                                "Agendamento de exames em relação a doenças crônicas na rede pública de saúde", 
                                "Pesquisa de satisfação em relação aos serviços prestados pela Prefeitura", 
                                "Consulta a status de protocolos de todos os atendimentos dos serviços assinalados acima"
                        ]

                        def cb_processa_e_salva_91():
                                sel91_coletado = []
                                for s_nome in opcoes_servicos:
                                        if st.session_state.get(f"q91_{s_nome}_{ano_sel}", s_nome in lista_salva_91):
                                                sel91_coletado.append(s_nome)
                                
                                lnk_val = st.session_state.get(chave_link_91, evidencia_91_salva).strip()
                                pts_91 = float(len(sel91_coletado) * 7.5)
                                string_salvar = str(sorted(sel91_coletado))
                                
                                save_resp("9.1", string_salvar, pts_91, lnk_val)
                                res_data["9.1"] = {"valor": string_salvar, "pontos": pts_91, "link": lnk_val}

                                # MODAL AUTOMÁTICO DO 9.1
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_91_salva or "")]
                                if lnk_val != evidencia_91_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_9_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                col_serv1, col_serv2 = st.columns(2)
                                for i, servico in enumerate(opcoes_servicos):
                                        with col_serv1 if i % 2 == 0 else col_serv2:
                                                st.checkbox(
                                                        f"{servico} (+7,5 pts)",
                                                        value=(servico in lista_salva_91),
                                                        key=f"q91_{servico}_{ano_sel}",
                                                        on_change=cb_processa_e_salva_91
                                                )

                        with col2:
                                link_91 = st.text_area(
                                        "Link/Evidência (9.1):",
                                        value=evidencia_91_salva,
                                        key=chave_link_91,
                                        on_change=cb_processa_e_salva_91,
                                        placeholder="Insira links comprobatórios das telas ou portais de serviços...",
                                        height=220
                                )
                                placeholder_links_91 = st.empty()
                                links_91_visuais = [u[0] for u in re.findall(regex_pure_url, link_91 or "")]
                                if links_91_visuais:
                                        placeholder_links_91.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_91_visuais]))

                        sel91_atual = []
                        for s_nome in opcoes_servicos:
                                if st.session_state.get(f"q91_{s_nome}_{ano_sel}", s_nome in lista_salva_91):
                                        sel91_atual.append(s_nome)
                        pts_atuais_91 = float(len(sel91_atual) * 7.5)
                        
                        teto_maximo = 120.0
                        st.progress(min(pts_atuais_91 / teto_maximo, 1.0))
                        
                        cor_txt_91 = "#28a745" if pts_atuais_91 > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_91}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 9.1: +{pts_atuais_91:.1f} / {teto_maximo:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 9.2 • FORMAS DE ATENDIMENTO À DISTÂNCIA
        # =============================================================================
        with st.container(key=f"container_bloco_serv_9_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.2 - Formas de Atendimento à Distância", expanded=True):
                        st.subheader("9.2 • Atendimento à Distância")
                        st.write("**Quais as formas de atendimento à distância disponibilizadas ao público pela Prefeitura?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        d92 = res_data.get("9.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d92 is None: d92 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_92 = ast.literal_eval(d92.get("valor", "[]"))
                                if not isinstance(lista_salva_92, list): lista_salva_92 = []
                        except Exception:
                                lista_salva_92 = []

                        evidencia_92_salva = d92.get("link", "")
                        chave_link_92 = f"l_92_txt_area_{ano_sel}"

                        opcoes_atendimento = [
                                "Telefone", "Site da Prefeitura", "Aplicativo de mensagens", 
                                "Redes sociais", "Aplicativo da Prefeitura", "Correio eletrônico (e-mail)", 
                                "Outros"
                        ]

                        def cb_processa_e_salva_92():
                                sel92_coletado = []
                                for forma_nome in opcoes_atendimento:
                                        if st.session_state.get(f"q92_{forma_nome}_{ano_sel}", forma_nome in lista_salva_92):
                                                sel92_coletado.append(forma_nome)
                                
                                lnk_val = st.session_state.get(chave_link_92, evidencia_92_salva).strip()
                                string_salvar = str(sorted(sel92_coletado))
                                
                                save_resp("9.2", string_salvar, 0.0, lnk_val)
                                res_data["9.2"] = {"valor": string_salvar, "pontos": 0.0, "link": lnk_val}

                                # MODAL AUTOMÁTICO DO 9.2
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_92_salva or "")]
                                if lnk_val != evidencia_92_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_9_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                col_atend1, col_atend2 = st.columns(2)
                                for i, forma in enumerate(opcoes_atendimento):
                                        with col_atend1 if i % 2 == 0 else col_atend2:
                                                st.checkbox(
                                                        forma,
                                                        value=(forma in lista_salva_92),
                                                        key=f"q92_{forma}_{ano_sel}",
                                                        on_change=cb_processa_e_salva_92
                                                )

                        with col2:
                                link_92 = st.text_area(
                                        "Link/Evidência (9.2):",
                                        value=evidencia_92_salva,
                                        key=chave_link_92,
                                        on_change=cb_processa_e_salva_92,
                                        placeholder="Insira links comprobatórios dos canais de atendimento à distância...",
                                        height=110
                                )
                                placeholder_links_92 = st.empty()
                                links_92_visuais = [u[0] for u in re.findall(regex_pure_url, link_92 or "")]
                                if links_92_visuais:
                                        placeholder_links_92.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_92_visuais]))

                        sel92_atual = []
                        for forma_nome in opcoes_atendimento:
                                if st.session_state.get(f"q92_{forma_nome}_{ano_sel}", forma_nome in lista_salva_92):
                                        sel92_atual.append(forma_nome)
                        
                        cor_txt_92 = "#28a745" if len(sel92_atual) > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_92}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 9.2: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.2", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (BLOCO 10 - LGPD)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_10_0_{ano_sel}", False):
                modal_aviso_link("10.0", st.session_state.get(f"links_pendentes_10_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_10_4_{ano_sel}", False):
                modal_aviso_link("10.4", st.session_state.get(f"links_pendentes_10_4_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_4_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_10_5_{ano_sel}", False):
                modal_aviso_link("10.5", st.session_state.get(f"links_pendentes_10_5_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_5_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 10.0 • REGULAMENTAÇÃO DA LGPD
        # =============================================================================
        with st.container(key=f"container_bloco_lgpd_10_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.0 - Regulamentação da LGPD", expanded=True):
                        st.subheader("10.0 • Regulamentação da LGPD")
                        st.write("**A Prefeitura Municipal regulamentou o tratamento de dados pessoais, inclusive nos meios digitais, segundo a LGPD (Lei Federal nº 13.709, de 14 de agosto de 2018)?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        lista100 = ["Selecione...", "Sim", "Não"]
                        d100 = res_data.get("10.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d100 is None: d100 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_100 = d100.get("valor", "Selecione...")
                        if v_salvo_100 not in lista100: v_salvo_100 = "Selecione..."
                        
                        evidencia_100_salva = d100.get("link", "")
                        chave_radio_100 = f"r_100_select_{ano_sel}"
                        chave_link_100 = f"l_100_txt_area_{ano_sel}"

                        def cb_processa_e_salva_100():
                                lnk_val = st.session_state.get(chave_link_100, evidencia_100_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_100, v_salvo_100)
                                
                                save_resp("10.0", val_salvar, 0.0, lnk_val)
                                res_data["10.0"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_100_salva or "")]
                                if lnk_val != evidencia_100_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx100 = lista100.index(v_salvo_100)
                                st.radio(
                                        "Selecione uma opção (10.0):",
                                        options=lista100,
                                        index=idx100,
                                        key=chave_radio_100,
                                        on_change=cb_processa_e_salva_100
                                )

                        with col2:
                                link_100 = st.text_area(
                                        "Link/Evidência (10.0):",
                                        value=evidencia_100_salva,
                                        key=chave_link_100,
                                        on_change=cb_processa_e_salva_100,
                                        placeholder="Insira o link principal que comprova a regulamentação...",
                                        height=110
                                )
                                placeholder_links_100 = st.empty()
                                links_100_visuais = [u[0] for u in re.findall(regex_pure_url, link_100 or "")]
                                if links_100_visuais:
                                        placeholder_links_100.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_100_visuais]))

                        v_atual_100 = st.session_state.get(chave_radio_100, v_salvo_100)
                        cor_txt_100 = "#28a745" if v_atual_100 == "Sim" else ("#dc3545" if v_atual_100 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_100}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.0: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.0", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.1 • DETALHES DO INSTRUMENTO NORMATIVO
        # =============================================================================
        with st.container(key=f"container_bloco_lgpd_10_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.1 - Dados do Instrumento Normativo", expanded=True):
                        st.subheader("10.1 • Dados da Regulamentação")
                        st.write("**Informe o Instrumento normativo, Número e Data da publicação:**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        d101 = res_data.get("10.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if d101 is None: d101 = {"valor": "", "pontos": 0.0, "link": ""}

                        v_salvo_101 = d101.get("valor", "")
                        chave_txt_101 = f"t_101_txt_area_{ano_sel}"

                        def cb_processa_e_salva_101():
                                val_salvar = st.session_state.get(chave_txt_101, v_salvo_101).strip()
                                save_resp("10.1", val_salvar, 0.0, "")
                                res_data["10.1"] = {"valor": val_salvar, "pontos": 0.0, "link": ""}

                        st.text_area(
                                "Informe os dados aqui (Tipo, Número e Data):",
                                value=v_salvo_101,
                                key=chave_txt_101,
                                on_change=cb_processa_e_salva_101,
                                placeholder="Exemplo: Decreto Municipal nº 1.234, publicado em DD/MM/AAAA",
                                height=110
                        )

                        v_atual_101 = st.session_state.get(chave_txt_101, v_salvo_101)
                        cor_txt_101 = "#28a745" if len(v_atual_101.strip()) > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_101}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.1: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.2 • PÁGINA ELETRÔNICA DA NORMA
        # =============================================================================
        with st.container(key=f"container_bloco_lgpd_10_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.2 - Link da Página Eletrônica", expanded=True):
                        st.subheader("10.2 • Link do Instrumento Normativo")
                        st.write("**Informe a página eletrônica (link na internet):**")
                        st.markdown("<small style='color:gray;'>Se não estiver disponível na internet, inserir no campo de resposta o texto <b>XYZ</b></small>", unsafe_allow_html=True)
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        d102 = res_data.get("10.2", {"valor": "", "pontos": 0.0, "link": ""})
                        if d102 is None: d102 = {"valor": "", "pontos": 0.0, "link": ""}

                        v_salvo_102 = d102.get("valor", "")
                        chave_txt_102 = f"t_102_txt_input_{ano_sel}"

                        def cb_processa_e_salva_102():
                                val_salvar = st.session_state.get(chave_txt_102, v_salvo_102).strip()
                                save_resp("10.2", val_salvar, 0.0, "")
                                res_data["10.2"] = {"valor": val_salvar, "pontos": 0.0, "link": ""}

                        link_input_102 = st.text_input(
                                "Link ou texto de contingência (XYZ):",
                                value=v_salvo_102,
                                key=chave_txt_102,
                                on_change=cb_processa_e_salva_102,
                                placeholder="Cole o link completo da publicação ou digite XYZ"
                        )

                        placeholder_links_102 = st.empty()
                        links_102_visuais = [u[0] for u in re.findall(regex_pure_url, link_input_102 or "")]
                        if links_102_visuais:
                                placeholder_links_102.markdown(f"**🔗 Link ativo detectado:** " + " | ".join([f"[{u}]({u})" for u in links_102_visuais]))

                        v_atual_102 = st.session_state.get(chave_txt_102, v_salvo_102)
                        cor_txt_102 = "#28a745" if len(v_atual_102.strip()) > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_102}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.2: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.2", res_data, ano_sel)


        # =============================================================================
        # GATILHO DO MODAL AUTOMÁTICO DO QUESITO 10.3 (Colocar no topo do script)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_10_3_{ano_sel}", False):
                modal_aviso_link("10.3", st.session_state.get(f"links_pendentes_10_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_3_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 10.3 • CLÁUSULAS CONTRATUAIS (LGPD)
        # =============================================================================
        with st.container(key=f"container_bloco_lgpd_10_3_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.3 - Cláusulas de Contratos Vigentes", expanded=True):
                        st.subheader("10.3 • Cláusulas Contratuais")
                        st.write("**Os contratos com os prestadores de serviços contêm cláusulas de observância à LGPD?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        lista103 = [
                                "Selecione...",
                                "Todos os contratos vigentes",
                                "A maior parte dos contratos vigentes",
                                "A menor parte dos contratos vigentes",
                                "Não"
                        ]

                        d103 = res_data.get("10.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d103 is None: d103 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_103 = d103.get("valor", "Selecione...")
                        if v_salvo_103 not in lista103: v_salvo_103 = "Selecione..."

                        evidencia_103_salva = d103.get("link", "")
                        chave_radio_103 = f"r_103_select_{ano_sel}"
                        chave_link_103 = f"l_103_txt_area_{ano_sel}"

                        def cb_processa_e_salva_103():
                                lnk_val = st.session_state.get(chave_link_103, evidencia_103_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_103, v_salvo_103)
                                
                                save_resp("10.3", val_salvar, 0.0, lnk_val)
                                res_data["10.3"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                # Ativação do modal de aviso para novos links detectados
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_103_salva or "")]
                                if lnk_val != evidencia_103_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_10_3_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_10_3_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx103 = lista103.index(v_salvo_103)
                                st.radio(
                                        "Selecione a abrangência nos contratos:",
                                        options=lista103,
                                        index=idx103,
                                        key=chave_radio_103,
                                        on_change=cb_processa_e_salva_103
                                )

                        with col2:
                                link_103 = st.text_area(
                                        "Link/Evidência (10.3):",
                                        value=evidencia_103_salva,
                                        key=chave_link_103,
                                        on_change=cb_processa_e_salva_103,
                                        placeholder="Insira o link para modelos de contratos ou termos aditivos padrão...",
                                        height=150
                                )
                                placeholder_links_103 = st.empty()
                                links_103_visuais = [u[0] for u in re.findall(regex_pure_url, link_103 or "")]
                                if links_103_visuais:
                                        placeholder_links_103.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_103_visuais]))

                        v_atual_103 = st.session_state.get(chave_radio_103, v_salvo_103)
                        cor_txt_103 = "#28a745" if "contratos" in str(v_atual_103) else ("#dc3545" if v_atual_103 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_103}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.3: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.3", res_data, ano_sel)

        # =============================================================================
        # QUESITO 10.4 • MAPEAMENTO DE DADOS (DATA MAPPING)
        # =============================================================================
        with st.container(key=f"container_bloco_lgpd_10_4_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.4 - Mapeamento de Dados (Data Mapping)", expanded=True):
                        st.subheader("10.4 • Data Mapping")
                        st.write("**A Prefeitura Municipal realizou mapeamento de dados (data mapping)?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        lista104 = ["Selecione...", "Sim", "Não"]
                        d104 = res_data.get("10.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d104 is None: d104 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_104 = d104.get("valor", "Selecione...")
                        if v_salvo_104 not in lista104: v_salvo_104 = "Selecione..."

                        evidencia_104_salva = d104.get("link", "")
                        chave_radio_104 = f"r_104_select_{ano_sel}"
                        chave_link_104 = f"l_104_txt_area_{ano_sel}"

                        def cb_processa_e_salva_104():
                                lnk_val = st.session_state.get(chave_link_104, evidencia_104_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_104, v_salvo_104)

                                save_resp("10.4", val_salvar, 0.0, lnk_val)
                                res_data["10.4"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_104_salva or "")]
                                if lnk_val != evidencia_104_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_10_4_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_10_4_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx104 = lista104.index(v_salvo_104)
                                st.radio(
                                        "Selecione uma opção (10.4):",
                                        options=lista104,
                                        index=idx104,
                                        key=chave_radio_104,
                                        on_change=cb_processa_e_salva_104
                                )

                        with col2:
                                link_104 = st.text_area(
                                        "Link/Evidência (10.4):",
                                        value=evidencia_104_salva,
                                        key=chave_link_104,
                                        on_change=cb_processa_e_salva_104,
                                        placeholder="Insira o link comprobatório do mapeamento de dados...",
                                        height=110
                                )
                                placeholder_links_104 = st.empty()
                                links_104_visuais = [u[0] for u in re.findall(regex_pure_url, link_104 or "")]
                                if links_104_visuais:
                                        placeholder_links_104.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_104_visuais]))

                        v_atual_104 = st.session_state.get(chave_radio_104, v_salvo_104)
                        cor_txt_104 = "#28a745" if v_atual_104 == "Sim" else ("#dc3545" if v_atual_104 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_104}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.4: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.4", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.5 • MEDIDAS DE SEGURANÇA ADOTADAS
        # =============================================================================
        with st.container(key=f"container_bloco_lgpd_10_5_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.5 - Medidas de Segurança Implementadas", expanded=True):
                        st.subheader("10.5 • Medidas de Segurança Técnicas/Administrativas")
                        st.write("**Foram adotadas medidas de segurança, técnicas e administrativas a fim de proteger os dados pessoais de acessos não autorizados e de situações acidentais ou ilícitas?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        lista105 = ["Selecione...", "Sim", "Não"]
                        d105 = res_data.get("10.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d105 is None: d105 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_105 = d105.get("valor", "Selecione...")
                        if v_salvo_105 not in lista105: v_salvo_105 = "Selecione..."

                        evidencia_105_salva = d105.get("link", "")
                        chave_radio_105 = f"r_105_select_{ano_sel}"
                        chave_link_105 = f"l_105_txt_area_{ano_sel}"

                        def cb_processa_e_salva_105():
                                lnk_val = st.session_state.get(chave_link_105, evidencia_105_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_105, v_salvo_105)

                                save_resp("10.5", val_salvar, 0.0, lnk_val)
                                res_data["10.5"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_105_salva or "")]
                                if lnk_val != evidencia_105_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_10_5_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_10_5_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx105 = lista105.index(v_salvo_105)
                                st.radio(
                                        "Selecione uma opção (10.5):",
                                        options=lista105,
                                        index=idx105,
                                        key=chave_radio_105,
                                        on_change=cb_processa_e_salva_105
                                )

                        with col2:
                                link_105 = st.text_area(
                                        "Link/Evidência (10.5):",
                                        value=evidencia_105_salva,
                                        key=chave_link_105,
                                        on_change=cb_processa_e_salva_105,
                                        placeholder="Insira o link principal comprovando as políticas/medidas de segurança...",
                                        height=110
                                )
                                placeholder_links_105 = st.empty()
                                links_105_visuais = [u[0] for u in re.findall(regex_pure_url, link_105 or "")]
                                if links_105_visuais:
                                        placeholder_links_105.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_105_visuais]))

                        v_atual_105 = st.session_state.get(chave_radio_105, v_salvo_105)
                        cor_txt_105 = "#28a745" if v_atual_105 == "Sim" else ("#dc3545" if v_atual_105 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_105}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.5: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.5", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.5.1 • DETALHAMENTO DAS MEDIDAS ADOTADAS
        # =============================================================================
        with st.container(key=f"container_bloco_lgpd_10_5_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.5.1 - Detalhamento das Medidas de Segurança", expanded=True):
                        st.subheader("10.5.1 • Descrição das Medidas Adotadas")
                        st.write("**Informe e detalhe as medidas técnicas e administrativas adotadas pela Prefeitura:**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        d1051 = res_data.get("10.5.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if d1051 is None: d1051 = {"valor": "", "pontos": 0.0, "link": ""}

                        v_salvo_1051 = d1051.get("valor", "")
                        chave_txt_1051 = f"t_1051_txt_area_{ano_sel}"

                        def cb_processa_e_salva_1051():
                                val_salvar = st.session_state.get(chave_txt_1051, v_salvo_1051).strip()
                                save_resp("10.5.1", val_salvar, 0.0, "")
                                res_data["10.5.1"] = {"valor": val_salvar, "pontos": 0.0, "link": ""}

                        st.text_area(
                                "Informe as medidas aqui:",
                                value=v_salvo_1051,
                                key=chave_txt_1051,
                                on_change=cb_processa_e_salva_1051,
                                placeholder="Descreva de forma suscinta ou detalhada quais firewalls, controles administrativos, treinamentos ou tokens foram implementados...",
                                height=130
                        )

                        v_atual_1051 = st.session_state.get(chave_txt_1051, v_salvo_1051)
                        cor_txt_1051 = "#28a745" if len(v_atual_1051.strip()) > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_1051}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.5.1: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.5.1", res_data, ano_sel)

       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (BLOCO 11 - DPO)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
                modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_1_{ano_sel}", False):
                modal_aviso_link("11.1", st.session_state.get(f"links_pendentes_11_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 11.0 • DESIGNAÇÃO DO ENCARREGADO DE DADOS (DPO)
        # =============================================================================
        with st.container(key=f"container_bloco_dpo_11_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 11.0 - Designação de Encarregado de Dados", expanded=True):
                        st.subheader("11.0 • Encarregado de Dados / DPO")
                        st.write("**A Prefeitura Municipal designou um encarregado para as operações de tratamento de dados pessoais?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        lista110 = ["Selecione...", "Sim", "Não"]
                        d110 = res_data.get("11.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d110 is None: d110 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_110 = d110.get("valor", "Selecione...")
                        if v_salvo_110 not in lista110: v_salvo_110 = "Selecione..."
                        
                        evidencia_110_salva = d110.get("link", "")
                        chave_radio_110 = f"r_110_select_{ano_sel}"
                        chave_link_110 = f"l_110_txt_area_{ano_sel}"

                        def cb_processa_e_salva_110():
                                lnk_val = st.session_state.get(chave_link_110, evidencia_110_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_110, v_salvo_110)
                                
                                save_resp("11.0", val_salvar, 0.0, lnk_val)
                                res_data["11.0"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_110_salva or "")]
                                if lnk_val != evidencia_110_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx110 = lista110.index(v_salvo_110)
                                st.radio(
                                        "Selecione uma opção (11.0):",
                                        options=lista110,
                                        index=idx110,
                                        key=chave_radio_110,
                                        on_change=cb_processa_e_salva_110
                                )

                        with col2:
                                link_110 = st.text_area(
                                        "Link/Evidência (11.0):",
                                        value=evidencia_110_salva,
                                        key=chave_link_110,
                                        on_change=cb_processa_e_salva_110,
                                        placeholder="Insira o link do ato oficial ou portaria de nomeação do DPO...",
                                        height=110
                                )
                                placeholder_links_110 = st.empty()
                                links_110_visuais = [u[0] for u in re.findall(regex_pure_url, link_110 or "")]
                                if links_110_visuais:
                                        placeholder_links_110.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_110_visuais]))

                        v_atual_110 = st.session_state.get(chave_radio_110, v_salvo_110)
                        cor_txt_110 = "#28a745" if v_atual_110 == "Sim" else ("#dc3545" if v_atual_110 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_110}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.0: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("11.0", res_data, ano_sel)


        # =============================================================================
        # QUESITO 11.1 • PÁGINA ELETRÔNICA DE CONTATO DO ENCARREGADO
        # =============================================================================
        with st.container(key=f"container_bloco_dpo_11_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 11.1 - Página Eletrônica do Encarregado", expanded=True):
                        st.subheader("11.1 • Canal de Contato e Identidade do DPO")
                        st.write("**Informe a página eletrônica (link no site da prefeitura), que contenha a identidade e as informações de contato do encarregado:**")
                        st.markdown("<small style='color:gray;'>Se não estiver disponível na internet, inserir no campo de resposta o texto <b>XYZ</b></small>", unsafe_allow_html=True)
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        d111 = res_data.get("11.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if d111 is None: d111 = {"valor": "", "pontos": 0.0, "link": ""}

                        v_salvo_111 = d111.get("valor", "")
                        evidencia_111_salva = d111.get("link", "")
                        
                        chave_txt_111 = f"t_111_txt_input_{ano_sel}"
                        chave_link_111 = f"l_111_txt_area_{ano_sel}"

                        def cb_processa_e_salva_111():
                                val_salvar = st.session_state.get(chave_txt_111, v_salvo_111).strip()
                                lnk_val = st.session_state.get(chave_link_111, evidencia_111_salva).strip()
                                
                                save_resp("11.1", val_salvar, 0.0, lnk_val)
                                res_data["11.1"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_111_salva or "")]
                                if lnk_val != evidencia_111_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_11_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                link_input_111 = st.text_input(
                                        "Link ou texto de contingência (11.1):",
                                        value=v_salvo_111,
                                        key=chave_txt_111,
                                        on_change=cb_processa_e_salva_111,
                                        placeholder="Cole a URL da página do encarregado ou digite XYZ"
                                )
                                placeholder_input_links_111 = st.empty()
                                links_input_111_visuais = [u[0] for u in re.findall(regex_pure_url, link_input_111 or "")]
                                if links_input_111_visuais:
                                        placeholder_input_links_111.markdown(f"**🔗 Link ativo detectado:** " + " | ".join([f"[{u}]({u})" for u in links_input_111_visuais]))

                        with col2:
                                link_111 = st.text_area(
                                        "Link/Evidência Adicional (11.1):",
                                        value=evidencia_111_salva,
                                        key=chave_link_111,
                                        on_change=cb_processa_e_salva_111,
                                        placeholder="Insira links de comprovação adicionais se necessário...",
                                        height=110
                                )
                                placeholder_links_111 = st.empty()
                                links_111_visuais = [u[0] for u in re.findall(regex_pure_url, link_111 or "")]
                                if links_111_visuais:
                                        placeholder_links_111.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_111_visuais]))

                        v_atual_111 = st.session_state.get(chave_txt_111, v_salvo_111)
                        cor_txt_111 = "#28a745" if len(v_atual_111.strip()) > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_111}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.1: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("11.1", res_data, ano_sel)

        # =============================================================================
        # GATILHO DO MODAL AUTOMÁTICO DO QUESITO 12.0 (Colocar no topo do script)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_12_0_{ano_sel}", False):
                modal_aviso_link("12.0", st.session_state.get(f"links_pendentes_12_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 12.0 • CONSIDERAÇÕES FINAIS E FEEDBACK
        # =============================================================================
        with st.container(key=f"container_bloco_feedback_12_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 12.0 - Considerações Finais e Feedback", expanded=True):
                        st.subheader("12.0 • Considerações Finais")
                        st.write("**Gostaria de registrar suas impressões, comentários e sugestões a respeito do presente questionário?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        d120 = res_data.get("12.0", {"valor": "", "pontos": 0.0, "link": ""})
                        if d120 is None: d120 = {"valor": "", "pontos": 0.0, "link": ""}

                        v_salvo_120 = d120.get("valor", "")
                        evidencia_120_salva = d120.get("link", "")
                        
                        chave_txt_120 = f"t_120_txt_area_{ano_sel}"
                        chave_link_120 = f"l_120_txt_area_{ano_sel}"

                        def cb_processa_e_salva_120():
                                val_salvar = st.session_state.get(chave_txt_120, v_salvo_120).strip()
                                lnk_val = st.session_state.get(chave_link_120, evidencia_120_salva).strip()
                                
                                save_resp("12.0", val_salvar, 0.0, lnk_val)
                                res_data["12.0"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                # Ativação do modal de aviso caso insiram algum link no campo de evidência complementar
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_120_salva or "")]
                                if lnk_val != evidencia_120_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.text_area(
                                        "Suas impressões / comentários:",
                                        value=v_salvo_120,
                                        key=chave_txt_120,
                                        on_change=cb_processa_e_salva_120,
                                        placeholder="Escreva aqui suas críticas, elogios, dificuldades ou sugestões de melhoria para os próximos anos...",
                                        height=150
                                )

                        with col2:
                                link_120 = st.text_area(
                                        "Link/Evidência Complementar (Opcional):",
                                        value=evidencia_120_salva,
                                        key=chave_link_120,
                                        on_change=cb_processa_e_salva_120,
                                        placeholder="Caso queira anexar uma URL com relatórios de melhoria ou documentos de feedback...",
                                        height=150
                                )
                                placeholder_links_120 = st.empty()
                                links_120_visuais = [u[0] for u in re.findall(regex_pure_url, link_120 or "")]
                                if links_120_visuais:
                                        placeholder_links_120.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_120_visuais]))

                        v_atual_120 = st.session_state.get(chave_txt_120, v_salvo_120)
                        cor_txt_120 = "#28a745" if len(v_atual_120.strip()) > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_120}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 12.0: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("12.0", res_data, ano_sel)

    # =========================================================================
    # ATENÇÃO AQUI: Note que o "with aba_graf:" tem EXATAMENTE 4 ESPAÇOS (1 Tab)
    # Ele fica alinhado verticalmente com o "with aba_quest:" lá do topo!
    # =========================================================================
    with aba_graf:
        st.subheader("📈 Evolução dos Resultados — Série Histórica")
        st.write("Acompanhe o desempenho da pontuação total acumulada ao longo dos anos:")

        # 1. Recupera o histórico tratado na sidebar
        dados_historicos = st.session_state.get("all_data", {})
        anos_periodo = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
        
        # 2. Processa os pontos de cada ano da série histórica
        pontuacoes_por_ano = {}
        for ano in anos_periodo:
            dados_do_ano = dados_historicos.get(ano, {})
            if isinstance(dados_do_ano, dict) and dados_do_ano:
                pts_ano = sum(float(v.get("pontos", 0)) for k, v in dados_do_ano.items() if not k.startswith("COM_"))
            else:
                pts_ano = 0.0
            pontuacoes_por_ano[str(ano)] = pts_ano

        # 3. Renderiza o Gráfico de Barras
        st.bar_chart(
            pontuacoes_por_ano, 
            x_label="Ano de Referência", 
            y_label="Pontuação Total",
            color="#1e3a5f"
        )
        
        # 4. Tabela resumida de apoio
        st.markdown("#### 📋 Resumo dos Dados")
        dados_tabela = {
            "Ano": list(pontuacoes_por_ano.keys()),
            "Pontuação": [f"{pts:.1f} pts" if pts > 0 else "-" for pts in pontuacoes_por_ano.values()]
        }
        st.dataframe(dados_tabela, hide_index=True, use_container_width=True)