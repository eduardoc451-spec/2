import json
import logging
import os
import re
import sys
import warnings
from datetime import date, datetime
from io import BytesIO

import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from plotly.subplots import make_subplots
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import streamlit as st

# Imports de componentes ReportLab para relatórios em PDF do iAMB
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import json
import logging
import os
import re
import warnings
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES DE AMBIENTE E BANCO DE DADOS NEON
# -----------------------------------------------------------------------------
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore")
os.environ["STREAMLIT_LOGGER_LEVEL"] = "error"
os.environ["PYTHONWARNINGS"] = "ignore"
logging.getLogger("streamlit").setLevel(logging.ERROR)


def get_connection():
    """Conecta ao banco Neon PostgreSQL usando st.secrets."""
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def init_db():
    """Cria a tabela respostas_iamb idêntica à estrutura configurada no Neon."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS respostas_iamb (
                        id SERIAL PRIMARY KEY,
                        ano INT NOT NULL,
                        quesito VARCHAR(50) NOT NULL,
                        resposta TEXT,
                        pontos DOUBLE PRECISION DEFAULT 0.0,
                        detalhes JSONB DEFAULT '{}'::jsonb,
                        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT unq_ano_quesito_iamb UNIQUE(ano, quesito)
                    );
                """)
            conn.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar banco iAMB: {e}")


# Inicializa a tabela no carregamento do módulo
try:
    init_db()
except Exception as e:
    logging.error(f"Erro no auto-init do iAMB: {e}")

# =============================================================================
# REGEX DE VALIDAÇÃO
# =============================================================================
REGEX_PURE_URL = r'((https?://[^\s<>"]+))'

# =============================================================================
# CONSTANTES GLOBAIS - IAMB
# =============================================================================
PONTUACOES_MAX_IAMB = {
    "1.1.2": 20.0, "1.1.3": 5.0, "1.2": 20.0, "2.0": 10.0, "2.1": 50.0,
    "3.0": 10.0, "3.1": 20.0, "4.0": 20.0, "5.2.1": 20.0, "6.0": 20.0,
    "6.1": 50.0, "6.2": 25.0, "7.2": 2.0, "7.3": 10.0, "7.3.1": 20.0,
    "7.4": 10.0, "7.4.1": 20.0, "7.5": 30.0, "7.7": 30.0, "7.8": 20.0,
    "7.8.1": 50.0, "7.9": 3.0, "8.2": 2.0, "8.3": 10.0, "8.4": 20.0,
    "8.4.1": 10.0, "8.4.2": 30.0, "8.4.3": 50.0, "9.2": 100.0, "9.3": 5.0,
    "9.3.1": 5.0, "11.2": 2.0, "11.3": 30.0, "11.3.2": 20.0, "11.3.3": 40.0,
    "11.5": 10.0, "12.1": 54.0, "14.3": 30.0, "15": 2.0, "15.1": 3.0,
    "A4.1.1": 90.0, "A4.1.2": 20.0, "A4.1.3": 22.0, "A6": 5.0
}

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
# 1. GESTÃO DE ESTADO E PERSISTÊNCIA (SESSION STATE + NEON POSTGRES)
# =============================================================================

def get_ano_atual() -> int:
    """Recupera o ano de referência ativo para o iAMB."""
    return int(st.session_state.get("ano_referencia_iamb") or st.session_state.get("ano_referencia_global") or 2026)


def load_respostas(ano: int = None) -> dict:
    """Carrega respostas do st.session_state ou do Neon (lendo a coluna detalhes)."""
    if ano is None:
        ano = get_ano_atual()
    
    key_ano = f"respostas_iamb_{ano}"
    
    if key_ano not in st.session_state:
        st.session_state[key_ano] = {}
        # Carrega do banco Neon
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        "SELECT quesito, resposta, pontos, detalhes FROM respostas_iamb WHERE ano = %s",
                        (int(ano),)
                    )
                    rows = cursor.fetchall()
                    for r in rows:
                        detalhes = r.get('detalhes') or {}
                        if isinstance(detalhes, str):
                            try:
                                detalhes = json.loads(detalhes)
                            except Exception:
                                detalhes = {}

                        st.session_state[key_ano][str(r['quesito'])] = {
                            "valor": r['resposta'] or "",
                            "pontos": float(r['pontos'] or 0.0),
                            "link": detalhes.get("link", ""),
                            "comentarios": detalhes.get("comentarios", []),
                            "comentario": detalhes.get("comentario", ""),
                            "detalhes": detalhes
                        }
        except Exception as e:
            logging.error(f"Erro ao carregar respostas do banco iAMB: {e}")

    return st.session_state[key_ano]


