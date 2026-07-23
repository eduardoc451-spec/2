import re

# Adicione no topo do arquivo igov.py:
REGEX_PURE_URL = r'((https?://[^\s<>"]+))'
import os
import sys
import re
import json
import warnings
import logging
from datetime import datetime, date
from io import BytesIO

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import streamlit as st

# Silencia alertas e logs não críticos no console/interface
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore")
os.environ["STREAMLIT_LOGGER_LEVEL"] = "error"
os.environ["PYTHONWARNINGS"] = "ignore"
logging.getLogger("streamlit").setLevel(logging.ERROR)

# Bibliotecas para o PDF (Requer: pip install reportlab)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart

# Bibliotecas para os Gráficos (Requer: pip install plotly)
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
# CONEXÃO OTIMIZADA E SEGURA COM O NEON (POSTGRESQL)
# =============================================================================

def get_db_url():
    """Recupera, higieniza e valida a URL de conexão do Neon."""
    db_url = os.environ.get("DATABASE_URL") or st.secrets.get("DATABASE_URL")
    if not db_url:
        st.error("❌ A variável DATABASE_URL do Neon não foi configurada nos Segredos do Streamlit!")
        st.stop()
    
    # 1. Remove o parâmetro channel_binding que provoca erros no psycopg2
    if "channel_binding=" in db_url:
        db_url = db_url.split("&channel_binding=")[0].split("?channel_binding=")[0]
    
    # 2. Garante o parâmetro de criptografia SSL exigido pelo Neon
    if "sslmode=require" not in db_url:
        db_url += ("&" if "?" in db_url else "?") + "sslmode=require"
        
    return db_url

class get_connection:
    """Context manager seguro para conexões diretas e gerenciadas com o Neon."""
    def __enter__(self):
        try:
            self.conn = psycopg2.connect(get_db_url())
            return self.conn
        except Exception as e:
            logging.error(f"Erro ao conectar com o Neon PostgreSQL: {e}")
            raise e

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "conn") and self.conn:
            try:
                if getattr(self.conn, "closed", 0) == 0:
                    if exc_type:
                        self.conn.rollback()
                    else:
                        self.conn.commit()
            except Exception as e:
                logging.error(f"Erro no encerramento da transação: {e}")
            finally:
                # Fecha a conexão após o uso (deixa o pooler do Neon gerenciar no servidor)
                try:
                    self.conn.close()
                except Exception:
                    pass

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

import streamlit as st
import json
import logging
import re
from datetime import datetime, date
import psycopg2
from psycopg2.extras import RealDictCursor

# Importe sua função de conexão existente (get_connection) ou ajuste se necessário
# from database import get_connection

# =============================================================================
# 1. FUNÇÕES DE BANCO DE DADOS (TABELA EXCLUSIVA: respostas_igov)
# =============================================================================

def init_db():
    """Garante a criação da tabela exclusiva respostas_igov."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS respostas_igov (
                        id VARCHAR(50) NOT NULL,
                        ano INTEGER NOT NULL,
                        valor TEXT,
                        pontos DOUBLE PRECISION DEFAULT 0,
                        link TEXT,
                        comentarios JSONB DEFAULT '[]'::jsonb,
                        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id, ano)
                    );
                """)
            conn.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar o banco respostas_igov: {e}")


@st.cache_data(ttl=2)
def load_respostas(ano: int) -> dict:
    """Busca os dados direto da tabela exclusiva respostas_igov."""
    respostas = {}
    try:
        ano_int = int(ano)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id, valor, pontos, link, comentarios FROM respostas_igov WHERE ano = %s",
                    (ano_int,)
                )
                rows = cursor.fetchall()
                for row in rows:
                    comentarios = row["comentarios"] or []
                    if isinstance(comentarios, str):
                        try:
                            comentarios = json.loads(comentarios)
                        except Exception:
                            comentarios = []
                            
                    respostas[str(row["id"])] = {
                        "valor": row["valor"] or "",
                        "pontos": float(row["pontos"] or 0.0),
                        "link": row["link"] or "",
                        "comentarios": comentarios
                    }
    except Exception as e:
        logging.error(f"Erro ao carregar iGov do ano {ano}: {e}")
    return respostas


