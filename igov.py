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

    # =============================================================================
    # QUESITO 1.4.1 • ETAPAS DE PARTICIPAÇÃO EM LICITAÇÕES (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_1_4_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.4.1 - Detalhamento das Etapas de Atuação Institucional", expanded=True):
            st.subheader("1.4.1 • Etapas de Atuação")
            st.write("**Selecione as etapas em que houve participação formalizada da equipe de TIC e anexe a comprovação:**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.4.1' para registrar.*")

            # Recupera e trata o estado inicial do dicionário com segurança
            d141 = res_data.get("1.4.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
            
            raw_v141 = d141.get("valor", "[]")
            if not isinstance(raw_v141, str) or not raw_v141.startswith("["):
                raw_v141 = "[]"
            try:
                lista_salva_141 = eval(raw_v141)
            except Exception:
                lista_salva_141 = []

            l_salvo_141 = d141.get("link", "")
            etapas = {
                "Elaboração do edital / Especificação técnica – 15": 15.0,
                "Comissão de Licitação / Equipe de Apoio – 10": 10.0,
                "Recebimento / Gestão de Contrato – 15": 15.0
            }

            # Chaves fixas por componente e ano
            chave_link_141 = f"l_141_txt_area_{ano_sel}"
            chave_coment_141 = f"coment_1.4.1_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("**Selecione as etapas de atuação comprovadas:**")
                
                # Leitura direta dos estados dos checkboxes na renderização
                chks_estados_141 = {}
                for etapa, pts in etapas.items():
                    slug_etapa = etapa.split(" – ")[0].replace(" / ", "_").replace(" ", "_").lower()
                    chk_key = f"chk_141_{slug_etapa}_{ano_sel}"
                    
                    chks_estados_141[etapa] = st.checkbox(
                        etapa,
                        value=(etapa in lista_salva_141),
                        key=chk_key
                    )

            with col2:
                link_141 = st.text_area(
                    "Link/Evidência das etapas de participação (1.4.1):",
                    value=l_salvo_141,
                    key=chave_link_141,
                    placeholder="Insira o link das publicações no Diário Oficial, atas de sessões com assinatura da TI ou relatórios de homologação técnica...",
                    height=110
                )
                
                placeholder_links_141 = st.empty()
                links_141_visuais = re.findall(regex_pure_url, link_141 or "")
                if links_141_visuais:
                    placeholder_links_141.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_141_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.4.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.4.1", key=f"btn_salvar_1_4_1_{ano_sel}", type="primary"):
                # Filtra etapas selecionadas e calcula a pontuação incremental
                selecionadas = [etapa for etapa, selecionado in chks_estados_141.items() if selecionado]
                pts_calculados_141 = sum(etapas[etapa] for etapa in selecionadas)
                val_str = str(selecionadas)

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_141, d141.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="1.4.1",
                    valor=val_str,
                    pontos=pts_calculados_141,
                    link=link_141.strip(),
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["1.4.1"] = {
                    "valor": val_str,
                    "pontos": pts_calculados_141,
                    "link": link_141.strip(),
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_141 or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_141 or "")

                if link_141 != l_salvo_141 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_4_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_4_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.4.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_141 = d141.get("pontos", 0.0)
            cor_txt_141 = "#28a745" if pts_atuais_141 == 40.0 else ("#ffc107" if pts_atuais_141 > 0.0 else "#6c757d")

            st.markdown(
                f"<span style='color:{cor_txt_141}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 1.4.1: +{pts_atuais_141:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 1.4.1 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_1_4_1_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("1.4.1", st.session_state.get(f"links_pendentes_1_4_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_1_4_1_{ano_sel}"] = False

# =============================================================================
    # QUESITO 1.4.2 • ESTUDOS PRELIMINARES DE SOFTWARE (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_1_4_2_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.4.2 - Análise de Viabilidade Técnica e Contratações de Software", expanded=True):
            st.subheader("1.4.2 • Estudos de Viabilidade de Software")
            st.write("**Sobre programas de computador (softwares) adquiridos ou licenciados nos últimos 5 anos, foi realizada análise ou estudo antes de sua contratação com a participação do pessoal de Tecnologia da Informação e Comunicação (TIC)?**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.4.2' para registrar.*")

            opc142 = {
                "Selecione...": 0.0,
                "Sim, para todos os softwares – 20": 20.0,
                "Sim, para a maior parte dos softwares – 15": 15.0,
                "Sim, para a menor parte dos softwares – 08": 8.0,
                "Não foi realizado – 00": 0.0,
                "Não foi adquirido nenhum software nos últimos 5 anos – 20": 20.0
            }
            lista142 = list(opc142.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d142 = res_data.get("1.4.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
            v_salvo_142 = d142.get("valor", "Selecione...")
            l_salvo_142 = d142.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_142 = f"r_142_{ano_sel}"
            chave_link_142 = f"l_142_txt_{ano_sel}"
            chave_coment_142 = f"coment_1.4.2_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx142 = lista142.index(v_salvo_142) if v_salvo_142 in lista142 else 0
                val_radio_142 = st.radio(
                    "Selecione 1.4.2:",
                    options=lista142,
                    index=idx142,
                    key=chave_radio_142,
                    label_visibility="collapsed"
                )

            with col2:
                link_142 = st.text_area(
                    "Link/Evidência (1.4.2):",
                    value=l_salvo_142,
                    key=chave_link_142,
                    placeholder="Insira o link dos Estudos Técnicos Preliminares (ETP), relatórios de análise de aderência ou certidões de inexistência de compras de software...",
                    height=120
                )
                placeholder_links_142 = st.empty()
                links_142_visuais = re.findall(regex_pure_url, link_142 or "")
                if links_142_visuais:
                    placeholder_links_142.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_142_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.4.2", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.4.2", key=f"btn_salvar_1_4_2_{ano_sel}", type="primary"):
                pts_calculados_142 = float(opc142.get(val_radio_142, 0.0))

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_142, d142.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="1.4.2",
                    valor=val_radio_142,
                    pontos=pts_calculados_142,
                    link=link_142.strip(),
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["1.4.2"] = {
                    "valor": val_radio_142,
                    "pontos": pts_calculados_142,
                    "link": link_142.strip(),
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_142 or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_142 or "")

                if link_142 != l_salvo_142 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_4_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 1.4.2 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_142 = d142.get("pontos", 0.0)
            cor_txt_142 = "#28a745" if pts_atuais_142 > 0.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_142}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 1.4.2: +{pts_atuais_142:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 1.4.2 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_1_4_2_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("1.4.2", st.session_state.get(f"links_pendentes_1_4_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = False

# =============================================================================
    # QUESITO 2.0 • PLANO DIRETOR DE TIC (PDTIC) (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_2_0_{ano_sel}", border=True):
        with st.expander("📌 Quesito 2.0 - Plano Diretor de Tecnologia da Informação e Comunicação", expanded=True):
            st.subheader("2.0 • PDTIC")
            st.write("**A prefeitura municipal possui um PDTIC – Plano Diretor de Tecnologia da Informação e Comunicação – vigente que estabeleça diretrizes e metas de atingimento no futuro?**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 2.0' para registrar.*")

            opc20 = {
                "Selecione...": 0.0,
                "SIM, com metas acima de 02 anos – 40": 40.0,
                "SIM, com metas para até 02 anos – 30": 30.0,
                "NÃO POSSUI PDTIC – 00": 0.0
            }
            lista20 = list(opc20.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d20 = res_data.get("2.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
            v_salvo_20 = d20.get("valor", "Selecione...")
            l_salvo_20 = d20.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_20 = f"r_20_{ano_sel}"
            chave_link_20 = f"l_20_txt_{ano_sel}"
            chave_coment_20 = f"coment_2.0_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx20 = lista20.index(v_salvo_20) if v_salvo_20 in lista20 else 0
                val_radio_20 = st.radio(
                    "Selecione 2.0:",
                    options=lista20,
                    index=idx20,
                    key=chave_radio_20,
                    label_visibility="collapsed"
                )

            with col2:
                link_20 = st.text_area(
                    "Link/Evidência (2.0):",
                    value=l_salvo_20,
                    key=chave_link_20,
                    placeholder="Insira o link da publicação do PDTIC no Diário Oficial, decreto de aprovação do plano ou página institucional de governança...",
                    height=100
                )
                placeholder_links_20 = st.empty()
                links_20_visuais = re.findall(regex_pure_url, link_20 or "")
                if links_20_visuais:
                    placeholder_links_20.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_20_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("2.0", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 2.0", key=f"btn_salvar_2_0_{ano_sel}", type="primary"):
                pts_calculados_20 = float(opc20.get(val_radio_20, 0.0))

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_20, d20.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="2.0",
                    valor=val_radio_20,
                    pontos=pts_calculados_20,
                    link=link_20.strip(),
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["2.0"] = {
                    "valor": val_radio_20,
                    "pontos": pts_calculados_20,
                    "link": link_20.strip(),
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, link_20 or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_20 or "")

                if link_20 != l_salvo_20 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 2.0 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_20 = d20.get("pontos", 0.0)
            cor_txt_20 = "#28a745" if pts_atuais_20 > 0.0 else "#6c757d"

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
    # QUESITO 2.1 • PÁGINA ELETRÔNICA DO PDTIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_2_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 2.1 - Endereço Eletrônico de Publicação do PDTIC", expanded=True):
            st.subheader("2.1 • Página Eletrônica do PDTIC")
            st.write("**Informe a página eletrônica (link na internet) do PDTIC:**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 2.1' para registrar.*")

            # Recupera e trata o estado inicial do dicionário com segurança
            d21 = res_data.get("2.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
            valor_salvo_21 = d21.get("valor", "")
            l_salvo_21 = d21.get("link", "")

            # Chaves fixas por componente e ano
            chave_link_21 = f"l_21_txt_input_{ano_sel}"
            chave_coment_21 = f"coment_2.1_{ano_sel}"

            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown("<br>", unsafe_allow_html=True)
                st.info("Insira a URL direta do plano publicado ou digite 'XYZ' caso esteja indisponível.")

            with col2:
                link_21 = st.text_input(
                    "Página eletrônica (link URL):",
                    value=valor_salvo_21,
                    key=chave_link_21,
                    placeholder="https://www.municipio.sp.gov.br/transparencia/pdtic.pdf"
                )

                placeholder_links_21 = st.empty()
                links_21_visuais = re.findall(regex_pure_url, link_21 or "")
                if links_21_visuais:
                    placeholder_links_21.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_21_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("2.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 2.1", key=f"btn_salvar_2_1_{ano_sel}", type="primary"):
                lnk_val = link_21.strip()

                # Regra de pontuação: Se preenchido e diferente de vazio ou XYZ, pontua 20.0
                pts_calculados_21 = 20.0 if lnk_val != "" and lnk_val.upper() != "XYZ" else 0.0

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_21, d21.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="2.1",
                    valor=lnk_val,
                    pontos=pts_calculados_21,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["2.1"] = {
                    "valor": lnk_val,
                    "pontos": pts_calculados_21,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, l_salvo_21 or "")

                if lnk_val != l_salvo_21 and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_2_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 2.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_21 = d21.get("pontos", 0.0)
            cor_txt_21 = "#28a745" if pts_atuais_21 > 0.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_21}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 2.1: +{pts_atuais_21:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 2.1 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_2_1_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("2.1", st.session_state.get(f"links_pendentes_2_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 2.2 • ESCOPO DO PLANO DE TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_2_2_{ano_sel}", border=True):
        with st.expander("📌 Quesito 2.2 - Elementos Contemplados no Plano de TIC", expanded=True):
            st.subheader("2.2 • Escopo do Plano de TIC")
            st.write("**O plano de TIC vigente contempla:**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 2.2' para registrar. Pontuação incremental acumulativa até 40 pontos.*")

            # Recupera e trata o estado inicial do dicionário com segurança
            d22 = res_data.get("2.2") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

            raw_v22 = d22.get("valor", "[]")
            if not isinstance(raw_v22, str) or not raw_v22.startswith("["):
                raw_v22 = "[]"
            try:
                lista_salva_22 = eval(raw_v22)
            except Exception:
                lista_salva_22 = []

            evidencia_22_salva = d22.get("link", "")
            contempla = {
                "Alocação de recursos orçamentários – 10": 10.0,
                "Alocação de recursos humanos – 10": 10.0,
                "Alocação de recursos materiais – 10": 10.0,
                "Estratégia de execução indireta (terceirização) – 10": 10.0
            }

            # Chaves fixas por componente e ano
            chave_link_22 = f"l_22_txt_area_{ano_sel}"
            chave_coment_22 = f"coment_2.2_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("**Selecione as metas/estratégias contempladas:**")
                # Renderização das caixas de seleção
                for item, pts in contempla.items():
                    slug_item = item.split(" – ")[0].replace(" (", "_").replace(")", "").replace(" ", "_").lower()
                    st.checkbox(
                        item,
                        value=item in lista_salva_22,
                        key=f"chk_22_{slug_item}_{ano_sel}"
                    )

            with col2:
                link_22 = st.text_area(
                    "Link/Evidência do escopo do plano (2.2):",
                    value=evidencia_22_salva,
                    key=chave_link_22,
                    placeholder="Insira as páginas ou links diretos das seções do PDTIC que comprovam as alocações de recursos e terceirizações...",
                    height=130
                )

                placeholder_links_22 = st.empty()
                links_22_visuais = re.findall(regex_pure_url, link_22 or "")
                if links_22_visuais:
                    placeholder_links_22.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_22_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("2.2", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 2.2", key=f"btn_salvar_2_2_{ano_sel}", type="primary"):
                sel22 = []
                pts22 = 0.0

                for item, pts in contempla.items():
                    slug_item = item.split(" – ")[0].replace(" (", "_").replace(")", "").replace(" ", "_").lower()
                    if st.session_state.get(f"chk_22_{slug_item}_{ano_sel}", False):
                        sel22.append(item)
                        pts22 += pts

                val_str = str(sel22)
                lnk_val = link_22.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_22, d22.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="2.2",
                    valor=val_str,
                    pontos=pts22,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["2.2"] = {
                    "valor": val_str,
                    "pontos": pts22,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_22_salva or "")

                if lnk_val != evidencia_22_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_2_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_2_2_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 2.2 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_22 = d22.get("pontos", 0.0)
            cor_txt_22 = "#28a745" if pts_atuais_22 == 40.0 else ("#ffc107" if pts_atuais_22 > 0.0 else "#6c757d")

            st.markdown(
                f"<span style='color:{cor_txt_22}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 2.2: +{pts_atuais_22:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 2.2 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_2_2_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("2.2", st.session_state.get(f"links_pendentes_2_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_2_2_{ano_sel}"] = False

# =============================================================================
    # QUESITO 2.3 • ATUALIZAÇÃO DO PDTIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_2_3_{ano_sel}", border=True):
        with st.expander("📌 Quesito 2.3 - Cronologia de Atualização / Publicação do PDTIC", expanded=True):
            st.subheader("2.3 • Data de Atualização do PDTIC")
            st.write("**Qual a data da última atualização do PDTIC? (Se não foi atualizado, informar a data da publicação)**")
            st.caption("ℹ *Preencha a data ou marque a indisponibilidade, insira a evidência e clique em 'Salvar Quesito 2.3'.*")

            st.info("""
            **Regra de Pontuação:**
            * ✅ **Data de até 5 anos atrás:** 20 pontos.
            * ⚠️ **Data entre 5 e 10 anos atrás:** 10 pontos.
            * 🚫 **Data com mais de 10 anos ou Inexistente:** 00 pontos.
            """)

            # Recupera e trata o estado inicial do dicionário com segurança
            d23 = res_data.get("2.3") or {"valor": None, "pontos": 0.0, "link": "", "comentario": ""}

            valor_salvo_23 = d23.get("valor", "")
            evidencia_23_salva = d23.get("link", "")

            # Trata a data inicial a ser exibida no picker
            try:
                if valor_salvo_23 and valor_salvo_23 != "XYZ":
                    dt_i = datetime.strptime(valor_salvo_23, '%Y-%m-%d').date()
                else:
                    dt_i = date.today()
            except Exception:
                dt_i = date.today()

            # Chaves fixas por componente e ano
            chave_switch_23 = f"chk_23_nao_possui_{ano_sel}"
            chave_date_23 = f"dt23_picker_{ano_sel}"
            chave_link_23 = f"l_23_txt_area_{ano_sel}"
            chave_coment_23 = f"coment_2.3_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                documento_indisponivel = st.checkbox(
                    "Documento indisponível / Não possui PDTIC",
                    value=(valor_salvo_23 == "XYZ" or evidencia_23_salva == "XYZ"),
                    key=chave_switch_23
                )

                dt_selecionada = st.date_input(
                    "Selecione a data de vigência/publicação:",
                    value=dt_i,
                    key=chave_date_23,
                    format="DD/MM/YYYY",
                    disabled=documento_indisponivel
                )

                if not documento_indisponivel and dt_selecionada:
                    idade_calculada = int(ano_sel) - dt_selecionada.year
                    st.markdown(
                        f"<div style='padding-top:10px;'><b>Idade calculada:</b> {idade_calculada} ano(s) em relação ao ciclo de {ano_sel}.</div>",
                        unsafe_allow_html=True
                    )
                elif documento_indisponivel:
                    st.markdown(
                        "<div style='padding-top:10px; color:#dc3545;'><b>Status:</b> Constante 'XYZ' aplicada.</div>",
                        unsafe_allow_html=True
                    )

            with col2:
                link_23 = st.text_area(
                    "Link/Evidência da data de publicação (2.3):",
                    value="" if evidencia_23_salva == "XYZ" else evidencia_23_salva,
                    key=chave_link_23,
                    placeholder="Insira o link direto da página da publicação ou diário oficial contendo a data...",
                    disabled=documento_indisponivel,
                    height=100
                )

                placeholder_links_23 = st.empty()
                links_23_visuais = re.findall(regex_pure_url, link_23 or "")
                if links_23_visuais and not documento_indisponivel:
                    placeholder_links_23.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_23_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("2.3", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 2.3", key=f"btn_salvar_2_3_{ano_sel}", type="primary"):
                chk_indisponivel = st.session_state.get(chave_switch_23, False)
                lnk_val = link_23.strip()

                if chk_indisponivel or lnk_val.upper() == "XYZ":
                    data_str = "XYZ"
                    pontos_23 = 0.0
                    lnk_val = "XYZ"
                else:
                    data_sel = dt_selecionada
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

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_23, d23.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="2.3",
                    valor=data_str,
                    pontos=pontos_23,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["2.3"] = {
                    "valor": data_str,
                    "pontos": pontos_23,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_23_salva or "")

                if lnk_val != evidencia_23_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_2_3_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_2_3_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 2.3 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_23 = d23.get("pontos", 0.0)
            cor_txt_23 = "#28a745" if pts_atuais_23 == 20.0 else ("#ffc107" if pts_atuais_23 == 10.0 else "#6c757d")

            st.markdown(
                f"<span style='color:{cor_txt_23}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 2.3: +{pts_atuais_23:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 2.3 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_2_3_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("2.3", st.session_state.get(f"links_pendentes_2_3_{ano_sel}", []))
        st.session_state[f"gatilho_modal_2_3_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.0 • POLÍTICA DE SEGURANÇA DA INFORMAÇÃO (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_0_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.0 - Política de Segurança da Informação (POSIC)", expanded=True):
            st.subheader("3.0 • Política de Segurança da Informação")
            st.write("**A Prefeitura dispõe de Política de Segurança da informação formalmente instituída e de cumprimento obrigatório?**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.0'.*")

            opc30 = {
                "Selecione...": 0.0,
                "Sim – 50": 50.0,
                "Não – 00": 0.0
            }
            lista30 = list(opc30.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d30 = res_data.get("3.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_30 = d30.get("valor", "Selecione...")
            evidencia_30_salva = d30.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_30 = f"r_30_select_{ano_sel}"
            chave_link_30 = f"l_30_txt_area_{ano_sel}"
            chave_coment_30 = f"coment_3.0_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx30 = lista30.index(v_salvo_30) if v_salvo_30 in lista30 else 0
                st.radio(
                    "Selecione o status da POSIC:",
                    options=lista30,
                    index=idx30,
                    key=chave_radio_30
                )

            with col2:
                link_30 = st.text_area(
                    "Link/Evidência (3.0):",
                    value=evidencia_30_salva,
                    key=chave_link_30,
                    placeholder="Insira o link da publicação do decreto, resolução ou portaria instituindo a POSIC municipal...",
                    height=90
                )

                placeholder_links_30 = st.empty()
                links_30_visuais = re.findall(regex_pure_url, link_30 or "")
                if links_30_visuais:
                    placeholder_links_30.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_30_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.0", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.0", key=f"btn_salvar_3_0_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_30, v_salvo_30)
                pts_30 = float(opc30.get(val_salvar, 0.0))
                lnk_val = link_30.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_30, d30.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.0",
                    valor=val_salvar,
                    pontos=pts_30,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.0"] = {
                    "valor": val_salvar,
                    "pontos": pts_30,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_30_salva or "")

                if lnk_val != evidencia_30_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.0 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_30 = d30.get("pontos", 0.0)
            cor_txt_30 = "#28a745" if pts_atuais_30 == 50.0 else "#6c757d"

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
    # QUESITO 3.1 • TERMO DE RESPONSABILIDADE (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.1 - Termo de Responsabilidade e Compromisso de TI", expanded=True):
            st.subheader("3.1 • Termo de Responsabilidade")
            st.write("**A Prefeitura estabelece procedimentos e responsabilidades quanto ao uso da tecnologia da informação pelos funcionários municipais, conhecido como Termo de Responsabilidade/Compromisso?**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.1'.*")

            opc31 = {
                "Selecione...": 0.0,
                "Sim – 20": 20.0,
                "Não – 00": 0.0
            }
            lista31 = list(opc31.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d31 = res_data.get("3.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_31 = d31.get("valor", "Selecione...")
            evidencia_31_salva = d31.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_31 = f"r_31_select_{ano_sel}"
            chave_link_31 = f"l_31_txt_area_{ano_sel}"
            chave_coment_31 = f"coment_3.1_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx31 = lista31.index(v_salvo_31) if v_salvo_31 in lista31 else 0
                st.radio(
                    "Selecione o status do Termo:",
                    options=lista31,
                    index=idx31,
                    key=chave_radio_31
                )

            with col2:
                link_31 = st.text_area(
                    "Link/Evidência (3.1):",
                    value=evidencia_31_salva,
                    key=chave_link_31,
                    placeholder="Insira o link de publicação do decreto, portaria ou regulamento interno do Termo de Responsabilidade...",
                    height=90
                )

                placeholder_links_31 = st.empty()
                links_31_visuais = re.findall(regex_pure_url, link_31 or "")
                if links_31_visuais:
                    placeholder_links_31.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_31_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.1", key=f"btn_salvar_3_1_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_31, v_salvo_31)
                pts_31 = float(opc31.get(val_salvar, 0.0))
                lnk_val = link_31.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_31, d31.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.1",
                    valor=val_salvar,
                    pontos=pts_31,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.1"] = {
                    "valor": val_salvar,
                    "pontos": pts_31,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_31_salva or "")

                if lnk_val != evidencia_31_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_31 = d31.get("pontos", 0.0)
            cor_txt_31 = "#28a745" if pts_atuais_31 == 20.0 else "#6c757d"

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
    # QUESITO 3.1.1 • DISPOSIÇÃO SOBRE ASSINATURA ELETRÔNICA (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_1_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.1.1 - Uso de Assinatura Eletrônica no Termo", expanded=True):
            st.subheader("3.1.1 • Regramento de Assinatura Eletrônica")
            st.write("**O Termo de Responsabilidade/Compromisso dispõe sobre o uso da assinatura eletrônica pelos funcionários municipais?**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.1.1'.*")

            opc311 = {
                "Selecione...": 0.0,
                "Sim – 40": 40.0,
                "Não – 00": 0.0
            }
            lista311 = list(opc311.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d311 = res_data.get("3.1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_311 = d311.get("valor", "Selecione...")
            evidencia_311_salva = d311.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_311 = f"r_311_select_{ano_sel}"
            chave_link_311 = f"l_311_txt_area_{ano_sel}"
            chave_coment_311 = f"coment_3.1.1_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx311 = lista311.index(v_salvo_311) if v_salvo_311 in lista311 else 0
                st.radio(
                    "Selecione o status do regramento:",
                    options=lista311,
                    index=idx311,
                    key=chave_radio_311
                )

            with col2:
                link_311 = st.text_area(
                    "Link/Evidência (3.1.1):",
                    value=evidencia_311_salva,
                    key=chave_link_311,
                    placeholder="Insira o link ou fragmento do termo explicativo...",
                    height=90
                )

                placeholder_links_311 = st.empty()
                links_311_visuais = re.findall(regex_pure_url, link_311 or "")
                if links_311_visuais:
                    placeholder_links_311.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_311_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.1.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.1.1", key=f"btn_salvar_3_1_1_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_311, v_salvo_311)
                pts_311 = float(opc311.get(val_salvar, 0.0))
                lnk_val = link_311.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_311, d311.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.1.1",
                    valor=val_salvar,
                    pontos=pts_311,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.1.1"] = {
                    "valor": val_salvar,
                    "pontos": pts_311,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_311_salva or "")

                if lnk_val != evidencia_311_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_1_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_1_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.1.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_311 = d311.get("pontos", 0.0)
            cor_txt_311 = "#28a745" if pts_atuais_311 == 40.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_311}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.1.1: +{pts_atuais_311:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.1.1 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_1_1_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.1.1", st.session_state.get(f"links_pendentes_3_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_1_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.1.1.1 • TIPO DE ASSINATURA ELETRÔNICA (MODELO PADRONIZADO iGov)
    # =============================================================================
    import ast

    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_1_1_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.1.1.1 - Tipos de Assinatura Eletrônica Utilizada", expanded=True):
            st.subheader("3.1.1.1 • Modalidades de Assinatura")
            st.write("**Identifique os tipos de assinatura eletrônica aplicados na municipalidade:**")
            st.caption("ℹ *Selecione as opções aplicáveis, preencha o link de evidência e clique no botão 'Salvar Quesito 3.1.1.1'.*")

            tipos_assinatura = {
                "Assinatura eletrônica de uso gratuito – 10": 10.0,
                "Assinatura eletrônica onerosa – 00": 0.0
            }

            # Recupera e trata o estado inicial do dicionário com segurança
            d3111 = res_data.get("3.1.1.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

            raw_v3111 = d3111.get("valor", "[]")
            if not isinstance(raw_v3111, str) or not raw_v3111.startswith("["):
                raw_v3111 = "[]"

            try:
                lista_salva_3111 = ast.literal_eval(raw_v3111)
            except (ValueError, SyntaxError):
                lista_salva_3111 = []

            evidencia_3111_salva = d3111.get("link", "")

            # Chaves fixas por componente e ano
            chave_link_3111 = f"l_3111_txt_area_{ano_sel}"
            chave_coment_3111 = f"coment_3.1.1.1_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                # Renderiza checkboxes independentes por item
                for item in tipos_assinatura.keys():
                    slug_item = item.split(" – ")[0].replace(" ", "_").lower()
                    st.checkbox(
                        item,
                        value=item in lista_salva_3111,
                        key=f"chk_3111_{slug_item}_{ano_sel}"
                    )

            with col2:
                link_3111 = st.text_area(
                    "Link/Evidência das modalidades (3.1.1.1):",
                    value=evidencia_3111_salva,
                    key=chave_link_3111,
                    placeholder="Insira os links comprobatórios...",
                    height=90
                )

                placeholder_links_3111 = st.empty()
                links_3111_visuais = re.findall(regex_pure_url, link_3111 or "")
                if links_3111_visuais:
                    placeholder_links_3111.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_3111_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.1.1.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.1.1.1", key=f"btn_salvar_3_1_1_1_{ano_sel}", type="primary"):
                sel3111 = []
                pts3111 = 0.0

                # Captura os estados atuais dos checkboxes
                for item, pts in tipos_assinatura.items():
                    slug_item = item.split(" – ")[0].replace(" ", "_").lower()
                    if st.session_state.get(f"chk_3111_{slug_item}_{ano_sel}", False):
                        sel3111.append(item)
                        pts3111 += pts

                val_str = str(sel3111)
                lnk_val = link_3111.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_3111, d3111.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.1.1.1",
                    valor=val_str,
                    pontos=pts3111,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.1.1.1"] = {
                    "valor": val_str,
                    "pontos": pts3111,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_3111_salva or "")

                if lnk_val != evidencia_3111_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_1_1_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_1_1_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.1.1.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_3111 = d3111.get("pontos", 0.0)
            cor_txt_3111 = "#28a745" if pts_atuais_3111 > 0.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_3111}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.1.1.1: +{pts_atuais_3111:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.1.1.1 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_1_1_1_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.1.1.1", st.session_state.get(f"links_pendentes_3_1_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_1_1_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.2 • IDENTIFICAÇÃO DE RISCOS DE TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_2_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.2 - Identificação de Riscos de TIC (ISO/IEC 27000)", expanded=True):
            st.subheader("3.2 • Riscos de TIC")
            st.write("**Os riscos de TIC são identificados de acordo com as normas brasileiras da família ISO/IEC 27000?**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.2'.*")

            opc32 = {
                "Selecione...": 0.0,
                "Sim": 0.0,
                "Não": 0.0
            }
            lista32 = list(opc32.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d32 = res_data.get("3.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_32 = d32.get("valor", "Selecione...")
            evidencia_32_salva = d32.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_32 = f"r_32_select_{ano_sel}"
            chave_link_32 = f"l_32_txt_area_{ano_sel}"
            chave_coment_32 = f"coment_3.2_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx32 = lista32.index(v_salvo_32) if v_salvo_32 in lista32 else 0
                st.radio(
                    "Selecione o status da identificação:",
                    options=lista32,
                    index=idx32,
                    key=chave_radio_32
                )

            with col2:
                link_32 = st.text_area(
                    "Link/Evidência (3.2):",
                    value=evidencia_32_salva,
                    key=chave_link_32,
                    placeholder="Insira o link do processo, relatório ou mapeamento de riscos baseado na ISO 27000...",
                    height=90
                )

                placeholder_links_32 = st.empty()
                links_32_visuais = re.findall(regex_pure_url, link_32 or "")
                if links_32_visuais:
                    placeholder_links_32.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_32_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.2", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.2", key=f"btn_salvar_3_2_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_32, v_salvo_32)
                pts_32 = float(opc32.get(val_salvar, 0.0))
                lnk_val = link_32.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_32, d32.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.2",
                    valor=val_salvar,
                    pontos=pts_32,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.2"] = {
                    "valor": val_salvar,
                    "pontos": pts_32,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_32_salva or "")

                if lnk_val != evidencia_32_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.2 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_32 = d32.get("pontos", 0.0)
            cor_txt_32 = "#28a745" if pts_atuais_32 > 0.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_32}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.2: +{pts_atuais_32:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.2 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_2_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.2", st.session_state.get(f"links_pendentes_3_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.2.1 • NORMAS ISO APLICADAS (MODELO PADRONIZADO iGov)
    # =============================================================================
    import ast

    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_2_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.2.1 - Normas da Família ISO/IEC 27000 Utilizadas", expanded=True):
            st.subheader("3.2.1 • Normas Utilizadas e Fiscalização")
            st.write("**As secretarias setoriais realizaram a fiscalização das áreas de risco? Informe quais normas da família ISO/IEC 27000 são utilizadas nos processos de segurança no uso de TIC:**")
            st.caption("ℹ *Selecione as opções aplicáveis, preencha o link de evidência e clique no botão 'Salvar Quesito 3.2.1'.*")

            normas_iso = {
                "ISO/IEC 27000 – 1,5": 1.5,
                "ISO/IEC 27001 – 1,5": 1.5,
                "ISO/IEC 27002 – 1,5": 1.5,
                "ISO/IEC 27003 – 1,5": 1.5,
                "ISO/IEC 27004 – 02": 2.0,
                "ISO/IEC 27005 – 02": 2.0
            }

            # Recupera e trata o estado inicial do dicionário com segurança
            d321 = res_data.get("3.2.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

            raw_v321 = d321.get("valor", "[]")
            if not isinstance(raw_v321, str) or not raw_v321.startswith("["):
                raw_v321 = "[]"

            try:
                lista_salva_321 = ast.literal_eval(raw_v321)
            except (ValueError, SyntaxError):
                lista_salva_321 = []

            evidencia_321_salva = d321.get("link", "")

            # Chaves fixas por componente e ano
            chave_link_321 = f"l_321_txt_area_{ano_sel}"
            chave_coment_321 = f"coment_3.2.1_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                # Renderiza checkboxes independentes para cada norma
                for norma, pts in normas_iso.items():
                    slug_norma = norma.split(" – ")[0].replace("/", "_").replace(" ", "_").lower()
                    st.checkbox(
                        norma,
                        value=norma in lista_salva_321,
                        key=f"chk_321_{slug_norma}_{ano_sel}"
                    )

            with col2:
                link_321 = st.text_area(
                    "Link/Evidência das normas e fiscalizações (3.2.1):",
                    value=evidencia_321_salva,
                    key=chave_link_321,
                    placeholder="Insira os links comprobatórios dos atos, portarias ou relatórios de fiscalização baseados nas ISOs...",
                    height=140
                )

                placeholder_links_321 = st.empty()
                links_321_visuais = re.findall(regex_pure_url, link_321 or "")
                if links_321_visuais:
                    placeholder_links_321.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_321_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.2.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.2.1", key=f"btn_salvar_3_2_1_{ano_sel}", type="primary"):
                sel321 = []
                pts321 = 0.0

                # Captura os estados atuais das seleções de normas
                for norma, pts in normas_iso.items():
                    slug_norma = norma.split(" – ")[0].replace("/", "_").replace(" ", "_").lower()
                    if st.session_state.get(f"chk_321_{slug_norma}_{ano_sel}", False):
                        sel321.append(norma)
                        pts321 += pts

                val_str = str(sel321)
                lnk_val = link_321.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_321, d321.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.2.1",
                    valor=val_str,
                    pontos=pts321,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.2.1"] = {
                    "valor": val_str,
                    "pontos": pts321,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_321_salva or "")

                if lnk_val != evidencia_321_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_2_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_2_1_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.2.1 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_321 = d321.get("pontos", 0.0)
            cor_txt_321 = "#28a745" if pts_atuais_321 > 0.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_321}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.2.1: +{pts_atuais_321:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.2.1 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_2_1_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.2.1", st.session_state.get(f"links_pendentes_3_2_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_2_1_{ano_sel}"] = False

# =============================================================================
    # QUESITO 3.3 • IDENTIFICAÇÃO DE RISCOS DE TIC (ISO 31000) (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_3_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.3 - Gestão de Riscos de TIC (ABNT NBR ISO/IEC 31000)", expanded=True):
            st.subheader("3.3 • Riscos de TIC (ISO 31000)")
            st.write("**Os riscos de TIC são identificados de acordo com as normas da ABNT NBR ISO/IEC 31000? Se tiver apenas antivírus e firewall, a resposta é NÃO.**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.3'.*")

            opc33 = {
                "Selecione...": 0.0,
                "Sim – 30": 30.0,
                "Não – 00": 0.0
            }
            lista33 = list(opc33.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d33 = res_data.get("3.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_33 = d33.get("valor", "Selecione...")
            evidencia_33_salva = d33.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_33 = f"r_33_select_{ano_sel}"
            chave_link_33 = f"l_33_txt_area_{ano_sel}"
            chave_coment_33 = f"coment_3.3_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx33 = lista33.index(v_salvo_33) if v_salvo_33 in lista33 else 0
                st.radio(
                    "Selecione o status da conformidade:",
                    options=lista33,
                    index=idx33,
                    key=chave_radio_33
                )

            with col2:
                link_33 = st.text_area(
                    "Link/Evidência (3.3):",
                    value=evidencia_33_salva,
                    key=chave_link_33,
                    placeholder="Insira o link da política, plano ou matriz institucional de gestão de riscos de TIC corporativos...",
                    height=90
                )

                placeholder_links_33 = st.empty()
                links_33_visuais = re.findall(regex_pure_url, link_33 or "")
                if links_33_visuais:
                    placeholder_links_33.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_33_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.3", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.3", key=f"btn_salvar_3_3_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_33, v_salvo_33)
                pts_33 = float(opc33.get(val_salvar, 0.0))
                lnk_val = link_33.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_33, d33.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.3",
                    valor=val_salvar,
                    pontos=pts_33,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.3"] = {
                    "valor": val_salvar,
                    "pontos": pts_33,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_33_salva or "")

                if lnk_val != evidencia_33_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_3_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_3_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.3 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_33 = d33.get("pontos", 0.0)
            cor_txt_33 = "#28a745" if pts_atuais_33 == 30.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_33}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.3: +{pts_atuais_33:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.3 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_3_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.3", st.session_state.get(f"links_pendentes_3_3_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_3_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.4 • PLANO DE CONTINUIDADE DE SERVIÇOS (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_4_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.4 - Plano de Continuidade dos Serviços de TIC", expanded=True):
            st.subheader("3.4 • Plano de Continuidade")
            st.write("**A Prefeitura possui um Plano de Continuidade dos Serviços de Tecnologia da Informação e Comunicação (TIC)? Recomendamos anexar o Plano de continuidade de serviços de TI, conforme Instrução de Preenchimento (IP)**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.4'.*")

            opc34 = {
                "Selecione...": 0.0,
                "Sim – 30": 30.0,
                "Não – 00": 0.0
            }
            lista34 = list(opc34.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d34 = res_data.get("3.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_34 = d34.get("valor", "Selecione...")
            evidencia_34_salva = d34.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_34 = f"r_34_select_{ano_sel}"
            chave_link_34 = f"l_34_txt_area_{ano_sel}"
            chave_coment_34 = f"coment_3.4_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx34 = lista34.index(v_salvo_34) if v_salvo_34 in lista34 else 0
                st.radio(
                    "Selecione o status da continuidade:",
                    options=lista34,
                    index=idx34,
                    key=chave_radio_34
                )

            with col2:
                link_34 = st.text_area(
                    "Link/Evidência (3.4):",
                    value=evidencia_34_salva,
                    key=chave_link_34,
                    placeholder="Insira o link para o Plano de Continuidade de Negócios/TI aprovado institucionalmente...",
                    height=90
                )

                placeholder_links_34 = st.empty()
                links_34_visuais = re.findall(regex_pure_url, link_34 or "")
                if links_34_visuais:
                    placeholder_links_34.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_34_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.4", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.4", key=f"btn_salvar_3_4_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_34, v_salvo_34)
                pts_34 = float(opc34.get(val_salvar, 0.0))
                lnk_val = link_34.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_34, d34.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.4",
                    valor=val_salvar,
                    pontos=pts_34,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.4"] = {
                    "valor": val_salvar,
                    "pontos": pts_34,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_34_salva or "")

                if lnk_val != evidencia_34_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_4_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_4_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.4 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_34 = d34.get("pontos", 0.0)
            cor_txt_34 = "#28a745" if pts_atuais_34 == 30.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_34}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.4: +{pts_atuais_34:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.4 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_4_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.4", st.session_state.get(f"links_pendentes_3_4_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_4_{ano_sel}"] = False

# =============================================================================
    # QUESITO 3.5 • POLÍTICA DE BACKUP (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_5_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.5 - Política de Cópias de Segurança (Backup)", expanded=True):
            st.subheader("3.5 • Política de Backup")
            st.write("**A Prefeitura dispõe de política de cópias de segurança (backup) formalmente instituída como norma de cumprimento obrigatório?**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.5'.*")

            opc35 = {
                "Selecione...": 0.0,
                "Sim – 30": 30.0,
                "Não – 00": 0.0
            }
            lista35 = list(opc35.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d35 = res_data.get("3.5") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_35 = d35.get("valor", "Selecione...")
            evidencia_35_salva = d35.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_35 = f"r_35_select_{ano_sel}"
            chave_link_35 = f"l_35_txt_area_{ano_sel}"
            chave_coment_35 = f"coment_3.5_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx35 = lista35.index(v_salvo_35) if v_salvo_35 in lista35 else 0
                st.radio(
                    "Selecione o status da política:",
                    options=lista35,
                    index=idx35,
                    key=chave_radio_35
                )

            with col2:
                link_35 = st.text_area(
                    "Link/Evidência (3.5):",
                    value=evidencia_35_salva,
                    key=chave_link_35,
                    placeholder="Insira o link do normativo, portaria ou regulamento interno que formaliza a Política de Backup...",
                    height=90
                )

                placeholder_links_35 = st.empty()
                links_35_visuais = re.findall(regex_pure_url, link_35 or "")
                if links_35_visuais:
                    placeholder_links_35.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_35_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.5", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.5", key=f"btn_salvar_3_5_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_35, v_salvo_35)
                pts_35 = float(opc35.get(val_salvar, 0.0))
                lnk_val = link_35.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_35, d35.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.5",
                    valor=val_salvar,
                    pontos=pts_35,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.5"] = {
                    "valor": val_salvar,
                    "pontos": pts_35,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_35_salva or "")

                if lnk_val != evidencia_35_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_5_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_5_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.5 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_35 = d35.get("pontos", 0.0)
            cor_txt_35 = "#28a745" if pts_atuais_35 == 30.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_35}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.5: +{pts_atuais_35:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.5 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_5_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.5", st.session_state.get(f"links_pendentes_3_5_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_5_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.6 • INVENTÁRIO DE ATIVOS DE TIC (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_3_6_{ano_sel}", border=True):
        with st.expander("📌 Quesito 3.6 - Inventário Atualizado de Ativos de TIC", expanded=True):
            st.subheader("3.6 • Inventário de Ativos")
            st.write("**A Prefeitura possui inventário atualizado dos ativos de TIC? Ativos de TIC: switches, roteadores, servidores, firewalls, Sistemas operacionais, carga de processamento, backup, utilização de storages, etc.**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 3.6'.*")

            opc36 = {
                "Selecione...": 0.0,
                "Sim – 20": 20.0,
                "Não – 00": 0.0
            }
            lista36 = list(opc36.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d36 = res_data.get("3.6") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_36 = d36.get("valor", "Selecione...")
            evidencia_36_salva = d36.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_36 = f"r_36_select_{ano_sel}"
            chave_link_36 = f"l_36_txt_area_{ano_sel}"
            chave_coment_36 = f"coment_3.6_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx36 = lista36.index(v_salvo_36) if v_salvo_36 in lista36 else 0
                st.radio(
                    "Selecione o status do inventário:",
                    options=lista36,
                    index=idx36,
                    key=chave_radio_36
                )

            with col2:
                link_36 = st.text_area(
                    "Link/Evidência (3.6):",
                    value=evidencia_36_salva,
                    key=chave_link_36,
                    placeholder="Insira o link do sistema de inventário, planilha corporativa compartilhada ou relatório de ativos...",
                    height=90
                )

                placeholder_links_36 = st.empty()
                links_36_visuais = re.findall(regex_pure_url, link_36 or "")
                if links_36_visuais:
                    placeholder_links_36.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_36_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("3.6", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 3.6", key=f"btn_salvar_3_6_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_36, v_salvo_36)
                pts_36 = float(opc36.get(val_salvar, 0.0))
                lnk_val = link_36.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_36, d36.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="3.6",
                    valor=val_salvar,
                    pontos=pts_36,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["3.6"] = {
                    "valor": val_salvar,
                    "pontos": pts_36,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_36_salva or "")

                if lnk_val != evidencia_36_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_3_6_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_3_6_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 3.6 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_36 = d36.get("pontos", 0.0)
            cor_txt_36 = "#28a745" if pts_atuais_36 == 20.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_36}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 3.6: +{pts_atuais_36:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 3.6 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_3_6_{ano_sel}", False):
        if "modal_aviso_link" in globals():
            modal_aviso_link("3.6", st.session_state.get(f"links_pendentes_3_6_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_6_{ano_sel}"] = False

# =============================================================================
    # QUESITO 4.0 • REGULAMENTAÇÃO DA LAI (MODELO PADRONIZADO iGov)
    # =============================================================================
    regex_pure_url = r'https?://[^\s<>"]+'

    with st.container(key=f"container_bloco_igov_4_0_{ano_sel}", border=True):
        with st.expander("📌 Quesito 4.0 - Regulamentação da Lei de Acesso à Informação (LAI)", expanded=True):
            st.subheader("4.0 • Regulamentação da LAI")
            st.write("**O município regulamentou a Lei de Acesso à Informação?**")
            st.caption("ℹ *Selecione a opção desejada, preencha o link de evidência e clique no botão 'Salvar Quesito 4.0'.*")

            opc40 = {
                "Selecione...": 0.0,
                "Sim – 40": 40.0,
                "Não – 00": 0.0
            }
            lista40 = list(opc40.keys())

            # Recupera e trata o estado inicial do dicionário com segurança
            d40 = res_data.get("4.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_40 = d40.get("valor", "Selecione...")
            evidencia_40_salva = d40.get("link", "")

            # Chaves fixas por componente e ano
            chave_radio_40 = f"r_40_select_{ano_sel}"
            chave_link_40 = f"l_40_txt_area_{ano_sel}"
            chave_coment_40 = f"coment_4.0_{ano_sel}"

            col1, col2 = st.columns([1, 1])
            with col1:
                idx40 = lista40.index(v_salvo_40) if v_salvo_40 in lista40 else 0
                st.radio(
                    "Selecione o status da regulamentação:",
                    options=lista40,
                    index=idx40,
                    key=chave_radio_40
                )

            with col2:
                link_40 = st.text_area(
                    "Link/Evidência (4.0):",
                    value=evidencia_40_salva,
                    key=chave_link_40,
                    placeholder="Insira o link do decreto ou ato normativo municipal que regulamentou a LAI local...",
                    height=90
                )

                placeholder_links_40 = st.empty()
                links_40_visuais = re.findall(regex_pure_url, link_40 or "")
                if links_40_visuais:
                    placeholder_links_40.markdown("**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_40_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("4.0", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 4.0", key=f"btn_salvar_4_0_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_40, v_salvo_40)
                pts_40 = float(opc40.get(val_salvar, 0.0))
                lnk_val = link_40.strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_40, d40.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="4.0",
                    valor=val_salvar,
                    pontos=pts_40,
                    link=lnk_val,
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["4.0"] = {
                    "valor": val_salvar,
                    "pontos": pts_40,
                    "link": lnk_val,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação de links para gatilho do modal
                links_atuais = re.findall(regex_pure_url, lnk_val or "")
                links_antigos = re.findall(regex_pure_url, evidencia_40_salva or "")

                if lnk_val != evidencia_40_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 4.0 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo dinâmico e impacto de pontuação
            pts_atuais_40 = d40.get("pontos", 0.0)
            cor_txt_40 = "#28a745" if pts_atuais_40 == 40.0 else "#6c757d"

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
    # QUESITO 4.1 • IDENTIFICAÇÃO DO INSTRUMENTO NORMATIVO (MODELO PADRONIZADO iGov)
    # =============================================================================
    with st.container(key=f"container_bloco_igov_4_1_{ano_sel}", border=True):
        with st.expander("📌 Quesito 4.1 - Dados de Identificação da Normativa da LAI", expanded=True):
            st.subheader("4.1 • Dados do Instrumento")
            st.write("**Informe o Instrumento normativo, Número e Data de publicação:**")
            st.caption("ℹ *Preencha os dados do instrumento e clique no botão 'Salvar Quesito 4.1'.*")

            # Recupera os dados do 4.1 de forma segura
            d41 = res_data.get("4.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

            v_salvo_41 = d41.get("valor", "")

            # Chaves fixas por componente e ano
            chave_input_41 = f"t_41_input_{ano_sel}"
            chave_coment_41 = f"coment_4.1_{ano_sel}"

            txt_normativa = st.text_input(
                "Identificação do Instrumento Normativo:",
                value=v_salvo_41,
                key=chave_input_41,
                placeholder="Ex: Decreto Municipal nº 1.234, de 15 de março de 2018"
            )

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("4.1", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 4.1", key=f"btn_salvar_4_1_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_input_41, v_salvo_41).strip()

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_41, d41.get("comentario", ""))

                # 2. Salva no banco de dados isolado do iGov (respostas_igov)
                save_resp(
                    qid="4.1",
                    valor=val_salvar,
                    pontos=0.0,
                    link="",
                    comentarios=comentario_para_salvar
                )

                # 3. Atualiza o dicionário local res_data
                res_data["4.1"] = {
                    "valor": val_salvar,
                    "pontos": 0.0,
                    "link": "",
                    "comentario": comentario_para_salvar
                }

                # Limpa o cache para forçar a atualização imediata dos painéis
                st.cache_data.clear()

                st.toast("Resposta e comentário do Quesito 4.1 salvos com sucesso!", icon="✅")

                # 4. FORÇA O RECARREGAMENTO DA TELA (Atualiza sidebar e painel)
                st.rerun()

            # Resumo de impacto de pontuação
            st.markdown(
                "<span style='color:#6c757d; font-weight:bold;'>"
                "📊 Impacto de Pontuação no Quesito 4.1: +0.0 pontos</span>",
                unsafe_allow_html=True
            )
