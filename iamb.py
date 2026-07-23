import os
import sys
import re
import json
import warnings
import logging
from iamb import init_db  # Troque 'database' pelo nome do seu arquivo .py
from datetime import datetime, date
from io import BytesIO

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import streamlit as st

# Silencia alertas e logs não críticos
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore")
os.environ["STREAMLIT_LOGGER_LEVEL"] = "error"
os.environ["PYTHONWARNINGS"] = "ignore"
logging.getLogger("streamlit").setLevel(logging.ERROR)

# Bibliotecas para o PDF (ReportLab)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart

# Bibliotecas para Gráficos (Plotly)
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# =============================================================================
# REGEX DE VALIDAÇÃO
# =============================================================================
REGEX_PURE_URL = r'((https?://[^\s<>"]+))'

# =============================================================================
# CONSTANTES GLOBAIS - IAMB
# =============================================================================
PONTUACOES_MAX_IAMB = {
    "1.1.2": 20,
    "1.1.3": 5,
    "1.2": 20,
    "2.0": 10,
    "2.1": 50,
    "3.0": 10,
    "3.1": 20,
    "4.0": 20,
    "5.2.1": 20,
    "6.0": 20,
    "6.1": 50,
    "6.2": 25,
    "7.2": 2,
    "7.3": 10,
    "7.3.1": 20,
    "7.4": 10,
    "7.4.1": 20,
    "7.5": 30,
    "7.7": 30,
    "7.8": 20,
    "7.8.1": 50,
    "7.9": 3,
    "8.2": 2,
    "8.3": 10,
    "8.4": 20,
    "8.4.1": 10,
    "8.4.2": 30,
    "8.4.3": 50,
    "9.2": 100,
    "9.3": 5,
    "9.3.1": 5,
    "11.2": 2,
    "11.3": 30,
    "11.3.2": 20,
    "11.3.3": 40,
    "11.5": 10,
    "12.1": 54,
    "14.3": 30,
    "15": 2,
    "15.1": 3,
    "A4.1.1": 90,
    "A4.1.2": 20,
    "A4.1.3": 22,
    "A6": 5
}

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO (CORRIGIDO PARA LINKS CLICÁVEIS)
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link Externo")
def modal_aviso_link(qid, links_encontrados):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")
        
    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
    
    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}"):
        st.rerun()

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link Externo")
def modal_aviso_link(qid, links_encontrados):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")
        
    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
    
    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}"):
        st.rerun()

# =============================================================================
# 1. GESTÃO DE ESTADO E PERSISTÊNCIA EM MEMÓRIA (st.session_state)
# =============================================================================

def get_ano_atual() -> int:
    """Recupera o ano de referência ativo no aplicativo."""
    return int(st.session_state.get("ano_referencia_igov") or st.session_state.get("ano_referencia_global") or 2024)

def load_respostas(ano: int = None) -> dict:
    """Carrega as respostas armazenadas no session_state para o ano especificado."""
    if ano is None:
        ano = get_ano_atual()
    
    key_ano = f"respostas_igov_{ano}"
    if key_ano not in st.session_state:
        st.session_state[key_ano] = {}
    
    return st.session_state[key_ano]