def save_resp(qid, valor, pontos, link, comentarios=None):
    """Salva/Atualiza na tabela exclusiva respostas_igov sem conflito com iCidade."""
    ano_sel = st.session_state.get("ano_referencia_igov") or st.session_state.get("ano_referencia_global") or 2024
    ano_int = int(ano_sel)

    if comentarios is None:
        dados_atuais = load_respostas(ano_int)
        comentarios = dados_atuais.get(str(qid), {}).get("comentarios", [])

    comentarios_json = json.dumps(comentarios, ensure_ascii=False)
    timestamp_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO respostas_igov (id, ano, valor, pontos, link, comentarios, atualizado_em)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (id, ano) DO UPDATE SET
                        valor = EXCLUDED.valor,
                        pontos = EXCLUDED.pontos,
                        link = EXCLUDED.link,
                        comentarios = EXCLUDED.comentarios,
                        atualizado_em = EXCLUDED.atualizado_em;
                """, (str(qid), ano_int, str(valor), float(pontos), str(link), comentarios_json, timestamp_atual))
            conn.commit()
        
        # Limpa cache e atualiza sessão do Streamlit
        st.cache_data.clear()
        st.session_state[f"respostas_igov_{ano_int}"] = load_respostas(ano_int)
    except Exception as e:
        st.error(f"Erro ao salvar iGov {qid}: {e}")
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
    ano_sel = st.session_state.get("ano_referencia_igov", date.today().year)
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
# 3. FUNÇÕES DE ANÁLISE E HISTÓRICO (ISOLADO PARA IGOV)
# =============================================================================

@st.cache_data(ttl=60)
def get_all_years_data():
    """Retorna todos os registros do iGov agrupados por ano."""
    all_data = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id, ano, valor, pontos, link, comentarios FROM respostas WHERE modulo = 'igov' ORDER BY ano DESC")
                rows = cursor.fetchall()
                for row in rows:
                    qid, ano = row["id"], row["ano"]
                    comentarios = row["comentarios"] or []
                    if isinstance(comentarios, str):
                        try:
                            comentarios = json.loads(comentarios)
                        except Exception:
                            comentarios = []

                    if ano not in all_data:
                        all_data[ano] = {}
                    all_data[ano][qid] = {
                        "valor": row["valor"] or "", 
                        "pontos": row["pontos"] or 0.0, 
                        "link": row["link"] or "", 
                        "comentarios": comentarios
                    }
    except Exception as e:
        logging.error(f"Erro ao buscar dados históricos do iGov: {e}")
    return all_data


def analyze_performance(res_data):
    """Mapeia os pontos fortes e fragilidades do ano atual no iGov usando o dicionário TETOS_VALIDOS."""
    pontos_fortes = []
    criticos_zero = {"Alta": [], "Média": [], "Baixa": []}
    criticos_negativos = {"Alta": [], "Média": [], "Baixa": []}

    # Novo dicionário de tetos máximos por quesito
    TETOS_VALIDOS = {
        "1.0": 30, "1.1": 30, "1.2": 30, "1.3": 30, "1.3.1": 30, "1.4.1": 40, "1.4.2": 20,
        "2.0": 40, "2.1": 20, "2.2": 40, "2.3": 20,
        "3.0": 50, "3.1": 20, "3.1.1": 40, "3.1.1.1": 10, "3.2.1": 10, "3.3": 30, "3.4": 30, "3.5": 30, "3.6": 20,
        "4.0": 40, "6.0": 20, "6.1": 20, "6.2": 20, "6.3": 10, "6.4": 30, "7.0": 25, "7.1": 10, "7.2": 10, "7.3": 5,
        "8.0": 40, "8.2.1": 50, "8.2.2": 30, "9.1": 120
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
    
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart

# =============================================================================
# 3. GERADOR DO RELATÓRIO PDF
# =============================================================================

def gerar_relatorio_pdf(dados, ano, total, faixa):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()

    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    
    # --- TRATAMENTO SEGURO DA IMAGEM DA CAPA ---
    logo_path = "iegm.png"
    if os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=380, height=180)
            logo.hAlign = 'CENTER'
            elements.append(logo)
        except Exception as e:
            elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
    else:
        elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    
    style_titulo_capa = ParagraphStyle(
        'TituloCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica-Bold', 
        fontSize=24, 
        textColor=colors.HexColor("#2c3e50"), 
        alignment=1  # Centralizado
    )

    elements.append(Paragraph("Relatório I-Cidade", style_titulo_capa))
    elements.append(Spacer(1, 15))
    
    style_ano_capa = ParagraphStyle('AnoCapa', parent=styles['Normal'], fontName='Helvetica', fontSize=16, textColor=colors.HexColor("#7f8c8d"), alignment=1)
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())
    
# =============================================================================
# GERADOR DO RELATÓRIO PDF (I-GOV TI)
# =============================================================================
def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=30, 
        leftMargin=30, 
        topMargin=30, 
        bottomMargin=30
    )
    elements = []
    styles = getSampleStyleSheet()

    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    
    # Tratamento seguro da logo na Capa
    logo_path = "iegm.png"
    if os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=380, height=180)
            logo.hAlign = 'CENTER'
            elements.append(logo)
        except Exception:
            elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
    else:
        elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    
    style_titulo_capa = ParagraphStyle(
        'TituloCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica-Bold', 
        fontSize=24, 
        textColor=colors.HexColor("#1b4f72"), 
        alignment=1  # Centralizado
    )

    elements.append(Paragraph("Relatório i-Gov TI", style_titulo_capa))
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
        [Paragraph("6. Série Histórica do i-Gov TI", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
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
    # 1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA DE EXERCÍCIOS)
    # -------------------------------------------------------------------------
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

    all_data = {}
    try:
        all_data = get_all_years_data()
    except Exception:
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

    # -------------------------------------------------------------------------
    # 2. ANÁLISE DE DESEMPENHO POR QUESITO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []
    reincidencias_detectadas = []

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): continue
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")
        pts_maximo = float(PONTUACOES_MAX.get(qid, 0))
        
        if pts_maximo > 0:
            eficiencia = (pts_obtidos / pts_maximo) * 100
            item_data = {"qid": qid, "pts_obtidos": pts_obtidos, "pts_maximo": pts_maximo, "eficiencia": eficiencia, "valor": valor_resposta, "link": link_evidencia}
            if eficiencia >= 70.0: lista_pontos_fortes.append(item_data)
            elif eficiencia < 50.0:
                lista_pontos_fracos.append(item_data)
                if qid in dados_ano_anterior:
                    info_ant = dados_ano_anterior[qid]
                    pts_anterior = float(info_ant.get("pontos", 0))
                    if pts_obtidos == pts_anterior:
                        reincidencias_detectadas.append({"qid": qid, "tipo": "Ponto Fraco", "detalhe": "Eficiência Crítica", "ant": f"{pts_anterior:.1f} pts", "atual": f"{pts_obtidos:.1f} pts"})

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
    # 3. ANÁLISE DE IMPACTO E PENALIDADES
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    PENALIDADES_MAX = {"4.2": -50.0, "5.1.1": -100.0, "5.2": -50.0, "6.0": -50.0, "10": -100.0, "10.0": -100.0, "11.1": -20.0, "11.2": -20.0, "11.2.1": -20.0, "12.1.3": -50.0, "14.0": -50.0}

    lista_penalidades = []
    for qid, pen_max in PENALIDADES_MAX.items():
        if qid in dados:
            info = dados[qid]
            nota_real = float(info.get("pontos", 0))
            nota_risco = nota_real if nota_real <= 0 else 0.0
            eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            lista_penalidades.append({"qid": qid, "nota_real": nota_real, "pen_max": pen_max, "eficiencia": eficiencia_preventiva, "valor": info.get("valor", ""), "link": info.get("link", "")})
            if eficiencia_preventiva < 100.0 and qid in dados_ano_anterior:
                info_ant = dados_ano_anterior[qid]
                nota_real_ant = float(info_ant.get("pontos", 0))
                if nota_real == nota_real_ant:
                    reincidencias_detectadas.append({"qid": qid, "tipo": "Penalidade Aplicada", "detalhe": f"Impacto Recorrente de {nota_real:.1f} pts", "ant": f"{nota_real_ant:.1f} pts", "atual": f"{nota_real:.1f} pts"})

    if lista_penalidades:
        data_penalidades = [["Quesito", "Penalidade Aplicada", "Pior Cenário", "Eficiência Preventiva", "Status de Risco"]]
        for item in sorted(lista_penalidades, key=lambda x: x["eficiencia"]):
            nota_txt = f"{item['nota_real']:.1f} pts"; teto_txt = f"{item['pen_max']:.1f} pts"; ef_txt = f"{item['eficiencia']:.1f}%"
            if item['eficiencia'] == 100.0: status = "<font color='#28a745'><b>Risco Mitigado</b></font>"
            elif item['eficiencia'] <= 0.0: status = "<font color='#dc3545'><b>Impacto Máximo</b></font>"
            else: status = "<font color='#ffc107'><b>Impacto Parcial</b></font>"
            data_penalidades.append([item['qid'], nota_txt, teto_txt, ef_txt, Paragraph(status, styles["Normal"])])
        tabela_pen = Table(data_penalidades, colWidths=[65, 110, 80, 115, 120])
        tabela_pen.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1b4f72")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        elements.append(tabela_pen)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS 
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS </b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    if reincidencias_detectadas:
        data_reinc = [["Quesito", "Origem da Falha", "Impacto Histórico", "Exercício Anterior", "Exercício Atual"]]
        for reinc in reincidencias_detectadas: data_reinc.append([reinc["qid"], reinc["tipo"], Paragraph(f"<b>{reinc['detalhe']}</b>", styles["Normal"]), reinc["ant"], reinc["atual"]])
        tabela_reinc = Table(data_reinc, colWidths=[65, 115, 170, 75, 65])
        tabela_reinc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        elements.append(tabela_reinc)
    else: elements.append(Paragraph("<font color='#28a745'><b>Nenhuma reincidência ativa detectada.</b></font>", styles["Normal"]))
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
    # 6. SÉRIE HISTÓRICA DO I-CIDADE
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 10))

    anos_serie = [2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    for a in anos_serie:
        if a == ano_atual: valores_serie.append(nota_atual)
        elif a in all_data:
            valores_serie.append(float(sum(info_h.get("pontos", 0) for qid_h, info_h in all_data[a].items() if isinstance(info_h, dict) and not qid_h.startswith("COM_"))))
        else: valores_serie.append(0.0)

    # Configuração do Gráfico
    desenho_grafico = Drawing(480, 165)
    bc = VerticalBarChart()
    bc.x = 45; bc.y = 25; bc.height = 110; bc.width = 410
    bc.data = [valores_serie]
    bc.categoryAxis.categoryNames = [str(a) for a in anos_serie]
    bc.categoryAxis.labels.fontSize = 9; bc.categoryAxis.labels.fontName = 'Helvetica-Bold'; bc.categoryAxis.labels.dy = -10
    
    bc.valueAxis.valueMin = 0; bc.valueAxis.valueMax = 1000; bc.valueAxis.valueStep = 200; bc.valueAxis.labels.fontSize = 8
    
    # Rótulos (Pontuação em cima da barra)
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    bc.bars[0].fillColor = colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(String(240, 150, "Série Histórica do I-cidade", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)

    # Fechamento do documento
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()

import json
import logging
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go
from psycopg2.extras import RealDictCursor

# =============================================================================
# 4. SIDEBAR - iGov
# =============================================================================

def zerar_questionario_igov(ano: int):
    """Deleta todas as respostas do ano selecionado com modulo = 'igov'."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM respostas WHERE ano = %s AND modulo = 'igov'",
                    (int(ano),)
                )
            conn.commit()
        st.cache_data.clear()  # Limpa o cache após deletar
    except Exception as e:
        st.error(f"Erro ao zerar questionário iGov: {e}")


