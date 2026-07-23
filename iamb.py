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