def save_resp(qid, valor, pontos, link, comentarios=None):
    """Salva/Atualiza as respostas diretamente no st.session_state do iGov."""
    ano_int = get_ano_atual()
    key_ano = f"respostas_igov_{ano_int}"
    
    if key_ano not in st.session_state:
        st.session_state[key_ano] = {}

    if comentarios is None:
        dados_atuais = st.session_state[key_ano].get(str(qid), {})
        comentarios = dados_atuais.get("comentarios", [])

    st.session_state[key_ano][str(qid)] = {
        "valor": str(valor),
        "pontos": float(pontos),
        "link": str(link),
        "comentarios": comentarios,
        "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# =============================================================================
# 2. COMPONENTE PARA RENDERIZAR E SALVAR QUESTÕES
# =============================================================================

def renderizar_questao(qid, res_data):
    """Renderiza a questão com botão de salvamento manual."""
    dados_q = res_data.get(qid, {})
    
    val_existente = dados_q.get("valor", "")
    pts_existente = float(dados_q.get("pontos", 0.0))
    link_existente = dados_q.get("link", "")
    
    with st.container(border=True):
        st.markdown(f"#### Quesito: `{qid}`")
        
        col_txt, col_meta = st.columns([3, 1])
        
        with col_txt:
            novo_valor = st.text_area(
                "Resposta / Evidência:", 
                value=val_existente, 
                key=f"txt_val_{qid}",
                height=100
            )
            novo_link = st.text_input(
                "Link da Evidência (opcional):", 
                value=link_existente, 
                key=f"txt_link_{qid}"
            )

        with col_meta:
            novos_pontos = st.number_input(
                "Pontuação:", 
                value=pts_existente, 
                key=f"num_pts_{qid}"
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("💾 Salvar Questão", key=f"btn_save_{qid}", type="primary", use_container_width=True):
                links = re.findall(r'https?://[^\s]+', novo_valor) + re.findall(r'https?://[^\s]+', novo_link)
                
                save_resp(
                    qid=qid, 
                    valor=novo_valor, 
                    pontos=novos_pontos, 
                    link=novo_link
                )
                
                st.toast(f"Questão {qid} salva com sucesso!", icon="✅")
                
                if links and "modal_aviso_link" in globals():
                    modal_aviso_link(qid, links)

        # Diálogo Interno (Comentários)
        bloco_comentarios(qid, res_data)


def bloco_comentarios(questao_id, res_data, sufixo=None):
    """Gera o diálogo interno avançado com histórico e status."""
    ano_sel = get_ano_atual()
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_{id_chave}_{ano_sel}"
    key_radio = f"rad_status_{id_chave}_{ano_sel}"
    
    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False
        
    dados_questao = res_data.get(questao_id, {})
    historico = list(dados_questao.get("comentarios", []))
    
    status_global = "Resolvido"
    for com in historico:
        if isinstance(com, dict) and "status_definido" in com:
            status_global = com["status_definido"]
            
    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    
    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global) if status_global in opcoes_status else 0
        
        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=key_radio
        )
        
        # Mudança de Status
        if key_radio in st.session_state and st.session_state[key_radio] != status_global:
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
                pontos=dados_questao.get("pontos", 0),
                link=dados_questao.get("link", ""),
                comentarios=historico
            )
            st.rerun()

        if historico:
            for idx, com in enumerate(historico):
                if not isinstance(com, dict):
                    continue
                col_balao, col_lixeira = st.columns([11, 1])
                
                with col_balao:
                    autor = com.get('autor', 'Anônimo')
                    data_com = com.get('data', '')
                    texto_com = com.get('texto', '')
                    
                    if "Sistema /" in autor:
                        st.markdown(
                            f"""<div style="background-color: #f1f3f5; padding: 6px 12px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ced4da;">
                                <span style="font-size: 11px; color: #6c757d; font-style: italic;">{autor} - {data_com}</span>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #495057;">{texto_com}</p>
                            </div>""", unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f"""<div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e88e5;">
                                <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">{autor}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{data_com}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{texto_com}</p>
                            </div>""", unsafe_allow_html=True
                        )
                
                with col_lixeira:
                    if st.button("🗑️", key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}"):
                        historico.pop(idx)
                        save_resp(
                            qid=questao_id,
                            valor=dados_questao.get("valor", ""),
                            pontos=dados_questao.get("pontos", 0),
                            link=dados_questao.get("link", ""),
                            comentarios=historico
                        )
                        st.rerun()
        
        # Limpeza do campo de entrada
        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False
            
        novo_texto = st.text_area("Novo comentário:", key=key_texto, height=70, label_visibility="collapsed")
        
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
                    pontos=dados_questao.get("pontos", 0), 
                    link=dados_questao.get("link", ""),
                    comentarios=historico
                )
                st.session_state[key_estado_limpar] = True
                st.rerun()

# =============================================================================
# 3. FUNÇÕES DE ANÁLISE E HISTÓRICO (ADAPTADO PARA IAMB)
# =============================================================================

def get_all_years_data():
    """Varre a sessão procurando por chaves do tipo respostas_iamb_<ano>."""
    all_data = {}
    prefixo = "respostas_iamb_"
    
    for key in list(st.session_state.keys()):
        if key.startswith(prefixo):
            try:
                ano = int(key.replace(prefixo, ""))
                all_data[ano] = st.session_state[key]
            except ValueError:
                continue
                
    return all_data