def save_resp(qid, valor, pontos, link="", comentarios=None, comentario=""):
    """Salva/Atualiza respostas no st.session_state e sincroniza com a tabela respostas_iamb no Neon."""
    ano_int = get_ano_atual()
    key_ano = f"respostas_iamb_{ano_int}"
    
    if key_ano not in st.session_state:
        st.session_state[key_ano] = {}

    dados_atuais = st.session_state[key_ano].get(str(qid), {})

    if comentarios is None:
        comentarios = dados_atuais.get("comentarios", [])
        
    if not comentario:
        comentario = dados_atuais.get("comentario", "")

    # Monta o pacote JSON para a coluna 'detalhes'
    dados_detalhes = {
        "link": str(link or ""),
        "comentarios": comentarios,
        "comentario": str(comentario or "")
    }

    # 1. Atualiza Session State
    dados_salvar = {
        "valor": str(valor),
        "pontos": float(pontos),
        "link": str(link or ""),
        "comentarios": comentarios,
        "comentario": str(comentario or ""),
        "detalhes": dados_detalhes,
        "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    st.session_state[key_ano][str(qid)] = dados_salvar

    # 2. Persiste no banco de dados Neon (UPSERT nas colunas exatas da tabela respostas_iamb)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO respostas_iamb (ano, quesito, resposta, pontos, detalhes, atualizado_em)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (ano, quesito) 
                    DO UPDATE SET 
                        resposta = EXCLUDED.resposta,
                        pontos = EXCLUDED.pontos,
                        detalhes = EXCLUDED.detalhes,
                        atualizado_em = CURRENT_TIMESTAMP;
                """, (
                    int(ano_int),
                    str(qid),
                    str(valor),
                    float(pontos),
                    json.dumps(dados_detalhes)
                ))
            conn.commit()
            return True
    except Exception as e:
        logging.error(f"Erro ao salvar resposta do iAMB no banco Neon: {e}")
        st.error(f"Erro ao salvar no banco Neon: {e}")
        return False

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
# 3. FUNÇÕES DE ANÁLISE E HISTÓRICO (iAMB)
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
    """Mapeia os pontos fortes e fragilidades do ano atual no iAMB usando PONTUACOES_MAX_IAMB."""
    pontos_fortes = []
    criticos_zero = {"Alta": [], "Média": [], "Baixa": []}
    criticos_negativos = {"Alta": [], "Média": [], "Baixa": []}

    def classificar_relevancia(impacto):
        abs_impacto = abs(impacto)
        if abs_impacto >= 16:
            return "Alta"
        elif 6 <= abs_impacto <= 15:
            return "Média"
        else:
            return "Baixa"

    for qid, info in res_data.items():
        if qid.startswith("COM_") or qid not in PONTUACOES_MAX_IAMB:
            continue

        pontos_atuais = float(info.get("pontos", 0.0))
        max_pontos = PONTUACOES_MAX_IAMB[qid]

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
import re
from datetime import datetime

import plotly.graph_objects as go
from psycopg2.extras import RealDictCursor
import streamlit as st

# =============================================================================
# 4. SIDEBAR - iAMB
# =============================================================================

def zerar_questionario_iamb(ano: int):
    """Deleta todas as respostas do ano selecionado na tabela respostas_iamb."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM respostas_iamb WHERE ano = %s",
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
                    zerar_questionario_iamb(ano)
                    
                    # Limpa a sessão
                    key_ano = f"respostas_iamb_{ano}"
                    st.session_state[key_ano] = {}
                    
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
    
    # Seleção do ano no session_state
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_iamb")

    res_data = load_respostas(ano_sel)
    total_pts = sum(item.get("pontos", 0.0) for item in res_data.values() if isinstance(item, dict))

    # Régua de Classificação IEGM / iAMB
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

    st.sidebar.metric("Pontuação Total iAMB", f"{total_pts:.1f} pts")
    st.sidebar.markdown(
        f"**Faixa:** <span style='color:{cor}; font-size:18px; font-weight:bold;'>{faixa}</span>",
        unsafe_allow_html=True
    )

    st.sidebar.divider()
    
    col1, col2 = st.sidebar.columns(2)
    
    # Botão de Download direto
    with col1:
        # Tratamento para verificar se a função gerar_relatorio_pdf existe no escopo
        pdf_bytes = b""
        if "gerar_relatorio_pdf" in globals():
            pdf_bytes = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa)
            
        st.download_button(
            label="📄 Baixar PDF",
            data=pdf_bytes,
            file_name=f"Relatorio_iAMB_{ano_sel}.pdf",
            mime="application/pdf",
            use_container_width=True,
            disabled=(pdf_bytes == b"")
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
    """Busca o histórico de dados de todos os anos salvos na tabela respostas_iamb e session_state."""
    all_data = {}
    
    # 1. Carrega via Banco
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT DISTINCT ano FROM respostas_iamb ORDER BY ano")
                anos_banco = [row[0] for row in cursor.fetchall()]
                for a in anos_banco:
                    all_data[a] = load_respostas(a)
    except Exception as e:
        logging.error(f"Erro ao buscar histórico de anos iAMB no banco: {e}")
        
    # 2. Carrega via Session State (para capturar anos ainda não persistidos)
    prefixo = "respostas_iamb_"
    for key in st.session_state.keys():
        if key.startswith(prefixo):
            try:
                ano = int(key.replace(prefixo, ""))
                if ano not in all_data or not all_data[ano]:
                    all_data[ano] = st.session_state[key]
            except ValueError:
                continue

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
        total = sum(v.get("pontos", 0.0) for k, v in res.items() if isinstance(v, dict) and not k.startswith("COM_"))
        totais.append(total)
        
        if total <= 500:    cores.append("#ef4444")  # Vermelho
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
    total_pts, res_data, ano_sel = render_sidebar()

    st.title(f"🌿 Gestão Ambiental (iAMB) - {ano_sel}")

    aba_quest, aba_graf = st.tabs(["📋 Questionário iAMB", "📊 Gráficos e Evolução"])

    with aba_quest:
        st.subheader("Formulário de Avaliação")
        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático via callback.*")

        # =============================================================================
        # QUESITO 1.0 • ESTRUTURA AMBIENTAL MUNICIPAL (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_iamb_1_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.0 - Estrutura Organizacional Ambiental", expanded=True):
                st.subheader("1.0 • Estrutura Ambiental")
                st.write(
                    "**A prefeitura possui alguma estrutura organizacional para tratar "
                    "de assuntos ligados ao Meio Ambiente Municipal?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.0' para registrar.*")

                # Dicionário com Mapeamento de Opções e Pontuações do iAMB
                opcoes_10 = {
                    "Selecione...": 0.0,
                    "Sim (30 pts)": 30.0,
                    "Não (00 pts)": 0.0
                }

                # Estado inicial / persistente
                d10 = res_data.get("1.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_10 = d10.get("valor", "Selecione...")
                
                # Trata migração de legado caso no banco esteja salvo apenas "Sim" ou "Não"
                if v_salvo_10 == "Sim":
                    v_salvo_10 = "Sim (30 pts)"
                elif v_salvo_10 == "Não":
                    v_salvo_10 = "Não (00 pts)"

                evidencia_10_salva = d10.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_10 = f"r_10_{ano_sel}"
                chave_link_10 = f"l_10_txt_{ano_sel}"
                chave_coment_10 = f"coment_1.0_{ano_sel}"  # Chave padrão do bloco_comentarios

                c10_1, c10_2 = st.columns([1, 1])
                with c10_1:
                    lista_opcoes_10 = list(opcoes_10.keys())
                    idx_10 = lista_opcoes_10.index(v_salvo_10) if v_salvo_10 in lista_opcoes_10 else 0

                    val_radio_10 = st.radio(
                        "Selecione a situação da Estrutura Ambiental:",
                        options=lista_opcoes_10,
                        index=idx_10,
                        key=chave_radio_10
                    )

                with c10_2:
                    link_10 = st.text_area(
                        "Link de Evidência / Organograma / Lei de Criação (1.0):",
                        value=evidencia_10_salva,
                        key=chave_link_10,
                        placeholder="Insira o link oficial do organograma ou lei da estrutura ambiental...",
                        height=100
                    )
                    placeholder_links_10 = st.empty()
                    links_10_visuais = re.findall(REGEX_PURE_URL, link_10 or "")
                    if links_10_visuais:
                        placeholder_links_10.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_10_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.0", key=f"btn_salvar_1_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_10, v_salvo_10)
                    pts_10 = float(opcoes_10.get(val_salvar, 0.0))
                    lnk_val = link_10.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_10, d10.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp(
                        qid="1.0",
                        valor=val_salvar,
                        pontos=pts_10,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_10,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_10_salva or "")]

                    if lnk_val != evidencia_10_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_10 = d10.get("pontos", 0.0)
                cor_txt_10 = "#28a745" if pts_atuais_10 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_10}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.0: +{pts_atuais_10:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.1 • DISPONIBILIDADE DE RECURSOS HUMANOS (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.1 - Recursos Humanos Operacionais", expanded=True):
                st.subheader("1.1 • Recursos Humanos")
                st.write("**A Prefeitura possui recursos humanos para operacionalização dos assuntos ligados ao Meio Ambiente?**")
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.1' para registrar.*")

                # Dicionário de Opções e Pontuações (Ajuste a pontuação se houver valor específico no iAMB)
                opcoes_11 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                lista_opcoes_11 = list(opcoes_11.keys())

                # Recupera estado inicial salvo
                d11 = res_data.get("1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_11 = d11.get("valor", "Selecione...")
                if v_salvo_11 not in lista_opcoes_11:
                    v_salvo_11 = "Selecione..."

                evidencia_11_salva = d11.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_11 = f"r_11_select_{ano_sel}"
                chave_link_11 = f"l_11_txt_area_{ano_sel}"
                chave_coment_11 = f"coment_1.1_{ano_sel}"

                c11_1, c11_2 = st.columns([1, 1])
                with c11_1:
                    idx11 = lista_opcoes_11.index(v_salvo_11) if v_salvo_11 in lista_opcoes_11 else 0
                    val_radio_11 = st.radio(
                        "Selecione a situação dos Recursos Humanos:",
                        options=lista_opcoes_11,
                        index=idx11,
                        key=chave_radio_11
                    )

                with c11_2:
                    link_11 = st.text_area(
                        "Link/Evidência (1.1):",
                        value=evidencia_11_salva,
                        key=chave_link_11,
                        placeholder="Insira o link com a relação de servidores, portarias de alocação, etc...",
                        height=110
                    )
                    placeholder_links_11 = st.empty()
                    links_11_visuais = re.findall(REGEX_PURE_URL, link_11 or "")
                    if links_11_visuais:
                        placeholder_links_11.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_11_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.1", key=f"btn_salvar_1_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_11, v_salvo_11)
                    pts_11 = float(opcoes_11.get(val_salvar, 0.0))
                    lnk_val = link_11.strip()

                    # Captura comentário da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_11, d11.get("comentario", ""))

                    # Grava no banco de dados Neon
                    save_resp(
                        qid="1.1",
                        valor=val_salvar,
                        pontos=pts_11,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.1"] = {
                        "valor": val_salvar,
                        "pontos": pts_11,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_11_salva or "")]

                    if lnk_val != evidencia_11_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                pts_atuais_11 = d11.get("pontos", 0.0)
                cor_txt_11 = "#28a745" if pts_atuais_11 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_11}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.1: +{pts_atuais_11:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.1.1 • QUANTIDADE DE PESSOAL (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.1.1 - Quadro Quantitativo de Servidores", expanded=True):
                st.subheader("1.1.1 • Detalhamento Quantitativo de Pessoal")
                st.write("**Informe a quantidade de pessoal alocado nas operações do Meio Ambiente:**")
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.1.1' para registrar.*")

                # Recupera o dicionário ou cria um padrão vazio estruturado
                d111 = res_data.get("1.1.1") or {"valor": "0", "pontos": 0.0, "link": "E:0, C:0, T:0 | Evidência: ", "comentario": ""}
                
                # Parse seguro dos valores numéricos salvos e do texto da evidência
                string_banco = d111.get("link", "E:0, C:0, T:0 | Evidência: ")
                try:
                    if " | Evidência: " in string_banco:
                        parte_numeros, evidencia_111_salva = string_banco.split(" | Evidência: ", 1)
                    else:
                        parte_numeros, evidencia_111_salva = string_banco, ""

                    parts = parte_numeros.split(",")
                    v_efe = int(parts[0].split(":")[1])
                    v_com = int(parts[1].split(":")[1])
                    v_ter = int(parts[2].split(":")[1])
                except Exception:
                    v_efe, v_com, v_ter = 0, 0, 0
                    evidencia_111_salva = ""

                # Chaves fixas por componente e ano
                chave_efe = f"q111_efe_num_{ano_sel}"
                chave_com = f"q111_com_num_{ano_sel}"
                chave_ter = f"q111_ter_num_{ano_sel}"
                chave_link_111 = f"l_111_txt_area_{ano_sel}"
                chave_coment_111 = f"coment_1.1.1_{ano_sel}"

                c111_1, c111_2 = st.columns([1, 1])
                with c111_1:
                    st.number_input("Servidores Efetivos:", min_value=0, value=v_efe, key=chave_efe)
                    st.number_input("Cargos Comissionados:", min_value=0, value=v_com, key=chave_com)
                    st.number_input("Profissionais Terceirizados:", min_value=0, value=v_ter, key=chave_ter)

                with c111_2:
                    n_efe_cur = st.session_state.get(chave_efe, v_efe)
                    n_com_cur = st.session_state.get(chave_com, v_com)
                    n_ter_cur = st.session_state.get(chave_ter, v_ter)
                    total_atual = n_efe_cur + n_com_cur + n_ter_cur

                    st.info(f"👥 **Força de Trabalho Total Calculada:** {total_atual} colaboradores")

                    link_111 = st.text_area(
                        "Link/Evidência (1.1.1):",
                        value=evidencia_111_salva,
                        key=chave_link_111,
                        placeholder="Insira o link do diário oficial, portal da transparência ou documento comprobatório do quadro...",
                        height=115
                    )
                    placeholder_links_111 = st.empty()
                    links_111_visuais = re.findall(REGEX_PURE_URL, link_111 or "")
                    if links_111_visuais:
                        placeholder_links_111.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_111_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.1.1", key=f"btn_salvar_1_1_1_{ano_sel}", type="primary"):
                    n_efe_salvar = st.session_state.get(chave_efe, v_efe)
                    n_com_salvar = st.session_state.get(chave_com, v_com)
                    n_ter_salvar = st.session_state.get(chave_ter, v_ter)
                    total_rh = n_efe_salvar + n_com_salvar + n_ter_salvar

                    lnk_val = link_111.strip()
                    str_formatada_banco = f"E:{n_efe_salvar}, C:{n_com_salvar}, T:{n_ter_salvar} | Evidência: {lnk_val}"

                    comentario_para_salvar = st.session_state.get(chave_coment_111, d111.get("comentario", ""))

                    # Grava no banco de dados Neon
                    save_resp(
                        qid="1.1.1",
                        valor=str(total_rh),
                        pontos=0.0,
                        link=str_formatada_banco,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.1.1"] = {
                        "valor": str(total_rh),
                        "pontos": 0.0,
                        "link": str_formatada_banco,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_111_salva or "")]

                    if lnk_val != evidencia_111_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo visual da pontuação
                pts_atuais_111 = d111.get("pontos", 0.0)
                cor_txt_111 = "#28a745" if pts_atuais_111 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_111}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.1.1: +{pts_atuais_111:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.1.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.1.1", st.session_state.get(f"links_pendentes_1_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.1.2 • TREINAMENTO ESPECÍFICO (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.1.2 - Capacitação da Equipe Técnica", expanded=True):
                st.subheader("1.1.2 • Treinamento Específico")
                ano_anterior = int(ano_sel) - 1
                st.write(f"**Os servidores responsáveis pelo Meio Ambiente receberam treinamento específico voltado ao Meio Ambiente em {ano_anterior}?**")
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.1.2' para registrar.*")

                # Dicionário de Opções e Pontuações
                opcoes_112 = {
                    "Selecione...": 0.0,
                    "Sim – 20": 20.0,
                    "Não – 00": 0.0
                }
                lista_opcoes_112 = list(opcoes_112.keys())

                # Recupera o estado inicial do banco ou padrão
                d112 = res_data.get("1.1.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_112 = d112.get("valor", "Selecione...")
                
                # Trata migrações de legado (caso esteja salvo como "Sim" ou "Não")
                if v_salvo_112 == "Sim":
                    v_salvo_112 = "Sim – 20"
                elif v_salvo_112 == "Não":
                    v_salvo_112 = "Não – 00"

                if v_salvo_112 not in lista_opcoes_112:
                    v_salvo_112 = "Selecione..."

                evidencia_112_salva = d112.get("link", "")

                # Chaves fixas do Streamlit por ano e componente
                chave_radio_112 = f"r_112_select_{ano_sel}"
                chave_link_112 = f"l_112_txt_area_{ano_sel}"
                chave_coment_112 = f"coment_1.1.2_{ano_sel}"

                c112_1, c112_2 = st.columns([1, 1])
                with c112_1:
                    idx112 = lista_opcoes_112.index(v_salvo_112) if v_salvo_112 in lista_opcoes_112 else 0
                    val_radio_112 = st.radio(
                        "Selecione a situação do Treinamento:",
                        options=lista_opcoes_112,
                        index=idx112,
                        key=chave_radio_112
                    )

                with c112_2:
                    link_112 = st.text_area(
                        "Link/Evidência (1.1.2):",
                        value=evidencia_112_salva,
                        key=chave_link_112,
                        placeholder="Insira os certificados, portarias de cursos ou listas de presença...",
                        height=110
                    )
                    placeholder_links_112 = st.empty()
                    links_112_visuais = re.findall(REGEX_PURE_URL, link_112 or "")
                    if links_112_visuais:
                        placeholder_links_112.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_112_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.1.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.1.2", key=f"btn_salvar_1_1_2_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_112, v_salvo_112)
                    pts_112 = float(opcoes_112.get(val_salvar, 0.0))
                    lnk_val = link_112.strip()

                    # Captura comentário da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_112, d112.get("comentario", ""))

                    # Grava no banco de dados Neon
                    save_resp(
                        qid="1.1.2",
                        valor=val_salvar,
                        pontos=pts_112,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.1.2"] = {
                        "valor": val_salvar,
                        "pontos": pts_112,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de aviso
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_112_salva or "")]

                    if lnk_val != evidencia_112_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.1.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo do impacto da pontuação
                pts_atuais_112 = d112.get("pontos", 0.0)
                cor_txt_112 = "#28a745" if pts_atuais_112 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_112}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.1.2: +{pts_atuais_112:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.1.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_1_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.1.2", st.session_state.get(f"links_pendentes_1_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.1.3 • CURSOS DE EDUCAÇÃO AMBIENTAL (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.1.3 - Cursos e Treinamentos Oferecidos à Comunidade", expanded=True):
                st.subheader("1.1.3 • Educação Ambiental")
                st.write("**A Secretaria Municipal de Meio Ambiente ou similar ofereceu cursos/treinamento sobre educação ambiental para qual público?**")
                st.caption("ℹ *Marque as opções aplicáveis e clique no botão 'Salvar Quesito 1.1.3' para registrar.*")

                opts113 = {
                    "Para escolas – 05": 5.0, 
                    "Para outras secretarias / entidades municipais – 02": 2.0, 
                    "Para munícipes ou empresas – 03": 3.0, 
                    "Não ofereceu nenhum curso/treinamento no ano – 00": 0.0
                }

                # Recupera os dados salvos no banco ou cria valor zerado
                d113 = res_data.get("1.1.3") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                texto_seguro_113 = str(d113.get("valor", "[]"))
                evidencia_113_salva = d113.get("link", "")

                # Chaves fixas para componentes Streamlit
                chave_link_113 = f"l_113_txt_area_{ano_sel}"
                chave_coment_113 = f"coment_1.1.3_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.write("*Selecione os públicos-alvo atendidos:*")
                    for txt, pts in opts113.items():
                        marcado = (txt in texto_seguro_113) if texto_seguro_113 and texto_seguro_113 != "[]" else False
                        st.checkbox(
                            txt,
                            value=marcado,
                            key=f"ck_113_{txt}_{ano_sel}"
                        )

                with col2:
                    link_113 = st.text_area(
                        "Link/Evidência (1.1.3):",
                        value=evidencia_113_salva,
                        key=chave_link_113,
                        placeholder="Links de fotos de divulgação, diário oficial, decretos ou notícias dos cursos...",
                        height=150
                    )
                    placeholder_links_113 = st.empty()
                    links_113_visuais = re.findall(REGEX_PURE_URL, link_113 or "")
                    if links_113_visuais:
                        placeholder_links_113.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_113_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.1.3", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.1.3", key=f"btn_salvar_1_1_3_{ano_sel}", type="primary"):
                    # Coleta as escolhas ativas no session_state
                    lista_selecionados = []
                    pts_totais = 0.0
                    for txt, pts in opts113.items():
                        if st.session_state.get(f"ck_113_{txt}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    val_salvar = str(lista_selecionados)
                    lnk_val = link_113.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_113, d113.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="1.1.3",
                        valor=val_salvar,
                        pontos=pts_totais,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["1.1.3"] = {
                        "valor": val_salvar,
                        "pontos": pts_totais,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_113_salva or "")]

                    if lnk_val != evidencia_113_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_1_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_1_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.1.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                pts_atuais_113 = d113.get("pontos", 0.0)
                cor_txt_113 = "#28a745" if pts_atuais_113 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_113}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.1.3: +{pts_atuais_113:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.1.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_1_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.1.3", st.session_state.get(f"links_pendentes_1_1_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.2 • RECURSOS DISPONIBILIZADOS (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_recursos_1_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.2 - Recursos Disponibilizados Operacionais", expanded=True):
                st.subheader("1.2 • Recursos Operacionais")
                st.write("**Assinale os recursos disponibilizados para a operacionalização das atividades de meio ambiente: Não considerar Recursos Humanos e Estrutura Física nesta questão.**")
                st.caption("ℹ *Marque as opções aplicáveis e clique no botão 'Salvar Quesito 1.2' para registrar.*")

                opts12 = [
                    "Recursos Tecnológicos – 05",
                    "Recursos Orçamentários – 05",
                    "Recursos Materiais – 05",
                    "Outros – 05"
                ]

                # Recupera os dados salvos no banco ou cria valor zerado
                d12 = res_data.get("1.2") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                texto_seguro_12 = str(d12.get("valor", "[]"))
                evidencia_12_salva = d12.get("link", "")

                # Chaves fixas para componentes Streamlit
                chave_link_12 = f"l_12_txt_area_{ano_sel}"
                chave_coment_12 = f"coment_1.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.write("*Selecione os recursos ativos:*")
                    for opt in opts12:
                        marcado = (opt in texto_seguro_12) if texto_seguro_12 and texto_seguro_12 != "[]" else False
                        st.checkbox(
                            opt,
                            value=marcado,
                            key=f"ck_12_{opt}_{ano_sel}"
                        )

                with col2:
                    link_12 = st.text_area(
                        "Link/Evidência (1.2):",
                        value=evidencia_12_salva,
                        key=chave_link_12,
                        placeholder="Links da LOA/QDD para orçamento, notas fiscais ou inventário de sistemas/materiais...",
                        height=150
                    )
                    placeholder_links_12 = st.empty()
                    links_12_visuais = re.findall(REGEX_PURE_URL, link_12 or "")
                    if links_12_visuais:
                        placeholder_links_12.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_12_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.2", key=f"btn_salvar_1_2_{ano_sel}", type="primary"):
                    # Coleta as escolhas ativas no session_state
                    lista_selecionados = []
                    pts_totais = 0.0
                    for opt in opts12:
                        if st.session_state.get(f"ck_12_{opt}_{ano_sel}", False):
                            lista_selecionados.append(opt)
                            pts_totais += 5.0

                    val_salvar = str(lista_selecionados)
                    lnk_val = link_12.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_12, d12.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="1.2",
                        valor=val_salvar,
                        pontos=pts_totais,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["1.2"] = {
                        "valor": val_salvar,
                        "pontos": pts_totais,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_12_salva or "")]

                    if lnk_val != evidencia_12_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                pts_atuais_12 = d12.get("pontos", 0.0)
                cor_txt_12 = "#28a745" if pts_atuais_12 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_12}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.2: +{pts_atuais_12:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 2.0 • PARTICIPAÇÃO EM PROGRAMA DE EDUCAÇÃO AMBIENTAL (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_prog_2_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 2.0 - Programa de Educação Ambiental", expanded=True):
                st.subheader("2.0 • Programa de Educação Ambiental")
                st.write("**O Município participa de algum Programa de Educação Ambiental?**")
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 2.0' para registrar.*")

                opc20 = ["Selecione...", "Sim – 10", "Não – 00"]
                
                # Recupera os dados salvos no banco ou cria valor padrão
                d20 = res_data.get("2.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_20 = d20.get("valor", "Selecione...")
                if v_salvo_20 not in opc20:
                    v_salvo_20 = "Selecione..."
                
                evidencia_20_salva = d20.get("link", "")

                # Chaves fixas para componentes Streamlit
                chave_radio_20 = f"r_20_select_{ano_sel}"
                chave_link_20 = f"l_20_txt_area_{ano_sel}"
                chave_coment_20 = f"coment_2.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx20 = opc20.index(v_salvo_20) if v_salvo_20 in opc20 else 0
                    val_radio_20 = st.radio(
                        "Selecione uma opção (2.0):",
                        options=opc20,
                        index=idx20,
                        key=chave_radio_20
                    )

                with col2:
                    link_20 = st.text_area(
                        "Link/Evidência (2.0):",
                        value=evidencia_20_salva,
                        key=chave_link_20,
                        placeholder="Insira o link oficial contendo o plano, adesão ou portaria do Programa...",
                        height=110
                    )
                    placeholder_links_20 = st.empty()
                    links_20_visuais = re.findall(REGEX_PURE_URL, link_20 or "")
                    if links_20_visuais:
                        placeholder_links_20.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_20_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("2.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 2.0", key=f"btn_salvar_2_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_20, v_salvo_20)
                    lnk_val = link_20.strip()
                    pts_calculados = 10.0 if "Sim" in str(val_salvar) else 0.0
                    
                    # Captura o comentário atual da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_20, d20.get("comentario", ""))

                    # Gravação no banco de dados Neon
                    save_resp(
                        qid="2.0",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["2.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_20_salva or "")]

                    if lnk_val != evidencia_20_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 2.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                pts_atuais_20 = d20.get("pontos", 0.0)
                v_val_atual = d20.get("valor", "")
                cor_txt_20 = "#28a745" if "Sim" in str(v_val_atual) else ("#dc3545" if "Não" in str(v_val_atual) else "#6c757d")

                st.markdown(
                    f"<span style='color:{cor_txt_20}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 2.0: +{pts_atuais_20:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 2.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 2.1 • AÇÃO EM REDE ESCOLAR MUNICIPAL (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_prog_2_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 2.1 - Cobertura de Educação Ambiental na Rede Escolar", expanded=True):
                st.subheader("2.1 • Ação em Rede Escolar")
                st.write("**Sobre programa ou ação de educação ambiental na rede escolar municipal, informe o número de escolas dos Anos Iniciais (1º ao 5º ano) que adotam o programa.**")
                st.caption("ℹ *Informe as métricas, adicione os links/comentários e clique no botão 'Salvar Quesito 2.1' para registrar.*")

                # Recupera os dados salvos no banco ou valores zerados
                d21 = res_data.get("2.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                raw_valor = d21.get("valor", "")

                # Extração segura do JSON
                try:
                    valores_salvos = json.loads(raw_valor) if raw_valor else {"n_com_programa": 0, "n_total": 1}
                except (json.JSONDecodeError, TypeError):
                    valores_salvos = {"n_com_programa": 0, "n_total": 1}

                v_com_programa_salvo = int(valores_salvos.get("n_com_programa", 0))
                v_total_salvo = int(valores_salvos.get("n_total", 1))
                evidencia_21_salva = d21.get("link", "")

                # Chaves fixas para componentes Streamlit
                chave_com_prog = f"q21_com_prog_num_{ano_sel}"
                chave_total_escolas = f"q21_total_num_{ano_sel}"
                chave_link_21 = f"l_21_txt_area_{ano_sel}"
                chave_coment_21 = f"coment_2.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("**Métricas da Rede Pública:**")
                    st.number_input(
                        "Nº de escolas com programa/ação ambiental:",
                        min_value=0,
                        value=v_com_programa_salvo,
                        key=chave_com_prog
                    )
                    st.number_input(
                        "Nº total de escolas de Anos Iniciais no município (i-Educ = E3.3):",
                        min_value=1,
                        value=v_total_salvo,
                        key=chave_total_escolas
                    )

                with col2:
                    link_21 = st.text_area(
                        "Link/Evidência (2.1):",
                        value=evidencia_21_salva,
                        key=chave_link_21,
                        placeholder="Insira o link contendo o relatório pedagógico, censo escolar municipal ou portarias das ações nas escolas...",
                        height=140
                    )
                    placeholder_links_21 = st.empty()
                    links_21_visuais = re.findall(REGEX_PURE_URL, link_21 or "")
                    if links_21_visuais:
                        placeholder_links_21.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_21_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("2.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 2.1", key=f"btn_salvar_2_1_{ano_sel}", type="primary"):
                    n_com_prog = st.session_state.get(chave_com_prog, v_com_programa_salvo)
                    n_tot = st.session_state.get(chave_total_escolas, v_total_salvo)
                    lnk_val = link_21.strip()

                    # Cálculo da proporção e pontuação limite (máx. 50.0)
                    den = n_tot if n_tot > 0 else 1
                    proporcao = n_com_prog / den
                    pts_calculados = float(min(proporcao * 50.0, 50.0))

                    valores_formatados = json.dumps({"n_com_programa": n_com_prog, "n_total": n_tot})
                    comentario_para_salvar = st.session_state.get(chave_coment_21, d21.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="2.1",
                        valor=valores_formatados,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["2.1"] = {
                        "valor": valores_formatados,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_21_salva or "")]

                    if lnk_val != evidencia_21_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                pts_atuais_21 = d21.get("pontos", 0.0)
                cor_txt_21 = "#28a745" if pts_atuais_21 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_21}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 2.1: +{pts_atuais_21:.2f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 2.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("2.1", st.session_state.get(f"links_pendentes_2_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.0 • ESTÍMULO AO USO RACIONAL DE RECURSOS NATURAIS (MODELO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_recursos_3_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 3.0 - Estímulo ao Uso Racional de Recursos", expanded=True):
                st.subheader("3.0 • Estímulo ao Uso Racional")
                st.write("**A prefeitura municipal estimula entre seus órgãos e entidades de sua responsabilidade projetos e/ou ações que promovam o uso racional de recursos naturais? Ex.: implantação de dispositivos para uso racional da água, coleta seletiva, reuso ou reciclagem de material entre outros.**")
                st.caption("ℹ *Selecione a opção aplicável, informe o link de evidência/comentário e clique no botão 'Salvar Quesito 3.0' para registrar.*")

                opc30 = ["Selecione...", "Sim, para todos os órgãos e entidades – 10", "Parcialmente - 3", "Não – 00"]
                
                # Recupera os dados salvos no banco ou valor zerado
                d30 = res_data.get("3.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_30 = d30.get("valor", "Selecione...")
                if v_salvo_30 not in opc30:
                    v_salvo_30 = "Selecione..."
                
                evidencia_30_salva = d30.get("link", "")

                # Chaves fixas para componentes Streamlit
                chave_radio_30 = f"r_30_select_{ano_sel}"
                chave_link_30 = f"l_30_txt_area_{ano_sel}"
                chave_coment_30 = f"coment_3.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx30 = opc30.index(v_salvo_30) if v_salvo_30 in opc30 else 0
                    val_radio_30 = st.radio(
                        "Selecione uma opção (3.0):",
                        options=opc30,
                        index=idx30,
                        key=chave_radio_30
                    )

                with col2:
                    link_30 = st.text_area(
                        "Link/Evidência (3.0):",
                        value=evidencia_30_salva,
                        key=chave_link_30,
                        placeholder="Insira o link de diretrizes, decretos de sustentabilidade institucional ou campanhas internas...",
                        height=110
                    )
                    placeholder_links_30 = st.empty()
                    links_30_visuais = re.findall(REGEX_PURE_URL, link_30 or "")
                    if links_30_visuais:
                        placeholder_links_30.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_30_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("3.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 3.0", key=f"btn_salvar_3_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_30, v_salvo_30)
                    lnk_val = link_30.strip()
                    
                    # Regra de pontuação
                    if "todos" in str(val_salvar):
                        pts_calculados = 10.0
                    elif "Parcialmente" in str(val_salvar):
                        pts_calculados = 3.0
                    else:
                        pts_calculados = 0.0

                    # Captura o comentário do estado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_30, d30.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="3.0",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["3.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_30_salva or "")]

                    if lnk_val != evidencia_30_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 3.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                pts_atuais_30 = d30.get("pontos", 0.0)
                v_val_atual = d30.get("valor", "")
                
                if pts_atuais_30 == 10.0:
                    cor_txt_30 = "#28a745"
                elif pts_atuais_30 == 3.0:
                    cor_txt_30 = "#ffc107"
                else:
                    cor_txt_30 = "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_30}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 3.0: +{pts_atuais_30:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 3.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.1 • AÇÕES REALIZADAS PELO MUNICÍPIO (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_recursos_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 3.1 - Tipos de Ações de Uso Racional Praticadas", expanded=True):
                st.subheader("3.1 • Ações Realizadas")
                st.write("**Assinale quais tipos de ações realizadas pela Prefeitura para o uso racional de recursos naturais:**")
                st.caption("ℹ *Marque todas as ações executadas, insira os links de evidência/comentários e clique no botão 'Salvar Quesito 3.1' para registrar.*")

                opts31 = {
                    "Coleta seletiva – 1,5": 1.5,
                    "Uso racional da água – 1,5": 1.5,
                    "Uso racional de energia elétrica – 1,5": 1.5,
                    "Reúso de materiais – 1,5": 1.5,
                    "Horta coletiva – 1,5": 1.5,
                    "Compostagem – 1,5": 1.5,
                    "Instalação de bicicletários e vestiários para os servidores públicos – 1,5": 1.5,
                    "Implantação de caixas acopladas nos vasos sanitários – 1,5": 1.5,
                    "Substituição de lâmpadas fluorescentes por lâmpadas LED – 1,5": 1.5,
                    "Instalação de estruturas para a captação de água de chuva – 1,5": 1.5,
                    "Instalação de torneiras com redutores de pressão – 1,5": 1.5,
                    "Substituição de material descartável – 1,5": 1.5,
                    "Logística reversa de pilhas, baterias e eletrônicos – 1,5": 1.5,
                    "Outros – 0,5": 0.5
                }

                # Recupera os dados salvos no banco de dados ou estrutura padrão
                d31 = res_data.get("3.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                texto_seguro_31 = str(d31.get("valor", "[]"))
                evidencia_31_salva = d31.get("link", "")

                # Chaves fixas de componentes no Streamlit
                chave_link_31 = f"l_31_txt_area_{ano_sel}"
                chave_coment_31 = f"coment_3.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.write("*Selecione as iniciativas em execução:*")
                    for i, (txt, pts) in enumerate(opts31.items()):
                        # Identifica se a opção estava salva anteriormente
                        marcado = (txt in texto_seguro_31) if texto_seguro_31 and texto_seguro_31 != "[]" else False
                        st.checkbox(
                            txt,
                            value=marcado,
                            key=f"ck_31_opt_{i}_{ano_sel}"
                        )

                with col2:
                    link_31 = st.text_area(
                        "Link/Evidência (3.1):",
                        value=evidencia_31_salva,
                        key=chave_link_31,
                        placeholder="Insira os links comprobatórios das iniciativas marcadas (contratos de LED, fotos de cisternas, etc)...",
                        height=320
                    )
                    placeholder_links_31 = st.empty()
                    links_31_visuais = re.findall(REGEX_PURE_URL, link_31 or "")
                    if links_31_visuais:
                        placeholder_links_31.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_31_visuais]))

                # Renderiza o bloco de comentários
                bloco_comentarios("3.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 3.1", key=f"btn_salvar_3_1_{ano_sel}", type="primary"):
                    lista_selecionados = []
                    pts_totais = 0.0

                    # Varre todos os checkboxes e soma a pontuação
                    for idx, (txt, pts) in enumerate(opts31.items()):
                        if st.session_state.get(f"ck_31_opt_{idx}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    lnk_val = link_31.strip()
                    val_salvar = json.dumps(lista_selecionados, ensure_ascii=False)
                    comentario_para_salvar = st.session_state.get(chave_coment_31, d31.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="3.1",
                        valor=val_salvar,
                        pontos=pts_totais,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["3.1"] = {
                        "valor": val_salvar,
                        "pontos": pts_totais,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_31_salva or "")]

                    if lnk_val != evidencia_31_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual da pontuação
                pts_atuais_31 = d31.get("pontos", 0.0)
                cor_txt_31 = "#28a745" if pts_atuais_31 > 0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_31}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 3.1: +{pts_atuais_31:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False

# =============================================================================
        # QUESITO 4.0 • FISCALIZAÇÃO DE EMISSÃO DE POLUENTES (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_poluentes_4_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 4.0 - Fiscalização de Emissões Veiculares", expanded=True):
                st.subheader("4.0 • Emissão de Poluentes")
                st.write("**O município fiscalizou a emissão de poluentes de combustíveis fósseis (diesel) na frota da Prefeitura Municipal?**")
                st.caption("ℹ *Selecione a opção aplicável, informe o link de evidência/comentário e clique no botão 'Salvar Quesito 4.0' para registrar.*")

                opc40 = [
                    "Selecione...",
                    "Sim, com medição da densidade colorimétrica da Escala Ringelmann ou equivalente – 20",
                    "Sim, através de outra forma de medição – 15",
                    "Não – 00"
                ]

                # Recupera os dados salvos no banco ou estrutura zerada
                d40 = res_data.get("4.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_40 = d40.get("valor", "Selecione...")
                if v_salvo_40 not in opc40:
                    v_salvo_40 = "Selecione..."

                evidencia_40_salva = d40.get("link", "")

                # Chaves fixas para componentes Streamlit
                chave_radio_40 = f"r_40_select_{ano_sel}"
                chave_link_40 = f"l_40_txt_area_{ano_sel}"
                chave_coment_40 = f"coment_4.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx40 = opc40.index(v_salvo_40) if v_salvo_40 in opc40 else 0
                    val_radio_40 = st.radio(
                        "Selecione uma opção (4.0):",
                        options=opc40,
                        index=idx40,
                        key=chave_radio_40
                    )

                with col2:
                    link_40 = st.text_area(
                        "Link/Evidência (4.0):",
                        value=evidencia_40_salva,
                        key=chave_link_40,
                        placeholder="Insira o link contendo relatórios de medição da frota, laudos da Escala Ringelmann, etc...",
                        height=110
                    )
                    placeholder_links_40 = st.empty()
                    links_40_visuais = re.findall(REGEX_PURE_URL, link_40 or "")
                    if links_40_visuais:
                        placeholder_links_40.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_40_visuais]))

                # Renderiza o bloco de comentários
                bloco_comentarios("4.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 4.0", key=f"btn_salvar_4_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_40, v_salvo_40)
                    lnk_val = link_40.strip()

                    # Regra de pontuação
                    if "Ringelmann" in str(val_salvar):
                        pts_calculados = 20.0
                    elif "outra" in str(val_salvar):
                        pts_calculados = 15.0
                    else:
                        pts_calculados = 0.0

                    # Captura o comentário do estado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_40, d40.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="4.0",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["4.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_40_salva or "")]

                    if lnk_val != evidencia_40_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 4.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                pts_atuais_40 = d40.get("pontos", 0.0)

                if pts_atuais_40 == 20.0:
                    cor_txt_40 = "#28a745"
                elif pts_atuais_40 == 15.0:
                    cor_txt_40 = "#ffc107"
                elif "Não" in str(d40.get("valor", "")):
                    cor_txt_40 = "#dc3545"
                else:
                    cor_txt_40 = "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_40}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 4.0: +{pts_atuais_40:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 4.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.0 • CONTRATO DE PRESTAÇÃO DE SERVIÇO DE PODA E CORTE (MODELO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.0 - Contratos Vigentes para Podas e Cortes", expanded=True):
                st.subheader("5.0 • Contrato de Prestação de Serviço")
                st.write("**A Prefeitura Municipal possui contrato de prestação de serviço de poda e corte de árvores, arbustos e outras plantas lenhosas em áreas urbanas?**")
                st.caption("ℹ *Selecione a opção aplicável, informe o link de evidência/comentário e clique no botão 'Salvar Quesito 5.0' para registrar.*")

                opc50 = ["Selecione...", "Sim", "Não"]

                # Recupera os dados salvos no banco de dados ou estrutura zerada
                d50 = res_data.get("5.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_50 = d50.get("valor", "Selecione...")
                if v_salvo_50 not in opc50:
                    v_salvo_50 = "Selecione..."

                evidencia_50_salva = d50.get("link", "")

                # Chaves fixas para os componentes Streamlit
                chave_radio_50 = f"r_50_select_{ano_sel}"
                chave_link_50 = f"l_50_txt_area_{ano_sel}"
                chave_coment_50 = f"coment_5.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx50 = opc50.index(v_salvo_50) if v_salvo_50 in opc50 else 0
                    val_radio_50 = st.radio(
                        "Selecione uma opção (5.0):",
                        options=opc50,
                        index=idx50,
                        key=chave_radio_50
                    )

                with col2:
                    link_50 = st.text_area(
                        "Link/Evidência (5.0):",
                        value=evidencia_50_salva,
                        key=chave_link_50,
                        placeholder="Insira o link do contrato de prestação de serviços, publicação no Diário Oficial ou termo de licitação...",
                        height=110
                    )
                    placeholder_links_50 = st.empty()
                    links_50_visuais = re.findall(REGEX_PURE_URL, link_50 or "")
                    if links_50_visuais:
                        placeholder_links_50.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_50_visuais]))

                # Renderiza o bloco de comentários
                bloco_comentarios("5.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.0", key=f"btn_salvar_5_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_50, v_salvo_50)
                    lnk_val = link_50.strip()

                    # Regra de pontuação: Quesito informativo (0.0 pontos)
                    pts_calculados = 0.0

                    # Captura o comentário do estado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_50, d50.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="5.0",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["5.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_50_salva or "")]

                    if lnk_val != evidencia_50_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 5.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto e resumo visual
                v_val_atual = d50.get("valor", "Selecione...")

                if v_val_atual == "Sim":
                    cor_txt_50 = "#28a745"
                elif v_val_atual == "Não":
                    cor_txt_50 = "#dc3545"
                else:
                    cor_txt_50 = "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_50}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.0: +0.0 pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.1 • NÚMERO DO CONTRATO E PRESTADOR DE SERVIÇO (MODELO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.1 - Detalhes do Contrato de Poda", expanded=True):
                st.subheader("5.1 • Identificação do Contrato")
                st.write("**Informe o número do contrato e o prestador de serviço:**")
                st.caption("ℹ *Informe os dados contratuais, insira os links de evidência/comentários e clique no botão 'Salvar Quesito 5.1' para registrar.*")

                # Recupera os dados salvos no banco de dados ou estrutura padrão
                d51 = res_data.get("5.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                val_salvo_raw = d51.get("valor", "")

                # Extração tolerante a falhas dos campos estruturados
                c_salvo, p_salvo = "", ""
                if val_salvo_raw and "|" in val_salvo_raw:
                    try:
                        parts = val_salvo_raw.split("|")
                        c_salvo = parts[0].split(":")[1].strip() if ":" in parts[0] else ""
                        p_salvo = parts[1].split(":")[1].strip() if ":" in parts[1] else ""
                    except Exception:
                        c_salvo, p_salvo = "", ""

                evidencia_51_salva = d51.get("link", "")

                # Chaves fixas de componentes no Streamlit
                chave_num_cont = f"q51_cont_txt_{ano_sel}"
                chave_prestador = f"q51_prest_txt_{ano_sel}"
                chave_link_51 = f"l_51_txt_area_{ano_sel}"
                chave_coment_51 = f"coment_5.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    num_contrato_input = st.text_input(
                        "Número do contrato:",
                        value=c_salvo,
                        key=chave_num_cont,
                        placeholder="Ex: 042/2024"
                    )
                    prestador_input = st.text_input(
                        "Prestador de serviço:",
                        value=p_salvo,
                        key=chave_prestador,
                        placeholder="Ex: Terceirizada Verde Ltda."
                    )

                with col2:
                    link_51 = st.text_area(
                        "Link/Evidência (5.1):",
                        value=evidencia_51_salva,
                        key=chave_link_51,
                        placeholder="Insira o link para a cópia digital do contrato ou termo de homologação...",
                        height=140
                    )
                    placeholder_links_51 = st.empty()
                    links_51_visuais = re.findall(REGEX_PURE_URL, link_51 or "")
                    if links_51_visuais:
                        placeholder_links_51.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_51_visuais]))

                # Renderiza o bloco de comentários
                bloco_comentarios("5.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.1", key=f"btn_salvar_5_1_{ano_sel}", type="primary"):
                    num_c = num_contrato_input.strip()
                    prest = prestador_input.strip()
                    lnk_val = link_51.strip()

                    valor_ajustado = f"Contrato: {num_c} | Prestador: {prest}"
                    pts_calculados = 0.0  # Quesito informativo/cadastral

                    comentario_para_salvar = st.session_state.get(chave_coment_51, d51.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="5.1",
                        valor=valor_ajustado,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["5.1"] = {
                        "valor": valor_ajustado,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_51_salva or "")]

                    if lnk_val != evidencia_51_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação (Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.1: +0.0 pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.1", st.session_state.get(f"links_pendentes_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.2 • PERIODICIDADE DE PODA/MANUTENÇÃO DAS ÁRVORES (MODELO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.2 - Cronograma e Regularidade de Podas", expanded=True):
                st.subheader("5.2 • Periodicidade de Manutenção")
                st.write("**A Prefeitura mantém uma periodicidade de poda/manutenção das árvores?**")
                st.caption("ℹ *Atenção: Opções incorretas geram impactos negativos/penalidades na nota total. Selecione uma opção, insira a evidência/comentários e clique em 'Salvar Quesito 5.2'.*")

                opts52 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não tem uma periodicidade – -10": -10.0,
                    "Somente por solicitação – -10": -10.0,
                    "Não realiza poda e/ou corte de árvores – -15": -15.0
                }
                lista_opts = list(opts52.keys())

                # Recupera os dados salvos no banco de dados
                d52 = res_data.get("5.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_52 = d52.get("valor", "Selecione...")
                if v_salvo_52 not in lista_opts:
                    v_salvo_52 = "Selecione..."

                evidencia_52_salva = d52.get("link", "")

                # Chaves fixas de componentes no Streamlit
                chave_radio_52 = f"r_52_select_{ano_sel}"
                chave_link_52 = f"l_52_txt_area_{ano_sel}"
                chave_coment_52 = f"coment_5.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    try:
                        idx52 = lista_opts.index(v_salvo_52)
                    except ValueError:
                        idx52 = 0

                    opcao_selecionada = st.radio(
                        "Selecione uma opção (5.2):",
                        options=lista_opts,
                        index=idx52,
                        key=chave_radio_52
                    )

                with col2:
                    link_52 = st.text_area(
                        "Link/Evidência (5.2):",
                        value=evidencia_52_salva,
                        key=chave_link_52,
                        placeholder="Insira o link do cronograma oficial de podas, decretos ou relatórios de atendimento...",
                        height=150
                    )
                    placeholder_links_52 = st.empty()
                    links_52_visuais = re.findall(REGEX_PURE_URL, link_52 or "")
                    if links_52_visuais:
                        placeholder_links_52.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_52_visuais]))

                # Renderiza o bloco de comentários
                bloco_comentarios("5.2", res_data, ano_sel)

                # Cálculo visual de pontuação dinâmica
                pts_atuais_52 = opts52.get(opcao_selecionada, 0.0)
                if opcao_selecionada == "Selecione...":
                    cor_txt_52 = "#6c757d"
                elif pts_atuais_52 < 0.0:
                    cor_txt_52 = "#dc3545"
                else:
                    cor_txt_52 = "#28a745"

                st.markdown(
                    f"<span style='color:{cor_txt_52}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.2: {pts_atuais_52:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.2", key=f"btn_salvar_5_2_{ano_sel}", type="primary"):
                    val_salvar = opcao_selecionada
                    lnk_val = link_52.strip()
                    pts_calculados = float(opts52.get(val_salvar, 0.0))
                    comentario_para_salvar = st.session_state.get(chave_coment_52, d52.get("comentario", ""))

                    # Gravação no Neon PostgreSQL
                    save_resp(
                        qid="5.2",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local res_data
                    res_data["5.2"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_52_salva or "")]

                    if lnk_val != evidencia_52_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 5.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 5.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.2", st.session_state.get(f"links_pendentes_5_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = False