@st.dialog("⚠️ Zerar Respostas do iGov")
def confirmar_zerar_dialog(ano):
    st.warning(f"Tem certeza que deseja apagar TODAS as respostas do iGov para o ano {ano}?")
    st.write("Esta ação é irreversível e excluirá os dados salvos no banco Neon.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔴 Sim, Zerar Tudo", type="primary", use_container_width=True):
            try:
                with get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("DELETE FROM respostas_igov WHERE ano = %s", (int(ano),))
                    conn.commit()
                
                st.cache_data.clear()
                st.session_state[f"respostas_igov_{ano}"] = {}
                st.toast("Respostas zeradas com sucesso!", icon="🗑️")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao zerar banco: {e}")

    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def render_sidebar():
    st.sidebar.title("🛠️ Painel de Controle")
    anos = [2024, 2025, 2026, 2027, 2028, 2029, 2030]
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_global")

    res_data = load_respostas(ano_sel)
    total_pts = sum(item.get("pontos", 0) for item in res_data.values())

    if total_pts <= 500:    faixa, cor = "C",  "red"
    elif total_pts <= 599: faixa, cor = "C+", "orange"
    elif total_pts <= 749: faixa, cor = "B",  "#d4d400"
    elif total_pts <= 899: faixa, cor = "B+", "lightgreen"
    else:                  faixa, cor = "A",  "green"

    st.sidebar.metric("Pontuação Total", f"{total_pts} pts")
    st.sidebar.markdown(
        f"**Faixa:** <span style='color:{cor}; font-size:20px; font-weight:bold;'>{faixa}</span>",
        unsafe_allow_html=True
    )

    st.sidebar.divider()
    
    col1, col2 = st.sidebar.columns(2)
    
    # Botão de Download direto (gera o PDF ao clicar, sem recarregar a tela antes)
    with col1:
        st.download_button(
            label="📄 Baixar PDF",
            data=gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa),
            file_name=f"Relatorio_{ano_sel}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    # Botão para abrir o Modal de confirmação
    with col2:
        if st.button("🔄 Zerar", help="Limpar todas as respostas do ano selecionado", use_container_width=True):
            confirmar_zerar_dialog(ano_sel)

    return total_pts, res_data, ano_sel