def analyze_performance(res_data):
    """Mapeia os pontos fortes e fragilidades do ano atual no iAmb usando o dicionário TETOS_VALIDOS."""
    pontos_fortes = []
    criticos_zero = {"Alta": [], "Média": [], "Baixa": []}
    criticos_negativos = {"Alta": [], "Média": [], "Baixa": []}

    # Dicionário de tetos máximos por quesito - iAmb
    TETOS_VALIDOS = {
        "1.1.2": 20.0, "1.1.3": 10.0, "1.2": 20.0, "2.0": 10.0, "2.1": 50.0, "3.0": 10.0, "3.1": 20.0, "4.0": 20.0,
        "5.2.1": 20.0, "6.0": 20.0, "6.1": 50.0, "6.2": 25.0, "7.2": 2.0, "7.3": 10.0, "7.3.1": 20.0, "7.4": 10.0,
        "7.4.1": 20.0, "7.5": 30.0, "7.7": 30.0, "7.8": 20.0, "7.8.1": 50.0, "7.9": 3.0, "8.2": 2.0, "8.3": 10.0,
        "8.4": 20.0, "8.4.1": 10.0, "8.4.2": 30.0, "8.4.3": 50.0, "9.2": 100.0, "9.3": 5.0, "9.3.1": 5.0,
        "11": 10.0, "11.2": 2.0, "11.3": 30.0, "11.3.2": 20.0, "11.3.3": 40.0, "11.5": 10.0, "12.1": 54.0, "14.3": 30.0,
        "15": 2.0, "15.1": 3.0, "A4.1.1": 90.0, "A4.1.2": 20.0, "A4.1.3": 22.0, "A6": 5.0
    }

    def classificar_relevancia(impacto):
        abs_impacto = abs(impacto)
        if abs_impacto >= 16:
            return "Alta"
        elif 6 <= abs_impacto <= 15:
            return "Média"
        else:
            return "Baixa"

    for qid, info in res_data.items():
        # Ignora campos de comentários ou quesitos fora do mapeamento
        if qid.startswith("COM_") or qid not in TETOS_VALIDOS:
            continue

        pontos_atuais = float(info.get("pontos", 0.0))
        max_pontos = TETOS_VALIDOS[qid]

        if pontos_atuais == max_pontos:
            pontos_fortes.append((qid, pontos_atuais, info.get("valor", ""), info.get("link", "")))
        else:
            impacto = max_pontos - pontos_atuais
            relevancia = classificar_relevancia(impacto)

            if pontos_atuais < 0:
                criticos_negativos[relevancia].append(
                    (qid, pontos_atuais, info.get("valor", ""), info.get("link", ""), impacto)
                )
            else:
                criticos_zero[relevancia].append(
                    (qid, pontos_atuais, info.get("valor", ""), info.get("link", ""), impacto)
                )

    # Ordenação dos resultados por pontuação/impacto
    pontos_fortes.sort(key=lambda x: x[1], reverse=True)
    for rel in ["Alta", "Média", "Baixa"]:
        criticos_zero[rel].sort(key=lambda x: x[4], reverse=True)
        criticos_negativos[rel].sort(key=lambda x: x[4], reverse=True)

    return pontos_fortes, criticos_zero, criticos_negativos

import io
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# =============================================================================
# 3. GERADOR DO RELATÓRIO PDF - i-AMB
# =============================================================================