# =============================================================================
        # QUESITO 5.2.1 • DESTINAÇÃO DOS RESÍDUOS DE PODAS (MÚLTIPLA ESCOLHA - iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_2_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.2.1 - Destinação Sustentável de Resíduos Verdes", expanded=True):
                st.subheader("5.2.1 • Destinação dos Resíduos de Podas")
                st.write("**Qual a destinação dos resíduos das podas de árvores?**")
                st.caption("ℹ *A pontuação aumenta progressivamente com o número de destinações sustentáveis. Aterros aplicam penalidade. Marque as opções válidas, insira o link/comentários e clique em 'Salvar Quesito 5.2.1'.*")

                opts_pontuam = [
                    "Reaproveitamento para produzir móveis, brinquedos, utensílios ou objetos de decoração",
                    "Compostagem para produção de mudas, na jardinagem e arborização da cidade",
                    "Queima para aquecimento e cocção",
                    "Geração de energia",
                    "Uso na construção civil"
                ]
                opt_aterro = "Envio para aterro sanitário – -05"
                opt_armazenamento = "Armazenamento dos resíduos das podas"

                # Recupera os dados salvos no banco de dados
                d521 = res_data.get("5.2.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                
                # Leitura defensiva para garantir formato de lista ou texto
                texto_seguro_521 = str(d521.get("valor", "[]"))
                evidencia_521_salva = d521.get("link", "")

                # Chaves fixas de componentes no Streamlit
                chave_link_521 = f"l_521_txt_area_{ano_sel}"
                chave_coment_521 = f"coment_5.2.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.write("*Selecione os destinos comprovados:*")
                    
                    # Renders para as opções que pontuam positivamente
                    for i, opt in enumerate(opts_pontuam):
                        marcado = (opt in texto_seguro_521) if texto_seguro_521 and texto_seguro_521 != "[]" else False
                        st.checkbox(
                            opt, 
                            value=marcado, 
                            key=f"ck_521_pos_{i}_{ano_sel}"
                        )
                    
                    # Checkbox para Aterro
                    marcado_aterro = (opt_aterro in texto_seguro_521) if texto_seguro_521 and texto_seguro_521 != "[]" else False
                    st.checkbox(
                        opt_aterro, 
                        value=marcado_aterro, 
                        key=f"ck_521_aterro_{ano_sel}"
                    )
                    
                    # Checkbox para Armazenamento
                    marcado_arm = (opt_armazenamento in texto_seguro_521) if texto_seguro_521 and texto_seguro_521 != "[]" else False
                    st.checkbox(
                        opt_armazenamento, 
                        value=marcado_arm, 
                        key=f"ck_521_arm_{ano_sel}"
                    )

                with col2:
                    link_521 = st.text_area(
                        "Link/Evidência (5.2.1):",
                        value=evidencia_521_salva,
                        key=chave_link_521,
                        placeholder="Insira links do pátio de compostagem, contratos de doação de biomassa ou controle de resíduos...",
                        height=240
                    )
                    placeholder_links_521 = st.empty()
                    links_521_visuais = re.findall(REGEX_PURE_URL, link_521 or "")
                    if links_521_visuais:
                        placeholder_links_521.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_521_visuais]))

                # Renderiza o bloco de comentários do Quesito 5.2.1
                bloco_comentarios("5.2.1", res_data, ano_sel)

                # Cálculo de preview visual de pontuação no render (com base nos checkboxes atuais do session_state)
                fb_validas = sum([1 for idx in range(len(opts_pontuam)) if st.session_state.get(f"ck_521_pos_{idx}_{ano_sel}", False)])
                fb_penalidade = -5.0 if st.session_state.get(f"ck_521_aterro_{ano_sel}", False) else 0.0
                fb_base = 20.0 if fb_validas >= 3 else (10.0 if fb_validas == 2 else (5.0 if fb_validas == 1 else 0.0))
                
                pts_feedback = fb_base + fb_penalidade
                if pts_feedback > 0:
                    cor_txt_521 = "#28a745"
                elif pts_feedback < 0:
                    cor_txt_521 = "#dc3545"
                else:
                    cor_txt_521 = "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_521}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.2.1: {pts_feedback:+.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.2.1", key=f"btn_salvar_5_2_1_{ano_sel}", type="primary"):
                    lnk_val = link_521.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_521, d521.get("comentario", ""))

                    lista_selecionados = []
                    qtd_validas = 0
                    penalidade = 0.0

                    # Varre os checkboxes ativos
                    for idx, opt in enumerate(opts_pontuam):
                        if st.session_state.get(f"ck_521_pos_{idx}_{ano_sel}", False):
                            lista_selecionados.append(opt)
                            qtd_validas += 1

                    if st.session_state.get(f"ck_521_aterro_{ano_sel}", False):
                        lista_selecionados.append(opt_aterro)
                        penalidade = -5.0

                    if st.session_state.get(f"ck_521_arm_{ano_sel}", False):
                        lista_selecionados.append(opt_armazenamento)

                    # Regra de pontuação
                    if qtd_validas >= 3:
                        pts_base = 20.0
                    elif qtd_validas == 2:
                        pts_base = 10.0
                    elif qtd_validas == 1:
                        pts_base = 5.0
                    else:
                        pts_base = 0.0

                    pts_totais = float(pts_base + penalidade)
                    val_salvar = str(lista_selecionados)

                    # Persistência via save_resp
                    save_resp(
                        qid="5.2.1",
                        valor=val_salvar,
                        pontos=pts_totais,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local
                    res_data["5.2.1"] = {
                        "valor": val_salvar,
                        "pontos": pts_totais,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_521_salva or "")]

                    if lnk_val != evidencia_521_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 5.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 5.2.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.2.1", st.session_state.get(f"links_pendentes_5_2_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_2_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.3 • ORIENTAÇÃO/TREINAMENTO DE EQUIPE DE MANUTENÇÃO (iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.3 - Capacitação e Treinamento da Equipe", expanded=True):
                st.subheader("5.3 • Treinamento de Equipe")
                st.write("**O pessoal da prefeitura responsável por manutenção das árvores é devidamente orientado/treinado para realizar a poda de maneira correta?**")
                st.caption("ℹ *Atenção: A ausência de treinamento formalizado gera penalidade direta de pontuação. Insira os dados, links/comentários e clique em 'Salvar Quesito 5.3'.*")

                opts53 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -10": -10.0
                }
                lista_opts53 = list(opts53.keys())

                # Recupera os dados salvos no banco de dados
                d53 = res_data.get("5.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                
                v_salvo_53 = d53.get("valor", "Selecione...")
                if v_salvo_53 not in lista_opts53:
                    v_salvo_53 = "Selecione..."

                evidencia_53_salva = d53.get("link", "")
                
                # Chaves fixas de componentes no Streamlit
                chave_radio_53 = f"r_53_select_{ano_sel}"
                chave_link_53 = f"l_53_txt_area_{ano_sel}"
                chave_coment_53 = f"coment_5.3_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx_salvo53 = lista_opts53.index(v_salvo_53)
                    st.radio(
                        "Selecione uma opção (5.3):",
                        options=lista_opts53,
                        index=idx_salvo53,
                        key=chave_radio_53
                    )

                with col2:
                    link_53 = st.text_area(
                        "Link/Evidência (5.3):",
                        value=evidencia_53_salva,
                        key=chave_link_53,
                        placeholder="Insira o link contendo certificados de treinamento, listas de presença ou editais de capacitação...",
                        height=120
                    )
                    placeholder_links_53 = st.empty()
                    links_53_visuais = re.findall(REGEX_PURE_URL, link_53 or "")
                    if links_53_visuais:
                        placeholder_links_53.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_53_visuais]))

                # Renderiza o bloco de comentários do Quesito 5.3
                bloco_comentarios("5.3", res_data, ano_sel)

                # Cálculo do preview de impacto visual na pontuação
                v_atual_53 = st.session_state.get(chave_radio_53, v_salvo_53)
                pts_atuais_53 = opts53.get(v_atual_53, 0.0)
                
                if v_atual_53 == "Selecione...":
                    cor_txt_53 = "#6c757d"
                elif pts_atuais_53 < 0:
                    cor_txt_53 = "#dc3545"
                else:
                    cor_txt_53 = "#28a745"

                st.markdown(
                    f"<span style='color:{cor_txt_53}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.3: {pts_atuais_53:+.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.3", key=f"btn_salvar_5_3_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_53, v_salvo_53)
                    lnk_val = link_53.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_53, d53.get("comentario", ""))

                    pts_calculados = float(opts53.get(val_salvar, 0.0))

                    # Persistência via save_resp
                    save_resp(
                        qid="5.3",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local
                    res_data["5.3"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_53_salva or "")]

                    if lnk_val != evidencia_53_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 5.3 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 5.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.3", st.session_state.get(f"links_pendentes_5_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 6.0 • AÇÕES PREVENTIVAS DE ESTIAGEM (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_estiagem_6_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 6.0 - Plano de Contingência para Estiagem", expanded=True):
                st.subheader("6.0 • Medidas Contra Estiagem")
                st.write("**Existem ações e medidas preventivas de contingenciamento para os períodos de estiagem executados pela Prefeitura?**")
                st.caption("ℹ *Estiagem é um período prolongado de baixa pluviosidade, ou sua ausência, na qual a perda de umidade do solo é superior à sua reposição. Selecione uma opção, insira os links/comentários e clique em 'Salvar Quesito 6.0'.*")

                opc60 = ["Selecione...", "Sim – 20", "Não – 00"]
                
                # Recupera os dados salvos no banco de dados
                d60 = res_data.get("6.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                
                v_salvo_60 = d60.get("valor", "Selecione...")
                if v_salvo_60 not in opc60:
                    v_salvo_60 = "Selecione..."

                evidencia_60_salva = d60.get("link", "")
                
                # Chaves fixas de componentes no Streamlit
                chave_radio_60 = f"r_60_select_{ano_sel}"
                chave_link_60 = f"l_60_txt_area_{ano_sel}"
                chave_coment_60 = f"coment_6.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    try:
                        idx60 = opc60.index(v_salvo_60)
                    except ValueError:
                        idx60 = 0

                    opcao_selecionada_60 = st.radio(
                        "Selecione uma opção (6.0):",
                        options=opc60,
                        index=idx60,
                        key=chave_radio_60
                    )

                with col2:
                    link_60 = st.text_area(
                        "Link/Evidência (6.0):",
                        value=evidencia_60_salva,
                        key=chave_link_60,
                        placeholder="Insira o link contendo o decreto de contingenciamento, plano de metas de estiagem, etc...",
                        height=110
                    )
                    placeholder_links_60 = st.empty()
                    links_60_visuais = re.findall(REGEX_PURE_URL, link_60 or "")
                    if links_60_visuais:
                        placeholder_links_60.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_60_visuais]))

                # Renderiza o bloco de comentários do Quesito 6.0
                bloco_comentarios("6.0", res_data, ano_sel)

                # Cálculo do preview de impacto visual na pontuação
                v_atual_60 = st.session_state.get(chave_radio_60, v_salvo_60)
                pts_atuais_60 = 20.0 if "Sim" in str(v_atual_60) else 0.0
                
                if v_atual_60 == "Selecione...":
                    cor_txt_60 = "#6c757d"
                elif pts_atuais_60 > 0:
                    cor_txt_60 = "#28a745"
                else:
                    cor_txt_60 = "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_60}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 6.0: +{pts_atuais_60:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 6.0", key=f"btn_salvar_6_0_{ano_sel}", type="primary"):
                    val_salvar = opcao_selecionada_60
                    lnk_val = link_60.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_60, d60.get("comentario", ""))

                    pts_calculados = 20.0 if "Sim" in str(val_salvar) else 0.0

                    # Persistência via save_resp
                    save_resp(
                        qid="6.0",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local
                    res_data["6.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_60_salva or "")]

                    if lnk_val != evidencia_60_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 6.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 6.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 6.1 • DETALHAMENTO DAS MEDIDAS DE ESTIAGEM (Padrão iGov)
        # =============================================================================
        import ast

        with st.container(key=f"container_bloco_estiagem_6_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 6.1 - Ações de Enfrentamento Executadas", expanded=True):
                st.subheader("6.1 • Detalhamento das Medidas")
                st.write("**Assinale as ações e medidas preventivas de contingenciamento para os períodos de estiagem executados pela Prefeitura:**")
                st.caption("ℹ *A pontuação deste quesito é cumulativa baseada nas diretrizes assinaladas. Marque as opções válidas, insira os links/comentários e clique em 'Salvar Quesito 6.1'.*")

                opts61 = {
                    "Plano emergencial ou de contingenciamento sobre abastecimento de água no caso de sua escassez – 30": 30.0,
                    "Manejo/manobras de água entre os reservatórios – 00": 0.0,
                    "Campanha de conscientização da população – 05": 5.0,
                    "Busca de fontes alternativas de abastecimento, como: poços artesianos – 00": 0.0,
                    "Uso racional da distribuição de água (racionamento) – 00": 0.0,
                    "Implantação de rodízio de fornecimento de água – 00": 0.0,
                    "Redução da pressão no abastecimento de água – 00": 0.0,
                    "Multa em caso de desperdício de água – 00": 0.0,
                    "Tarifa/taxa diferenciada para o aumento de consumo de água – 00": 0.0,
                    "Fornecimento de caminhões pipa – 00": 0.0,
                    "Drenagem pluvial – 00": 0.0,
                    "Incentivo à instalação de sistema para água de reúso – 05": 5.0,
                    "Redução das perdas na distribuição de água – 00": 0.0,
                    "Desassoreamento – 00": 0.0,
                    "Divulgação dos resultados obtidos com o contingenciamento, situação dos mananciais/represas/ETAs – 10": 10.0
                }

                # Recupera os dados salvos no banco de dados
                d61 = res_data.get("6.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                
                texto_seguro_61 = str(d61.get("valor", "[]"))
                
                # Conversão segura da string recuperada para lista
                try:
                    lista_salva_61 = ast.literal_eval(texto_seguro_61) if isinstance(texto_seguro_61, str) else texto_seguro_61
                    if not isinstance(lista_salva_61, list):
                        lista_salva_61 = []
                except Exception:
                    lista_salva_61 = []

                evidencia_61_salva = d61.get("link", "")
                
                # Chaves fixas de componentes no Streamlit
                chave_link_61 = f"l_61_txt_area_{ano_sel}"
                chave_coment_61 = f"coment_6.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.write("*Selecione as ações válidas:*")
                    for i, (txt, pts) in enumerate(opts61.items()):
                        marcado = (txt in lista_salva_61) if lista_salva_61 else (txt in texto_seguro_61)
                        st.checkbox(
                            txt,
                            value=marcado,
                            key=f"ck_61_opt_{i}_{ano_sel}"
                        )

                with col2:
                    link_61 = st.text_area(
                        "Link/Evidência (6.1):",
                        value=evidencia_61_salva,
                        key=chave_link_61,
                        placeholder="Insira links de diários oficiais, campanhas institucionais ou legislações tarifárias aplicadas...",
                        height=340
                    )
                    placeholder_links_61 = st.empty()
                    links_61_visuais = re.findall(REGEX_PURE_URL, link_61 or "")
                    if links_61_visuais:
                        placeholder_links_61.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_61_visuais]))

                # Renderiza o bloco de comentários do Quesito 6.1
                bloco_comentarios("6.1", res_data, ano_sel)

                # Cálculo dinâmico do impacto na pontuação em tempo de execução
                fb_pts_61 = sum([
                    pts for i, (txt, pts) in enumerate(opts61.items())
                    if st.session_state.get(f"ck_61_opt_{i}_{ano_sel}", (txt in lista_salva_61 if lista_salva_61 else False))
                ])
                
                cor_txt_61 = "#28a745" if fb_pts_61 > 0 else "#6c757d"
                st.markdown(
                    f"<span style='color:{cor_txt_61}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 6.1: +{fb_pts_61:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 6.1", key=f"btn_salvar_6_1_{ano_sel}", type="primary"):
                    lista_selecionados = []
                    pts_totais = 0.0

                    for i, (txt, pts) in enumerate(opts61.items()):
                        if st.session_state.get(f"ck_61_opt_{i}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    val_salvar = str(lista_selecionados)
                    lnk_val = link_61.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_61, d61.get("comentario", ""))

                    # Persistência via save_resp
                    save_resp(
                        qid="6.1",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local
                    res_data["6.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_61_salva or "")]

                    if lnk_val != evidencia_61_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 6.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 6.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_6_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("6.1", st.session_state.get(f"links_pendentes_6_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 6.2 • SETORES ATENDIDOS POR AÇÕES ESPECÍFICAS (Padrão iGov)
        # =============================================================================
        import ast

        with st.container(key=f"container_bloco_estiagem_6_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 6.2 - Setores Estratégicos com Provisão Assegurada", expanded=True):
                st.subheader("6.2 • Setores Atendidos")
                st.write("**Em quais setores existem ações e medidas de contingenciamento específicos para provisão de água potável?**")
                st.caption("ℹ *A pontuação deste quesito é cumulativa baseada nas diretrizes assinaladas. Marque as opções válidas, insira os links/comentários e clique em 'Salvar Quesito 6.2'.*")

                opts62 = {
                    "Rede Municipal de Educação – 10": 10.0,
                    "Rede Municipal da Atenção Básica da Saúde – 10": 10.0,
                    "Outro – 05": 5.0
                }

                # Recupera os dados salvos no banco de dados
                d62 = res_data.get("6.2") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                
                texto_seguro_62 = str(d62.get("valor", "[]"))
                
                # Conversão segura da string recuperada para lista
                try:
                    lista_salva_62 = ast.literal_eval(texto_seguro_62) if isinstance(texto_seguro_62, str) else texto_seguro_62
                    if not isinstance(lista_salva_62, list):
                        lista_salva_62 = []
                except Exception:
                    lista_salva_62 = []

                evidencia_62_salva = d62.get("link", "")
                
                # Chaves fixas de componentes no Streamlit
                chave_link_62 = f"l_62_txt_area_{ano_sel}"
                chave_coment_62 = f"coment_6.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.write("*Selecione os setores cobertos:*")
                    for i, (txt, pts) in enumerate(opts62.items()):
                        marcado = (txt in lista_salva_62) if lista_salva_62 else (txt in texto_seguro_62)
                        st.checkbox(
                            txt,
                            value=marcado,
                            key=f"ck_62_opt_{i}_{ano_sel}"
                        )

                with col2:
                    link_62 = st.text_area(
                        "Link/Evidência (6.2):",
                        value=evidencia_62_salva,
                        key=chave_link_62,
                        placeholder="Insira links de termos de cooperação, contratos de abastecimento complementar dedicados a postos ou escolas...",
                        height=140
                    )
                    placeholder_links_62 = st.empty()
                    links_62_visuais = re.findall(REGEX_PURE_URL, link_62 or "")
                    if links_62_visuais:
                        placeholder_links_62.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_62_visuais]))

                # Renderiza o bloco de comentários do Quesito 6.2
                bloco_comentarios("6.2", res_data, ano_sel)

                # Cálculo dinâmico do impacto na pontuação em tempo de execução
                fb_pts_62 = sum([
                    pts for i, (txt, pts) in enumerate(opts62.items())
                    if st.session_state.get(f"ck_62_opt_{i}_{ano_sel}", (txt in lista_salva_62 if lista_salva_62 else False))
                ])
                
                cor_txt_62 = "#28a745" if fb_pts_62 > 0 else "#6c757d"
                st.markdown(
                    f"<span style='color:{cor_txt_62}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 6.2: +{fb_pts_62:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 6.2", key=f"btn_salvar_6_2_{ano_sel}", type="primary"):
                    lista_selecionados = []
                    pts_totais = 0.0

                    for i, (txt, pts) in enumerate(opts62.items()):
                        if st.session_state.get(f"ck_62_opt_{i}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    val_salvar = str(lista_selecionados)
                    lnk_val = link_62.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_62, d62.get("comentario", ""))

                    # Persistência via save_resp
                    save_resp(
                        qid="6.2",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local
                    res_data["6.2"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação para acionar modal de validação de link público
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_62_salva or "")]

                    if lnk_val != evidencia_62_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 6.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 6.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_6_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("6.2", st.session_state.get(f"links_pendentes_6_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.0 • INSTITUIÇÃO DO PLANO DE SANEAMENTO BÁSICO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.0 - Plano Municipal/Regional de Saneamento", expanded=True):
                st.subheader("7.0 • Plano de Saneamento Básico")
                st.write("**O município possui seu Plano Municipal ou Regional de Saneamento Básico instituído?**")
                st.caption("ℹ *O plano instituído orienta as diretrizes de infraestrutura urbana. Selecione a opção, insira a evidência/comentários e clique em 'Salvar Quesito 7.0'.*")

                opc70 = ["Selecione...", "Sim", "Não"]
                
                # Recupera os dados salvos do banco
                d70 = res_data.get("7.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                
                v_salvo_70 = d70.get("valor", "Selecione...")
                if v_salvo_70 not in opc70:
                    v_salvo_70 = "Selecione..."

                evidencia_70_salva = d70.get("link", "")
                
                # Chaves de identificação no Streamlit
                chave_radio_70 = f"r_70_select_{ano_sel}"
                chave_link_70 = f"l_70_txt_area_{ano_sel}"
                chave_coment_70 = f"coment_7.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx70 = opc70.index(v_salvo_70)
                    st.radio(
                        "Selecione uma opção (7.0):",
                        options=opc70,
                        index=idx70,
                        key=chave_radio_70
                    )

                with col2:
                    link_70 = st.text_area(
                        "Link/Evidência (7.0):",
                        value=evidencia_70_salva,
                        key=chave_link_70,
                        placeholder="Insira o link para o decreto, lei municipal ou ato regulamentar de instituição do plano...",
                        height=110
                    )
                    placeholder_links_70 = st.empty()
                    links_70_visuais = re.findall(REGEX_PURE_URL, link_70 or "")
                    if links_70_visuais:
                        placeholder_links_70.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_70_visuais]))

                # Renderiza o bloco de comentários do Quesito 7.0
                bloco_comentarios("7.0", res_data, ano_sel)

                # Feedback do impacto na pontuação (Quesito Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.0: +0.0 pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.0", key=f"btn_salvar_7_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_70, v_salvo_70)
                    lnk_val = link_70.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_70, d70.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.0",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.0"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_70_salva or "")]

                    if lnk_val != evidencia_70_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.1 • INSTRUMENTO NORMATIVO DO PLANO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.1 - Atos de Regulamentação Normativa", expanded=True):
                st.subheader("7.1 • Instrumento Normativo")
                st.write("**Informe o Instrumento normativo, Número e Data da publicação:**")
                st.caption("ℹ *Preencha os campos abaixo, insira o link de evidência/comentários e clique em 'Salvar Quesito 7.1'.*")

                # Recupera os dados salvos do banco
                d71 = res_data.get("7.1") or {"valor": "Inst: | Nº: | Data:", "pontos": 0.0, "link": "", "comentario": ""}

                # Faz o parse dos dados salvos no formato: "Inst: X | Nº: Y | Data: Z"
                valor_salvo = d71.get("valor", "")
                try:
                    parts = valor_salvo.split("|")
                    inst_salvo = parts[0].split(":")[1].strip() if len(parts) > 0 and ":" in parts[0] else ""
                    num_salvo = parts[1].split(":")[1].strip() if len(parts) > 1 and ":" in parts[1] else ""
                    data_salvo = parts[2].split(":")[1].strip() if len(parts) > 2 and ":" in parts[2] else ""
                except Exception:
                    inst_salvo, num_salvo, data_salvo = "", "", ""

                evidencia_71_salva = d71.get("link", "")

                # Chaves de identificação no Streamlit
                chave_inst = f"q71_inst_txt_{ano_sel}"
                chave_num = f"q71_num_txt_{ano_sel}"
                chave_data = f"q71_data_txt_{ano_sel}"
                chave_link_71 = f"l_71_txt_area_{ano_sel}"
                chave_coment_71 = f"coment_7.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_input("Instrumento normativo:", value=inst_salvo, key=chave_inst)
                    st.text_input("Número:", value=num_salvo, key=chave_num)
                    st.text_input("Data da publicação:", value=data_salvo, key=chave_data)

                with col2:
                    link_71 = st.text_area(
                        "Link/Evidência (7.1):",
                        value=evidencia_71_salva,
                        key=chave_link_71,
                        placeholder="Link para o Diário Oficial contendo a publicação da portaria, decreto ou lei...",
                        height=220
                    )
                    placeholder_links_71 = st.empty()
                    links_71_visuais = re.findall(REGEX_PURE_URL, link_71 or "")
                    if links_71_visuais:
                        placeholder_links_71.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_71_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.1
                bloco_comentarios("7.1", res_data, ano_sel)

                # Feedback do impacto na pontuação (Quesito Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.1: +0.0 pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.1", key=f"btn_salvar_7_1_{ano_sel}", type="primary"):
                    inst_v = st.session_state.get(chave_inst, inst_salvo).strip()
                    num_v = st.session_state.get(chave_num, num_salvo).strip()
                    dt_v = st.session_state.get(chave_data, data_salvo).strip()

                    val_salvar = f"Inst: {inst_v} | Nº: {num_v} | Data: {dt_v}"
                    lnk_val = link_71.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_71, d71.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.1",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.1"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_71_salva or "")]

                    if lnk_val != evidencia_71_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.1", st.session_state.get(f"links_pendentes_7_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.2 • PÁGINA ELETRÔNICA DO PLANO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.2 - Transparência Pública e Acesso ao Plano", expanded=True):
                st.subheader("7.2 • Página Eletrônica do Plano")
                st.write("**Informe a página eletrônica (link na internet) do Plano Municipal ou Regional de Saneamento Básico:**")
                st.caption("ℹ *Se não estiver disponível na internet, insira o texto **XYZ** no campo de resposta para fins de auditoria.*")

                # Recupera os dados salvos do banco
                d72 = res_data.get("7.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_72 = d72.get("valor", "")
                evidencia_72_salva = d72.get("link", "")

                # Chaves de identificação no Streamlit
                chave_val_72 = f"q72_link_val_{ano_sel}"
                chave_link_72 = f"l_72_txt_area_{ano_sel}"
                chave_coment_72 = f"coment_7.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    txt_val_input = st.text_input(
                        "Link do Plano ou XYZ:",
                        value=v_salvo_72,
                        key=chave_val_72,
                        placeholder="http://www... ou XYZ"
                    )
                    
                    # Cálculo em tempo real da pontuação exibida no painel
                    current_txt_72 = txt_val_input.strip().upper()
                    fb_pts_72 = 0.0 if current_txt_72 in ["XYZ", ""] else 2.0
                    st.metric(label="Pontuação do Quesito", value=f"{fb_pts_72:.1f} pts")

                with col2:
                    link_72 = st.text_area(
                        "Link/Evidência (7.2):",
                        value=evidencia_72_salva,
                        key=chave_link_72,
                        placeholder="Link da transparência, site da agência reguladora ou portal do município...",
                        height=130
                    )
                    placeholder_links_72 = st.empty()
                    links_72_visuais = re.findall(REGEX_PURE_URL, link_72 or "")
                    if links_72_visuais:
                        placeholder_links_72.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_72_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.2
                bloco_comentarios("7.2", res_data, ano_sel)

                # Feedback visual do impacto na pontuação
                cor_txt_72 = "#28a745" if fb_pts_72 > 0 else "#6c757d"
                st.markdown(
                    f"<span style='color:{cor_txt_72}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.2: +{fb_pts_72:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.2", key=f"btn_salvar_7_2_{ano_sel}", type="primary"):
                    txt_val = st.session_state.get(chave_val_72, v_salvo_72).strip()
                    lnk_val = link_72.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_72, d72.get("comentario", ""))

                    # Regra de pontuação: XYZ ou Vazio = 0.0, Qualquer outra entrada = 2.0
                    pts_calculados = 0.0 if txt_val.upper() in ["XYZ", ""] else 2.0

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.2",
                        valor=txt_val,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.2"] = {
                        "valor": txt_val,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_72_salva or "")]

                    if lnk_val != evidencia_72_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.2", st.session_state.get(f"links_pendentes_7_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.3 • METAS DE ABASTECIMENTO DE ÁGUA (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.3 - Fixação de Metas de Distribuição de Água", expanded=True):
                st.subheader("7.3 • Metas de Abastecimento de Água")
                st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de abastecimento de água potável?**")

                opts73 = {"Selecione...": 0.0, "Sim – 10": 10.0, "Não – 00": 0.0}
                lista_opts73 = list(opts73.keys())

                # Recupera os dados salvos do banco
                d73 = res_data.get("7.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_73 = d73.get("valor", "Selecione...")
                if v_salvo_73 not in lista_opts73:
                    v_salvo_73 = "Selecione..."

                evidencia_73_salva = d73.get("link", "")

                # Chaves de identificação no Streamlit
                chave_radio_73 = f"r_73_select_{ano_sel}"
                chave_link_73 = f"l_73_txt_area_{ano_sel}"
                chave_coment_73 = f"coment_7.3_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx_salvo73 = lista_opts73.index(v_salvo_73)
                    sel_opt_73 = st.radio(
                        "Selecione uma opção (7.3):",
                        options=lista_opts73,
                        index=idx_salvo73,
                        key=chave_radio_73
                    )
                    
                    # Cálculo em tempo real da pontuação exibida no painel
                    fb_pts_73 = opts73.get(sel_opt_73, 0.0)
                    st.metric(label="Pontuação do Quesito", value=f"{fb_pts_73:.1f} pts")

                with col2:
                    link_73 = st.text_area(
                        "Link/Evidência (7.3):",
                        value=evidencia_73_salva,
                        key=chave_link_73,
                        placeholder="Páginas específicas do plano contendo o capítulo de metas físicas e cronogramas de água...",
                        height=130
                    )
                    placeholder_links_73 = st.empty()
                    links_73_visuais = re.findall(REGEX_PURE_URL, link_73 or "")
                    if links_73_visuais:
                        placeholder_links_73.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_73_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.3
                bloco_comentarios("7.3", res_data, ano_sel)

                # Feedback visual do impacto na pontuação
                cor_txt_73 = "#28a745" if fb_pts_73 > 0 else ("#6c757d" if sel_opt_73 == "Selecione..." else "#dc3545")
                st.markdown(
                    f"<span style='color:{cor_txt_73}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3: +{fb_pts_73:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.3", key=f"btn_salvar_7_3_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_73, v_salvo_73)
                    lnk_val = link_73.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_73, d73.get("comentario", ""))

                    pts_calculados = float(opts73.get(val_salvar, 0.0))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.3",
                        valor=val_salvar,
                        pontos=pts_calculados,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.3"] = {
                        "valor": val_salvar,
                        "pontos": pts_calculados,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_73_salva or "")]

                    if lnk_val != evidencia_73_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.3 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.3", st.session_state.get(f"links_pendentes_7_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.3.1 • DETALHAMENTO DAS METAS (Padrão iGov - Múltipla Escolha)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.3.1 - Detalhamento das Metas Estabelecidas", expanded=True):
                st.subheader("7.3.1 • Metas de Qualidade e Eficiência")
                st.write("**Assinale quais as metas estabelecidas sobre abastecimento de água potável:**")

                opts731 = {
                    "Metas de expansão do serviço de abastecimento de água – 00": 0.0,
                    "Metas de redução de perdas na distribuição de água tratada – 2,5": 2.5,
                    "Metas de qualidade na prestação do serviço de abastecimento de água – 2,5": 2.5,
                    "Metas de eficiência e de uso racional da água – 2,5": 2.5,
                    "Estabelecimento de volume mínimo de abastecimento de água per capita – 2,5": 2.5,
                    "Estabelecimento de direitos e deveres dos usuários – 2,5": 2.5,
                    "Meta de universalização do abastecimento de água potável até 31 de dezembro de 2033 – 2,5": 2.5,
                    "Estabelecimento de cronograma para o atingimento das metas assinaladas acima – 05": 5.0
                }

                # Recupera os dados salvos do banco
                d731 = res_data.get("7.3.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                
                texto_seguro_731 = str(d731.get("valor", "[]"))
                evidencia_731_salva = d731.get("link", "")

                # Chaves de identificação no Streamlit
                chave_link_731 = f"l_731_txt_area_{ano_sel}"
                chave_coment_731 = f"coment_7.3.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.write("*Selecione os parâmetros contemplados:*")
                    
                    # Renderiza checkboxes e acumula estado/pontuação
                    pts_calculados_731 = 0.0
                    for i, (txt, pts) in enumerate(opts731.items()):
                        key_ck = f"ck_731_opt_{i}_{ano_sel}"
                        
                        # Define valor inicial baseando-se no banco ou session_state
                        if key_ck not in st.session_state:
                            marcado_inicial = (txt in texto_seguro_731) if (texto_seguro_731 and texto_seguro_731 != "[]") else False
                            st.session_state[key_ck] = marcado_inicial

                        is_checked = st.checkbox(
                            txt,
                            key=key_ck
                        )
                        if is_checked:
                            pts_calculados_731 += pts

                    # Exibição do feedback de pontuação
                    st.metric(label="Pontuação do Quesito (Acumulada)", value=f"{pts_calculados_731:.1f} pts")

                with col2:
                    link_731 = st.text_area(
                        "Link/Evidência (7.3.1):",
                        value=evidencia_731_salva,
                        key=chave_link_731,
                        placeholder="Links para anexos de engenharia municipal ou relatórios oficiais da regulação setorial...",
                        height=280
                    )
                    placeholder_links_731 = st.empty()
                    links_731_visuais = re.findall(REGEX_PURE_URL, link_731 or "")
                    if links_731_visuais:
                        placeholder_links_731.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_731_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.3.1
                bloco_comentarios("7.3.1", res_data, ano_sel)

                # Feedback visual do impacto na pontuação
                cor_txt_731 = "#28a745" if pts_calculados_731 > 0 else "#6c757d"
                st.markdown(
                    f"<span style='color:{cor_txt_731}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3.1: +{pts_calculados_731:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.3.1", key=f"btn_salvar_7_3_1_{ano_sel}", type="primary"):
                    lnk_val = link_731.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_731, d731.get("comentario", ""))

                    # Varre os checkboxes para consolidar lista e total de pontos
                    lista_selecionados = []
                    pts_totais = 0.0
                    for idx, (txt, pts) in enumerate(opts731.items()):
                        if st.session_state.get(f"ck_731_opt_{idx}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    val_salvar = str(lista_selecionados)

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.3.1",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.3.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_731_salva or "")]

                    if lnk_val != evidencia_731_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.3.1", st.session_state.get(f"links_pendentes_7_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_3_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.3.2 • DATA DE UNIVERSALIZAÇÃO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_3_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.3.2 - Prazo Limite do Marco Legal do Saneamento", expanded=True):
                st.subheader("7.3.2 • Data Limite de Universalização")
                st.write("**Qual a data prevista para universalização do abastecimento de água potável no município?**")
                st.caption("ℹ *Caso já tenha sido universalizado por completo, configure a data regulamentar padrão **01/01/2001**.*")

                # Recupera os dados salvos do banco
                d732 = res_data.get("7.3.2") or {"valor": "31/12/2033", "pontos": 0.0, "link": "", "comentario": ""}
                
                valor_salvo_732 = str(d732.get("valor", "31/12/2033"))
                try:
                    dia_salvo, mes_salvo, ano_salvo = map(int, valor_salvo_732.split("/"))
                except Exception:
                    dia_salvo, mes_salvo, ano_salvo = 31, 12, 2033

                evidencia_732_salva = d732.get("link", "")

                # Chaves de identificação no Streamlit
                chave_d = f"q732_d_num_{ano_sel}"
                chave_m = f"q732_m_num_{ano_sel}"
                chave_a = f"q732_a_num_{ano_sel}"
                chave_link_732 = f"l_732_txt_area_{ano_sel}"
                chave_coment_732 = f"coment_7.3.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    c_dia, c_mes, c_ano = st.columns(3)
                    with c_dia:
                        v_dia = st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d)
                    with c_mes:
                        v_mes = st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m)
                    with c_ano:
                        v_ano = st.number_input("Ano", min_value=2000, max_value=2100, value=ano_salvo, key=chave_a)

                    # Regra de corte baseada nas diretrizes federais (31/12/2033)
                    if v_ano > 2033 or (v_ano == 2033 and v_mes == 12 and v_dia > 31) or (v_ano == 2033 and v_mes > 12):
                        pts_calculados_732 = -5.0
                    else:
                        pts_calculados_732 = 0.0

                    st.metric(label="Penalização por Atraso", value=f"{pts_calculados_732:.1f} pts")

                with col2:
                    link_732 = st.text_area(
                        "Link/Evidência (7.3.2):",
                        value=evidencia_732_salva,
                        key=chave_link_732,
                        placeholder="Seção específica contendo o plano de metas consolidadas de universalização de recursos hídricos...",
                        height=140
                    )
                    placeholder_links_732 = st.empty()
                    links_732_visuais = re.findall(REGEX_PURE_URL, link_732 or "")
                    if links_732_visuais:
                        placeholder_links_732.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_732_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.3.2
                bloco_comentarios("7.3.2", res_data, ano_sel)

                # Feedback visual do impacto na pontuação
                cor_txt_732 = "#28a745" if pts_calculados_732 == 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_732}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3.2: {pts_calculados_732:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.3.2", key=f"btn_salvar_7_3_2_{ano_sel}", type="primary"):
                    lnk_val = link_732.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_732, d732.get("comentario", ""))

                    d_v = st.session_state.get(chave_d, v_dia)
                    m_v = st.session_state.get(chave_m, v_mes)
                    a_v = st.session_state.get(chave_a, v_ano)

                    if a_v > 2033 or (a_v == 2033 and m_v == 12 and d_v > 31) or (a_v == 2033 and m_v > 12):
                        pts_totais = -5.0
                    else:
                        pts_totais = 0.0

                    val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.3.2",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.3.2"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_732_salva or "")]

                    if lnk_val != evidencia_732_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_3_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_3_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.3.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.3.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_3_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.3.2", st.session_state.get(f"links_pendentes_7_3_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_3_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.4 • METAS DE COLETA DE ESGOTO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.4 - Fixação de Metas de Esgotamento Sanitário", expanded=True):
                st.subheader("7.4 • Metas de Coleta de Esgoto")
                st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de coleta de esgoto?**")

                opts74 = {"Selecione...": 0.0, "Sim – 10": 10.0, "Não – 00": 0.0}
                lista_opts74 = list(opts74.keys())

                # Recupera os dados salvos no banco
                d74 = res_data.get("7.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_74 = d74.get("valor", "Selecione...")
                if v_salvo_74 not in lista_opts74:
                    v_salvo_74 = "Selecione..."

                evidencia_74_salva = d74.get("link", "")

                # Chaves de identificação no Streamlit
                chave_radio_74 = f"r_74_select_{ano_sel}"
                chave_link_74 = f"l_74_txt_area_{ano_sel}"
                chave_coment_74 = f"coment_7.4_{ano_sel}"

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx_salvo74 = lista_opts74.index(v_salvo_74)
                    v_selecionado_74 = st.radio(
                        "Selecione uma opção (7.4):",
                        options=lista_opts74,
                        index=idx_salvo74,
                        key=chave_radio_74
                    )

                with col2:
                    link_74 = st.text_area(
                        "Link/Evidência (7.4):",
                        value=evidencia_74_salva,
                        key=chave_link_74,
                        placeholder="Páginas do plano que estipulam as metas físicas estruturais para coleta de efluentes...",
                        height=110
                    )
                    placeholder_links_74 = st.empty()
                    links_74_visuais = re.findall(REGEX_PURE_URL, link_74 or "")
                    if links_74_visuais:
                        placeholder_links_74.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_74_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.4
                bloco_comentarios("7.4", res_data, ano_sel)

                # Feedback visual reativo do impacto na pontuação
                pts_atuais_74 = opts74.get(v_selecionado_74, 0.0)
                cor_txt_74 = "#28a745" if pts_atuais_74 > 0 else ("#6c757d" if v_selecionado_74 == "Selecione..." else "#dc3545")
                st.markdown(
                    f"<span style='color:{cor_txt_74}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.4: +{pts_atuais_74:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.4", key=f"btn_salvar_7_4_{ano_sel}", type="primary"):
                    lnk_val = link_74.strip()
                    val_salvar = st.session_state.get(chave_radio_74, v_salvo_74)
                    pts_calculados = opts74.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_74, d74.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.4",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.4"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_74_salva or "")]

                    if lnk_val != evidencia_74_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.4 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.4 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.4", st.session_state.get(f"links_pendentes_7_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.4.1 • DETALHAMENTO DAS METAS DE ESGOTO (MÚLTIPLA ESCOLHA - Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_4_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.4.1 - Detalhamento das Metas de Esgoto Assinaladas", expanded=True):
                st.subheader("7.4.1 • Parâmetros e Diretrizes do Esgotamento")
                st.write("**Assinale quais as metas estabelecidas sobre coleta de esgoto:**")

                opts741 = {
                    "Metas de expansão do serviço de coleta de esgoto – 00": 0.0,
                    "Metas de qualidade na prestação do serviço de coleta de esgoto – 3,5": 3.5,
                    "Meta do reúso de efluentes sanitários – 3,5": 3.5,
                    "Estabelecimento de direitos e deveres dos usuários – 3,5": 3.5,
                    "Meta de universalização da coleta de esgoto até 31 de dezembro de 2033 – 3,5": 3.5,
                    "Estabelecimento de cronograma para o atingimento das metas assinaladas acima – 06": 6.0
                }

                # Recupera os dados salvos do banco
                d741 = res_data.get("7.4.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                # Conversão segura do valor salvo para lista de selecionados
                raw_val_741 = d741.get("valor", "[]")
                lista_salva_741 = []
                if raw_val_741:
                    try:
                        lista_salva_741 = json.loads(raw_val_741) if isinstance(raw_val_741, str) else raw_val_741
                    except (json.JSONDecodeError, TypeError, ValueError):
                        try:
                            lista_salva_741 = ast.literal_eval(raw_val_741)
                        except Exception:
                            lista_salva_741 = []

                if not isinstance(lista_salva_741, list):
                    lista_salva_741 = []

                evidencia_741_salva = d741.get("link", "")

                # Chaves de identificação no Streamlit
                chave_link_741 = f"l_741_txt_area_{ano_sel}"
                chave_coment_741 = f"coment_7.4.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    st.write("*Selecione os parâmetros contemplados:*")
                    for i, (txt_opt, pts_opt) in enumerate(opts741.items()):
                        key_ck = f"ck_741_opt_{i}_{ano_sel}"
                        marcado_previo = txt_opt in lista_salva_741
                        st.checkbox(
                            txt_opt,
                            value=marcado_previo,
                            key=key_ck
                        )

                with col2:
                    link_741 = st.text_area(
                        "Link/Evidência (7.4.1):",
                        value=evidencia_741_salva,
                        key=chave_link_741,
                        placeholder="Anexos técnicos do Plano Municipal ou relatórios da concessionária local...",
                        height=240
                    )
                    placeholder_links_741 = st.empty()
                    links_741_visuais = re.findall(REGEX_PURE_URL, link_741 or "")
                    if links_741_visuais:
                        placeholder_links_741.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_741_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.4.1
                bloco_comentarios("7.4.1", res_data, ano_sel)

                # Feedback visual reativo da pontuação acumulada dos checkboxes selecionados
                fb_pts_741 = sum([
                    pts for i, (txt, pts) in enumerate(opts741.items())
                    if st.session_state.get(f"ck_741_opt_{i}_{ano_sel}", False)
                ])
                cor_txt_741 = "#28a745" if fb_pts_741 > 0 else "#6c757d"
                st.markdown(
                    f"<span style='color:{cor_txt_741}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.4.1: +{fb_pts_741:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.4.1", key=f"btn_salvar_7_4_1_{ano_sel}", type="primary"):
                    lnk_val = link_741.strip()
                    
                    # Coleta os itens selecionados nos checkboxes
                    selecionados = []
                    pts_totais = 0.0
                    for i, (txt_opt, pts_opt) in enumerate(opts741.items()):
                        if st.session_state.get(f"ck_741_opt_{i}_{ano_sel}", False):
                            selecionados.append(txt_opt)
                            pts_totais += pts_opt

                    val_salvar = json.dumps(selecionados, ensure_ascii=False)
                    comentario_para_salvar = st.session_state.get(chave_coment_741, d741.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.4.1",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização da estrutura em memória
                    res_data["7.4.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_741_salva or "")]

                    if lnk_val != evidencia_741_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.4.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.4.1", st.session_state.get(f"links_pendentes_7_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_4_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.4.2 • DATA DE UNIVERSALIZAÇÃO DO ESGOTO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_4_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.4.2 - Prazo Limite do Marco Regulatório de Esgoto", expanded=True):
                st.subheader("7.4.2 • Data Limite de Universalização de Esgoto")
                st.write("**Qual a data prevista para universalização da coleta de esgoto no município?**")
                st.caption("ℹ *Caso já tenha sido universalizado por completo, configure a data regulamentar padrão **01/01/2001**.*")

                # Recupera os dados salvos no banco
                d742 = res_data.get("7.4.2") or {"valor": "31/12/2033", "pontos": 0.0, "link": "", "comentario": ""}

                # Decomposição da data salva com tratamento de erro
                raw_val_742 = d742.get("valor", "31/12/2033")
                try:
                    dia_salvo, mes_salvo, ano_salvo = map(int, str(raw_val_742).split("/"))
                except Exception:
                    dia_salvo, mes_salvo, ano_salvo = 31, 12, 2033

                evidencia_742_salva = d742.get("link", "")

                # Definindo chaves do Streamlit
                chave_d = f"q742_d_num_{ano_sel}"
                chave_m = f"q742_m_num_{ano_sel}"
                chave_a = f"q742_a_num_{ano_sel}"
                chave_link_742 = f"l_742_txt_area_{ano_sel}"
                chave_coment_742 = f"coment_7.4.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    c_dia, c_mes, c_ano = st.columns(3)
                    with c_dia:
                        num_d = st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d)
                    with c_mes:
                        num_m = st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m)
                    with c_ano:
                        num_a = st.number_input("Ano", min_value=2000, max_value=2100, value=ano_salvo, key=chave_a)

                    # Regra federal de penalização do Marco Legal do Saneamento (31/12/2033)
                    if num_a > 2033 or (num_a == 2033 and num_m == 12 and num_d > 31) or (num_a == 2033 and num_m > 12):
                        fb_pts_742 = -5.0
                    else:
                        fb_pts_742 = 0.0

                    st.metric(label="Penalização por Atraso", value=f"{fb_pts_742:.1f} pts")

                with col2:
                    link_742 = st.text_area(
                        "Link/Evidência (7.4.2):",
                        value=evidencia_742_salva,
                        key=chave_link_742,
                        placeholder="Seção contendo o planejamento cronológico de obras e metas de universalização de esgoto...",
                        height=140
                    )
                    placeholder_links_742 = st.empty()
                    links_742_visuais = re.findall(REGEX_PURE_URL, link_742 or "")
                    if links_742_visuais:
                        placeholder_links_742.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_742_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.4.2
                bloco_comentarios("7.4.2", res_data, ano_sel)

                # Feedback visual reativo
                cor_txt_742 = "#28a745" if fb_pts_742 == 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_742}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.4.2: {fb_pts_742:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.4.2", key=f"btn_salvar_7_4_2_{ano_sel}", type="primary"):
                    lnk_val = link_742.strip()
                    d_v = st.session_state.get(chave_d, num_d)
                    m_v = st.session_state.get(chave_m, num_m)
                    a_v = st.session_state.get(chave_a, num_a)

                    # Cálculo final da pontuação
                    if a_v > 2033 or (a_v == 2033 and m_v == 12 and d_v > 31) or (a_v == 2033 and m_v > 12):
                        pts_calculados = -5.0
                    else:
                        pts_calculados = 0.0

                    val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"
                    comentario_para_salvar = st.session_state.get(chave_coment_742, d742.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.4.2",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.4.2"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_742_salva or "")]

                    if lnk_val != evidencia_742_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.4.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.4.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.4.2", st.session_state.get(f"links_pendentes_7_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_4_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.5 • METAS DE TRATAMENTO DE ESGOTO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_5_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.5 - Planejamento e Tratamento de Efluentes", expanded=True):
                st.subheader("7.5 • Metas de Tratamento de Esgoto")
                st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de tratamento de esgoto?**")

                # Dicionário e lista de opções
                opts75 = {"Selecione...": 0.0, "Sim – 30": 30.0, "Não – 00": 0.0}
                lista_opts75 = list(opts75.keys())

                # Recupera os dados salvos do banco
                d75 = res_data.get("7.5") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_75 = d75.get("valor", "Selecione...")
                if v_salvo_75 not in lista_opts75:
                    v_salvo_75 = "Selecione..."

                evidencia_75_salva = d75.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_75 = f"r_75_select_{ano_sel}"
                chave_link_75 = f"l_75_txt_area_{ano_sel}"
                chave_coment_75 = f"coment_7.5_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx_salvo75 = lista_opts75.index(v_salvo_75)
                    st.radio(
                        "Selecione uma opção (7.5):",
                        options=lista_opts75,
                        index=idx_salvo75,
                        key=chave_radio_75
                    )

                with col2:
                    link_75 = st.text_area(
                        "Link/Evidência (7.5):",
                        value=evidencia_75_salva,
                        key=chave_link_75,
                        placeholder="Páginas do plano contendo os compromissos de evolução do tratamento de esgoto...",
                        height=110
                    )
                    placeholder_links_75 = st.empty()
                    links_75_visuais = re.findall(REGEX_PURE_URL, link_75 or "")
                    if links_75_visuais:
                        placeholder_links_75.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_75_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.5
                bloco_comentarios("7.5", res_data, ano_sel)

                # Feedback visual reativo da pontuação
                v_atual_75 = st.session_state.get(chave_radio_75, v_salvo_75)
                pts_atuais_75 = opts75.get(v_atual_75, 0.0)

                if pts_atuais_75 > 0:
                    cor_txt_75 = "#28a745"
                elif v_atual_75 == "Selecione...":
                    cor_txt_75 = "#6c757d"
                else:
                    cor_txt_75 = "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_75}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.5: +{pts_atuais_75:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.5", key=f"btn_salvar_7_5_{ano_sel}", type="primary"):
                    lnk_val = link_75.strip()
                    val_salvar = st.session_state.get(chave_radio_75, v_salvo_75)
                    pts_calculados = opts75.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_75, d75.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.5",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.5"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_75_salva or "")]

                    if lnk_val != evidencia_75_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.5 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.5 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.5", st.session_state.get(f"links_pendentes_7_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_5_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.5.1 • DATA DE UNIVERSALIZAÇÃO DO TRATAMENTO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_5_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.5.1 - Prazo Limite do Marco Legal do Tratamento de Esgoto", expanded=True):
                st.subheader("7.5.1 • Data de Universalização do Tratamento")
                st.write("**Qual a data prevista para universalização do tratamento de esgoto no município?**")
                st.caption("ℹ *Caso já tenha sido universalizado por completo, configure a data regulamentar padrão **01/01/2001**.*")

                # Recupera os dados salvos do banco
                d751 = res_data.get("7.5.1") or {"valor": "31/12/2033", "pontos": 0.0, "link": "", "comentario": ""}

                # Decomposição da data salva com tratamento de erro
                raw_val_751 = d751.get("valor", "31/12/2033")
                try:
                    dia_salvo, mes_salvo, ano_salvo = map(int, str(raw_val_751).split("/"))
                except Exception:
                    dia_salvo, mes_salvo, ano_salvo = 31, 12, 2033

                evidencia_751_salva = d751.get("link", "")

                # Definindo chaves do Streamlit
                chave_d = f"q751_d_num_{ano_sel}"
                chave_m = f"q751_m_num_{ano_sel}"
                chave_a = f"q751_a_num_{ano_sel}"
                chave_link_751 = f"l_751_txt_area_{ano_sel}"
                chave_coment_751 = f"coment_7.5.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    c_dia, c_mes, c_ano = st.columns(3)
                    with c_dia:
                        num_d = st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d)
                    with c_mes:
                        num_m = st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m)
                    with c_ano:
                        num_a = st.number_input("Ano", min_value=2000, max_value=2100, value=ano_salvo, key=chave_a)

                    # Regra de penalização por atraso no Marco Legal do Saneamento (31/12/2033)
                    if num_a > 2033 or (num_a == 2033 and num_m == 12 and num_d > 31) or (num_a == 2033 and num_m > 12):
                        fb_pts_751 = -5.0
                    else:
                        fb_pts_751 = 0.0

                    st.metric(label="Penalização por Atraso", value=f"{fb_pts_751:.1f} pts")

                with col2:
                    link_751 = st.text_area(
                        "Link/Evidência (7.5.1):",
                        value=evidencia_751_salva,
                        key=chave_link_751,
                        placeholder="Páginas do cronograma físico-financeiro de expansão de tratamento...",
                        height=140
                    )
                    placeholder_links_751 = st.empty()
                    links_751_visuais = re.findall(REGEX_PURE_URL, link_751 or "")
                    if links_751_visuais:
                        placeholder_links_751.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_751_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.5.1
                bloco_comentarios("7.5.1", res_data, ano_sel)

                # Feedback visual reativo
                cor_txt_751 = "#28a745" if fb_pts_751 == 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_751}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.5.1: {fb_pts_751:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.5.1", key=f"btn_salvar_7_5_1_{ano_sel}", type="primary"):
                    lnk_val = link_751.strip()
                    d_v = st.session_state.get(chave_d, num_d)
                    m_v = st.session_state.get(chave_m, num_m)
                    a_v = st.session_state.get(chave_a, num_a)

                    # Cálculo final da pontuação
                    if a_v > 2033 or (a_v == 2033 and m_v == 12 and d_v > 31) or (a_v == 2033 and m_v > 12):
                        pts_calculados = -5.0
                    else:
                        pts_calculados = 0.0

                    val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"
                    comentario_para_salvar = st.session_state.get(chave_coment_751, d751.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.5.1",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.5.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_751_salva or "")]

                    if lnk_val != evidencia_751_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.5.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.5.1", st.session_state.get(f"links_pendentes_7_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_5_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.6 • METAS DE DRENAGEM URBANAS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_6_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.6 - Diretrizes de Drenagem e Águas Pluviais", expanded=True):
                st.subheader("7.6 • Metas de Drenagem Urbana")
                st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de drenagem e manejo de águas pluviais urbanas?**")

                # Dicionário e lista de opções
                opts76 = {"Selecione...": 0.0, "Sim": 0.0, "Não": 0.0}
                lista_opts76 = list(opts76.keys())

                # Recupera os dados salvos do banco
                d76 = res_data.get("7.6") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_76 = d76.get("valor", "Selecione...")
                if v_salvo_76 not in lista_opts76:
                    v_salvo_76 = "Selecione..."

                evidencia_76_salva = d76.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_76 = f"r_76_select_{ano_sel}"
                chave_link_76 = f"l_76_txt_area_{ano_sel}"
                chave_coment_76 = f"coment_7.6_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx_salvo76 = lista_opts76.index(v_salvo_76)
                    st.radio(
                        "Selecione uma opção (7.6):",
                        options=lista_opts76,
                        index=idx_salvo76,
                        key=chave_radio_76
                    )

                with col2:
                    link_76 = st.text_area(
                        "Link/Evidência (7.6):",
                        value=evidencia_76_salva,
                        key=chave_link_76,
                        placeholder="Seções ou anexos voltados ao gerenciamento de águas pluviais...",
                        height=110
                    )
                    placeholder_links_76 = st.empty()
                    links_76_visuais = re.findall(REGEX_PURE_URL, link_76 or "")
                    if links_76_visuais:
                        placeholder_links_76.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_76_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.6
                bloco_comentarios("7.6", res_data, ano_sel)

                # Feedback visual reativo da pontuação (Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.6: +0.0 pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.6", key=f"btn_salvar_7_6_{ano_sel}", type="primary"):
                    lnk_val = link_76.strip()
                    val_salvar = st.session_state.get(chave_radio_76, v_salvo_76)
                    pts_calculados = opts76.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_76, d76.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.6",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.6"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_76_salva or "")]

                    if lnk_val != evidencia_76_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_6_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_6_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.6 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.6 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_6_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.6", st.session_state.get(f"links_pendentes_7_6_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_6_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.6.1 • DETALHAMENTO DAS METAS DE DRENAGEM (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_6_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.6.1 - Detalhes do Escopo de Manejo Pluvial", expanded=True):
                st.subheader("7.6.1 • Escopo e Cronogramas de Drenagem")
                st.write("**Assinale quais as metas estabelecidas sobre drenagem e manejo de águas pluviais urbanas:**")

                opts761 = {
                    "Metas de expansão do serviço de drenagem e manejo de águas pluviais urbanas": 0.0,
                    "Metas de qualidade na prestação do serviço de drenagem e manejo de águas pluviais urbanas": 0.0,
                    "Metas de aproveitamento de águas da chuva": 0.0,
                    "Estabelecimento de direitos e deveres dos usuários": 0.0,
                    "Estabelecimento de cronograma para o atingimento das metas assinaladas acima": 0.0
                }

                # Recupera os dados salvos do banco
                d761 = res_data.get("7.6.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                texto_seguro_761 = str(d761.get("valor", "[]"))
                evidencia_761_salva = d761.get("link", "")

                # Definindo chaves do Streamlit
                chave_link_761 = f"l_761_txt_area_{ano_sel}"
                chave_coment_761 = f"coment_7.6.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    st.write("*Selecione os parâmetros contemplados:*")
                    for i, (txt, pts) in enumerate(opts761.items()):
                        marcado = (txt in texto_seguro_761) if texto_seguro_761 and texto_seguro_761 != "[]" else False
                        st.checkbox(
                            txt,
                            value=marcado,
                            key=f"ck_761_opt_{i}_{ano_sel}"
                        )

                with col2:
                    link_761 = st.text_area(
                        "Link/Evidência (7.6.1):",
                        value=evidencia_761_salva,
                        key=chave_link_761,
                        placeholder="Páginas do plano que comprovem os eixos de macrodrenagem e diretrizes sustentáveis...",
                        height=220
                    )
                    placeholder_links_761 = st.empty()
                    links_761_visuais = re.findall(REGEX_PURE_URL, link_761 or "")
                    if links_761_visuais:
                        placeholder_links_761.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_761_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.6.1
                bloco_comentarios("7.6.1", res_data, ano_sel)

                # Feedback visual reativo da pontuação (Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.6.1: +0.0 pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.6.1", key=f"btn_salvar_7_6_1_{ano_sel}", type="primary"):
                    lnk_val = link_761.strip()

                    # Processa as opções selecionadas nos checkboxes
                    lista_selecionados = []
                    pts_totais = 0.0
                    for i, (txt, pts) in enumerate(opts761.items()):
                        if st.session_state.get(f"ck_761_opt_{i}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    val_salvar = str(lista_selecionados)
                    comentario_para_salvar = st.session_state.get(chave_coment_761, d761.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.6.1",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.6.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_761_salva or "")]

                    if lnk_val != evidencia_761_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_6_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_6_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.6.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.6.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_6_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.6.1", st.session_state.get(f"links_pendentes_7_6_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_6_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.7 • MONITORAMENTO DE ÁGUA E ESGOTO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_7_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.7 - Monitoramento e Avaliação das Ações e Metas", expanded=True):
                st.subheader("7.7 • Monitoramento de Água e Esgoto")
                st.write("**Realiza monitoramento e avaliação das ações e metas relacionadas ao abastecimento de água potável e esgotamento sanitário?**")

                # Dicionário e lista de opções
                opts77 = {"Selecione...": 0.0, "Sim – 30": 30.0, "Não – 00": 0.0}
                lista_opts77 = list(opts77.keys())

                # Recupera os dados salvos do banco
                d77 = res_data.get("7.7") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_77 = d77.get("valor", "Selecione...")
                if v_salvo_77 not in lista_opts77:
                    v_salvo_77 = "Selecione..."

                evidencia_77_salva = d77.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_77 = f"r_77_select_{ano_sel}"
                chave_link_77 = f"l_77_txt_area_{ano_sel}"
                chave_coment_77 = f"coment_7.7_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx_salvo77 = lista_opts77.index(v_salvo_77)
                    st.radio(
                        "Selecione uma opção (7.7):",
                        options=lista_opts77,
                        index=idx_salvo77,
                        key=chave_radio_77
                    )

                with col2:
                    link_77 = st.text_area(
                        "Link/Evidência (7.7):",
                        value=evidencia_77_salva,
                        key=chave_link_77,
                        placeholder="Insira as evidências do monitoramento sistemático...",
                        height=110
                    )
                    placeholder_links_77 = st.empty()
                    links_77_visuais = re.findall(REGEX_PURE_URL, link_77 or "")
                    if links_77_visuais:
                        placeholder_links_77.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_77_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.7
                bloco_comentarios("7.7", res_data, ano_sel)

                # Feedback visual reativo da pontuação
                pts_salvos_77 = float(d77.get("pontos", 0.0))
                cor_txt_77 = "#28a745" if pts_salvos_77 > 0 else ("#6c757d" if v_salvo_77 == "Selecione..." else "#dc3545")
                st.markdown(
                    f"<span style='color:{cor_txt_77}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.7: +{pts_salvos_77:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.7", key=f"btn_salvar_7_7_{ano_sel}", type="primary"):
                    lnk_val = link_77.strip()
                    val_salvar = st.session_state.get(chave_radio_77, v_salvo_77)
                    pts_calculados = opts77.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_77, d77.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.7",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.7"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_77_salva or "")]

                    if lnk_val != evidencia_77_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_7_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_7_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.7 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.7 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_7_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.7", st.session_state.get(f"links_pendentes_7_7_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_7_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.7.1 • FORMA DE MONITORAMENTO (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_7_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.7.1 - Metodologia e Instrumentos de Controle", expanded=True):
                st.subheader("7.7.1 • Forma de Monitoramento")
                st.write("**De que forma é realizado o monitoramento e avaliação relacionadas ao abastecimento de água potável e esgotamento sanitário?**")

                opts771 = {
                    "Relatórios anuais discutidos e/ou publicados": 0.0,
                    "Indicadores de eficácia e eficiência": 0.0,
                    "Avaliação de recursos aplicados": 0.0,
                    "Outro": 0.0
                }

                # Recupera os dados salvos do banco
                d771 = res_data.get("7.7.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                texto_seguro_771 = str(d771.get("valor", "[]"))
                evidencia_771_salva = d771.get("link", "")

                # Definindo chaves do Streamlit
                chave_link_771 = f"l_771_txt_area_{ano_sel}"
                chave_coment_771 = f"coment_7.7.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    st.write("*Selecione as opções aplicáveis:*")
                    for i, (txt, pts) in enumerate(opts771.items()):
                        marcado = (txt in texto_seguro_771) if texto_seguro_771 and texto_seguro_771 != "[]" else False
                        st.checkbox(
                            txt,
                            value=marcado,
                            key=f"ck_771_opt_{i}_{ano_sel}"
                        )

                with col2:
                    link_771 = st.text_area(
                        "Link/Evidência (7.7.1):",
                        value=evidencia_771_salva,
                        key=chave_link_771,
                        placeholder="Links para atas do conselho municipal, painéis SNIS ou relatórios públicos...",
                        height=180
                    )
                    placeholder_links_771 = st.empty()
                    links_771_visuais = re.findall(REGEX_PURE_URL, link_771 or "")
                    if links_771_visuais:
                        placeholder_links_771.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_771_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.7.1
                bloco_comentarios("7.7.1", res_data, ano_sel)

                # Feedback visual reativo da pontuação (Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.7.1: +0.0 pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.7.1", key=f"btn_salvar_7_7_1_{ano_sel}", type="primary"):
                    lnk_val = link_771.strip()

                    # Processa as opções selecionadas nos checkboxes
                    lista_selecionados = []
                    pts_totais = 0.0
                    for i, (txt, pts) in enumerate(opts771.items()):
                        if st.session_state.get(f"ck_771_opt_{i}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    val_salvar = str(lista_selecionados)
                    comentario_para_salvar = st.session_state.get(chave_coment_771, d771.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.7.1",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.7.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_771_salva or "")]

                    if lnk_val != evidencia_771_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_7_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_7_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.7.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.7.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_7_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.7.1", st.session_state.get(f"links_pendentes_7_7_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_7_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.8 • CRONOGRAMA DE METAS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_8_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.8 - Linha do Tempo e Escalonamento do Plano", expanded=True):
                st.subheader("7.8 • Cronograma de Metas")
                st.write("**O Plano Municipal ou Regional de Saneamento Básico possui cronograma com as metas a serem cumpridas?**")

                opts78 = {"Selecione...": 0.0, "Sim – 20": 20.0, "Não – 00": 0.0}
                lista_opts78 = list(opts78.keys())

                # Recupera os dados salvos do banco
                d78 = res_data.get("7.8") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_78 = d78.get("valor", "Selecione...")
                if v_salvo_78 not in lista_opts78:
                    v_salvo_78 = "Selecione..."

                evidencia_78_salva = d78.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_78 = f"r_78_select_{ano_sel}"
                chave_link_78 = f"l_78_txt_area_{ano_sel}"
                chave_coment_78 = f"coment_7.8_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx_salvo78 = lista_opts78.index(v_salvo_78)
                    st.radio(
                        "Selecione uma opção (7.8):",
                        options=lista_opts78,
                        index=idx_salvo78,
                        key=chave_radio_78
                    )

                with col2:
                    link_78 = st.text_area(
                        "Link/Evidência (7.8):",
                        value=evidencia_78_salva,
                        key=chave_link_78,
                        placeholder="Páginas do cronograma físico-financeiro quadrienal ou anual...",
                        height=110
                    )
                    placeholder_links_78 = st.empty()
                    links_78_visuais = re.findall(REGEX_PURE_URL, link_78 or "")
                    if links_78_visuais:
                        placeholder_links_78.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_78_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.8
                bloco_comentarios("7.8", res_data, ano_sel)

                # Feedback visual reativo da pontuação
                pts_salvos_78 = float(d78.get("pontos", 0.0))
                cor_txt_78 = "#28a745" if pts_salvos_78 > 0 else ("#6c757d" if v_salvo_78 == "Selecione..." else "#dc3545")
                st.markdown(
                    f"<span style='color:{cor_txt_78}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.8: +{pts_salvos_78:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.8", key=f"btn_salvar_7_8_{ano_sel}", type="primary"):
                    lnk_val = link_78.strip()
                    val_salvar = st.session_state.get(chave_radio_78, v_salvo_78)
                    pts_calculados = opts78.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_78, d78.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.8",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.8"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_78_salva or "")]

                    if lnk_val != evidencia_78_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_8_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_8_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.8 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.8 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_8_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.8", st.session_state.get(f"links_pendentes_7_8_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_8_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.8.1 • CUMPRIMENTO DOS PRAZOS ESTIPULADOS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_8_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.8.1 - Grau de Adimplemento das Metas e Prazos", expanded=True):
                st.subheader("7.8.1 • Cumprimento dos Prazos Estipulados")
                st.write("**As metas do Plano relacionadas ao abastecimento de água potável e esgotamento sanitário estão sendo cumpridas no prazo estipulado?**")

                opts781 = {
                    "Selecione...": 0.0,
                    "Todas as metas foram cumpridas dentro do prazo – 50": 50.0,
                    "A maior parte das metas foram cumpridas dentro do prazo – 30": 30.0,
                    "A menor parte das metas foram cumpridas dentro do prazo – 10": 10.0,
                    "As metas não foram cumpridas dentro do prazo – 00": 0.0
                }
                lista_opts781 = list(opts781.keys())

                # Recupera os dados salvos do banco
                d781 = res_data.get("7.8.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_781 = d781.get("valor", "Selecione...")
                if v_salvo_781 not in lista_opts781:
                    v_salvo_781 = "Selecione..."

                evidencia_781_salva = d781.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_781 = f"r_781_select_{ano_sel}"
                chave_link_781 = f"l_781_txt_area_{ano_sel}"
                chave_coment_781 = f"coment_7.8.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx_salvo781 = lista_opts781.index(v_salvo_781)
                    st.radio(
                        "Selecione uma opção (7.8.1):",
                        options=lista_opts781,
                        index=idx_salvo781,
                        key=chave_radio_781
                    )

                with col2:
                    link_781 = st.text_area(
                        "Link/Evidência (7.8.1):",
                        value=evidencia_781_salva,
                        key=chave_link_781,
                        placeholder="Relatórios de auditoria da agência reguladora local ou balanço de metas...",
                        height=130
                    )
                    placeholder_links_781 = st.empty()
                    links_781_visuais = re.findall(REGEX_PURE_URL, link_781 or "")
                    if links_781_visuais:
                        placeholder_links_781.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_781_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.8.1
                bloco_comentarios("7.8.1", res_data, ano_sel)

                # Feedback visual reativo da pontuação
                pts_salvos_781 = float(d781.get("pontos", 0.0))
                cor_txt_781 = "#28a745" if pts_salvos_781 > 10 else ("#6c757d" if v_salvo_781 == "Selecione..." else "#dc3545")
                st.markdown(
                    f"<span style='color:{cor_txt_781}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.8.1: +{pts_salvos_781:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.8.1", key=f"btn_salvar_7_8_1_{ano_sel}", type="primary"):
                    lnk_val = link_781.strip()
                    val_salvar = st.session_state.get(chave_radio_781, v_salvo_781)
                    pts_calculados = opts781.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_781, d781.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.8.1",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.8.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_781_salva or "")]

                    if lnk_val != evidencia_781_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_8_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_8_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.8.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.8.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_8_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.8.1", st.session_state.get(f"links_pendentes_7_8_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_8_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.8.1.1 • MOTIVOS DO NÃO CUMPRIMENTO (MÚLTIPLA ESCOLHA) (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_8_1_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.8.1.1 - Fatores de Restrição e Descumprimento de Metas", expanded=True):
                st.subheader("7.8.1.1 • Motivos do Não Cumprimento")
                st.write("**Assinale os motivos pelos quais as metas relacionadas ao abastecimento de água potável e esgotamento sanitário não estão sendo cumpridas:**")

                opts7811 = {
                    "Falta de recursos orçamentários": 0.0,
                    "Falta de aprovação legislativa": 0.0,
                    "Atraso na licitação": 0.0,
                    "Não realizou licitação necessária": 0.0,
                    "Falta de pessoal qualificado": 0.0,
                    "Falta de consenso no consórcio intermunicipal": 0.0,
                    "Outros": 0.0
                }

                # Recupera os dados salvos do banco
                d7811 = res_data.get("7.8.1.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                # Conversão segura da string salva em lista Python
                raw_valor = d7811.get("valor", "[]")
                try:
                    selecionados_salvos = ast.literal_eval(raw_valor) if isinstance(raw_valor, str) and raw_valor.startswith("[") else []
                except Exception:
                    selecionados_salvos = []

                evidencia_7811_salva = d7811.get("link", "")

                # Definindo chaves do Streamlit
                chave_link_7811 = f"l_7811_txt_area_{ano_sel}"
                chave_coment_7811 = f"coment_7.8.1.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    st.write("*Selecione as justificativas apresentadas:*")
                    for i, (txt, pts) in enumerate(opts7811.items()):
                        marcado = txt in selecionados_salvos
                        st.checkbox(
                            txt,
                            value=marcado,
                            key=f"ck_7811_opt_{i}_{ano_sel}"
                        )

                with col2:
                    link_7811 = st.text_area(
                        "Link/Evidência (7.8.1.1):",
                        value=evidencia_7811_salva,
                        key=chave_link_7811,
                        placeholder="Páginas de justificativas oficiais, pareceres do comitê técnico ou notificações...",
                        height=240
                    )
                    placeholder_links_7811 = st.empty()
                    links_7811_visuais = re.findall(REGEX_PURE_URL, link_7811 or "")
                    if links_7811_visuais:
                        placeholder_links_7811.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_7811_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.8.1.1
                bloco_comentarios("7.8.1.1", res_data, ano_sel)

                # Feedback visual de pontuação (Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.8.1.1: +0.0 pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.8.1.1", key=f"btn_salvar_7_8_1_1_{ano_sel}", type="primary"):
                    lnk_val = link_7811.strip()
                    lista_selecionados = []
                    pts_totais = 0.0

                    # Coleta as opções marcadas
                    for idx, (txt, pts) in enumerate(opts7811.items()):
                        if st.session_state.get(f"ck_7811_opt_{idx}_{ano_sel}", False):
                            lista_selecionados.append(txt)
                            pts_totais += pts

                    val_salvar = str(lista_selecionados)
                    comentario_para_salvar = st.session_state.get(chave_coment_7811, d7811.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.8.1.1",
                        valor=val_salvar,
                        pontos=float(pts_totais),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.8.1.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_totais),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_7811_salva or "")]

                    if lnk_val != evidencia_7811_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_8_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_8_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.8.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.8.1.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_8_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.8.1.1", st.session_state.get(f"links_pendentes_7_8_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_8_1_1_{ano_sel}"] = False

# =============================================================================
        # QUESITO 7.9 • ÁREAS PRIORITÁRIAS / CRÍTICAS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_9_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.9 - Identificação de Vulnerabilidades Setoriais", expanded=True):
                st.subheader("7.9 • Áreas Prioritárias / Críticas")
                st.write("**Possui previsão para áreas prioritárias/críticas de abastecimento de água potável e esgotamento sanitário do município?**")
                st.caption("ℹ *Ex.: Áreas com assentamentos habitacionais precários, corpos de água degradados (em especial nas regiões de mananciais) ou áreas vulneráveis quanto aos indicadores de saúde pública.*")

                opts79 = {
                    "Selecione...": 0.0,
                    "Sim – 03": 3.0,
                    "Não – 00": 0.0,
                    "Não há áreas prioritárias/críticas no município – 03": 3.0
                }
                lista_opts79 = list(opts79.keys())

                # Recupera os dados salvos do banco
                d79 = res_data.get("7.9") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_79 = d79.get("valor", "Selecione...")
                if v_salvo_79 not in lista_opts79:
                    v_salvo_79 = "Selecione..."

                evidencia_79_salva = d79.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_79 = f"r_79_select_{ano_sel}"
                chave_link_79 = f"l_79_txt_area_{ano_sel}"
                chave_coment_79 = f"coment_7.9_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx_salvo79 = lista_opts79.index(v_salvo_79)
                    st.radio(
                        "Selecione uma opção (7.9):",
                        options=lista_opts79,
                        index=idx_salvo79,
                        key=chave_radio_79
                    )

                with col2:
                    link_79 = st.text_area(
                        "Link/Evidência (7.9):",
                        value=evidencia_79_salva,
                        key=chave_link_79,
                        placeholder="Seção mapeada no Plano Municipal ou relatórios de vulnerabilidade social...",
                        height=120
                    )
                    placeholder_links_79 = st.empty()
                    links_79_visuais = re.findall(REGEX_PURE_URL, link_79 or "")
                    if links_79_visuais:
                        placeholder_links_79.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_79_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.9
                bloco_comentarios("7.9", res_data, ano_sel)

                # Feedback visual reativo da pontuação
                pts_salvos_79 = float(d79.get("pontos", 0.0))
                cor_txt_79 = "#28a745" if pts_salvos_79 > 0 else ("#6c757d" if v_salvo_79 == "Selecione..." else "#dc3545")
                st.markdown(
                    f"<span style='color:{cor_txt_79}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.9: +{pts_salvos_79:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.9", key=f"btn_salvar_7_9_{ano_sel}", type="primary"):
                    lnk_val = link_79.strip()
                    val_salvar = st.session_state.get(chave_radio_79, v_salvo_79)
                    pts_calculados = opts79.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_79, d79.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.9",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.9"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_79_salva or "")]

                    if lnk_val != evidencia_79_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_9_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_9_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.9 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.9 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_9_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.9", st.session_state.get(f"links_pendentes_7_9_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_9_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.10 • ÚLTIMA REVISÃO DO PLANO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_10_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.10 - Vigência e Atualização Tempestiva do Plano", expanded=True):
                st.subheader("7.10 • Última Revisão do Plano")
                st.write("**Qual a data da última revisão do Plano Municipal ou Regional de Saneamento Básico?**")
                st.caption("ℹ *Se não houve revisão do plano de saneamento básico, informe a data de início de vigência original dele.*")

                # Recupera os dados salvos do banco
                d710 = res_data.get("7.10") or {"valor": "01/01/2015", "pontos": 0.0, "link": "", "comentario": ""}

                # Tratamento de conversão da data salva (DD/MM/AAAA)
                val_data_salva = d710.get("valor", "01/01/2015")
                try:
                    dia_salvo, mes_salvo, ano_salvo = map(int, val_data_salva.split("/"))
                except Exception:
                    dia_salvo, mes_salvo, ano_salvo = 1, 1, 2015

                evidencia_710_salva = d710.get("link", "")

                # Definindo chaves do Streamlit
                chave_d_710 = f"q710_d_num_{ano_sel}"
                chave_m_710 = f"q710_m_num_{ano_sel}"
                chave_a_710 = f"q710_a_num_{ano_sel}"
                chave_link_710 = f"l_710_txt_area_{ano_sel}"
                chave_coment_710 = f"coment_7.10_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    c_dia, c_mes, c_ano = st.columns(3)
                    with c_dia:
                        st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d_710)
                    with c_mes:
                        st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m_710)
                    with c_ano:
                        st.number_input("Ano", min_value=1900, max_value=2100, value=ano_salvo, key=chave_a_710)

                    # Leitura atual dos campos para exibição do status na tela
                    cur_d = st.session_state.get(chave_d_710, dia_salvo)
                    cur_m = st.session_state.get(chave_m_710, mes_salvo)
                    cur_a = st.session_state.get(chave_a_710, ano_salvo)

                    if cur_a < 2014 or (cur_a == 2014 and cur_m < 12) or (cur_a == 2014 and cur_m == 12 and cur_d <= 31):
                        fb_pts_710 = -30.0
                    else:
                        fb_pts_710 = 0.0

                    st.metric(label="Penalidade por Defasagem", value=f"{fb_pts_710:.1f} pts")

                with col2:
                    link_710 = st.text_area(
                        "Link/Evidência (7.10):",
                        value=evidencia_710_salva,
                        key=chave_link_710,
                        placeholder="Página do Diário Oficial que publicou o decreto de revisão ou lei sancionada...",
                        height=130
                    )
                    placeholder_links_710 = st.empty()
                    links_710_visuais = re.findall(REGEX_PURE_URL, link_710 or "")
                    if links_710_visuais:
                        placeholder_links_710.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_710_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 7.10
                bloco_comentarios("7.10", res_data, ano_sel)

                # Feedback visual de pontuação baseado na gravação salva
                pts_salvos_710 = float(d710.get("pontos", 0.0))
                cor_txt_710 = "#28a745" if pts_salvos_710 == 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_710}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.10: {pts_salvos_710:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.10", key=f"btn_salvar_7_10_{ano_sel}", type="primary"):
                    lnk_val = link_710.strip()
                    d_v = st.session_state.get(chave_d_710, dia_salvo)
                    m_v = st.session_state.get(chave_m_710, mes_salvo)
                    a_v = st.session_state.get(chave_a_710, ano_salvo)

                    # Regra de negócio para aplicação da penalidade
                    if a_v < 2014 or (a_v == 2014 and m_v < 12) or (a_v == 2014 and m_v == 12 and d_v <= 31):
                        pts_calculados = -30.0
                    else:
                        pts_calculados = 0.0

                    val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"
                    comentario_para_salvar = st.session_state.get(chave_coment_710, d710.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="7.10",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["7.10"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_710_salva or "")]

                    if lnk_val != evidencia_710_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_10_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_10_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 7.10 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 7.10 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_10_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.10", st.session_state.get(f"links_pendentes_7_10_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_10_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.0 • PLANO DE GESTÃO INTEGRADA DE RESÍDUOS SÓLIDOS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.0 - Elaboração do Plano de Resíduos Sólidos (PMGIRS/PRGIRS)", expanded=True):
                st.subheader("8.0 • Existência de Plano Temático")
                st.write("**Foi elaborado o Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos?**")

                opts80 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                lista_opts80 = list(opts80.keys())

                # Recupera os dados salvos do banco
                d80 = res_data.get("8.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_80 = d80.get("valor", "Selecione...")
                if v_salvo_80 not in lista_opts80:
                    v_salvo_80 = "Selecione..."

                evidencia_80_salva = d80.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_80 = f"r_80_select_{ano_sel}"
                chave_link_80 = f"l_80_txt_area_{ano_sel}"
                chave_coment_80 = f"coment_8.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx80 = lista_opts80.index(v_salvo_80)
                    st.radio(
                        "Selecione uma opção (8.0):",
                        options=lista_opts80,
                        index=idx80,
                        key=chave_radio_80
                    )

                with col2:
                    link_80 = st.text_area(
                        "Link/Evidência (8.0):",
                        value=evidencia_80_salva,
                        key=chave_link_80,
                        placeholder="Insira o link para o decreto, lei ou o plano digitalizado...",
                        height=100
                    )
                    placeholder_links_80 = st.empty()
                    links_80_visuais = re.findall(REGEX_PURE_URL, link_80 or "")
                    if links_80_visuais:
                        placeholder_links_80.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_80_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 8.0
                bloco_comentarios("8.0", res_data, ano_sel)

                # Feedback visual de pontuação (Referencial)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.0: +0.0 pontos (Referencial)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.0", key=f"btn_salvar_8_0_{ano_sel}", type="primary"):
                    lnk_val = link_80.strip()
                    val_salvar = st.session_state.get(chave_radio_80, v_salvo_80)
                    pts_calculados = opts80.get(val_salvar, 0.0)
                    comentario_para_salvar = st.session_state.get(chave_coment_80, d80.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.0",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.0"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novo link para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_80_salva or "")]

                    if lnk_val != evidencia_80_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.0", st.session_state.get(f"links_pendentes_8_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = False

# =============================================================================
        # QUESITO 8.1 • INSTRUMENTO NORMATIVO DE PUBLICAÇÃO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.1 - Dados de Formalização Legal do Plano", expanded=True):
                st.subheader("8.1 • Instrumento Normativo, Número e Data")
                st.write("**Informe o Instrumento normativo, Número e Data da publicação:**")

                # Recupera os dados salvos do banco
                d81 = res_data.get("8.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_81 = d81.get("valor", "")
                evidencia_81_salva = d81.get("link", "") or v_salvo_81

                # Definindo chaves do Streamlit
                chave_texto_81 = f"q81_txt_area_{ano_sel}"
                chave_coment_81 = f"coment_8.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    texto_81 = st.text_area(
                        "Dados da Publicação (8.1):",
                        value=v_salvo_81,
                        key=chave_texto_81,
                        placeholder="Ex: Lei Municipal nº 4.321, de 15 de Outubro de 2021",
                        height=110
                    )

                with col2:
                    st.write("*Links ativos extraídos do texto:*")
                    placeholder_links_81 = st.empty()
                    links_81_visuais = re.findall(REGEX_PURE_URL, texto_81 or "")
                    if links_81_visuais:
                        placeholder_links_81.markdown(
                            " | ".join([f"🔗 [{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_81_visuais])
                        )
                    else:
                        placeholder_links_81.caption("Nenhum link detectado no corpo do texto.")

                # Renderiza o bloco de comentários do Quesito 8.1
                bloco_comentarios("8.1", res_data, ano_sel)

                # Feedback visual de pontuação (Informativo)
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.1: +0.0 pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.1", key=f"btn_salvar_8_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_texto_81, v_salvo_81).strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_81, d81.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.1",
                        valor=val_salvar,
                        pontos=0.0,
                        link=val_salvar,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.1"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": val_salvar,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links inseridos no texto para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_salvar or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_81_salva or "")]

                    if val_salvar != v_salvo_81 and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.1", st.session_state.get(f"links_pendentes_8_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.2 • ENDEREÇO ELETRÔNICO DO PLANO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.2 - Transparência Ativa e Disponibilização Digital", expanded=True):
                st.subheader("8.2 • Página Eletrônica do Plano")
                st.write("**Informe a página eletrônica (link na internet) do instrumento normativo do Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos:**")
                st.caption("ℹ *Se não estiver disponível na internet, insira no campo de resposta o texto **XYZ**.*")

                # Recupera os dados salvos do banco
                d82 = res_data.get("8.2") or {"valor": "XYZ", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_82 = d82.get("valor", "XYZ")
                evidencia_82_salva = d82.get("link", "")

                # Definindo chaves do Streamlit
                chave_input_82 = f"q82_txt_input_{ano_sel}"
                chave_link_82 = f"l_82_txt_area_{ano_sel}"
                chave_coment_82 = f"coment_8.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    val82 = st.text_input(
                        "Endereço eletrônico (Link) ou XYZ:",
                        value=v_salvo_82,
                        key=chave_input_82,
                        placeholder="http://..."
                    )

                    cur_val_82 = st.session_state.get(chave_input_82, v_salvo_82)
                    fb_pts_82 = 0.0 if cur_val_82.strip().upper() == "XYZ" or cur_val_82.strip() == "" else 2.0
                    st.metric(label="Pontuação do Quesito", value=f"{fb_pts_82:.1f} pts")

                    placeholder_links_v82 = st.empty()
                    links_v82_visuais = re.findall(REGEX_PURE_URL, cur_val_82 or "")
                    if links_v82_visuais:
                        placeholder_links_v82.markdown(
                            "**🔗 Link do Plano:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_v82_visuais])
                        )

                with col2:
                    link_82 = st.text_area(
                        "Link/Evidência Adicional (8.2):",
                        value=evidencia_82_salva,
                        key=chave_link_82,
                        placeholder="Links complementares como portais da transparência ou repositórios municipais...",
                        height=130
                    )
                    placeholder_links_82 = st.empty()
                    links_82_visuais = re.findall(REGEX_PURE_URL, link_82 or "")
                    if links_82_visuais:
                        placeholder_links_82.markdown(
                            "**🔗 Link complementar:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_82_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 8.2
                bloco_comentarios("8.2", res_data, ano_sel)

                # Feedback visual de pontuação baseado na gravação salva
                pts_salvos_82 = float(d82.get("pontos", 0.0))
                cor_txt_82 = "#28a745" if pts_salvos_82 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_82}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.2: +{pts_salvos_82:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.2", key=f"btn_salvar_8_2_{ano_sel}", type="primary"):
                    val_input = st.session_state.get(chave_input_82, v_salvo_82).strip()
                    lnk_val = link_82.strip()

                    if val_input.upper() == "XYZ" or val_input == "":
                        pts_calculados = 0.0
                    else:
                        pts_calculados = 2.0

                    comentario_para_salvar = st.session_state.get(chave_coment_82, d82.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.2",
                        valor=val_input,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.2"] = {
                        "valor": val_input,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais_val = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_input or "")]
                    links_atuais_lnk = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    todos_atuais = links_atuais_val + links_atuais_lnk

                    links_antigos_val = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_82 or "")]
                    links_antigos_lnk = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_82_salva or "")]
                    todos_antigos = links_antigos_val + links_antigos_lnk

                    if (val_input != v_salvo_82 or lnk_val != evidencia_82_salva) and todos_atuais and todos_atuais != todos_antigos:
                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = todos_atuais
                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.2", st.session_state.get(f"links_pendentes_8_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.3 • CARACTERIZAÇÃO DOS RESÍDUOS SÓLIDOS URBANOS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.3 - Gravimetria, Qualificação e Quantificação de RSU", expanded=True):
                st.subheader("8.3 • Caracterização Qualitativa e Quantitativa")
                st.write("**A Prefeitura realizou a caracterização qualitativa e quantitativa dos resíduos sólidos urbanos gerados no município, identificando ainda sua origem?**")

                opc83 = ["Selecione...", "Sim – 10", "Não – 00"]

                # Recupera os dados salvos do banco
                d83 = res_data.get("8.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_83 = d83.get("valor", "Selecione...")
                if v_salvo_83 not in opc83:
                    v_salvo_83 = "Selecione..."

                evidencia_83_salva = d83.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_83 = f"r_83_select_{ano_sel}"
                chave_link_83 = f"l_83_txt_area_{ano_sel}"
                chave_coment_83 = f"coment_8.3_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx83 = opc83.index(v_salvo_83)
                    st.radio(
                        "Selecione uma opção (8.3):",
                        options=opc83,
                        index=idx83,
                        key=chave_radio_83
                    )

                    v_atual_83 = st.session_state.get(chave_radio_83, v_salvo_83)
                    fb_pts_83 = 10.0 if "Sim" in v_atual_83 else 0.0
                    st.metric(label="Pontuação do Quesito", value=f"{fb_pts_83:.1f} pts")

                with col2:
                    link_83 = st.text_area(
                        "Link/Evidência (8.3):",
                        value=evidencia_83_salva,
                        key=chave_link_83,
                        placeholder="Estudos gravimétricos oficiais, laudos técnicos ou relatórios anexos ao PMGIRS...",
                        height=110
                    )
                    placeholder_links_83 = st.empty()
                    links_83_visuais = re.findall(REGEX_PURE_URL, link_83 or "")
                    if links_83_visuais:
                        placeholder_links_83.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_83_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 8.3
                bloco_comentarios("8.3", res_data, ano_sel)

                # Feedback visual de pontuação baseado na gravação salva
                pts_salvos_83 = float(d83.get("pontos", 0.0))
                val_salvo_atual = d83.get("valor", "Selecione...")

                if pts_salvos_83 > 0:
                    cor_txt_83 = "#28a745"
                elif val_salvo_atual == "Selecione...":
                    cor_txt_83 = "#6c757d"
                else:
                    cor_txt_83 = "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_83}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.3: +{pts_salvos_83:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.3", key=f"btn_salvar_8_3_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_83, v_salvo_83)
                    lnk_val = link_83.strip()

                    pts_calculados = 10.0 if "Sim" in val_salvar else 0.0
                    comentario_para_salvar = st.session_state.get(chave_coment_83, d83.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.3",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.3"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_83_salva or "")]

                    if lnk_val != evidencia_83_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.3 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.3", st.session_state.get(f"links_pendentes_8_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.3.1 • MÉTODOS DE CARACTERIZAÇÃO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.3.1 - Métodos de Caracterização", expanded=True):
                st.subheader("8.3.1 • Métodos de Caracterização")
                st.write("**Assinale a forma utilizada para caracterizar os resíduos sólidos do município:**")

                # Recupera os dados salvos do banco
                d831 = res_data.get("8.3.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                texto_seguro_831 = str(d831.get("valor", "")) if d831.get("valor") not in ["", "[]"] else ""
                evidencia_831_salva = d831.get("link", "")
                opts831 = [
                    "Estimativa com base em dados secundários",
                    "Realização de estudo gravimétrico, por amostragem",
                    "Pesquisa de dados primários com medição direta",
                    "Outros"
                ]

                # Definindo chaves do Streamlit
                chave_link_831 = f"l831_in_{ano_sel}"
                chave_coment_831 = f"coment_8.3.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    for opt in opts831:
                        st.checkbox(
                            opt,
                            value=(opt in texto_seguro_831),
                            key=f"c831_{opt}_{ano_sel}"
                        )

                    # Quesito puramente referencial
                    st.metric(label="Pontuação do Quesito", value="0.0 pts", help="Quesito de caráter referencial/informativo.")

                with col2:
                    link_831 = st.text_area(
                        "Link/Evidência (8.3.1):",
                        value=evidencia_831_salva,
                        key=chave_link_831,
                        placeholder="Inserir laudos, links de estudos ou documentação complementar...",
                        height=120
                    )
                    placeholder_links_831 = st.empty()
                    links_831_visuais = re.findall(REGEX_PURE_URL, link_831 or "")
                    if links_831_visuais:
                        placeholder_links_831.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_831_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 8.3.1
                bloco_comentarios("8.3.1", res_data, ano_sel)

                # Feedback visual de pontuação referencial
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.3.1: +0.0 pontos (Referencial)</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.3.1", key=f"btn_salvar_8_3_1_{ano_sel}", type="primary"):
                    lnk_val = link_831.strip()
                    marcados = [opt for opt in opts831 if st.session_state.get(f"c831_{opt}_{ano_sel}", False)]
                    val_salvar = str(marcados)

                    pts_calculados = 0.0
                    comentario_para_salvar = st.session_state.get(chave_coment_831, d831.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.3.1",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.3.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_831_salva or "")]

                    if lnk_val != evidencia_831_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.3.1", st.session_state.get(f"links_pendentes_8_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_3_1_{ano_sel}"] = False

# =============================================================================
        # QUESITO 8.4 • CRONOGRAMA DE METAS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.4 - Cronograma de Metas", expanded=True):
                st.subheader("8.4 • Cronograma de Metas")
                st.write("**Possui cronograma com as metas a serem cumpridas de resíduos sólidos?**")

                opc84 = ["Selecione...", "Sim – 20", "Não – 00"]

                # Recupera os dados salvos do banco
                d84 = res_data.get("8.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_84 = d84.get("valor", "Selecione...")
                if v_salvo_84 not in opc84:
                    v_salvo_84 = "Selecione..."

                evidencia_84_salva = d84.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_84 = f"r84_in_{ano_sel}"
                chave_link_84 = f"l84_in_{ano_sel}"
                chave_coment_84 = f"coment_8.4_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx84 = opc84.index(v_salvo_84)
                    st.radio(
                        "Selecione uma opção (8.4):",
                        options=opc84,
                        index=idx84,
                        key=chave_radio_84
                    )

                    v_atual_84 = st.session_state.get(chave_radio_84, v_salvo_84)
                    fb_pts_84 = 20.0 if "Sim" in v_atual_84 else 0.0
                    st.metric(label="Pontuação do Quesito", value=f"{fb_pts_84:.1f} pts")

                with col2:
                    link_84 = st.text_area(
                        "Link/Evidência (8.4):",
                        value=evidencia_84_salva,
                        key=chave_link_84,
                        placeholder="Inserir documentos comprobatórios, cronogramas de metas do PMGIRS...",
                        height=110
                    )
                    placeholder_links_84 = st.empty()
                    links_84_visuais = re.findall(REGEX_PURE_URL, link_84 or "")
                    if links_84_visuais:
                        placeholder_links_84.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_84_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 8.4
                bloco_comentarios("8.4", res_data, ano_sel)

                # Feedback visual de pontuação baseado na gravação salva
                pts_salvos_84 = float(d84.get("pontos", 0.0))
                val_salvo_atual = d84.get("valor", "Selecione...")

                if pts_salvos_84 > 0:
                    cor_txt_84 = "#28a745"
                elif val_salvo_atual == "Selecione...":
                    cor_txt_84 = "#6c757d"
                else:
                    cor_txt_84 = "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_84}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.4: +{pts_salvos_84:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.4", key=f"btn_salvar_8_4_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_84, v_salvo_84)
                    lnk_val = link_84.strip()

                    pts_calculados = 20.0 if "Sim" in val_salvar else 0.0
                    comentario_para_salvar = st.session_state.get(chave_coment_84, d84.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.4",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.4"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_84_salva or "")]

                    if lnk_val != evidencia_84_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.4 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.4 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.4", st.session_state.get(f"links_pendentes_8_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.4.1 • METAS ESTABELECIDAS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.4.1 - Metas Estabelecidas", expanded=True):
                st.subheader("8.4.1 • Metas Estabelecidas")
                st.write("**Assinale quais as metas estabelecidas sobre resíduos sólidos:**")

                # Dicionário de opções e pontuações correspondentes
                opts841 = {
                    "Metas de redução da geração de resíduos sólidos na fonte – 2,5": 2.5,
                    "Metas de coleta seletiva – 02": 2.0,
                    "Metas de redução de resíduos sólidos secos dispostos em aterros – 2,5": 2.5,
                    "Metas de redução de resíduos sólidos úmidos dispostos em aterros – 2,5": 2.5,
                    "Outro – 0,5": 0.5
                }

                # Recupera os dados salvos do banco
                d841 = res_data.get("8.4.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                texto_seguro_841 = str(d841.get("valor", "")) if d841.get("valor") not in ["", "[]"] else ""
                evidencia_841_salva = d841.get("link", "")

                # Definindo chaves do Streamlit
                chave_link_841 = f"l841_in_{ano_sel}"
                chave_coment_841 = f"coment_8.4.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    marcados_atuais = []
                    for txt in opts841.keys():
                        chk_key = f"c841_{txt}_{ano_sel}"
                        chk_val = st.checkbox(
                            txt,
                            value=(txt in texto_seguro_841),
                            key=chk_key
                        )
                        if chk_val:
                            marcados_atuais.append(txt)

                    # Cálculo em tempo real da pontuação selecionada
                    pts_tempo_real_841 = sum(opts841[txt] for txt in marcados_atuais)
                    st.metric(label="Pontuação do Quesito", value=f"{pts_tempo_real_841:.1f} pts")

                with col2:
                    link_841 = st.text_area(
                        "Link/Evidência (8.4.1):",
                        value=evidencia_841_salva,
                        key=chave_link_841,
                        placeholder="Inserir laudos, links dos planos de metas ou documentos comprobatórios...",
                        height=150
                    )
                    placeholder_links_841 = st.empty()
                    links_841_visuais = re.findall(REGEX_PURE_URL, link_841 or "")
                    if links_841_visuais:
                        placeholder_links_841.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_841_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 8.4.1
                bloco_comentarios("8.4.1", res_data, ano_sel)

                # Feedback visual de pontuação baseado na gravação salva
                pts_salvos_841 = float(d841.get("pontos", 0.0))
                cor_txt_841 = "#28a745" if pts_salvos_841 > 0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_841}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.4.1: +{pts_salvos_841:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.4.1", key=f"btn_salvar_8_4_1_{ano_sel}", type="primary"):
                    lnk_val = link_841.strip()
                    marcados = [txt for txt in opts841.keys() if st.session_state.get(f"c841_{txt}_{ano_sel}", False)]
                    val_salvar = str(marcados)

                    pts_calculados = sum(opts841[txt] for txt in marcados)
                    comentario_para_salvar = st.session_state.get(chave_coment_841, d841.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.4.1",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.4.1"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_841_salva or "")]

                    if lnk_val != evidencia_841_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.4.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.4.1", st.session_state.get(f"links_pendentes_8_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_4_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.4.2 • MONITORAMENTO E AVALIAÇÃO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.4.2 - Monitoramento e Avaliação", expanded=True):
                st.subheader("8.4.2 • Monitoramento e Avaliação")
                st.write("**Realiza monitoramento e avaliação das ações e metas de resíduos sólidos?**")

                opc842 = ["Selecione...", "Sim – 30", "Não – 00"]

                # Recupera os dados salvos do banco
                d842 = res_data.get("8.4.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_842 = d842.get("valor", "Selecione...")
                if v_salvo_842 not in opc842:
                    v_salvo_842 = "Selecione..."

                evidencia_842_salva = d842.get("link", "")

                # Definindo chaves do Streamlit
                chave_radio_842 = f"r842_in_{ano_sel}"
                chave_link_842 = f"l842_in_{ano_sel}"
                chave_coment_842 = f"coment_8.4.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    idx842 = opc842.index(v_salvo_842)
                    st.radio(
                        "Selecione uma opção (8.4.2):",
                        options=opc842,
                        index=idx842,
                        key=chave_radio_842
                    )

                    v_atual_842 = st.session_state.get(chave_radio_842, v_salvo_842)
                    fb_pts_842 = 30.0 if "Sim" in v_atual_842 else 0.0
                    st.metric(label="Pontuação do Quesito", value=f"{fb_pts_842:.1f} pts")

                with col2:
                    link_842 = st.text_area(
                        "Link/Evidência (8.4.2):",
                        value=evidencia_842_salva,
                        key=chave_link_842,
                        placeholder="Inserir relatórios de monitoramento, atas de avaliação do PMGIRS...",
                        height=110
                    )
                    placeholder_links_842 = st.empty()
                    links_842_visuais = re.findall(REGEX_PURE_URL, link_842 or "")
                    if links_842_visuais:
                        placeholder_links_842.markdown(
                            "**🔗 Link ativo:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_842_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 8.4.2
                bloco_comentarios("8.4.2", res_data, ano_sel)

                # Feedback visual de pontuação baseado na gravação salva
                pts_salvos_842 = float(d842.get("pontos", 0.0))
                val_salvo_atual = d842.get("valor", "Selecione...")

                if pts_salvos_842 > 0:
                    cor_txt_842 = "#28a745"
                elif val_salvo_atual == "Selecione...":
                    cor_txt_842 = "#6c757d"
                else:
                    cor_txt_842 = "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_842}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.4.2: +{pts_salvos_842:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.4.2", key=f"btn_salvar_8_4_2_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_842, v_salvo_842)
                    lnk_val = link_842.strip()

                    pts_calculados = 30.0 if "Sim" in val_salvar else 0.0
                    comentario_para_salvar = st.session_state.get(chave_coment_842, d842.get("comentario", ""))

                    # Persistência no banco via save_resp
                    save_resp(
                        qid="8.4.2",
                        valor=val_salvar,
                        pontos=float(pts_calculados),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização em memória
                    res_data["8.4.2"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_842_salva or "")]

                    if lnk_val != evidencia_842_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 8.4.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 8.4.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.4.2", st.session_state.get(f"links_pendentes_8_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_4_2_{ano_sel}"] = False