# =============================================================================
# 5. GRÁFICOS E HISTÓRICO - iGov
# =============================================================================

def get_all_years_data_igov() -> dict:
    """Busca o histórico de dados de todos os anos para a métrica iGov."""
    all_data = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT ano FROM respostas WHERE modulo = 'igov' ORDER BY ano"
                )
                anos = [row[0] for row in cursor.fetchall()]
                for ano in anos:
                    all_data[ano] = load_respostas(ano)
    except Exception as e:
        logging.error(f"Erro ao buscar histórico de anos iGov: {e}")
    return all_data


def get_faixa_igov(total):
    if total <= 30:  return "Crítico"
    if total <= 55:  return "Básico"
    if total <= 75:  return "Intermediário"
    if total <= 90:  return "Aprimorado"
    return "Excelência"


def grafico_pontos_por_ano(all_data):
    """Gráfico de barras vertical com pontos totais por ano."""
    anos = sorted(all_data.keys())
    totais = []
    cores = []
    
    for ano in anos:
        res = all_data[ano]
        total = sum(v.get("pontos", 0.0) for k, v in res.items() if not k.startswith("COM_"))
        totais.append(total)
        
        if total <= 30:    cores.append("#ef4444")
        elif total <= 55:  cores.append("#f97316")
        elif total <= 75:  cores.append("#eab308")
        elif total <= 90:  cores.append("#22c55e")
        else:              cores.append("#16a34a")
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[str(a) for a in anos],
        y=totais,
        marker_color=cores,
        text=[f"{t:.1f} pts" for t in totais],
        textposition="outside",
        hovertemplate="<b>Ano: %{x}</b><br>iGov Total: %{y:.1f} pts<extra></extra>",
    ))
    
    fig.update_layout(
        title="Índice Histórico iGov por Exercício",
        xaxis_title="Ano",
        yaxis_title="Pontuação iGov",
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        height=400,
    )
    
    return fig