def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    # Inicializa os estilos padrões do ReportLab
    styles = getSampleStyleSheet()
    
    # Definição explícita dos estilos customizados da capa e tabelas
    style_titulo_capa = ParagraphStyle(
        'TituloCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica-Bold', 
        fontSize=24, 
        leading=28, 
        textColor=colors.HexColor("#2e7d32"), 
        alignment=1
    )
    
    style_ano_capa = ParagraphStyle(
        'AnoCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica', 
        fontSize=16, 
        leading=20,
        textColor=colors.HexColor("#7f8c8d"), 
        alignment=1
    )

    style_tabela_padrao = ParagraphStyle(
        'TextoTabela',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=0
    )

    style_tabela_centro = ParagraphStyle(
        'TextoTabelaCentro',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=1
    )

    # Função interna para limpar strings contra quebras no interpretador XML do ReportLab
    def limpar_xml(texto):
        return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    if all_data is None:
        all_data = {}
        
    if 'PONTUACOES_MAX' not in globals():
        PONTUACOES_MAX = {
            "1.1.2": 20.0, "1.1.3": 10.0, "1.2": 20.0, "2.0": 10.0, "2.1": 50.0, "3.0": 10.0, "3.1": 20.0, "4.0": 20.0,
            "5.2.1": 20.0, "6.0": 20.0, "6.1": 50.0, "6.2": 25.0, "7.2": 2.0, "7.3": 10.0, "7.3.1": 20.0, "7.4": 10.0,
            "7.4.1": 20.0, "7.5": 30.0, "7.7": 30.0, "7.8": 20.0, "7.8.1": 50.0, "7.9": 3.0, "8.2": 2.0, "8.3": 10.0,
            "8.4": 20.0, "8.4.1": 10.0, "8.4.2": 30.0, "8.4.3": 50.0, "9.2": 100.0, "9.3": 5.0, "9.3.1": 5.0,
            "11.2": 2.0, "11.3": 30.0, "11.3.2": 20.0, "11.3.3": 40.0, "11.5": 10.0, "12.1": 54.0, "14.3": 30.0,
            "15": 2.0, "15.1": 3.0, "A4.1.1": 90.0, "A4.1.2": 20.0, "A4.1.3": 22.0, "A6": 5.0, "11": 10.0
        }
    else:
        PONTUACOES_MAX = globals()['PONTUACOES_MAX']

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
    elements.append(Paragraph("Relatório i-AMB", style_titulo_capa))
    elements.append(Spacer(1, 5))
    elements.append(Spacer(1, 15))
    
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2e7d32"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito i-AMB", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("6. Série Histórica Ambiental", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
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
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-AMB (MEIO AMBIENTE) - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA AMBIENTAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    nota_atual = float(total)
    ano_atual = int(str(ano).strip()[:4])
    ano_ant = ano_atual - 1

    def converter_pontos_em_faixa_iamb(pontos):
        pts = float(pontos)
        if pts <= 500.0:             return "C"
        elif 501.0 <= pts <= 599.9:  return "C+"
        elif 600.0 <= pts <= 749.9:  return "B"
        elif 750.0 <= pts <= 899.9:  return "B+"
        else:                        return "A"

    dados_ano_anterior = all_data.get(ano_ant, {})
    nota_anterior = 0.0
    if ano_ant in all_data:
        nota_anterior = float(sum(
            info_ant.get("pontos", 0) 
            for qid_ant, info_ant in dados_ano_anterior.items() 
            if isinstance(info_ant, dict) and not qid_ant.startswith("COM_")
        ))

    faixa_anterior = converter_pontos_em_faixa_iamb(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_iamb(nota_atual)

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

    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor("#2e7d32"), alignment=1)
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
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global socioambientais comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores de sustentabilidade e conservação em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade ambiental."

    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # =========================================================================
    # 2. ANÁLISE DE DESEMPENHO POR QUESITO
    # =========================================================================
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []
    dados_consolidados = {}

    subquestoes_11 = ["11.2", "11.3", "11.3.2", "11.3.3", "11.5"]
    resposta_11_nao = False
    if "11" in dados and isinstance(dados["11"], dict):
        if str(dados["11"].get("valor", "")).strip().lower() in ["não", "nao", "n"]:
            resposta_11_nao = True

    for sub_id in subquestoes_11:
        if resposta_11_nao or (sub_id not in dados):
            dados[sub_id] = {
                "pontos": 0.0,
                "valor": "Não aplicável / Não implantado (Mãe respondida como Não)",
                "link": ""
            }

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
        
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")

        qid_str = str(qid).strip()
        
        if qid_str.startswith("A4.1.1_"):   chave_mae = "A4.1.1"
        elif qid_str.startswith("A4.1.2_"): chave_mae = "A4.1.2"
        elif qid_str.startswith("A4.1.3_"): chave_mae = "A4.1.3"
        elif qid_str == "11" or qid_str.startswith("11."):
            if qid_str in PONTUACOES_MAX:
                chave_mae = qid_str
            else:
                chave_mae = "11"
        else:
            chave_mae = qid_str

        if chave_mae not in PONTUACOES_MAX:
            continue

        if chave_mae not in dados_consolidados:
            dados_consolidados[chave_mae] = {"pts_obtidos": 0.0, "valores": [], "links": []}
        
        dados_consolidados[chave_mae]["pts_obtidos"] += pts_obtidos
        
        if valor_resposta:
            sub_nome = qid_str.split('_')[-1] if '_' in qid_str else qid_str
            dados_consolidados[chave_mae]["valores"].append(f"{sub_nome}: {limpar_xml(valor_resposta)}")
            
        if link_evidencia:
            link_limpo = limpar_xml(link_evidencia)
            if link_limpo not in dados_consolidados[chave_mae]["links"]:
                dados_consolidados[chave_mae]["links"].append(link_limpo)

    for qid, info in dados_consolidados.items():
        pts_maximo = float(PONTUACOES_MAX.get(qid, 10.0))
        if pts_maximo <= 0: pts_maximo = 10.0
            
        pts_obtidos = max(0.0, min(info["pts_obtidos"], pts_maximo))
        eficiencia = (pts_obtidos / pts_maximo) * 100
        
        respostas_unificadas = " | ".join(info["valores"]) if info["valores"] else "-"
        evidencias_unificadas = ", ".join(info["links"]) if info["links"] else ""

        item_data = {
            "qid": qid, 
            "pts_obtidos": pts_obtidos, 
            "pts_maximo": pts_maximo, 
            "eficiencia": eficiencia, 
            "valor": respostas_unificadas, 
            "link": evidencias_unificadas
        }

        if eficiencia >= 100.0: 
            lista_pontos_fortes.append(item_data)
        else:
            lista_pontos_fracos.append(item_data)

    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes Ambientais:</b>", styles["h3"]))
        data_fortes = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["pts_obtidos"], reverse=True):
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e7d32")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2e7d32")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Fracos / Oportunidades de Melhoria:</b>", styles["h3"]))
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
        "5.2": -15.0, "5.3": -10.0, "7.3.2": -5.0, "7.4.2": -5.0, "7.5.1": -5.0, 
        "8.4.4": -30.0, "9.1": -30.0, "10.0": -100.0, "10.1": -30.0, "14.0": -30.0, "A1": -200.0
    }

    dados_penalidades = dados.copy()
    reincidencias_detectadas = []

    # 🛠️ CORREÇÃO: Se não existir no dicionário, assume 0.0 pontos (não houve penalidade)
    for qid_pen, val_max in PENALIDADES_MAX.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {"pontos": 0.0, "valor": "Não aplicável / Ocultado por condicional", "link": ""}

    lista_penalidades = []
    
    for qid, pen_max in PENALIDADES_MAX.items():
        if qid in dados_penalidades:
            info = dados_penalidades[qid]
            nota_real = float(info.get("pontos", 0.0))
            
            # Garante que apenas valores negativos (penalidades reais) entrem no cálculo do risco
            nota_risco = nota_real if nota_real <= 0.0 else 0.0
            
            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0
                
            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))

            lista_penalidades.append({
                "qid": qid, "nota_real": nota_real, "pen_max": pen_max, "eficiencia": eficiencia_preventiva, 
                "valor": info.get("valor", ""), "link": info.get("link", "")
            })
            
            if eficiencia_preventiva < 100.0 and isinstance(dados_ano_anterior, dict) and qid in dados_ano_anterior:
                info_ant = dados_ano_anterior[qid]
                nota_real_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) else 0.0
                if nota_real == nota_real_ant:
                    reincidencias_detectadas.append({
                        "qid": qid, "tipo": "Penalidade Aplicada", 
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
            # Formatação para não exibir "-0.0 pts" caso o valor venha flutuante negativo zerado
            valor_nota = 0.0 if abs(item['nota_real']) < 0.01 else item['nota_real']
            
            nota_txt = f"{valor_nota:.1f} pts"
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
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS 
    # =========================================================================
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS </b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    TETOS_VALIDOS = {
        "1.1.2": 20, "1.1.3": 5, "1.2": 20, "2.0": 10, "2.1": 50, "3.0": 10, "3.1": 20, "4.0": 20,
        "5.2.1": 20, "6.0": 20, "6.1": 50, "6.2": 25, "7.2": 2, "7.3": 10, "7.3.1": 20, "7.4": 10,
        "7.4.1": 20, "7.5": 30, "7.7": 30, "7.8": 20, "7.8.1": 50, "7.9": 3, "8.2": 2, "8.3": 10,
        "8.4": 20, "8.4.1": 10, "8.4.2": 30, "8.4.3": 50, "9.2": 100, "9.3": 5, "9.3.1": 5,
        "11.2": 2, "11.3": 30, "11.3.2": 20, "11.3.3": 40, "11.5": 10, "12.1": 54, "14.3": 30,
        "15": 2, "15.1": 3, "A4.1.1": 90, "A4.1.2": 20, "A4.1.3": 22, "A6": 5
    }
    
    dados_analise_reinc = dados.copy()
    
    for sub_id in subquestoes_11:
        if resposta_11_nao or (sub_id not in dados_analise_reinc):
            dados_analise_reinc[sub_id] = {"pontos": 0.0, "valor": "Não", "link": ""}

    for qid, info_atual in dados_analise_reinc.items():
        if qid.startswith("COM_") or not isinstance(info_atual, dict): 
            continue
            
        qid_str = str(qid).strip()
        
        if qid_str.startswith("A4.1.1_"):   chave_mae = "A4.1.1"
        elif qid_str.startswith("A4.1.2_"): chave_mae = "A4.1.2"
        elif qid_str.startswith("A4.1.3_"): chave_mae = "A4.1.3"
        else:                               chave_mae = qid_str
            
        if chave_mae not in TETOS_VALIDOS:
            continue
            
        pts_maximo = float(TETOS_VALIDOS[chave_mae])
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0))
        
        if pts_maximo > 0 and (pts_obtidos_atual / pts_maximo) * 100 < 50.0:
            info_ant = dados_ano_anterior.get(qid, {}) if isinstance(dados_ano_anterior, dict) else {}
            pts_obtidos_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) else 0.0
            
            if (pts_obtidos_ant / pts_maximo) * 100 < 50.0:
                origem = "Gestão Ambiental Geral"
                if 'CATEGORIAS_MAP' in globals():
                    for cat_chave, cat_info in CATEGORIAS_MAP.items():
                        if chave_mae in cat_info.get("qids", []):
                            origem = cat_info.get("label", "Outros")
                            break
                else:
                    if chave_mae.startswith("1.") or chave_mae.startswith("2.") or chave_mae.startswith("3."):
                        origem = "Planejamento e Infraestrutura"
                    elif chave_mae.startswith("7.") or chave_mae.startswith("8."):
                        origem = "Resíduos e Saneamento"
                    elif chave_mae.startswith("11.") or chave_mae.startswith("12."):
                        origem = "Biodiversidade e Água"
                    elif chave_mae.startswith("A4"):
                        origem = "Indicadores SINISA"
                            
                reincidencias_detectadas.append({
                    "qid": qid_str, 
                    "tipo": origem, 
                    "detalhe": "Ineficiência Crônica de Desempenho (Eficiência inferior a 50% por 2 anos)",
                    "ant": f"{pts_obtidos_ant:.1f} / {pts_maximo:.1f} pts", 
                    "atual": f"{pts_obtidos_atual:.1f} / {pts_maximo:.1f} pts"
                })

    if reincidencias_detectadas:
        data_reinc = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Origem da Falha", style_th), 
            Paragraph("Impacto Histórico", style_th), 
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
        elements.append(Paragraph("<font color='#2e7d32'><b>✅ Nenhuma reincidência ativa detectada. O município corrigiu ou mitigou as falhas do ano anterior.</b></font>", styles["Normal"]))
        
    elements.append(Spacer(1, 15))
        
    # -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU) - FORMATADO PADRÃO I-GOV
    # -------------------------------------------------------------------------
    import reportlab.lib.colors as rl_colors
    # Mudança radical no nome do import local para extinguir o erro de UnboundLocalError
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
    
    # Lista atualizada contendo todos os quesitos novos e existentes
    quesitos_validos_ods = [
        "1.0", "1.1", "1.1.2", "2.0", "3.0", "4.0", "5.0", "6.0", "6.2", "7.0", 
        "7.3", "7.4", "7.5", "7.7.1", "7.8", "7.8.1", "7.9", "8.0", "8.3", 
        "8.3.1", "8.4", "8.4.1", "9.0", "10.0", "10.1", "10.2", "10.3", "11.0", 
        "12.0", "13.0", "14.0", "15.0"
    ]

    for qid in quesitos_validos_ods:
        if qid not in dados: 
            continue
            
        info = dados[qid]
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()
        
        if not resp or resp_l == "não respondido" or resp == "[]": 
            continue

        metas = ""
        status = "Não Atendido"

        # Lógica de Mapeamento do iAMB atualizada
        if qid in ["1.0", "1.1"]:
            metas = "12.2, 15.2, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "1.1.2":
            metas = "12.8"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "2.0":
            metas = "4.7, 12.8, 15.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "3.0":
            metas = "12.2, 16.6, 17.14"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "4.0":
            metas = "12.4"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "5.0":
            metas = "5.0"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "6.0":
            metas = "6.4, 6.b, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "6.2":
            metas = "6.4, 6.5, 6.b, 16.6"
            pct = calcular_percentual_checklist(resp, 3)
            status = f"{pct:.1f}% Atendido"
        elif qid == "7.0":
            metas = "6.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.3":
            metas = "6.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["7.4", "7.5"]:
            metas = "6.2, 6.3"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.7.1":
            metas = "6.0, 16.6"
            pct = calcular_percentual_checklist(resp, 3)
            status = f"{pct:.1f}% Atendido"
        elif qid == "7.8":
            metas = "6.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.8.1":
            metas = "6.2, 6.3"
            status = "Atendido" if "todas as metas foram cumpridas dentro do prazo" in resp_l else "Não Atendido"
        elif qid == "7.9":
            metas = "6.2, 6.3"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["8.0", "8.3", "8.4", "9.0"]:
            metas = "11.6, 12.5"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "8.3.1":
            metas = "11.6, 12.5, 12.4"
            pct = calcular_percentual_checklist(resp, 3)
            status = f"{pct:.1f}% Atendido"
        elif qid == "8.4.1":
            metas = "11.6, 12.5, 12.4"
            pct = calcular_percentual_checklist(resp, 4)
            status = f"{pct:.1f}% Atendido"
        elif qid in ["10.0", "10.1"]:
            metas = "11.6, 12.5, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "10.2":
            metas = "11.6, 12.5, 16.6"
            status = "Atendido" if "todos os bairros do município são atendidos" in resp_l else "Não Atendido"
        elif qid == "10.3":
            metas = "11.6, 12.5, 12.4, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "11.0":
            metas = "11.6, 12.4, 12.5, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "12.0":
            metas = "11.6, 12.5, 12.4"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "13.0":
            metas = "11.6, 12.4"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.0":
            # 🔄 Lógica Inversa solicitada para o quesito 14.0
            metas = "11.6, 12.4"
            status = "Atendido" if "não" in resp_l else "Não Atendido"
        elif qid == "15.0":
            metas = "12.0, 16.6"
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
        style_td_ods = Alias_Style('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        # Ordenação correta dos quesitos (ex: 1.0, 1.1, 1.1.2, 2.0...)
        for item in sorted(analise_ods, key=lambda x: [float(i) if i.replace('.','',1).isdigit() else 999 for i in x['qid'].split('.')]):
            st_txt = item["status"]
            
            # Formatação de Cores Dinâmicas para o Status igual ao iGov
            if "Não Atendido" in st_txt:
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt:
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else:
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
                
            data_ods.append([
                Paragraph(f"<b>{item['qid']}</b>", style_tabela_centro), 
                Paragraph(item["resp"], style_tabela_padrao), 
                Paragraph(item["metas"], style_tabela_centro), 
                st_p
            ])
            
        tabela_ods = Table(data_ods, colWidths=[55, 210, 115, 110])
        tabela_ods.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#0f9d58")), # Verde institucional do iGov aplicado aqui
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
    # 📊 6. SÉRIE HISTÓRICA DO IAMB (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>6. SÉRIE HISTÓRICA DO IAMB (CONSOLIDADO FINAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    
    # Captura do ano atual de forma segura
    ano_reference = None
    for nome_var in ['ano_sel', 'ano_atual', 'ano', 'exercicio']:
        if nome_var in locals():
            ano_reference = locals()[nome_var]
            break
    if ano_reference is None:
        ano_reference = 2026

    # Captura da nota atual (calculada no início do seu compilador)
    nota_reference = 0.0
    for nome_var in ['total_pts', 'nota_atual', 'pontuacao_final', 'total']:
        if nome_var in locals():
            try:
                nota_reference = float(locals()[nome_var])
                break
            except (ValueError, TypeError):
                continue

    import streamlit as st
    
    # Captura segura da variável all_data sem disparar NameError
    var_all_data = locals().get('all_data', globals().get('all_data', None))

    # Montagem do array de dados para o Gráfico
    for a in anos_serie:
        if a == 0 or a == "0":
            valores_serie.append(0.0)
        elif a == ano_reference: 
            valores_serie.append(min(nota_reference, 100.0) if nota_reference <= 100.0 else min(nota_reference, 1000.0))
        elif var_all_data and a in var_all_data:
            dados_ano = var_all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(info_h.get("pontos", 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not qid_h.startswith("COM_")))
                valores_serie.append(pontos_ano)
            else:
                valores_serie.append(float(dados_ano))
        elif hasattr(st, 'session_state') and 'all_data' in st.session_state and a in st.session_state.all_data:
            dados_ano = st.session_state.all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(info_h.get("pontos", 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not qid_h.startswith("COM_")))
                valores_serie.append(pontos_ano)
            else:
                valores_serie.append(float(dados_ano))
        else: 
            valores_serie.append(0.0)

    # Identifica se a escala do iAMB é até 100 ou até 1000 para ajustar o gráfico dinamicamente
    max_escala = 1000 if any(v > 100 for v in valores_serie) else 100
    passo_escala = 200 if max_escala == 1000 else 20

    # Configuração e renderização do Gráfico do iAMB
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
    
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max_escala
    bc.valueAxis.valueStep = passo_escala
    bc.valueAxis.labels.fontSize = 8
    
    # Ativação dos rótulos acima das barras
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    # Customização de cor temática azul-escura/institucional
    bc.bars[0].fillColor = rl_colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = rl_colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(String(240, 150, "Série Histórica de Evolução do iAMB", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=rl_colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))

    # =========================================================================
    # FIM DA FUNÇÃO: GERAÇÃO E RETORNO SEGURO DO BUFFER
    # =========================================================================
    doc.build(elements)
    buffer.seek(0)
    return buffer
import json
import logging
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go
from psycopg2.extras import RealDictCursor
import re  # Necessário para as expressões regulares dos links

# =============================================================================
# 4. SIDEBAR - iAMB
# =============================================================================

def zerar_questionario_iamb(ano: int):
    """Deleta todas as respostas do ano selecionado com modulo = 'iamb'."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM respostas WHERE ano = %s AND modulo = 'iamb'",
                    (int(ano),)
                )
            conn.commit()
        st.cache_data.clear()  # Limpa o cache após deletar
    except Exception as e:
        st.error(f"Erro ao zerar questionário iAMB: {e}")


@st.dialog("⚠️ Zerar Respostas do iAMB")
def confirmar_zerar_dialog(ano):
    st.warning(f"Tem certeza que deseja apagar TODAS as respostas do iAMB para o ano {ano}?")
    st.write("Esta ação é irreversível e excluirá os dados salvos no banco Neon.")
    
    # Campo para inserção da senha de confirmação
    senha_digitada = st.text_input(
        "Digite a senha de confirmação para prosseguir:",
        type="password",
        placeholder="Digite a senha..."
    )
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔴 Sim, Zerar Tudo", type="primary", use_container_width=True):
            if senha_digitada.strip() == "fidelios":
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute("DELETE FROM respostas_iamb WHERE ano = %s", (int(ano),))
                        conn.commit()
                    
                    st.cache_data.clear()
                    st.session_state[f"respostas_iamb_{ano}"] = {}
                    st.toast("Respostas do iAMB zeradas com sucesso!", icon="🗑️")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao zerar banco: {e}")
            else:
                st.error("🔒 Senha incorreta! Ação cancelada.")

    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def render_sidebar():
    st.sidebar.title("🌱 Painel de Controle - iAMB")
    anos = [2024, 2025, 2026, 2027, 2028, 2029, 2030]
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_global")

    res_data = load_respostas(ano_sel)
    total_pts = sum(item.get("pontos", 0) for item in res_data.values())

    # Régua de Classificação IEGM / iAMB
    if total_pts <= 500:    faixa, cor = "C (Inefetivo)",           "red"
    elif total_pts <= 599: faixa, cor = "C+ (Em Adequação)",      "orange"
    elif total_pts <= 749: faixa, cor = "B (Efetivo)",             "#d4d400"
    elif total_pts <= 899: faixa, cor = "B+ (Muito Efetivo)",     "lightgreen"
    else:                  faixa, cor = "A (Altamente Efetivo)", "green"

    st.sidebar.metric("Pontuação Total iAMB", f"{total_pts:.1f} pts")
    st.sidebar.markdown(
        f"**Faixa:** <span style='color:{cor}; font-size:18px; font-weight:bold;'>{faixa}</span>",
        unsafe_allow_html=True
    )

    st.sidebar.divider()
    
    col1, col2 = st.sidebar.columns(2)
    
    # Botão de Download direto
    with col1:
        st.download_button(
            label="📄 Baixar PDF",
            data=gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa),
            file_name=f"Relatorio_iAMB_{ano_sel}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    # Botão para abrir o Modal de confirmação
    with col2:
        if st.button("🔄 Zerar", help="Limpar todas as respostas do ano selecionado", use_container_width=True):
            confirmar_zerar_dialog(ano_sel)

    return total_pts, res_data, ano_sel

# =============================================================================
# 5. GRÁFICOS E HISTÓRICO - iAMB
# =============================================================================

def get_all_years_data_iamb() -> dict:
    """Busca o histórico de dados de todos os anos para a métrica iAMB."""
    all_data = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT ano FROM respostas WHERE modulo = 'iamb' ORDER BY ano"
                )
                anos = [row[0] for row in cursor.fetchall()]
                for ano in anos:
                    all_data[ano] = load_respostas(ano)
    except Exception as e:
        logging.error(f"Erro ao buscar histórico de anos iAMB: {e}")
    return all_data


def get_faixa_iamb(total):
    if total <= 500: return "C - Inefetivo"
    if total <= 599: return "C+ - Em Adequação"
    if total <= 749: return "B - Efetivo"
    if total <= 899: return "B+ - Muito Efetivo"
    return "A - Altamente Efetivo"


def grafico_pontos_por_ano(all_data):
    """Gráfico de barras vertical com pontos totais por ano para o iAMB."""
    anos = sorted(all_data.keys())
    totais = []
    cores = []
    
    for ano in anos:
        res = all_data[ano]
        total = sum(v.get("pontos", 0.0) for k, v in res.items() if not k.startswith("COM_"))
        totais.append(total)
        
        if total <= 500:   cores.append("#ef4444")  # Vermelho
        elif total <= 599: cores.append("#f97316")  # Laranja
        elif total <= 749: cores.append("#eab308")  # Amarelo
        elif total <= 899: cores.append("#84cc16")  # Verde Claro
        else:              cores.append("#16a34a")  # Verde Escuro
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[str(a) for a in anos],
        y=totais,
        marker_color=cores,
        text=[f"{t:.1f} pts" for t in totais],
        textposition="outside",
        hovertemplate="<b>Ano: %{x}</b><br>iAMB Total: %{y:.1f} pts<extra></extra>",
    ))
    
    fig.update_layout(
        title="Índice Histórico iAMB (Gestão Ambiental) por Exercício",
        xaxis_title="Ano",
        yaxis_title="Pontuação iAMB",
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        height=400,
    )
    
    return fig


def render_graficos(res_data_atual, ano_sel):
    st.header("📊 Painel de Análise do iAMB")
    
    all_data = get_all_years_data_iamb()
    
    if not all_data:
        st.info("Nenhum dado do iAMB registrado ainda. Preencha os itens para visualizar os gráficos.")
        return

    st.plotly_chart(grafico_pontos_por_ano(all_data), use_container_width=True)

# =============================================================================
# 6. FORMULÁRIO PRINCIPAL - iAMB
# =============================================================================

def mostrar_formulario_iamb():
    dados_sidebar = render_sidebar()
    
    if dados_sidebar and len(dados_sidebar) == 3:
        total_pts, res_data, ano_sel = dados_sidebar
    else:
        total_pts, res_data, ano_sel = 0.0, {}, 2026

    st.title(f"🌿 Gestão Ambiental (iAMB) - {ano_sel}")

    aba_quest, aba_graf = st.tabs(["📋 Questionário iAMB", "📊 Gráficos e Evolução"])

    # -------------------------------------------------------------------------
    # ABA 1: QUESTIONÁRIO (Quesitos entram AQUI)
    # -------------------------------------------------------------------------
    with aba_quest:
        st.info("Responda às questões da gestão ambiental municipal para calcular o índice iAMB.")

        