def render_graficos(res_data_atual, ano_sel):
    st.header("📊 Painel de Análise do iGov")
    
    all_data = get_all_years_data_igov()
    
    if not all_data:
        st.info("Nenhum dado do iGov registrado ainda. Preencha os itens para visualizar os gráficos.")
        return

    st.plotly_chart(grafico_pontos_por_ano(all_data), use_container_width=True)

import re  # Necessário para as expressões regulares dos links

# =============================================================================
# 6. FORMULÁRIO PRINCIPAL - iGov
# =============================================================================

def mostrar_formulario_igov():
    dados_sidebar = render_sidebar()
    
    if dados_sidebar and len(dados_sidebar) == 3:
        total_pts, res_data, ano_sel = dados_sidebar
    else:
        total_pts, res_data, ano_sel = 0.0, {}, 2026

    st.title(f"🏛️ Avaliação de Governança (iGov) - {ano_sel}")

    aba_quest, aba_graf = st.tabs(["📋 Questionário iGov", "📊 Análise & Gráficos"])

    # -------------------------------------------------------------------------
    # ABA 1: QUESTIONÁRIO (Quesitos entram AQUI)
    # -------------------------------------------------------------------------
    with aba_quest:
        st.info("Responda às questões da governança para atualizar a pontuação.")

    # =============================================================================
    # QUESITO 1.0 • SETOR DE TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    with st.container(key=f"container_bloco_igov_1_0_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.0 - Setor de Tecnologia da Informação e Comunicação", expanded=True):
            st.subheader("1.0 • Setor de TIC")
            st.write(
                "**A Prefeitura possui uma área ou setor responsável por cuidar da "
                "Tecnologia da Informação e Comunicação (TIC)?**"
            )
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.0' para registrar.*")

            opcoes_10 = {
                "Selecione...": 0.0,
                "Sim (30 pts)": 30.0,
                "Não (00 pts)": 0.0
            }

            # Estado inicial / persistente
            d10 = res_data.get("1.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
            v_salvo_10 = d10.get("valor", "Selecione...")

            # Chaves fixas por componente e ano
            chave_radio_10 = f"r_10_{ano_sel}"
            chave_link_10 = f"l_10_txt_{ano_sel}"
            chave_coment_10 = f"coment_1.0_{ano_sel}" # Chave padrão usada pela função bloco_comentarios

            c10_1, c10_2 = st.columns([1, 1])
            with c10_1:
                lista_opcoes_10 = list(opcoes_10.keys())
                idx_10 = lista_opcoes_10.index(v_salvo_10) if v_salvo_10 in lista_opcoes_10 else 0

                val_radio_10 = st.radio(
                    "Selecione a situação do setor de TIC:",
                    options=lista_opcoes_10,
                    index=idx_10,
                    key=chave_radio_10,
                    label_visibility="collapsed"
                )

            with c10_2:
                link_10 = st.text_area(
                    "Link de Evidência / Lei de Criacao / Organograma (1.0):",
                    value=d10.get("link", ""),
                    key=chave_link_10,
                    placeholder="Insira o link da lei de estrutura administrativa...",
                    height=100
                )
                placeholder_links_10 = st.empty()
                regex_url = r'https?://[^\s<>"]+'
                links_10_visuais = re.findall(regex_url, link_10 or "")
                if links_10_visuais:
                    placeholder_links_10.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_10_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.0", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.0", key=f"btn_salvar_1_0_{ano_sel}", type="primary"):
                pts_10 = opcoes_10.get(val_radio_10, 0.0)
                
                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_10, d10.get("comentario", ""))
                
                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp("1.0", val_radio_10, pts_10, link_10, comentario_para_salvar)
                
                # 3. Atualiza o dicionário local res_data
                res_data["1.0"] = {
                    "valor": val_radio_10, 
                    "pontos": pts_10, 
                    "link": link_10, 
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_url, link_10 or "")
                links_antigos = re.findall(regex_url, d10.get("link", "") or "")

                if link_10 != d10.get("link", "") and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                # Limpa o cache para garantir atualização no banco
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.0 salvos com sucesso!", icon="✅")
                
                # 5. FORÇA O RECARREGAMENTO DA TELA (Resolve o duplo clique e atualiza painéis)
                st.rerun()

            # Exibição da pontuação dentro do expander
            pts_atuais_10 = d10.get("pontos", 0.0)
            cor_txt_10 = "#28a745" if pts_atuais_10 == 30.0 else ("#dc3545" if v_salvo_10 != "Selecione..." else "#6c757d")
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

    # Garante a exposição da variável r10 para dependências condicionais de outros quesitos
    r10 = v_salvo_10

    # =============================================================================
    # QUESITO 1.1 • RECURSOS HUMANOS EM TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_1_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.1 - Composição de Recursos Humanos do Setor de TIC", expanded=True):
            st.subheader("1.1 • Recursos Humanos em TIC")
            st.write("**Informe a quantidade da equipe que atua no suporte e atendimento de primeiro nível:**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.1' para registrar.*")

            # Recupera e trata o estado inicial do dicionário com segurança
            d11 = res_data.get("1.1") or {"valor": "0", "pontos": 0.0, "link": "", "comentario": ""}
            
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

            # Chaves fixas por componente e ano
            chave_conc_11 = f"q11_num_conc_{ano_sel}"
            chave_comi_11 = f"q11_num_comi_{ano_sel}"
            chave_esta_11 = f"q11_num_esta_{ano_sel}"
            chave_outr_11 = f"q11_num_outr_{ano_sel}"
            chave_link_11 = f"l_11_txt_area_{ano_sel}"
            chave_coment_11 = f"coment_1.1_{ano_sel}"

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown('<label style="font-size: 14px; font-weight: 500;">Concursados:</label>', unsafe_allow_html=True)
                val_conc_11 = st.number_input("", min_value=0, step=1, value=v_conc_i, key=chave_conc_11, label_visibility="collapsed")
            with col2:
                st.markdown('<label style="font-size: 14px; font-weight: 500;">Comissionados:</label>', unsafe_allow_html=True)
                val_comi_11 = st.number_input("", min_value=0, step=1, value=v_comi_i, key=chave_comi_11, label_visibility="collapsed")
            with col3:
                st.markdown('<label style="font-size: 14px; font-weight: 500;">Estagiários:</label>', unsafe_allow_html=True)
                val_esta_11 = st.number_input("", min_value=0, step=1, value=v_esta_i, key=chave_esta_11, label_visibility="collapsed")
            with col4:
                st.markdown('<label style="font-size: 14px; font-weight: 500;">Outros:</label>', unsafe_allow_html=True)
                val_outr_11 = st.number_input("", min_value=0, step=1, value=v_outr_i, key=chave_outr_11, label_visibility="collapsed")

            st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)

            link_11 = st.text_area(
                "Link/Evidência da composição da equipe (1.1):", 
                value=evidencia_11_salva, 
                key=chave_link_11, 
                placeholder="Cole aqui o link do decreto de lotação de pessoal, relatório do setor de RH ou folha simplificada da TI...",
                height=90
            )

            placeholder_links_11 = st.empty()
            links_11_visuais = re.findall(regex_pure_url, link_11 or "")
            if links_11_visuais:
                placeholder_links_11.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_11_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.1", key=f"btn_salvar_1_1_{ano_sel}", type="primary"):
                total_p = val_conc_11 + val_comi_11 + val_esta_11
                pts_calculados_11 = 30.0 if total_p > 0 else 0.0
                composite_string = f"C:{val_conc_11},Co:{val_comi_11},E:{val_esta_11},O:{val_outr_11}|LINK:{link_11.strip()}"

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_11, d11.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="1.1",
                    valor=str(total_p),
                    pontos=pts_calculados_11,
                    link=composite_string,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["1.1"] = {
                    "valor": str(total_p),
                    "pontos": pts_calculados_11,
                    "link": composite_string,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_11 or "")
                links_antigos = re.findall(regex_pure_url, evidencia_11_salva or "")

                if link_11 != evidencia_11_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            total_pessoal = int(d11.get("valor", "0"))
            pts_atuais_11 = d11.get("pontos", 0.0)
            cor_txt_11 = "#28a745" if pts_atuais_11 == 30.0 else "#6c757d"

            st.info(f"👥 Total de Pessoal Efetivo Computado (C+Co+E): {total_pessoal} funcionário(s)")
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
    # QUESITO 1.2 • ATRIBUIÇÕES DO SETOR DE TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_1_2_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.2 - Definição de Atribuições Formais da Equipe", expanded=True):
            st.subheader("1.2 • Atribuições Formais")
            st.write("**A prefeitura municipal definiu formalmente as atribuições do pessoal do setor de Tecnologia da Informação e Comunicação (TIC)?**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.2' para registrar.*")

            opcoes12 = ["Selecione...", "Sim – 30", "Não – 00"]

            # Recupera e trata o estado inicial do dicionário com segurança
            d12 = res_data.get("1.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
            v_salvo_12 = d12.get("valor", "Selecione...")
            l_salvo_12 = d12.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_12 = f"r_12_{ano_sel}"
            chave_link_12 = f"l_12_txt_{ano_sel}"
            chave_coment_12 = f"coment_1.2_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx12 = opcoes12.index(v_salvo_12) if v_salvo_12 in opcoes12 else 0
                val_radio_12 = st.radio(
                    "Selecione 1.2:",
                    options=opcoes12,
                    index=idx12,
                    key=chave_radio_12,
                    label_visibility="collapsed"
                )

            with col2:
                link_12 = st.text_area(
                    "Link/Evidência (1.2):",
                    value=l_salvo_12,
                    key=chave_link_12,
                    placeholder="Insira o link do manual de cargos, decreto de atribuições de secretarias ou manual interno de procedimentos...",
                    height=100
                )
                placeholder_links_12 = st.empty()
                links_12_visuais = re.findall(regex_pure_url, link_12 or "")
                if links_12_visuais:
                    placeholder_links_12.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_12_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.2", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.2", key=f"btn_salvar_1_2_{ano_sel}", type="primary"):
                pts_calculados_12 = 30.0 if "Sim" in val_radio_12 else 0.0

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_12, d12.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="1.2",
                    valor=val_radio_12,
                    pontos=pts_calculados_12,
                    link=link_12.strip(),
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["1.2"] = {
                    "valor": val_radio_12,
                    "pontos": pts_calculados_12,
                    "link": link_12.strip(),
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_12 or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_12 or "")

                if link_12 != l_salvo_12 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.2 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_12 = d12.get("pontos", 0.0)
            cor_txt_12 = "#28a745" if pts_atuais_12 == 30.0 else "#6c757d"

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
    # QUESITO 1.3 • CAPACITAÇÃO EM TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_1_3_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.3 - Capacitação e Treinamento do Pessoal de TIC", expanded=True):
            st.subheader("1.3 • Capacitação do Setor")
            st.write("**A prefeitura disponibilizou capacitação para o pessoal da área de Tecnologia da Informação e Comunicação (TIC)?**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.3' para registrar.*")

            opcoes13 = ["Selecione...", "Sim – 30", "Não – 00"]

            # Recupera e trata o estado inicial do dicionário com segurança
            d13 = res_data.get("1.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
            v_salvo_13 = d13.get("valor", "Selecione...")
            l_salvo_13 = d13.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_13 = f"r_13_{ano_sel}"
            chave_link_13 = f"l_13_txt_{ano_sel}"
            chave_coment_13 = f"coment_1.3_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx13 = opcoes13.index(v_salvo_13) if v_salvo_13 in opcoes13 else 0
                val_radio_13 = st.radio(
                    "Selecione 1.3:",
                    options=opcoes13,
                    index=idx13,
                    key=chave_radio_13,
                    label_visibility="collapsed"
                )

            with col2:
                link_13 = st.text_area(
                    "Link/Evidência (1.3):",
                    value=l_salvo_13,
                    key=chave_link_13,
                    placeholder="Insira o link de certificados emitidos, notas de empenho de cursos contratados ou plano anual de capacitação...",
                    height=100
                )
                placeholder_links_13 = st.empty()
                links_13_visuais = re.findall(regex_pure_url, link_13 or "")
                if links_13_visuais:
                    placeholder_links_13.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_13_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.3", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.3", key=f"btn_salvar_1_3_{ano_sel}", type="primary"):
                pts_calculados_13 = 30.0 if "Sim" in val_radio_13 else 0.0

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_13, d13.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="1.3",
                    valor=val_radio_13,
                    pontos=pts_calculados_13,
                    link=link_13.strip(),
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["1.3"] = {
                    "valor": val_radio_13,
                    "pontos": pts_calculados_13,
                    "link": link_13.strip(),
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_13 or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_13 or "")

                if link_13 != l_salvo_13 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_3_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.3 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_13 = d13.get("pontos", 0.0)
            cor_txt_13 = "#28a745" if pts_atuais_13 == 30.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_13}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 1.3: +{pts_atuais_13:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 1.3 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_1_3_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("1.3", st.session_state.get(f"links_pendentes_1_3_{ano_sel}", []))
        st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = False

# =============================================================================
    # QUESITO 1.3.1 • ÁREAS DE CAPACITAÇÃO EM TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_1_3_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.3.1 - Detalhamento das Áreas Temáticas de Capacitação", expanded=True):
            st.subheader("1.3.1 • Áreas Temáticas de Treinamento")
            st.write("**Informe em quais áreas houve capacitação para a equipe do setor de TIC e anexe a comprovação:**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.3.1' para registrar.*")

            # Recupera e trata o estado inicial do dicionário com segurança
            d131 = res_data.get("1.3.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
            
            raw_v131 = d131.get("valor", "[]")
            if not isinstance(raw_v131, str) or not raw_v131.startswith("["):
                raw_v131 = "[]"
            try:
                lista_salva_131 = eval(raw_v131)
            except Exception:
                lista_salva_131 = []

            l_salvo_131 = d131.get("link", "")
            areas = ["Infraestrutura e Redes", "Desenvolvimento e Software", "Análise de Dados", "Gestão e Segurança", "Outros"]

            # Chaves fixas por componente e ano
            chave_link_131 = f"l_131_txt_area_{ano_sel}"
            chave_coment_131 = f"coment_1.3.1_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("**Assinale as verticais de treinamento aplicadas:**")
                col_sub1, col_sub2 = st.columns([1, 1])
                
                # Leitura direta dos estados dos checkboxes na renderização
                chks_estados_131 = {}
                for idx, area in enumerate(areas):
                    area_key = area.replace(" ", "_").lower()
                    target_col = col_sub1 if idx % 2 == 0 else col_sub2
                    chk_key = f"chk_131_{area_key}_{ano_sel}"
                    
                    with target_col:
                        chks_estados_131[area] = st.checkbox(
                            area,
                            value=(area in lista_salva_131),
                            key=chk_key
                        )

            with col2:
                link_131 = st.text_area(
                    "Link/Evidência das áreas de capacitação (1.3.1):",
                    value=l_salvo_131,
                    key=chave_link_131,
                    placeholder="Insira o link das ementas dos cursos, certificados de conclusão anexados na transparência ou portarias de fomento ao treino...",
                    height=110
                )
                
                placeholder_links_131 = st.empty()
                links_131_visuais = re.findall(regex_pure_url, link_131 or "")
                if links_131_visuais:
                    placeholder_links_131.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_131_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.3.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.3.1", key=f"btn_salvar_1_3_1_{ano_sel}", type="primary"):
                # Filtra áreas selecionadas
                selecionadas = [area for area, selecionado in chks_estados_131.items() if selecionado]
                
                # Regra de negócio: Mínimo 3 áreas (desconsiderando 'Outros') garante +30 pontos
                contagem = len([a for a in selecionadas if a != "Outros"])
                pts_calculados_131 = 30.0 if contagem >= 3 else (15.0 if contagem == 2 else (5.0 if contagem == 1 else 0.0))
                val_str = str(selecionadas)

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_131, d131.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="1.3.1",
                    valor=val_str,
                    pontos=pts_calculados_131,
                    link=link_131.strip(),
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["1.3.1"] = {
                    "valor": val_str,
                    "pontos": pts_calculados_131,
                    "link": link_131.strip(),
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_131 or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_131 or "")

                if link_131 != l_salvo_131 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_3_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.3.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_131 = d131.get("pontos", 0.0)
            cor_txt_131 = "#28a745" if pts_atuais_131 == 30.0 else ("#ffc107" if pts_atuais_131 > 0.0 else "#6c757d")

            st.markdown(
                f"<span style='color:{cor_txt_131}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 1.3.1: +{pts_atuais_131:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 1.3.1 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_1_3_1_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("1.3.1", st.session_state.get(f"links_pendentes_1_3_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = False

# =============================================================================
    # QUESITO 1.4 • PARTICIPAÇÃO EM LICITAÇÕES DE TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_1_4_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.4 - Participação Institucional em Compras de TIC", expanded=True):
            st.subheader("1.4 • Participação em Licitações")
            st.write("**Nas licitações e contratos que tenham como soluções o uso de Tecnologia da Informação e Comunicação, houve participação formalizada do pessoal de TIC? Considerar somente compras com verba municipal**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.4' para registrar.*")

            opcoes14 = ["Selecione...", "Sim", "Não"]

            # Recupera e trata o estado inicial do dicionário com segurança
            d14 = res_data.get("1.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
            v_salvo_14 = d14.get("valor", "Selecione...")
            l_salvo_14 = d14.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_14 = f"r_14_{ano_sel}"
            chave_link_14 = f"l_14_txt_{ano_sel}"
            chave_coment_14 = f"coment_1.4_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx14 = opcoes14.index(v_salvo_14) if v_salvo_14 in opcoes14 else 0
                val_radio_14 = st.radio(
                    "Selecione 1.4:",
                    options=opcoes14,
                    index=idx14,
                    key=chave_radio_14,
                    label_visibility="collapsed"
                )

            with col2:
                link_14 = st.text_area(
                    "Link/Evidência (1.4):",
                    value=l_salvo_14,
                    key=chave_link_14,
                    placeholder="Insira o link de termos de referência assinados pela TI, pareceres técnicos em editais ou portarias de equipe de apoio...",
                    height=100
                )
                placeholder_links_14 = st.empty()
                links_14_visuais = re.findall(regex_pure_url, link_14 or "")
                if links_14_visuais:
                    placeholder_links_14.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_14_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.4", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.4", key=f"btn_salvar_1_4_{ano_sel}", type="primary"):
                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_14, d14.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="1.4",
                    valor=val_radio_14,
                    pontos=0.0,  # Mantido 0.0 por ter pontuação computada no sub-quesito 1.4.1
                    link=link_14.strip(),
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["1.4"] = {
                    "valor": val_radio_14,
                    "pontos": 0.0,
                    "link": link_14.strip(),
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_14 or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_14 or "")

                if link_14 != l_salvo_14 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_4_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.4 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            st.markdown(
                "<span style='color:#6c757d; font-weight:bold;'>"
                "📊 Impacto de Pontuação no Quesito 1.4: 0.0 pontos (A pontuação é computada no sub-quesito 1.4.1)</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 1.4 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_1_4_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("1.4", st.session_state.get(f"links_pendentes_1_4_{ano_sel}", []))
        st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = False
