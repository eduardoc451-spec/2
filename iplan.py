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

# Imports de componentes ReportLab para relatórios em PDF do iPLAN
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

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES DE AMBIENTE E BANCO DE DADOS NEON
# -----------------------------------------------------------------------------
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore")
os.environ["STREAMLIT_LOGGER_LEVEL"] = "error"
os.environ["PYTHONWARNINGS"] = "ignore"
logging.getLogger("streamlit").setLevel(logging.ERROR)


# Gerenciamento otimizado de pool de conexões Neon Postgres
@st.cache_resource
def get_db_pool():
    """Cria e mantém um pool de conexões persistente com o Postgres Neon."""
    try:
        db_url = st.secrets["DATABASE_URL"]
        return psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=db_url)
    except Exception as e:
        logging.error(f"Erro ao inicializar pool de conexões: {e}")
        st.error(f"Falha de conexão com o banco de dados Neon: {e}")
        return None


def get_connection():
    """Obtém uma conexão a partir do pool gerenciado."""
    connection_pool = get_db_pool()
    if connection_pool:
        return connection_pool.getconn()
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def release_connection(conn):
    """Devolve a conexão ao pool com segurança ou fecha se for avulsa."""
    if not conn:
        return
    connection_pool = get_db_pool()
    if connection_pool:
        try:
            connection_pool.putconn(conn)
        except Exception:
            conn.close()
    else:
        conn.close()


def init_db_iplan():
    """Cria a tabela respostas_iplan para o Módulo de Planejamento Urbano."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS respostas_iplan (
                    id SERIAL PRIMARY KEY,
                    ano INT NOT NULL,
                    quesito VARCHAR(50) NOT NULL,
                    resposta TEXT,
                    pontos DOUBLE PRECISION DEFAULT 0.0,
                    detalhes JSONB DEFAULT '{}'::jsonb,
                    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unq_ano_quesito_iplan UNIQUE(ano, quesito)
                );
            """)
        conn.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar banco iPLAN: {e}")
    finally:
        if conn:
            release_connection(conn)


# 💡 Alias para evitar 'NameError: name 'init_db' is not defined'
# caso a função seja chamada como init_db() em mostrar_formulario_plan()
init_db = init_db_iplan


# Inicializa a tabela no carregamento do módulo
try:
    init_db_iplan()
except Exception as e:
    logging.error(f"Erro no auto-init do iPLAN: {e}")

# =============================================================================
# REGEX DE VALIDAÇÃO
# =============================================================================
REGEX_PURE_URL = r'((https?://[^\s<>"]+))'

# =============================================================================
# CONSTANTES GLOBAIS - IPLAN (PLANEJAMENTO URBANO E TERRITORIAL)
# =============================================================================

CATEGORIAS_MAP_IPLAN = {
    "plano_diretor": {
        "label": "Plano Diretor e Legislação Correlata", 
        "qids": ["1.0", "1.1", "1.2", "1.3", "1.4", "2.0", "2.1", "2.2"]
    },
    "uso_solo": {
        "label": "Uso, Ocupação e Parcelamento do Solo", 
        "qids": ["3.0", "3.1", "3.2", "3.3", "4.0", "4.1", "4.2"]
    },
    "habitacao": {
        "label": "Habitação de Interesse Social e Regularização Fundiária", 
        "qids": ["5.0", "5.1", "5.2", "5.3", "6.0", "6.1"]
    },
    "mobilidade": {
        "label": "Mobilidade e Acessibilidade Urbana", 
        "qids": ["7.0", "7.1", "7.2", "8.0", "8.1", "8.2", "8.3"]
    },
    "gestao_territorial": {
        "label": "Sistema de Informações e Gestão Territorial", 
        "qids": ["9.0", "9.1", "9.2", "10.0", "10.1", "10.2"]
    },
    "participacao_transparencia": {
        "label": "Gestão Democrática e Participação Social", 
        "qids": ["11.0", "11.1", "11.2", "12.0", "12.1"]
    }
}

PONTUACOES_MAX_IPLAN = {
    "1.1": 10.0, "1.2": 15.0, "1.3": 10.0, "1.4": 5.0, "2.0": 10.0, "2.1": 10.0, "2.2": 10.0,
    "3.1": 15.0, "3.2": 10.0, "3.3": 5.0, "4.1": 10.0, "4.2": 10.0,
    "5.1": 20.0, "5.2": 15.0, "5.3": 15.0, "6.1": 10.0,
    "7.1": 15.0, "7.2": 10.0, "8.1": 10.0, "8.2": 10.0, "8.3": 5.0,
    "9.1": 15.0, "9.2": 10.0, "10.1": 10.0, "10.2": 10.0,
    "11.1": 10.0, "11.2": 10.0, "12.1": 10.0
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
        st.session_state[f"aviso_link_exibido_{qid}"] = True
        st.rerun()

# =============================================================================
# 1. GESTÃO DE ESTADO E PERSISTÊNCIA (SESSION STATE + NEON POSTGRES) - iPLAN
# =============================================================================

def get_ano_atual() -> int:
    """Recupera o ano de referência ativo para o iPLAN."""
    return int(st.session_state.get("ano_referencia_iplan") or st.session_state.get("ano_referencia_global") or 2026)


def load_respostas(ano: int = None) -> dict:
    """Carrega respostas do st.session_state ou do Neon (tabela respostas_iplan)."""
    if ano is None:
        ano = get_ano_atual()
    
    key_ano = f"respostas_iplan_{ano}"
    
    if key_ano not in st.session_state:
        st.session_state[key_ano] = {}
        conn = None
        try:
            conn = get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT quesito, resposta, pontos, detalhes FROM respostas_iplan WHERE ano = %s",
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

                    try:
                        pts = float(r['pontos']) if r['pontos'] is not None else 0.0
                    except (ValueError, TypeError):
                        pts = 0.0

                    st.session_state[key_ano][str(r['quesito'])] = {
                        "valor": r['resposta'] or "",
                        "pontos": pts,
                        "link": detalhes.get("link", ""),
                        "comentarios": detalhes.get("comentarios", []),
                        "comentario": detalhes.get("comentario", ""),
                        "detalhes": detalhes
                    }
        except Exception as e:
            logging.error(f"Erro ao carregar respostas do banco iPLAN: {e}")
        finally:
            if conn:
                release_connection(conn)

    return st.session_state[key_ano]


def save_resp(qid, valor, pontos, link="", comentarios=None, comentario=""):
    """Salva/Atualiza respostas no st.session_state e sincroniza com a tabela respostas_iplan no Neon."""
    ano_int = get_ano_atual()
    key_ano = f"respostas_iplan_{ano_int}"
    
    if key_ano not in st.session_state:
        st.session_state[key_ano] = {}

    dados_atuais = st.session_state[key_ano].get(str(qid), {})

    if comentarios is None:
        comentarios = dados_atuais.get("comentarios", [])
        
    if not comentario:
        comentario = dados_atuais.get("comentario", "")

    # Garantia de tratamento dos pontos
    try:
        pontos_float = float(pontos)
    except (ValueError, TypeError):
        pontos_float = 0.0

    # Monta o pacote JSON para a coluna 'detalhes'
    dados_detalhes = {
        "link": str(link or ""),
        "comentarios": comentarios,
        "comentario": str(comentario or "")
    }

    # 1. Atualiza Session State
    dados_salvar = {
        "valor": str(valor),
        "pontos": pontos_float,
        "link": str(link or ""),
        "comentarios": comentarios,
        "comentario": str(comentario or ""),
        "detalhes": dados_detalhes,
        "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    st.session_state[key_ano][str(qid)] = dados_salvar

    # 2. Persiste no banco de dados Neon (UPSERT em respostas_iplan)
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO respostas_iplan (ano, quesito, resposta, pontos, detalhes, atualizado_em)
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
                pontos_float,
                json.dumps(dados_detalhes)
            ))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Erro ao salvar resposta do iPLAN no banco Neon: {e}")
        st.error(f"Erro ao salvar no banco Neon: {e}")
        return False
    finally:
        if conn:
            release_connection(conn)

# =============================================================================
# 2. COMPONENTE PARA RENDERIZAR E SALVAR QUESTÕES
# =============================================================================

def renderizar_questao(qid, res_data):
    """Renderiza a questão do iPLAN com campo de formulário e salvamento."""
    dados_q = res_data.get(qid, {})
    
    val_existente = dados_q.get("valor", "")
    try:
        pts_existente = float(dados_q.get("pontos", 0.0))
    except (ValueError, TypeError):
        pts_existente = 0.0
        
    link_existente = dados_q.get("link", "")
    max_pts = PONTUACOES_MAX_IPLAN.get(qid, 100.0)
    
    with st.container(border=True):
        st.markdown(f"#### Quesito Territorial: `{qid}`")
        
        col_txt, col_meta = st.columns([3, 1])
        
        with col_txt:
            novo_valor = st.text_area(
                "Resposta / Evidência Urbana:", 
                value=val_existente, 
                key=f"txt_val_iplan_{qid}",
                height=100
            )
            novo_link = st.text_input(
                "Link do Documento/Mapa/Decreto (opcional):", 
                value=link_existente, 
                key=f"txt_link_iplan_{qid}"
            )

        with col_meta:
            novos_pontos = st.number_input(
                f"Pontuação (Máx: {max_pts}):", 
                value=pts_existente, 
                min_value=0.0,
                max_value=float(max_pts),
                step=0.5,
                key=f"num_pts_iplan_{qid}"
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("💾 Salvar Questão", key=f"btn_save_iplan_{qid}", type="primary", use_container_width=True):
                links = re.findall(REGEX_PURE_URL, novo_valor) + re.findall(REGEX_PURE_URL, novo_link)
                # Extrai apenas as URLs casadas
                links_formatados = [l[0] if isinstance(l, tuple) else l for l in links]
                
                sucesso = save_resp(
                    qid=qid, 
                    valor=novo_valor, 
                    pontos=novos_pontos, 
                    link=novo_link
                )
                
                if sucesso:
                    st.toast(f"Quesito {qid} do iPLAN salvo com sucesso!", icon="✅")
                    if links_formatados and "modal_aviso_link" in globals():
                        modal_aviso_link(qid, links_formatados)

        # Diálogo Interno (Comentários)
        bloco_comentarios(qid, res_data)


def bloco_comentarios(questao_id, res_data, sufixo=None):
    """Gera o diálogo interno avançado para o iPLAN com histórico e status."""
    ano_sel = get_ano_atual()
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_iplan_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_iplan_{id_chave}_{ano_sel}"
    key_radio = f"rad_status_iplan_{id_chave}_{ano_sel}"
    
    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False
        
    dados_questao = res_data.get(questao_id, {})
    historico = list(dados_questao.get("comentarios", []))
    
    status_global = "Resolvido"
    for com in historico:
        if isinstance(com, dict) and "status_definido" in com:
            status_global = com["status_definido"]
            
    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    
    with st.expander(f"💬 Diálogo Interno iPLAN {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
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
                "texto": f"ℹ️ Alterou o status do quesito urbano para: **{novo_status_clicado.upper()}**.",
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
                            f"""<div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #0056b3;">
                                <span style="font-size: 11px; color: #0056b3; font-weight: bold;">{autor}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{data_com}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{texto_com}</p>
                            </div>""", unsafe_allow_html=True
                        )
                
                with col_lixeira:
                    if st.button("🗑️", key=f"btn_del_com_iplan_{id_chave}_{idx}_{ano_sel}"):
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
        
        if st.button("Postar Comentário", key=f"btn_com_iplan_{id_chave}_{ano_sel}", type="primary"):
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
# 3. FUNÇÕES DE ANÁLISE E HISTÓRICO (iPLAN)
# =============================================================================

def get_all_years_data():
    """Varre a sessão procurando por chaves do tipo respostas_iplan_<ano>."""
    all_data = {}
    prefixo = "respostas_iplan_"
    
    for key in list(st.session_state.keys()):
        if key.startswith(prefixo):
            try:
                ano = int(key.replace(prefixo, ""))
                all_data[ano] = st.session_state[key]
            except ValueError:
                continue
                
    return all_data


def analyze_performance(res_data):
    """Mapeia pontos fortes e fragilidades do ano atual no iPLAN usando PONTUACOES_MAX_IPLAN."""
    pontos_fortes = []
    criticos_zero = {"Alta": [], "Média": [], "Baixa": []}
    criticos_negativos = {"Alta": [], "Média": [], "Baixa": []}

    pontuacoes_ref = globals().get('PONTUACOES_MAX_IPLAN', {})

    def classificar_relevancia(impacto):
        abs_impacto = abs(impacto)
        if abs_impacto >= 15:
            return "Alta"
        elif 6 <= abs_impacto < 15:
            return "Média"
        else:
            return "Baixa"

    # Itera sobre todas as questões mapeadas no iPLAN para não ignorar quesitos não cadastrados no banco
    for qid, max_pontos in pontuacoes_ref.items():
        info = res_data.get(qid, {})
        
        try:
            pontos_atuais = float(info.get("pontos", 0.0))
        except (ValueError, TypeError):
            pontos_atuais = 0.0

        max_pontos = float(max_pontos)

        if pontos_atuais >= max_pontos:
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

# =============================================================================
# 4. GERADOR DO RELATÓRIO PDF - i-PLAN (PLANEJAMENTO URBANO)
# =============================================================================

def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    
    style_titulo_capa = ParagraphStyle(
        'TituloCapaIPLAN', 
        parent=styles['Normal'], 
        fontName='Helvetica-Bold', 
        fontSize=24, 
        leading=28, 
        textColor=colors.HexColor("#004085"), 
        alignment=1
    )
    
    style_ano_capa = ParagraphStyle(
        'AnoCapaIPLAN', 
        parent=styles['Normal'], 
        fontName='Helvetica', 
        fontSize=16, 
        leading=20,
        textColor=colors.HexColor("#6c757d"), 
        alignment=1
    )

    style_tabela_padrao = ParagraphStyle(
        'TextoTabelaIPLAN',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=0
    )

    style_tabela_centro = ParagraphStyle(
        'TextoTabelaCentroIPLAN',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=1
    )

    def limpar_xml(texto):
        return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    if all_data is None:
        all_data = {}
        
    pontuacoes_max = globals().get('PONTUACOES_MAX_IPLAN', {})

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
    elements.append(Paragraph("Relatório i-PLAN (Planejamento Urbano)", style_titulo_capa))
    elements.append(Spacer(1, 15))
    
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsqIPLAN', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#1b4965"))
    style_pag_direita = ParagraphStyle('PagDirIPLAN', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#004085"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa Urbano-Territorial)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito i-PLAN", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Legislação Urbana", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Adequação ao Plano Diretor", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com Políticas Habitacionais e Mobilidade", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("6. Série Histórica do Planejamento Territorial", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
    ]
    
    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1"), 1, (2, 4)), 
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-PLAN (PLANEJAMENTO URBANO) - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA TERRITORIAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    nota_atual = float(total)
    ano_atual = int(str(ano).strip()[:4])
    ano_ant = ano_atual - 1

    def converter_pontos_em_faixa_iplan(pontos):
        pts = float(pontos)
        if pts <= 100.0:              return "C"
        elif 100.1 <= pts <= 150.0:  return "C+"
        elif 150.1 <= pts <= 220.0:  return "B"
        elif 220.1 <= pts <= 270.0:  return "B+"
        else:                        return "A"

    dados_ano_anterior = all_data.get(ano_ant, {})
    nota_anterior = 0.0
    if ano_ant in all_data:
        nota_anterior = float(sum(
            info_ant.get("pontos", 0) 
            for qid_ant, info_ant in dados_ano_anterior.items() 
            if isinstance(info_ant, dict) and not qid_ant.startswith("COM_")
        ))

    faixa_anterior = converter_pontos_em_faixa_iplan(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_iplan(nota_atual)

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

    style_th = ParagraphStyle('ThIPLAN', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAnoIPLAN', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#1e293b"), alignment=1)
    style_td_pts = ParagraphStyle('TdPtsIPLAN', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixaIPLAN', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor("#004085"), alignment=1)
    style_td_var = ParagraphStyle('TdVarIPLAN', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_variacao, alignment=1)

    dados_comparativos = [
        [Paragraph("Exercício", style_th), Paragraph("Pontuação Obtida", style_th), Paragraph("Faixa / Conceito", style_th), Paragraph("Variação Nominal", style_th), Paragraph("Variação Percentual", style_th)],
        [Paragraph(str(ano_ant), style_td_ano), Paragraph(f"{nota_anterior:.1f} pts", style_td_pts), Paragraph(str(faixa_anterior), style_td_faixa), Paragraph("-", style_td_var), Paragraph("-", style_td_var)],
        [Paragraph(str(ano_atual), style_td_ano), Paragraph(f"{nota_atual:.1f} pts", style_td_pts), Paragraph(str(faixa_real_atual), style_td_faixa), Paragraph(f"{seta_tendencia} {variacao_pontos:+.1f} pts", style_td_var), Paragraph(f"{seta_tendencia} {texto_percentual}", style_td_var)]
    ]

    tabela_comp = Table(dados_comparativos, colWidths=[80, 105, 95, 105, 105])
    tabela_comp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")), 
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8fafc")), ("BACKGROUND", (0, 2), (-1, 2), colors.whitesmoke),                    
    ]))
    elements.append(tabela_comp)
    elements.append(Spacer(1, 12))

    style_analise = ParagraphStyle('AnaliseIPLAN', parent=styles['Normal'], fontSize=10, leading=14)
    if variacao_pontos > 0:
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou avanço em suas diretrizes urbanísticas, com acréscimo de <b>{texto_percentual}</b> no desempenho do iPLAN em relação ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Descontinuidade:</b></font> Houve uma queda de <b>{texto_percentual}</b> na conformidade dos instrumentos de planejamento territorial em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município manteve estabilidade (0.00%) no seu indicador de gestão e planejamento urbano."

    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # =========================================================================
    # 2. ANÁLISE DE DESEMPENHO POR QUESITO - iPLAN
    # =========================================================================
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO TERRITORIAL</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []
    dados_consolidados = {}

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
        
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")

        qid_str = str(qid).strip()
        
        if qid_str not in pontuacoes_max:
            continue

        if qid_str not in dados_consolidados:
            dados_consolidados[qid_str] = {"pts_obtidos": 0.0, "valores": [], "links": []}
        
        dados_consolidados[qid_str]["pts_obtidos"] += pts_obtidos
        
        if valor_resposta:
            dados_consolidados[qid_str]["valores"].append(limpar_xml(valor_resposta))
            
        if link_evidencia:
            link_limpo = limpar_xml(link_evidencia)
            if link_limpo not in dados_consolidados[qid_str]["links"]:
                dados_consolidados[qid_str]["links"].append(link_limpo)

    for qid, info in dados_consolidados.items():
        pts_maximo = float(pontuacoes_max.get(qid, 10.0))
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
        elements.append(Paragraph("<b>✅ Pontos Fortes em Planejamento Urbano:</b>", styles["h3"]))
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#004085")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#004085")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Oportunidades de Adequação Urbana e Territorial:</b>", styles["h3"]))
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d97706")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d97706")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 15))        
    # =========================================================================
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (PLANEJAMENTO URBANO - iPLAN)
    # =========================================================================
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    # Mapeamento atualizado de penalidades para o i-PLAN / Planejamento Urbano
    PENALIDADES_MAX = {
        "4.3": -10.0,
        "7.1": -30.0,
        "8.1": -10.0,
        "9.1": -10.0,
        "10.0": -10.0,
        "12.1.1": -10.0,
        "12.1.2": -10.0,
        "13.1": -10.0,
        "14.4.4.1": -6.0,
        "14.4.4.2": -3.0,
        "14.4.5.1.1": -3.0,
        "15.3": -2.5,
        "15.4.1": -10.0,
        "15.4.2": -10.0,
        "15.5": -1.0,
        "18.1": -10.0
    }

    dados_penalidades = dados.copy()
    reincidencias_detectadas = []

    # Tratamento para quesitos ausentes do dict original (considera 0.0 pontos / sem aplicação)
    for qid_pen, val_max in PENALIDADES_MAX.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {
                "pontos": 0.0, 
                "valor": "Não aplicável / Ocultado por condicional territorial", 
                "link": ""
            }

    lista_penalidades = []
    
    for qid, pen_max in PENALIDADES_MAX.items():
        if qid in dados_penalidades:
            info = dados_penalidades[qid]
            nota_real = float(info.get("pontos", 0.0))
            
            # Garante que apenas penalidades reais (valores <= 0) componham o cálculo
            nota_risco = nota_real if nota_real <= 0.0 else 0.0
            
            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0
                
            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))

            lista_penalidades.append({
                "qid": qid, 
                "nota_real": nota_real, 
                "pen_max": pen_max, 
                "eficiencia": eficiencia_preventiva, 
                "valor": info.get("valor", ""), 
                "link": info.get("link", "")
            })
            
            # Verificação de Reincidência de Penalidade Territorial em Relação ao Ano Anterior
            if eficiencia_preventiva < 100.0 and isinstance(dados_ano_anterior, dict) and qid in dados_ano_anterior:
                info_ant = dados_ano_anterior[qid]
                nota_real_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) else 0.0
                if nota_real == nota_real_ant:
                    reincidencias_detectadas.append({
                        "qid": qid, 
                        "tipo": "Penalidade Urbana Recorrente", 
                        "detalhe": f"Impacto Recorrente em Diretriz Urbana de {nota_real:.1f} pts", 
                        "ant": f"{nota_real_ant:.1f} pts", 
                        "atual": f"{nota_real:.1f} pts"
                    })

    if lista_penalidades:
        data_penalidades = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Penalidade Aplicada", style_th), 
            Paragraph("Pior Cenário", style_th), 
            Paragraph("Eficiência Preventiva", style_th), 
            Paragraph("Status de Risco Territorial", style_th)
        ]]
        
        # Função auxiliar para ordenação hierárquica por números de quesitos urbanos (ex: 14.4.5.1.1)
        def ordenar_quesitos_complexos(x):
            limpo = ''.join(c for c in x["qid"] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]

        for item in sorted(lista_penalidades, key=ordenar_quesitos_complexos):
            # Tratamento de arredondamento para evitar impressão visual de "-0.0 pts"
            valor_nota = 0.0 if abs(item['nota_real']) < 0.01 else item['nota_real']
            
            nota_txt = f"{valor_nota:.1f} pts"
            teto_txt = f"{item['pen_max']:.1f} pts"
            ef_txt = f"{item['eficiencia']:.1f}%"
            
            if item['eficiencia'] >= 100.0: 
                status = "<font color='#2e7d32'><b>Conformidade Preservada</b></font>"
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#004085")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#004085")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), 
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_pen)
        elements.append(Spacer(1, 15))
        
    # =========================================================================
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES i-PLAN)
    # =========================================================================
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    # Nota: A lista 'reincidencias_detectadas' já foi populada dinamicamente 
    # na Seção 3 ao comparar os impactos reais das penalidades entre os dois anos.

    # Renderização da Tabela de Gargalos Baseada nas Penalidades do i-PLAN
    if reincidencias_detectadas:
        data_reinc = [[
            Paragraph("Quesito", style_th),
            Paragraph("Macro-Categoria", style_th),
            Paragraph("Descrição do Gargalo", style_th),
            Paragraph("Exercício Ant.", style_th),
            Paragraph("Exercício Atual", style_th)
        ]]
        for reinc in reincidencias_detectadas:
            data_reinc.append([
                Paragraph(reinc["qid"], style_tabela_centro),
                Paragraph(reinc["tipo"], style_tabela_padrao),
                Paragraph(reinc["detalhe"], style_tabela_padrao),
                Paragraph(reinc["ant"], style_tabela_centro),
                Paragraph(reinc["atual"], style_tabela_centro)
            ])
        tabela_reinc = Table(data_reinc, colWidths=[60, 110, 170, 80, 80])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#78281f")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#78281f")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_reinc)
    else:
        elements.append(Paragraph("<i>Nenhuma reincidência de impacto crítico por penalidade detectada entre os dois exercícios analíticos.</i>", style_analise))

    # -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU) - FORMATADO PADRÃO I-GOV
    # -------------------------------------------------------------------------
    import reportlab.lib.colors as rl_colors
    from reportlab.lib.styles import ParagraphStyle as Alias_Style

    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    def calcular_percentual_checklist(resposta_bruta, total_itens):
        if not resposta_bruta: 
            return 0.0
        itens = [i.strip().lower() for i in str(resposta_bruta).split(",") if i.strip()]
        itens_validos = [i for i in itens if i and "não" not in i]
        if total_itens > 0:
            return min((len(itens_validos) / total_itens) * 100.0, 100.0)
        return 0.0

    analise_ods = []

    # Mapeamento do i-PLAN
    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()

        if not resp or resp_l == "não respondido" or resp == "[]":
            continue

        metas = ""
        status = "Não Atendido"

        # ---------------------------------------------------------------------
        # REGRAS DE MAPEAMENTO DOS QUESITOS E METAS ODS (i-PLAN)
        # ---------------------------------------------------------------------
        if qid == "1.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "1.2":
            metas = "16.6"
            condicoes_12 = ["dia de semana após horário comercial", "aos sábados, domingos e feriados", "sábados", "domingos", "feriados"]
            status = "Atendido" if any(c in resp_l for c in condicoes_12) else "Não Atendido"
        elif qid == "1.3":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "1.4": # Checklist com 8 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 8):.1f}% Atendido"
        elif qid in ["2", "2.0"]:
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "2.1":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "3.0":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "3.1":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "3.2":
            metas = "16.6"
            status = "Atendido" if "sim, para todos os programas ppa" in resp_l else "Não Atendido"
        elif qid == "4.0":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim, com metas físicas e financeiras" in resp_l else "Não Atendido"
        elif qid == "4.1.1.1.1": # Checklist com 3 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 3):.1f}% Atendido"
        elif qid == "4.1.1.2":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim, para todos os programas finalísticos avaliados do ppa" in resp_l else "Não Atendido"
        elif qid == "4.2":
            metas = "16.6, 17.14"
            status = "Atendido" if "todos os indicadores do ppa" in resp_l else "Não Atendido"
        elif qid == "4.3": # Checklist com 9 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 9):.1f}% Atendido"
        elif qid == "5.0":
            metas = "16.6, 17.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "5.1": # Checklist com 7 opções
            metas = "16.6, 17.1"
            status = f"{calcular_percentual_checklist(resp, 7):.1f}% Atendido"
        elif qid == "5.1.1":
            metas = "16.6, 17.1"
            status = "Atendido" if "sim, com reestimativa da receita prevista na loa no decorrer da execução orçamentária-financeira" in resp_l else "Não Atendido"
        elif qid == "5.2":
            metas = "16.6, 17.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "6.0": # Checklist com 11 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 11):.1f}% Atendido"
        elif qid == "7.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "8.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "8.2": # Checklist com 8 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 8):.1f}% Atendido"
        elif qid == "9.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "9.2": # Checklist com 6 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 6):.1f}% Atendido"
        elif qid == "10.0": # Checklist com 9 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 9):.1f}% Atendido"
        elif qid == "12.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "12.1":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "12.1.1":
            metas = "16.6"
            status = "Atendido" if "sim, todos os servidores possuem qualificação técnica" in resp_l else "Não Atendido"
        elif qid == "12.1.2":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["13", "13.0"]:
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "13.1": # Checklist com 3 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 3):.1f}% Atendido"
        elif qid == "13.1.1": # Checklist com 3 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 3):.1f}% Atendido"
        elif qid == "13.2":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.3": # Checklist com 15 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 15):.1f}% Atendido"
        elif qid == "14.4":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.4.1":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.4.5":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "15.0":
            metas = "16.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "15.4":
            metas = "16.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "16.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "16.2":
            metas = "16.6, 16.7"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "16.3":
            metas = "16.6, 16.7"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "17.0":
            metas = "16.6, 16.7"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "18.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"

        if metas:
            # Trata tamanho da string para segurança do layout
            exibicao_resp = limpar_xml(resp) if 'limpar_xml' in globals() or 'limpar_xml' in locals() else resp
            if len(exibicao_resp) > 45:
                exibicao_resp = exibicao_resp[:45] + "..."

            analise_ods.append({
                "qid": qid,
                "metas": metas,
                "resp": exibicao_resp,
                "status": status
            })

    if analise_ods:
        data_ods = [["Quesito", "Resposta Informada", "Vínculo Metas ODS", "Status de Alinhamento"]]
        style_td_ods = Alias_Style('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        # Ordenação inteligente de chaves aninhadas (ex: 4.1.1.1.1 antes de 4.1.1.2)
        def sort_key_ods(x):
            partes = [int(i) for i in ''.join(c for c in x['qid'] if c.isdigit() or c == '.').split('.') if i.isdigit()]
            return partes if partes else [999]

        for item in sorted(analise_ods, key=sort_key_ods):
            st_txt = item["status"]
            
            # Formatação de Cores Dinâmicas para o Status
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
    # 📊 6. SÉRIE HISTÓRICA DO I-PLAN (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    import streamlit as st

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>6. SÉRIE HISTÓRICA DO I-PLAN (CONSOLIDADO FINAL)</b>", styles["h2"]))
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

    # Captura da nota atual
    nota_reference = 0.0
    for nome_var in ['total_pts', 'nota_atual', 'pontuacao_final', 'total']:
        if nome_var in locals():
            try:
                nota_reference = float(locals()[nome_var])
                break
            except (ValueError, TypeError):
                continue

    # Captura segura da variável all_data sem disparar NameError
    var_all_data = locals().get('all_data', globals().get('all_data', None))

    # Montagem do array de dados para o Gráfico
    for a in anos_serie:
        if a == 0 or a == "0":
            valores_serie.append(0.0)
        elif a == ano_reference: 
            valores_serie.append(min(nota_reference, 1000.0))
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

    # Identifica se a escala é até 100 ou até 1000 para ajustar o gráfico dinamicamente
    max_escala = 1000 if any(v > 100 for v in valores_serie) else 100
    passo_escala = 200 if max_escala == 1000 else 20

    # Configuração e renderização do Gráfico do i-PLAN
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
    
    # Customização de cor temática
    bc.bars[0].fillColor = rl_colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = rl_colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(String(240, 150, "Série Histórica de Evolução do i-PLAN", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=rl_colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))

    # =========================================================================
    # FIM DA FUNÇÃO: GERAÇÃO E RETORNO SEGURO DO BUFFER
    # =========================================================================
    doc.build(elements)
    buffer.seek(0)
    return buffer
    
# =============================================================================
# 2. INTERFACE E FORMULÁRIO
# =============================================================================

def render_sidebar():
    st.sidebar.title("🛠️ Painel i-PLAN")
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
    
    # =========================================================================
    # CORREÇÃO: Carrega o histórico completo de todos os anos para o PDF
    # =========================================================================
    historico_completo = {}
    for ano_h in anos:
        dados_ano_h = load_respostas(ano_h)
        if dados_ano_h: # Só adiciona se houver respostas salvas para aquele ano
            historico_completo[str(ano_h)] = dados_ano_h
    # =========================================================================

    # Geração Dinâmica do PDF na Sidebar passando o historico_completo
    try:
        pdf_buffer = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa, all_data=historico_completo)
        st.sidebar.download_button(
            label="📥Relatório PDF",
            data=pdf_buffer.getvalue(),
            file_name=f"Relatorio_iPLAN_{ano_sel}.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.sidebar.error(f"Erro ao gerar PDF para download: {e}")
    
    if st.sidebar.button("🔄 Zerar Questionário"):
        with get_connection() as conn:
            conn.execute("DELETE FROM respostas WHERE ano = ?", (ano_sel,))
            conn.commit()
        
        # Limpa o session_state para desmarcar todos os widgets (radio, checkbox, etc)
        # Filtramos as chaves que terminam com o ano de referência para não afetar configurações globais
        for key in list(st.session_state.keys()):
            if key.endswith(f"_{ano_sel}"):
                del st.session_state[key]
                
        st.rerun()
        
    return total_pts, res_data, ano_sel

def mostrar_formulario_plan():
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

    st.title(f"📊 Auditoria i-Plan - {ano_sel}")
    
    # 1. Criamos as abas normalmente
    aba_quest, aba_graf = st.tabs(["📋 Questionário", "📈 Gráficos"])
    
    # 2. SEPARADOS: Criamos a lógica dos gráficos isolada aqui em cima
    with aba_graf:
        st.subheader("📊 Evolução dos Resultados — Série Histórica")
        st.write("Acompanhe o desempenho da pontuação total acumulada ao longo dos anos:")
        
        # Aqui montamos o gráfico em Plotly para a tela do Streamlit (já que o ReportLab é só pro PDF)
        anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
        valores_serie = []
        
        # Carrega os dados para o gráfico da tela
        for a in anos_serie:
            dados_ano_h = load_respostas(a)
            soma_ano = sum(float(item.get("pontos", 0)) for k, item in dados_ano_h.items() if not k.startswith("COM_"))
            valores_serie.append(soma_ano)
            
        import plotly.express as px
        fig = px.bar(
            x=[str(a) for a in anos_serie], 
            y=valores_serie,
            labels={'x': 'Ano de Referência', 'y': 'Pontuação Total'},
            range_y=[0, 1000]
        )
        fig.update_traces(marker_color='#1b4f72')
        st.plotly_chart(fig, use_container_width=True)
        
    # 3. O SEGREDO: Abrimos a aba de questionário e DEIXAMOS ELA ABERTA. 
    # Todo o resto do seu arquivo gigante que vem abaixo vai cair automaticamente dentro dela!
    with aba_quest:
        # --- SEÇÃO 1: AUDIÊNCIAS PÚBLICAS ---
        st.header("1.0 Audiências Públicas")
        
        # O RESTO DO SEU ARQUIVO SEGUE AQUI PARA BAIXO NORMALMENTE...
        
        # =============================================================================
        # QUESITO 1.0 • PLANO DIRETOR MUNICIPAL (MODELO PADRONIZADO iPLAN)
        # =============================================================================
        with st.container(key=f"container_bloco_iplan_1_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.0 - Existência e Vigência do Plano Diretor Municipal", expanded=True):
                st.subheader("1.0 • Plano Diretor Municipal")
                st.write(
                    "**O município possui Plano Diretor aprovado por Lei Municipal e atualizado "
                    "conforme as diretrizes do Estatuto da Cidade (Lei Federal nº 10.257/2001)?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.0' para registrar.*")

                # Dicionário com Mapeamento de Opções e Pontuações do iPLAN (Máx 10.0 pts)
                opcoes_10 = {
                    "Selecione...": 0.0,
                    "Sim, aprovado e atualizado há menos de 10 anos (10 pts)": 10.0,
                    "Sim, mas desatualizado há mais de 10 anos (05 pts)": 5.0,
                    "Não possui Plano Diretor (00 pts)": 0.0
                }

                # Estado inicial / persistente
                d10 = res_data.get("1.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_10 = d10.get("valor", "Selecione...")

                # Trata migração de legado caso no banco esteja salvo apenas texto simples
                if v_salvo_10 == "Sim":
                    v_salvo_10 = "Sim, aprovado e atualizado há menos de 10 anos (10 pts)"
                elif v_salvo_10 == "Desatualizado":
                    v_salvo_10 = "Sim, mas desatualizado há mais de 10 anos (05 pts)"
                elif v_salvo_10 == "Não":
                    v_salvo_10 = "Não possui Plano Diretor (00 pts)"

                evidencia_10_salva = d10.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_10 = f"r_iplan_10_{ano_sel}"
                chave_link_10 = f"l_iplan_10_txt_{ano_sel}"
                chave_coment_10 = f"coment_1.0_{ano_sel}"  # Chave padrão do bloco_comentarios

                c10_1, c10_2 = st.columns([1, 1])
                with c10_1:
                    lista_opcoes_10 = list(opcoes_10.keys())
                    idx_10 = lista_opcoes_10.index(v_salvo_10) if v_salvo_10 in lista_opcoes_10 else 0

                    val_radio_10 = st.radio(
                        "Selecione a situação do Plano Diretor:",
                        options=lista_opcoes_10,
                        index=idx_10,
                        key=chave_radio_10
                    )

                with c10_2:
                    link_10 = st.text_area(
                        "Link de Evidência / Lei do Plano Diretor (1.0):",
                        value=evidencia_10_salva,
                        key=chave_link_10,
                        placeholder="Insira o link oficial da lei do Plano Diretor ou Diário Oficial...",
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
                if st.button("💾 Salvar Quesito 1.0", key=f"btn_salvar_iplan_1_0_{ano_sel}", type="primary"):
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

                    # Validação de novos links para acionar o modal de verificação
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
        # QUESITO 1.1 • INSTRUMENTOS DE PLANEJAMENTO URBANO (MODELO PADRONIZADO iPLAN)
        # =============================================================================
        with st.container(key=f"container_bloco_iplan_1_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.1 - Legislação Complementar ao Plano Diretor", expanded=True):
                st.subheader("1.1 • Legislação Urbana Complementar")
                st.write(
                    "**Assinale quais das seguintes leis e instrumentos de planejamento urbano "
                    "estão instituídos e em vigor no município:**"
                )
                st.caption("ℹ *Marque as opções aplicáveis, preencha o link das leis e clique em 'Salvar Quesito 1.1'.*")

                # Mapeamento de Instrumentos e Pontuações (Soma Máxima = 10.0 pts)
                instrumentos_11 = {
                    "Lei de Uso e Ocupação do Solo (Zonamento) (3.0 pts)": 3.0,
                    "Código de Obras e Edificações (2.5 pts)": 2.5,
                    "Plano de Mobilidade Urbana / Transporte (2.5 pts)": 2.5,
                    "Lei de Parcelamento do Solo Urbano (2.0 pts)": 2.0
                }

                # Estado inicial / persistente
                d11 = res_data.get("1.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                
                # Tratamento seguro da lista de marcados recuperada do banco
                raw_valor_11 = d11.get("valor", "[]")
                try:
                    lista_salva_11 = ast.literal_eval(raw_valor_11) if isinstance(raw_valor_11, str) else raw_valor_11
                    if not isinstance(lista_salva_11, list):
                        lista_salva_11 = []
                except Exception:
                    lista_salva_11 = []

                evidencia_11_salva = d11.get("link", "")

                # Chaves fixas por componente e ano
                chave_link_11 = f"l_iplan_11_txt_{ano_sel}"
                chave_coment_11 = f"coment_1.1_{ano_sel}"

                c11_1, c11_2 = st.columns([1, 1])
                
                with c11_1:
                    st.write("**Selecione os instrumentos vigentes:**")
                    itens_selecionados_11 = []
                    pts_calculados_11 = 0.0

                    for item_nome, item_pts in instrumentos_11.items():
                        # Verifica se o item estava marcado anteriormente
                        chk_inicial = item_nome in lista_salva_11
                        chk_val = st.checkbox(
                            item_nome,
                            value=chk_inicial,
                            key=f"chk_iplan_1_1_{item_nome}_{ano_sel}"
                        )
                        if chk_val:
                            itens_selecionados_11.append(item_nome)
                            pts_calculados_11 += item_pts

                with c11_2:
                    link_11 = st.text_area(
                        "Link de Evidência / Leis Urbanísticas (1.1):",
                        value=evidencia_11_salva,
                        key=chave_link_11,
                        placeholder="Insira o link oficial do Portal da Transparência, Legislação ou Repositório...",
                        height=130
                    )
                    placeholder_links_11 = st.empty()
                    links_11_visuais = re.findall(REGEX_PURE_URL, link_11 or "")
                    if links_11_visuais:
                        placeholder_links_11.markdown("**🔗 Links ativos:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_11_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.1", key=f"btn_salvar_iplan_1_1_{ano_sel}", type="primary"):
                    val_str_11 = str(itens_selecionados_11)
                    lnk_val = link_11.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_11, d11.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp(
                        qid="1.1",
                        valor=val_str_11,
                        pontos=pts_calculados_11,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.1"] = {
                        "valor": val_str_11,
                        "pontos": pts_calculados_11,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_11_salva or "")]

                    if lnk_val != evidencia_11_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
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
        # QUESITO 1.2 • DIA E HORÁRIO DAS AUDIÊNCIAS PÚBLICAS (MODELO PADRONIZADO iPLAN)
        # =============================================================================
        with st.container(key=f"container_bloco_iplan_1_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.2 - Dia e Horário de Realização das Audiências Públicas", expanded=True):
                st.subheader("1.2 • Dia e Horário das Audiências Públicas de Planejamento Urbano")
                st.write(
                    "**Assinale os dias e horários em que são realizadas as audiências públicas "
                    "para debates de planos, leis de zoneamento ou projetos urbanísticos:**"
                )
                st.caption("ℹ *Marque os horários praticados, insira o link das atas/editais e clique em 'Salvar Quesito 1.2'.*")

                # Mapeamento de Opções e Pontuações (Máximo acumulado = 4.0 pts)
                horarios_12 = {
                    "Dia de semana em horário comercial (ex: 8h às 18h) – 0,0 pt": 0.0,
                    "Dia de semana após horário comercial (ex: após às 18h) – 2,0 pts": 2.0,
                    "Aos sábados, domingos e feriados – 2,0 pts": 2.0
                }

                # Estado inicial / persistente
                d12 = res_data.get("1.2") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                # Tratamento seguro da lista de marcados recuperada do banco
                raw_valor_12 = d12.get("valor", "[]")
                try:
                    lista_salva_12 = ast.literal_eval(raw_valor_12) if isinstance(raw_valor_12, str) else raw_valor_12
                    if not isinstance(lista_salva_12, list):
                        lista_salva_12 = []
                except Exception:
                    lista_salva_12 = []

                evidencia_12_salva = d12.get("link", "")

                # Chaves fixas por componente e ano
                chave_link_12 = f"l_iplan_12_txt_{ano_sel}"
                chave_coment_12 = f"coment_1.2_{ano_sel}"

                c12_1, c12_2 = st.columns([1, 1])

                with c12_1:
                    st.write("**Selecione os períodos utilizados:**")
                    itens_selecionados_12 = []
                    pts_calculados_12 = 0.0

                    for item_nome, item_pts in horarios_12.items():
                        chk_inicial = item_nome in lista_salva_12
                        chk_val = st.checkbox(
                            item_nome,
                            value=chk_inicial,
                            key=f"chk_iplan_1_2_{item_nome}_{ano_sel}"
                        )
                        if chk_val:
                            itens_selecionados_12.append(item_nome)
                            pts_calculados_12 += item_pts

                    # Limita a pontuação acumulada ao teto do quesito (4.0 pts)
                    if pts_calculados_12 > 4.0:
                        pts_calculados_12 = 4.0

                with c12_2:
                    link_12 = st.text_area(
                        "Link de Evidência / Editais e Atas de Audiências (1.2):",
                        value=evidencia_12_salva,
                        key=chave_link_12,
                        placeholder="Insira o link oficial do diário oficial, convocatórias ou atas de audiência...",
                        height=130
                    )
                    placeholder_links_12 = st.empty()
                    links_12_visuais = re.findall(REGEX_PURE_URL, link_12 or "")
                    if links_12_visuais:
                        placeholder_links_12.markdown("**🔗 Links ativos:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_12_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.2", key=f"btn_salvar_iplan_1_2_{ano_sel}", type="primary"):
                    val_str_12 = str(itens_selecionados_12)
                    lnk_val = link_12.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_12, d12.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp(
                        qid="1.2",
                        valor=val_str_12,
                        pontos=pts_calculados_12,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.2"] = {
                        "valor": val_str_12,
                        "pontos": pts_calculados_12,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_12_salva or "")]

                    if lnk_val != evidencia_12_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
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
        # QUESITO 1.3 • TRANSCRIÇÃO DAS AUDIÊNCIAS (MODELO PADRONIZADO iPLAN)
        # =============================================================================
        with st.container(key=f"container_bloco_iplan_1_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.3 - Transcrição de Audiências Públicas", expanded=True):
                st.subheader("1.3 • Transcrição de Audiências Públicas")
                st.write(
                    "**As audiências públicas são transcritas em atas ou outro documento de registro "
                    "das demandas e sugestões apresentadas pela participação popular?**"
                )
                st.caption("ℹ *Selecione a opção aplicável, informe o link de comprovação e clique em 'Salvar Quesito 1.3'.*")

                # Mapeamento de Opções e Pontuações (Quesito de Avaliação Qualitativa sem atribuição direta de pontos nesta etapa)
                opc13 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Estado inicial / persistente
                d13 = res_data.get("1.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_13 = d13.get("valor", "Selecione...")
                evidencia_13_salva = d13.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_13 = f"r_iplan_13_{ano_sel}"
                chave_link_13 = f"l_iplan_13_txt_{ano_sel}"
                chave_coment_13 = f"coment_1.3_{ano_sel}"

                c13_1, c13_2 = st.columns([1, 1])

                with c13_1:
                    lista_opcoes_13 = list(opc13.keys())
                    idx13 = lista_opcoes_13.index(val_salvo_13) if val_salvo_13 in opc13 else 0

                    sel_1_3 = st.radio(
                        "Selecione a opção para o Quesito 1.3:",
                        options=lista_opcoes_13,
                        index=idx13,
                        key=chave_radio_13
                    )

                with c13_2:
                    link_1_3 = st.text_area(
                        "Link de Evidência / Transcrições e Atas (1.3):",
                        value=evidencia_13_salva,
                        key=chave_link_13,
                        placeholder="Insira o link com os registros, atas ou transcrições das audiências públicas...",
                        height=130
                    )
                    placeholder_links_13 = st.empty()
                    links_13_visuais = re.findall(REGEX_PURE_URL, link_1_3 or "")
                    if links_13_visuais:
                        placeholder_links_13.markdown("**🔗 Links ativos:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_13_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.3", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.3", key=f"btn_salvar_iplan_1_3_{ano_sel}", type="primary"):
                    val_selecionado_13 = sel_1_3
                    pts_calculados_13 = opc13.get(val_selecionado_13, 0.0)
                    lnk_val = link_1_3.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_13, d13.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp(
                        qid="1.3",
                        valor=val_selecionado_13,
                        pontos=pts_calculados_13,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.3"] = {
                        "valor": val_selecionado_13,
                        "pontos": pts_calculados_13,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_13_salva or "")]

                    if lnk_val != evidencia_13_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_13 = d13.get("pontos", 0.0)
                status_txt_13 = " (Aguardando seleção)" if sel_1_3 == "Selecione..." else ""
                
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.3: {pts_atuais_13:.1f} pontos{status_txt_13}</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.3", st.session_state.get(f"links_pendentes_1_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.3.1 • LINK DO INSTRUMENTO DE REGISTRO (MODELO PADRONIZADO iPLAN)
        # =============================================================================
        with st.container(key=f"container_bloco_iplan_1_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.3.1 - Página Eletrônica do Instrumento de Registro", expanded=True):
                st.subheader("1.3.1 • Página Eletrônica do Instrumento de Registro")
                st.write(
                    "**Página eletrônica (link) do instrumento (Ata ou documento de registro de audiências). "
                    "Informe a URL oficial ou digite 'XYZ' se não estiver disponível:**"
                )
                st.caption("ℹ *Informe a URL principal do instrumento, adicione evidências complementares se necessário e clique em 'Salvar Quesito 1.3.1'.*")

                # Estado inicial / persistente
                d131 = res_data.get("1.3.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                valor_salvo_131 = d131.get("valor", "")
                evidencia_131_salva = d131.get("link", "")

                # Chaves fixas por componente e ano
                chave_input_131 = f"i_iplan_131_{ano_sel}"
                chave_link_131 = f"l_iplan_131_txt_{ano_sel}"
                chave_coment_131 = f"coment_1.3.1_{ano_sel}"

                c131_1, c131_2 = st.columns([1, 1])

                with c131_1:
                    v131_input = st.text_input(
                        "URL Principal / Instrumento de Registro (1.3.1):",
                        value=valor_salvo_131,
                        key=chave_input_131,
                        placeholder="https://... ou XYZ se indisponível"
                    )
                    
                    # Cálculo em tempo de renderização para feedback visual
                    v131_clean_pre = v131_input.strip().upper() if v131_input else ""
                    pts_previsto_131 = 0.0 if (v131_clean_pre == "XYZ" or not v131_input.strip()) else 3.0

                with c131_2:
                    link_evidencia_131 = st.text_area(
                        "Link/Evidência Adicional (1.3.1):",
                        value=evidencia_131_salva,
                        key=chave_link_131,
                        placeholder="Links adicionais ou observações sobre o acervo de atas...",
                        height=95
                    )
                    placeholder_links_131 = st.empty()
                    links_131_visuais = re.findall(REGEX_PURE_URL, link_evidencia_131 or "")
                    if links_131_visuais:
                        placeholder_links_131.markdown("**🔗 Links ativos:** " + " | ".join([f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_131_visuais]))

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios("1.3.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.3.1", key=f"btn_salvar_iplan_1_3_1_{ano_sel}", type="primary"):
                    val_input_131 = v131_input.strip()
                    val_clean_131 = val_input_131.upper()
                    
                    # Regra de negócio da pontuação: 0.0 para XYZ / Vazio; 3.0 para links/textos válidos
                    pts_calculados_131 = 0.0 if (val_clean_131 == "XYZ" or not val_input_131) else 3.0
                    lnk_val = link_evidencia_131.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_131, d131.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp(
                        qid="1.3.1",
                        valor=val_input_131,
                        pontos=pts_calculados_131,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.3.1"] = {
                        "valor": val_input_131,
                        "pontos": pts_calculados_131,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação (considera input principal e evidência)
                    texto_completo_links = f"{val_input_131} {lnk_val}"
                    texto_antigo_links = f"{valor_salvo_131} {evidencia_131_salva}"

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, texto_completo_links or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, texto_antigo_links or "")]

                    if (val_input_131 != valor_salvo_131 or lnk_val != evidencia_131_salva) and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_131 = d131.get("pontos", 0.0)
                cor_txt_131 = "#28a745" if pts_atuais_131 > 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_131}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.3.1: {pts_atuais_131:.1f} / 3.0 pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.3.1", st.session_state.get(f"links_pendentes_1_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.4 • ELEMENTOS DE PLANEJAMENTO DAS AUDIÊNCIAS (MODELO PADRONIZADO iPLAN)
        # =============================================================================
        with st.container(key=f"container_bloco_iplan_1_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.4 - Elementos de Planejamento e Organização", expanded=True):
                st.subheader("1.4 • Elementos de Planejamento e Organização")
                st.write("**Assinale os elementos considerados no processo de planejamento e organização das audiências públicas:**")
                st.caption("ℹ *Selecione os itens aplicáveis, informe o link de evidência, adicione seus comentários e clique em 'Salvar Quesito 1.4'.*")

                elementos = {
                    "Estabelecimento da Pauta – 0,5": 0.5,
                    "Disponibilização prévia de material de apoio a respeito dos temas a serem debatidos – 0,5": 0.5,
                    "Convocação contendo o dia, horário e o local através dos jornais, das rádios, do Portal da Prefeitura e outras plataformas digitais. Ex.: Instagram, Facebook etc. – 0,5": 0.5,
                    "Planejamento logístico. Ex.: localização do ambiente, acomodações adequadas aos participantes, regulação e testagem dos equipamentos eletrônicos (som, vídeo e iluminação), verificação dos equipamentos relacionados a transmissão das audiências etc. – 1,0": 1.0,
                    "Indicação de mediador qualificado – 0,5": 0.5,
                    "Estabelecimento da abordagem de interação – 0,5": 0.5,
                    "Definição de mecanismos de avaliação – 0,5": 0.5,
                    "Elaboração e divulgação do Relatório contendo a análise das demandas e sugestões coletadas – 1,0": 1.0
                }

                # Estado inicial / persistente
                d14 = res_data.get("1.4") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                try:
                    lista_salva_14 = ast.literal_eval(d14.get("valor", "[]"))
                    if not isinstance(lista_salva_14, list):
                        lista_salva_14 = []
                except Exception:
                    lista_salva_14 = []

                evidencia_14_salva = d14.get("link", "")

                # Chaves fixas por componente e ano
                chave_link_14 = f"l_iplan_14_txt_{ano_sel}"
                chave_coment_14 = f"coment_1.4_{ano_sel}"

                c14_1, c14_2 = st.columns([1, 1])

                with c14_1:
                    selecionados_14 = []
                    pts_previsto_14 = 0.0
                    for item_nome, peso_item in elementos.items():
                        is_checked = item_nome in lista_salva_14
                        chk = st.checkbox(
                            item_nome,
                            value=is_checked,
                            key=f"chk_iplan_1_4_{item_nome}_{ano_sel}"
                        )
                        if chk:
                            selecionados_14.append(item_nome)
                            pts_previsto_14 += peso_item

                with c14_2:
                    link_evidencia_14 = st.text_area(
                        "Link/Evidência (1.4):",
                        value=evidencia_14_salva,
                        key=chave_link_14,
                        placeholder="Insira os links e documentos comprobatórios dos elementos de planejamento...",
                        height=220
                    )
                    placeholder_links_14 = st.empty()
                    links_14_visuais = re.findall(REGEX_PURE_URL, link_evidencia_14 or "")
                    if links_14_visuais:
                        placeholder_links_14.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("1.4", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.4", key=f"btn_salvar_iplan_1_4_{ano_sel}", type="primary"):
                    str_selecionados_14 = str(selecionados_14)
                    lnk_val = link_evidencia_14.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_14, d14.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="1.4",
                        valor=str_selecionados_14,
                        pontos=pts_previsto_14,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.4"] = {
                        "valor": str_selecionados_14,
                        "pontos": pts_previsto_14,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_14_salva or "")]

                    if lnk_val != evidencia_14_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 1.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_14 = d14.get("pontos", 0.0)
                cor_txt_14 = "#28a745" if pts_atuais_14 > 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_14}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.4: {pts_atuais_14:.1f} / 5.0 pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.4 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.4", st.session_state.get(f"links_pendentes_1_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESTÃO 2.0 - REALIZAÇÃO DA CONSULTA (PADRÃO REFINADO iPLAN)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_i_plan_2_0_{ano_sel}", border=True):
            with st.expander(f"📌 Questão 2.0 • Consulta Pública Online ({ano_sel})", expanded=True):
                st.subheader("2.0 • Consulta Pública (I-PLAN)")
                st.write("**Houve a realização de consulta pública online para coleta de sugestões para a elaboração do PPA 2026-2029?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 2.0'.*")

                # Mapeamento com a pontuação formatada ao lado do rótulo da alternativa
                opcoes20 = {
                    "Selecione...": 0.0, 
                    "Sim – 6,0 pontos": 6.0, 
                    "Não – 0,0 ponto": 0.0
                }

                # Resgate seguro e mapeamento dos valores legados/existentes
                d20 = res_data.get("2.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_20 = str(d20.get("valor", "Selecione..."))
                if "Sim" in val_salvo_20:
                    val_salvo_20 = "Sim – 6,0 pontos"
                elif "Não" in val_salvo_20:
                    val_salvo_20 = "Não – 0,0 ponto"
                else:
                    val_salvo_20 = "Selecione..."

                evidencia_20_salva = d20.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_20 = f"r_iplan_2_0_{ano_sel}"
                chave_link_20 = f"txt_i_plan_20_{ano_sel}"
                chave_coment_20 = f"coment_2.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_20 = list(opcoes20.keys())
                    idx20 = lista_opcoes_20.index(val_salvo_20)
                    
                    val_selecionado_20 = st.radio(
                        "Selecione 2.0:",
                        options=lista_opcoes_20,
                        index=idx20,
                        key=chave_radio_20,
                        label_visibility="collapsed"
                    )
                    pts_previstos_20 = opcoes20[val_selecionado_20]

                with col2:
                    link_evidencia_20 = st.text_area(
                        "Link/Evidência (2.0):",
                        value=evidencia_20_salva,
                        key=chave_link_20,
                        placeholder="Insira os links e documentos comprobatórios da consulta pública...",
                        height=130
                    )
                    placeholder_links_20 = st.empty()
                    links_2_0_visuais = re.findall(REGEX_PURE_URL, link_evidencia_20 or "")
                    if links_2_0_visuais:
                        placeholder_links_20.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_2_0_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("2.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 2.0", key=f"btn_salvar_iplan_2_0_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_20.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_20, d20.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="2.0",
                        valor=val_selecionado_20,
                        pontos=pts_previstos_20,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["2.0"] = {
                        "valor": val_selecionado_20,
                        "pontos": pts_previstos_20,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_20_salva or "")]

                    if lnk_val != evidencia_20_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 2.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_20 = d20.get("pontos", 0.0)
                val_atual_20 = d20.get("valor", "Selecione...")

                if val_atual_20 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_20 = "#28a745" if pts_atuais_20 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_20}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 2.0: {pts_atuais_20:.1f} / 6.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 2.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 2.1 • GLOSSÁRIO NA CONSULTA PÚBLICA DO PPA
        # =============================================================================
        with st.container(key=f"container_bloco_glossario_ppa_2_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Questão 2.1 • Glossário Explicativo na Consulta Pública do PPA ({ano_sel})", expanded=True):
                st.subheader("2.1 • Glossário e Linguagem Cidadã")
                st.write("**Na consulta pública online de elaboração do Plano Plurianual (PPA) foi disponibilizado glossário explicando os objetivos, como contribuir, em linguagem clara e simples?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 2.1'.*")

                # Mapeamento oficial com pontuação ao lado do rótulo
                opcoes21 = {
                    "Selecione...": 0.0, 
                    "Sim – 2,0 pontos": 2.0, 
                    "Não – 0,0 ponto": 0.0
                }

                # Resgate seguro e mapeamento dos valores legados/existentes
                d21 = res_data.get("2.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_21 = str(d21.get("valor", "Selecione..."))
                if "Sim" in val_salvo_21:
                    val_salvo_21 = "Sim – 2,0 pontos"
                elif "Não" in val_salvo_21:
                    val_salvo_21 = "Não – 0,0 ponto"
                else:
                    val_salvo_21 = "Selecione..."

                evidencia_21_salva = d21.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_21 = f"r_iplan_2_1_{ano_sel}"
                chave_link_21 = f"txt_i_plan_21_{ano_sel}"
                chave_coment_21 = f"coment_2.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_21 = list(opcoes21.keys())
                    idx21 = lista_opcoes_21.index(val_salvo_21) if val_salvo_21 in lista_opcoes_21 else 0
                    
                    val_selecionado_21 = st.radio(
                        "Selecione 2.1:",
                        options=lista_opcoes_21,
                        index=idx21,
                        key=chave_radio_21,
                        label_visibility="collapsed"
                    )
                    pts_previstos_21 = opcoes21[val_selecionado_21]

                with col2:
                    link_evidencia_21 = st.text_area(
                        "Link/Evidência (2.1):",
                        value=evidencia_21_salva,
                        key=chave_link_21,
                        placeholder="Insira os links e documentos comprobatórios do glossário...",
                        height=130
                    )
                    placeholder_links_21 = st.empty()
                    links_2_1_visuais = re.findall(REGEX_PURE_URL, link_evidencia_21 or "")
                    if links_2_1_visuais:
                        placeholder_links_21.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_2_1_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("2.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 2.1", key=f"btn_salvar_iplan_2_1_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_21.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_21, d21.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="2.1",
                        valor=val_selecionado_21,
                        pontos=pts_previstos_21,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["2.1"] = {
                        "valor": val_selecionado_21,
                        "pontos": pts_previstos_21,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_21_salva or "")]

                    if lnk_val != evidencia_21_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_21 = d21.get("pontos", 0.0)
                val_atual_21 = d21.get("valor", "Selecione...")

                if val_atual_21 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_21 = "#28a745" if pts_atuais_21 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_21}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 2.1: {pts_atuais_21:.1f} / 2.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 2.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("2.1", st.session_state.get(f"links_pendentes_2_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 3.0 - DIAGNÓSTICO PRÉVIO AO PLANEJAMENTO (PADRÃO REFINADO iPLAN)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_diagnostico_3_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.0 • Diagnóstico Prévio ao Planejamento ({ano_sel})", expanded=True):
                st.subheader("3.0 • Diagnóstico Prévio")
                st.write("**Além das audiências públicas, a Prefeitura realizou diagnóstico anteriormente ao planejamento, através do levantamento formal de seus problemas, necessidades e deficiências?**")
                st.caption("⚠️ **Obs:** *Os Planos Municipais Setoriais (Educação, Saúde, Saneamento Básico etc.) somente podem ser considerados se neles houver evidências do levantamento formal dos problemas.*")

                # Mapeamento oficial com pontuação ao lado do rótulo
                opcoes30 = {
                    "Selecione...": 0.0, 
                    "Sim – 0,0 ponto": 0.0, 
                    "Não – 0,0 ponto": 0.0
                }

                # Resgate seguro e mapeamento dos valores legados/existentes
                d30 = res_data.get("3.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_30 = str(d30.get("valor", "Selecione..."))
                if "Sim" in val_salvo_30:
                    val_salvo_30 = "Sim – 0,0 ponto"
                elif "Não" in val_salvo_30:
                    val_salvo_30 = "Não – 0,0 ponto"
                else:
                    val_salvo_30 = "Selecione..."

                evidencia_30_salva = d30.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_30 = f"r_iplan_3_0_{ano_sel}"
                chave_link_30 = f"txt_i_plan_30_{ano_sel}"
                chave_coment_30 = f"coment_3.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_30 = list(opcoes30.keys())
                    idx30 = lista_opcoes_30.index(val_salvo_30) if val_salvo_30 in lista_opcoes_30 else 0
                    
                    val_selecionado_30 = st.radio(
                        "Selecione 3.0:",
                        options=lista_opcoes_30,
                        index=idx30,
                        key=chave_radio_30,
                        label_visibility="collapsed"
                    )
                    pts_previstos_30 = opcoes30[val_selecionado_30]

                with col2:
                    link_evidencia_30 = st.text_area(
                        "Link/Evidência (3.0):",
                        value=evidencia_30_salva,
                        key=chave_link_30,
                        placeholder="Insira os links e documentos comprobatórios do diagnóstico prévio...",
                        height=130
                    )
                    placeholder_links_30 = st.empty()
                    links_3_0_visuais = re.findall(REGEX_PURE_URL, link_evidencia_30 or "")
                    if links_3_0_visuais:
                        placeholder_links_30.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_3_0_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("3.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 3.0", key=f"btn_salvar_iplan_3_0_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_30.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_30, d30.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="3.0",
                        valor=val_selecionado_30,
                        pontos=pts_previstos_30,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["3.0"] = {
                        "valor": val_selecionado_30,
                        "pontos": pts_previstos_30,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_30_salva or "")]

                    if lnk_val != evidencia_30_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 3.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_30 = d30.get("pontos", 0.0)
                val_atual_30 = d30.get("valor", "Selecione...")

                if val_atual_30 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação no Quesito 3.0: {pts_atuais_30:.1f} pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 3.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 3.1 - ALINHAMENTO COM PLANOS FEDERAIS/ESTADUAIS (PADRÃO REFINADO iPLAN)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_abordagem_diagnostico_3_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Questão 3.1 • Alinhamento com Planos Federais/Estaduais ({ano_sel})", expanded=True):
                st.subheader("3.1 • Alinhamento com Planos Federais/Estaduais")
                st.write("**3.1 A abordagem do diagnóstico levou em conta algum plano do governo federal e/ou estadual?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 3.1'.*")

                # Mapeamento oficial com pontuação ao lado do rótulo
                opcoes31 = {
                    "Selecione...": 0.0, 
                    "Sim – 14,0 pontos": 14.0, 
                    "Não – 0,0 ponto": 0.0
                }

                # Resgate seguro e mapeamento dos valores legados/existentes
                d31 = res_data.get("3.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_31 = str(d31.get("valor", "Selecione..."))
                if "Sim" in val_salvo_31:
                    val_salvo_31 = "Sim – 14,0 pontos"
                elif "Não" in val_salvo_31:
                    val_salvo_31 = "Não – 0,0 ponto"
                else:
                    val_salvo_31 = "Selecione..."

                evidencia_31_salva = d31.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_31 = f"r_iplan_3_1_{ano_sel}"
                chave_link_31 = f"txt_i_plan_31_{ano_sel}"
                chave_coment_31 = f"coment_3.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_31 = list(opcoes31.keys())
                    idx31 = lista_opcoes_31.index(val_salvo_31) if val_salvo_31 in lista_opcoes_31 else 0
                    
                    val_selecionado_31 = st.radio(
                        "Selecione 3.1:",
                        options=lista_opcoes_31,
                        index=idx31,
                        key=chave_radio_31,
                        label_visibility="collapsed"
                    )
                    pts_previstos_31 = opcoes31[val_selecionado_31]

                with col2:
                    link_evidencia_31 = st.text_area(
                        "Link/Evidência (3.1):",
                        value=evidencia_31_salva,
                        key=chave_link_31,
                        placeholder="Insira os links e documentos comprobatórios do alinhamento com planos...",
                        height=130
                    )
                    placeholder_links_31 = st.empty()
                    links_3_1_visuais = re.findall(REGEX_PURE_URL, link_evidencia_31 or "")
                    if links_3_1_visuais:
                        placeholder_links_31.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_3_1_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("3.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 3.1", key=f"btn_salvar_iplan_3_1_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_31.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_31, d31.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="3.1",
                        valor=val_selecionado_31,
                        pontos=pts_previstos_31,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["3.1"] = {
                        "valor": val_selecionado_31,
                        "pontos": pts_previstos_31,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_31_salva or "")]

                    if lnk_val != evidencia_31_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_31 = d31.get("pontos", 0.0)
                val_atual_31 = d31.get("valor", "Selecione...")

                if val_atual_31 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_31 = "#28a745" if pts_atuais_31 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_31}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 3.1: {pts_atuais_31:.1f} / 14.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 3.1.1 • DESCRIÇÃO DOS PROGRAMAS UTILIZADOS (CONDICIONAL AO 3.1)
        # -----------------------------------------------------------------------------
        val_31_parent = res_data.get("3.1", {}).get("valor", "")
        if "Sim" in str(val_31_parent):
            with st.container(key=f"container_bloco_i_plan_3_1_1_{ano_sel}", border=True):
                with st.expander(f"📝 Questão 3.1.1 • Descrição dos Programas Utilizados ({ano_sel})", expanded=True):
                    st.subheader("3.1.1 • Detalhamento dos Programas")
                    st.write("**Descreva os programas utilizados:**")
                    st.caption("ℹ *Preencha a descrição dos programas, adicione seus comentários e clique em 'Salvar Questão 3.1.1'.*")

                    # Resgate seguro dos dados da questão 3.1.1
                    d311 = res_data.get("3.1.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                    desc_311_salva = d311.get("valor", "")

                    # Chaves fixas por componente e ano
                    chave_txt_311 = f"txt_i_plan_311_{ano_sel}"
                    chave_coment_311 = f"coment_3.1.1_{ano_sel}"

                    desc_programas_311 = st.text_area(
                        "Descrição dos programas:",
                        value=desc_311_salva,
                        key=chave_txt_311,
                        placeholder="Informe os detalhes dos programas federais e/ou estaduais utilizados no diagnóstico...",
                        height=130,
                        label_visibility="collapsed"
                    )

                    # Renderiza o bloco de comentários padronizado
                    bloco_comentarios("3.1.1", res_data, ano_sel)

                    # -----------------------------------------------------------------
                    # BOTÃO DE SALVAMENTO MANUAL
                    # -----------------------------------------------------------------
                    if st.button("💾 Salvar Questão 3.1.1", key=f"btn_salvar_iplan_3_1_1_{ano_sel}", type="primary"):
                        txt_val = desc_programas_311.strip()

                        # Captura o comentário do session_state
                        comentario_para_salvar = st.session_state.get(chave_coment_311, d311.get("comentario", ""))

                        # Salva no banco de dados (Questão descritiva possui 0.0 pontos e sem link obrigatório)
                        save_resp(
                            qid="3.1.1",
                            valor=txt_val,
                            pontos=0.0,
                            link="",
                            comentario=comentario_para_salvar
                        )

                        # Atualiza o dicionário local res_data
                        res_data["3.1.1"] = {
                            "valor": txt_val,
                            "pontos": 0.0,
                            "link": "",
                            "comentario": comentario_para_salvar
                        }

                        st.cache_data.clear()
                        st.toast("Descrição e comentários da Questão 3.1.1 salvos com sucesso!", icon="✅")
                        st.rerun()

                    # Resumo dinâmico de preenchimento
                    val_atual_311 = d311.get("valor", "")
                    if not val_atual_311.strip():
                        st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(
                            "<span style='color:#28a745; font-weight:bold;'>"
                            "✅ Questão 3.1.1 preenchida e gravada</span>",
                            unsafe_allow_html=True
                        )

        # -----------------------------------------------------------------------------
        # QUESITO 3.2 • DIAGNÓSTICO PRÉVIO DOS PROGRAMAS DO PPA (PADRÃO REFINADO iPLAN)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_i_plan_3_2_{ano_sel}", border=True):
            with st.expander(f"📌 Questão 3.2 • Diagnóstico Prévio do PPA ({ano_sel})", expanded=True):
                st.subheader("3.2 • Diagnóstico Prévio")
                st.write("**Os programas do PPA 2026-2029 tiveram diagnóstico prévio?**")
                st.caption("ℹ *Obs: Os Planos Municipais Setoriais (Educação, Saúde, Saneamento Básico etc.) somente podem ser considerados se neles houver evidências do levantamento formal dos problemas.*")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 3.2'.*")

                # Mapeamento oficial com pontuação padronizada ao lado do rótulo
                opcoes32 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os programas PPA – 10,0 pontos": 10.0,
                    "Sim, para a maior parte dos programas do PPA – 5,0 pontos": 5.0,
                    "Sim, para a menor parte dos programas do PPA – 3,0 pontos": 3.0,
                    "Não – 0,0 ponto": 0.0
                }

                # Resgate seguro e mapeamento dos valores existentes/legados
                d32 = res_data.get("3.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_32 = str(d32.get("valor", "Selecione..."))
                if "todos" in val_salvo_32.lower():
                    val_salvo_32 = "Sim, para todos os programas PPA – 10,0 pontos"
                elif "maior parte" in val_salvo_32.lower():
                    val_salvo_32 = "Sim, para a maior parte dos programas do PPA – 5,0 pontos"
                elif "menor parte" in val_salvo_32.lower():
                    val_salvo_32 = "Sim, para a menor parte dos programas do PPA – 3,0 pontos"
                elif "Não" in val_salvo_32:
                    val_salvo_32 = "Não – 0,0 ponto"
                else:
                    val_salvo_32 = "Selecione..."

                evidencia_32_salva = d32.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_32 = f"r_iplan_3_2_{ano_sel}"
                chave_link_32 = f"txt_i_plan_32_{ano_sel}"
                chave_coment_32 = f"coment_3.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_32 = list(opcoes32.keys())
                    idx32 = lista_opcoes_32.index(val_salvo_32) if val_salvo_32 in lista_opcoes_32 else 0

                    val_selecionado_32 = st.radio(
                        "Selecione 3.2:",
                        options=lista_opcoes_32,
                        index=idx32,
                        key=chave_radio_32,
                        label_visibility="collapsed"
                    )
                    pts_previstos_32 = opcoes32[val_selecionado_32]

                with col2:
                    link_evidencia_32 = st.text_area(
                        "Link/Evidência (3.2):",
                        value=evidencia_32_salva,
                        key=chave_link_32,
                        placeholder="Insira os links e documentos comprobatórios do diagnóstico prévio do PPA...",
                        height=140
                    )
                    placeholder_links_32 = st.empty()
                    links_3_2_visuais = re.findall(REGEX_PURE_URL, link_evidencia_32 or "")
                    if links_3_2_visuais:
                        placeholder_links_32.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_3_2_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("3.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 3.2", key=f"btn_salvar_iplan_3_2_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_32.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_32, d32.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="3.2",
                        valor=val_selecionado_32,
                        pontos=pts_previstos_32,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["3.2"] = {
                        "valor": val_selecionado_32,
                        "pontos": pts_previstos_32,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_32_salva or "")]

                    if lnk_val != evidencia_32_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 3.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_32 = d32.get("pontos", 0.0)
                val_atual_32 = d32.get("valor", "Selecione...")

                if val_atual_32 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_32 = "#28a745" if pts_atuais_32 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_32}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 3.2: {pts_atuais_32:.1f} / 10.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 3.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.2", st.session_state.get(f"links_pendentes_3_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = False


        # -----------------------------------------------------------------------------
        # QUESITO 4.0 • METAS FÍSICAS E FINANCEIRAS NO PPA (PADRÃO REFINADO iPLAN)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_metas_indicadores_4_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Questão 4.0 • Metas Físicas e Financeiras no PPA ({ano_sel})", expanded=True):
                st.subheader("4.0 • Metas e Indicadores")
                st.write("**Há o estabelecimento de metas físicas e financeiras de forma anual nas ações previstas no PPA?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 4.0'.*")

                # Mapeamento oficial com pontuação padronizada ao lado do rótulo
                opcoes40 = {
                    "Selecione...": 0.0,
                    "Sim, com metas físicas e financeiras – 10,0 pontos": 10.0,
                    "Sim, apenas financeiras – 5,0 pontos": 5.0,
                    "Sim, apenas físicas – 5,0 pontos": 5.0,
                    "Não houve o estabelecimento de metas anuais – 0,0 ponto": 0.0
                }

                # Resgate seguro e mapeamento dos valores existentes/legados
                d40 = res_data.get("4.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_40 = str(d40.get("valor", "Selecione..."))
                if "físicas e financeiras" in val_salvo_40.lower():
                    val_salvo_40 = "Sim, com metas físicas e financeiras – 10,0 pontos"
                elif "apenas financeiras" in val_salvo_40.lower():
                    val_salvo_40 = "Sim, apenas financeiras – 5,0 pontos"
                elif "apenas físicas" in val_salvo_40.lower():
                    val_salvo_40 = "Sim, apenas físicas – 5,0 pontos"
                elif "não houve" in val_salvo_40.lower() or "não" in val_salvo_40.lower():
                    val_salvo_40 = "Não houve o estabelecimento de metas anuais – 0,0 ponto"
                else:
                    val_salvo_40 = "Selecione..."

                evidencia_40_salva = d40.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_40 = f"r_iplan_4_0_{ano_sel}"
                chave_link_40 = f"txt_i_plan_40_{ano_sel}"
                chave_coment_40 = f"coment_4.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_40 = list(opcoes40.keys())
                    idx40 = lista_opcoes_40.index(val_salvo_40) if val_salvo_40 in lista_opcoes_40 else 0

                    val_selecionado_40 = st.radio(
                        "Selecione 4.0:",
                        options=lista_opcoes_40,
                        index=idx40,
                        key=chave_radio_40,
                        label_visibility="collapsed"
                    )
                    pts_previstos_40 = opcoes40[val_selecionado_40]

                with col2:
                    link_evidencia_40 = st.text_area(
                        "Link/Evidência (4.0):",
                        value=evidencia_40_salva,
                        key=chave_link_40,
                        placeholder="Insira os links e documentos comprobatórios das metas físicas e financeiras...",
                        height=140
                    )
                    placeholder_links_40 = st.empty()
                    links_40_visuais = re.findall(REGEX_PURE_URL, link_evidencia_40 or "")
                    if links_40_visuais:
                        placeholder_links_40.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_40_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("4.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.0", key=f"btn_salvar_iplan_4_0_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_40.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_40, d40.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="4.0",
                        valor=val_selecionado_40,
                        pontos=pts_previstos_40,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["4.0"] = {
                        "valor": val_selecionado_40,
                        "pontos": pts_previstos_40,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_40_salva or "")]

                    if lnk_val != evidencia_40_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 4.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_40 = d40.get("pontos", 0.0)
                val_atual_40 = d40.get("valor", "Selecione...")

                if val_atual_40 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_40 = "#28a745" if pts_atuais_40 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_40}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.0: {pts_atuais_40:.1f} / 10.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 4.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.1 • ARTICULAÇÃO DE PROGRAMAS FINALÍSTICOS (PADRÃO REFINADO iPLAN)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_articulacao_programas_4_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Questão 4.1 • Articulação de Programas Finalísticos ({ano_sel})", expanded=True):
                st.subheader("4.1 • Articulação de Programas Finalísticos")
                st.write("**Os programas finalísticos articulam um conjunto de ações que concorrem para um objetivo comum preestabelecido, visando à solução de um problema ou necessidade da sociedade?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 4.1'.*")

                # Mapeamento oficial com pontuação padronizada ao lado do rótulo
                opcoes41 = {
                    "Selecione...": 0.0,
                    "Todos os programas finalísticos – 15,0 pontos": 15.0,
                    "A maior parte dos programas finalísticos – 10,0 pontos": 10.0,
                    "A menor parte dos programas finalísticos – 5,0 pontos": 5.0,
                    "Nenhum programa finalístico – 0,0 ponto": 0.0
                }

                # Resgate seguro e tratamento de legados
                d41 = res_data.get("4.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_41 = str(d41.get("valor", "Selecione..."))
                if "todos os" in val_salvo_41.lower():
                    val_salvo_41 = "Todos os programas finalísticos – 15,0 pontos"
                elif "maior parte" in val_salvo_41.lower():
                    val_salvo_41 = "A maior parte dos programas finalísticos – 10,0 pontos"
                elif "menor parte" in val_salvo_41.lower():
                    val_salvo_41 = "A menor parte dos programas finalísticos – 5,0 pontos"
                elif "nenhum" in val_salvo_41.lower():
                    val_salvo_41 = "Nenhum programa finalístico – 0,0 ponto"
                else:
                    val_salvo_41 = "Selecione..."

                evidencia_41_salva = d41.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_41 = f"r_iplan_4_1_{ano_sel}"
                chave_link_41 = f"txt_i_plan_41_{ano_sel}"
                chave_coment_41 = f"coment_4.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_41 = list(opcoes41.keys())
                    idx41 = lista_opcoes_41.index(val_salvo_41) if val_salvo_41 in lista_opcoes_41 else 0

                    val_selecionado_41 = st.radio(
                        "Selecione 4.1:",
                        options=lista_opcoes_41,
                        index=idx41,
                        key=chave_radio_41,
                        label_visibility="collapsed"
                    )
                    pts_previstos_41 = opcoes41[val_selecionado_41]

                with col2:
                    link_evidencia_41 = st.text_area(
                        "Link/Evidência (4.1):",
                        value=evidencia_41_salva,
                        key=chave_link_41,
                        placeholder="Insira os links e documentos comprobatórios sobre a articulação dos programas...",
                        height=140
                    )
                    placeholder_links_41 = st.empty()
                    links_41_visuais = re.findall(REGEX_PURE_URL, link_evidencia_41 or "")
                    if links_41_visuais:
                        placeholder_links_41.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_41_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("4.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.1", key=f"btn_salvar_iplan_4_1_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_41.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_41, d41.get("comentario", ""))

                    # Salva no banco de dados
                    save_resp(
                        qid="4.1",
                        valor=val_selecionado_41,
                        pontos=pts_previstos_41,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["4.1"] = {
                        "valor": val_selecionado_41,
                        "pontos": pts_previstos_41,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal de verificação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_41_salva or "")]

                    if lnk_val != evidencia_41_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_41 = d41.get("pontos", 0.0)
                val_atual_41 = d41.get("valor", "Selecione...")

                if val_atual_41 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_41 = "#28a745" if pts_atuais_41 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_41}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.1: {pts_atuais_41:.1f} / 15.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 4.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.1", st.session_state.get(f"links_pendentes_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.1.1 • AVALIAÇÃO DE PROGRAMAS FINALÍSTICOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_avaliacao_programas_4_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.1.1 - Avaliação da Implementação dos Programas Finalísticos ({ano_sel})", expanded=True):
                st.subheader("4.1.1 • Avaliação de Programas Finalísticos")
                st.write("**Houve avaliação da implementação dos programas finalísticos em relação a seus indicadores, objetivos e metas?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 4.1.1'.*")

                # Mapeamento oficial com pontuação padronizada no rótulo
                opcoes_411 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os programas finalísticos monitorados – 10,0 pontos": 10.0,
                    "Sim, para a maior parte dos programas finalísticos monitorados – 7,0 pontos": 7.0,
                    "Sim, para a menor parte dos programas finalísticos monitorados – 3,0 pontos": 3.0,
                    "Não houve avaliação – 0,0 ponto": 0.0
                }

                # Resgate seguro dos dados e tratamento de versões legadas
                d411 = res_data.get("4.1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_411 = str(d411.get("valor", "Selecione..."))
                if "todos os" in val_salvo_411.lower():
                    val_salvo_411 = "Sim, para todos os programas finalísticos monitorados – 10,0 pontos"
                elif "maior parte" in val_salvo_411.lower():
                    val_salvo_411 = "Sim, para a maior parte dos programas finalísticos monitorados – 7,0 pontos"
                elif "menor parte" in val_salvo_411.lower():
                    val_salvo_411 = "Sim, para a menor parte dos programas finalísticos monitorados – 3,0 pontos"
                elif "não houve" in val_salvo_411.lower():
                    val_salvo_411 = "Não houve avaliação – 0,0 ponto"
                else:
                    val_salvo_411 = "Selecione..."

                evidencia_411_salva = d411.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_411 = f"r_4_1_1_{ano_sel}"
                chave_link_411 = f"t_4_1_1_{ano_sel}"
                chave_coment_411 = f"coment_4.1.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_411 = list(opcoes_411.keys())
                    idx411 = lista_opcoes_411.index(val_salvo_411) if val_salvo_411 in lista_opcoes_411 else 0

                    val_selecionado_411 = st.radio(
                        "Selecione 4.1.1:",
                        options=lista_opcoes_411,
                        index=idx411,
                        key=chave_radio_411,
                        label_visibility="collapsed"
                    )
                    pts_previstos_411 = opcoes_411[val_selecionado_411]

                with col2:
                    link_evidencia_411 = st.text_area(
                        "Link/Evidência (4.1.1):",
                        value=evidencia_411_salva,
                        key=chave_link_411,
                        placeholder="Insira os links e documentos comprobatórios referentes à avaliação dos programas...",
                        height=140
                    )
                    placeholder_links_411 = st.empty()
                    links_411_visuais = re.findall(REGEX_PURE_URL, link_evidencia_411 or "")
                    if links_411_visuais:
                        placeholder_links_411.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_411_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("4.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.1.1", key=f"btn_salvar_4_1_1_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_411.strip()

                    # Captura o comentário atualizado via session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_411, d411.get("comentario", ""))

                    # Salva no banco de dados / estado global
                    save_resp(
                        qid="4.1.1",
                        valor=val_selecionado_411,
                        pontos=pts_previstos_411,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza a estrutura local res_data
                    res_data["4.1.1"] = {
                        "valor": val_selecionado_411,
                        "pontos": pts_previstos_411,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_411_salva or "")]

                    if lnk_val != evidencia_411_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 4.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação
                pts_atuais_411 = d411.get("pontos", 0.0)
                val_atual_411 = d411.get("valor", "Selecione...")

                if val_atual_411 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_411 = "#28a745" if pts_atuais_411 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_411}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.1.1: {pts_atuais_411:.1f} / 10.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS (Executado fora do container do componente)
        if st.session_state.get(f"gatilho_modal_4_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.1.1", st.session_state.get(f"links_pendentes_4_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.1.1.1 • RELATÓRIO ANUAL DE AVALIAÇÃO DO PPA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_relatorio_avaliacao_4_1_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.1.1.1 - Relatório Anual de Avaliação do PPA ({ano_sel})", expanded=True):
                st.subheader("4.1.1.1 • Relatório Anual de Avaliação")
                st.write("**Houve a elaboração de Relatório Anual de Avaliação dos programas finalísticos do PPA?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 4.1.1.1'.*")

                # Mapeamento oficial com pontuação padronizada no rótulo (Pontuação máxima: 7,0)
                opcoes_4111 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os programas finalísticos do PPA – 7,0 pontos": 7.0,
                    "Sim, para a maior parte dos programas finalísticos do PPA – 4,0 pontos": 4.0,
                    "Sim, para a menor parte dos programas finalísticos do PPA – 1,0 ponto": 1.0,
                    "Não houve execução do Relatório Anual de Avaliação do PPA – 0,0 ponto": 0.0
                }

                # Resgate seguro dos dados e tratamento de versões legadas
                d4111 = res_data.get("4.1.1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_4111 = str(d4111.get("valor", "Selecione..."))
                if "todos os" in val_salvo_4111.lower():
                    val_salvo_4111 = "Sim, para todos os programas finalísticos do PPA – 7,0 pontos"
                elif "maior parte" in val_salvo_4111.lower():
                    val_salvo_4111 = "Sim, para a maior parte dos programas finalísticos do PPA – 4,0 pontos"
                elif "menor parte" in val_salvo_4111.lower():
                    val_salvo_4111 = "Sim, para a menor parte dos programas finalísticos do PPA – 1,0 ponto"
                elif "não houve" in val_salvo_4111.lower():
                    val_salvo_4111 = "Não houve execução do Relatório Anual de Avaliação do PPA – 0,0 ponto"
                else:
                    val_salvo_4111 = "Selecione..."

                evidencia_4111_salva = d4111.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_4111 = f"r_4_1_1_1_{ano_sel}"
                chave_link_4111 = f"t_4_1_1_1_{ano_sel}"
                chave_coment_4111 = f"coment_4.1.1.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_4111 = list(opcoes_4111.keys())
                    idx4111 = lista_opcoes_4111.index(val_salvo_4111) if val_salvo_4111 in lista_opcoes_4111 else 0

                    val_selecionado_4111 = st.radio(
                        "Selecione 4.1.1.1:",
                        options=lista_opcoes_4111,
                        index=idx4111,
                        key=chave_radio_4111,
                        label_visibility="collapsed"
                    )
                    pts_previstos_4111 = opcoes_4111[val_selecionado_4111]

                with col2:
                    link_evidencia_4111 = st.text_area(
                        "Link/Evidência (4.1.1.1):",
                        value=evidencia_4111_salva,
                        key=chave_link_4111,
                        placeholder="Insira os links dos relatórios anuais de avaliação do PPA publicados...",
                        height=140
                    )
                    placeholder_links_4111 = st.empty()
                    links_4111_visuais = re.findall(REGEX_PURE_URL, link_evidencia_4111 or "")
                    if links_4111_visuais:
                        placeholder_links_4111.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_4111_visuais]
                            )
                        )

                # Renderiza o bloco de comentários padronizado
                bloco_comentarios("4.1.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.1.1.1", key=f"btn_salvar_4_1_1_1_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_4111.strip()

                    # Captura o comentário atualizado via session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_4111, d4111.get("comentario", ""))

                    # Salva no banco de dados / estado global
                    save_resp(
                        qid="4.1.1.1",
                        valor=val_selecionado_4111,
                        pontos=pts_previstos_4111,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualiza a estrutura local res_data
                    res_data["4.1.1.1"] = {
                        "valor": val_selecionado_4111,
                        "pontos": pts_previstos_4111,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_4111_salva or "")]

                    if lnk_val != evidencia_4111_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 4.1.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação
                pts_atuais_4111 = d4111.get("pontos", 0.0)
                val_atual_4111 = d4111.get("valor", "Selecione...")

                if val_atual_4111 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_4111 = "#28a745" if pts_atuais_4111 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_4111}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.1.1.1: {pts_atuais_4111:.1f} / 7.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS (Executado fora do container do componente)
        if st.session_state.get(f"gatilho_modal_4_1_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.1.1.1", st.session_state.get(f"links_pendentes_4_1_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.1.1.1.1 • ASPECTOS ANALISADOS NA AVALIAÇÃO DO PPA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_aspectos_ppa_4_1_1_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.1.1.1.1 - Aspectos Analisados no Acompanhamento ({ano_sel})", expanded=True):
                st.subheader("4.1.1.1.1 • Aspectos Analisados no Acompanhamento")
                st.write("**Assinale os aspectos analisados no processo de acompanhamento e avaliação do PPA:**")
                st.caption("ℹ *Marque os aspectos aplicáveis, forneça o link/evidência, inclua seus comentários e clique no botão 'Salvar Questão 4.1.1.1.1'.*")

                # Mapeamento oficial de aspectos com pontuação (Soma máxima: 60,0)
                aspectos_41111 = {
                    "Percepção de coerência, em todos os programas, do necessário encadeamento lógico-causal entre os insumos que mobiliza, os produtos/ações que gera, os resultados que provoca e os impactos esperados pela sociedade – 20,0 pontos": 20.0,
                    "Análise quanto a se Programas, Metas e Ações são mensurados por um ou mais indicadores próprios e adequados, e que permitam aferir a situação atual (aquela que se pretende modificar) e os avanços obtidos ao longo da execução do programa (em direção àquela mudança pretendida) – 20,0 pontos": 20.0,
                    "Avaliação entre os produtos ofertados à população e as reais demandas da sociedade, coletadas, principalmente, nas audiências públicas realizadas e nos demais instrumentos de diagnóstico dos problemas, necessidades e deficiências do município – 20,0 pontos": 20.0,
                    "Outros – 0,0 ponto": 0.0
                }

                # Resgate seguro e desserialização dos dados da questão
                d41111 = res_data.get("4.1.1.1.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_raw_41111 = d41111.get("valor", "[]")
                try:
                    lista_salva_41111 = ast.literal_eval(val_raw_41111) if isinstance(val_raw_41111, str) else val_raw_41111
                    if not isinstance(lista_salva_41111, list):
                        lista_salva_41111 = []
                except Exception:
                    lista_salva_41111 = []

                evidencia_41111_salva = d41111.get("link", "")

                # Chaves padronizadas por ano de exercício
                chave_link_41111 = f"t_4_1_1_1_1_{ano_sel}"
                chave_coment_41111 = f"coment_4.1.1.1.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    st.markdown("**Selecione os itens verificados:**")
                    selecionados_41111 = []
                    pts_calculados_41111 = 0.0

                    # Renderização dinâmica das opções com identificação parcial para dados legados
                    for idx, (asp_texto, asp_pontos) in enumerate(aspectos_41111.items()):
                        key_chk = f"chk_41111_{idx}_{ano_sel}"
                        
                        # Verifica marcadores salvos no banco ou no estado
                        is_checked_default = any(
                            (asp_texto == item) or (asp_texto[:25].lower() in str(item).lower())
                            for item in lista_salva_41111
                        )

                        chk_valor = st.checkbox(
                            asp_texto,
                            value=is_checked_default,
                            key=key_chk
                        )

                        if chk_valor:
                            selecionados_41111.append(asp_texto)
                            pts_calculados_41111 += asp_pontos

                with col2:
                    link_evidencia_41111 = st.text_area(
                        "Link/Evidência (4.1.1.1.1):",
                        value=evidencia_41111_salva,
                        key=chave_link_41111,
                        placeholder="Insira os links dos documentos que comprovam a análise dos aspectos do PPA...",
                        height=180
                    )
                    placeholder_links_41111 = st.empty()
                    links_41111_visuais = re.findall(REGEX_PURE_URL, link_evidencia_41111 or "")
                    if links_41111_visuais:
                        placeholder_links_41111.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_41111_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("4.1.1.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.1.1.1.1", key=f"btn_salvar_4_1_1_1_1_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_41111.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_41111, d41111.get("comentario", ""))
                    str_selecionados = str(selecionados_41111)

                    # Gravação no banco de dados e atualização local
                    save_resp(
                        qid="4.1.1.1.1",
                        valor=str_selecionados,
                        pontos=pts_calculados_41111,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    res_data["4.1.1.1.1"] = {
                        "valor": str_selecionados,
                        "pontos": pts_calculados_41111,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Validação de alteração em links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_41111_salva or "")]

                    if lnk_val != evidencia_4111_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_1_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opções, evidências e comentários da Questão 4.1.1.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status e totalização de pontos
                pts_atuais_41111 = float(d41111.get("pontos", 0.0))
                val_atual_41111 = d41111.get("valor", "[]")

                if val_atual_41111 == "[]" or not selecionados_41111:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nítida ausência de seleção de aspectos (0,0 pontos)</span>", unsafe_allow_html=True)
                else:
                    cor_txt_41111 = "#28a745" if pts_atuais_41111 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_41111}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.1.1.1.1: {pts_atuais_41111:.1f} / 60.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_4_1_1_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.1.1.1.1", st.session_state.get(f"links_pendentes_4_1_1_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_1_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.1.1.2 • PUBLICAÇÃO DOS RESULTADOS DA AVALIAÇÃO DO PPA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_publicacao_resultados_4_1_1_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.1.1.2 - Publicação dos Resultados da Avaliação do PPA ({ano_sel})", expanded=True):
                st.subheader("4.1.1.2 • Publicação dos Resultados")
                st.write("**Houve publicação dos resultados da avaliação dos programas finalísticos do PPA?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 4.1.1.2'.*")

                # Mapeamento oficial com pontuação padronizada no rótulo (Pontuação máxima: 4,0)
                opcoes_4112 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os programas finalísticos avaliados do PPA – 4,0 pontos": 4.0,
                    "Sim, para a maior parte dos programas finalísticos avaliados – 3,0 pontos": 3.0,
                    "Sim, para a menor parte dos programas finalísticos avaliados – 1,0 ponto": 1.0,
                    "Não – 0,0 ponto": 0.0
                }

                # Resgate seguro dos dados e tratamento de versões legadas
                d4112 = res_data.get("4.1.1.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_4112 = str(d4112.get("valor", "Selecione..."))
                if "todos os" in val_salvo_4112.lower():
                    val_salvo_4112 = "Sim, para todos os programas finalísticos avaliados do PPA – 4,0 pontos"
                elif "maior parte" in val_salvo_4112.lower():
                    val_salvo_4112 = "Sim, para a maior parte dos programas finalísticos avaliados – 3,0 pontos"
                elif "menor parte" in val_salvo_4112.lower():
                    val_salvo_4112 = "Sim, para a menor parte dos programas finalísticos avaliados – 1,0 ponto"
                elif "não" in val_salvo_4112.lower():
                    val_salvo_4112 = "Não – 0,0 ponto"
                else:
                    val_salvo_4112 = "Selecione..."

                evidencia_4112_salva = d4112.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_4112 = f"r_4_1_1_2_{ano_sel}"
                chave_link_4112 = f"t_4_1_1_2_{ano_sel}"
                chave_coment_4112 = f"coment_4.1.1.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_4112 = list(opcoes_4112.keys())
                    idx4112 = lista_opcoes_4112.index(val_salvo_4112) if val_salvo_4112 in lista_opcoes_4112 else 0

                    val_selecionado_4112 = st.radio(
                        "Selecione 4.1.1.2:",
                        options=lista_opcoes_4112,
                        index=idx4112,
                        key=chave_radio_4112,
                        label_visibility="collapsed"
                    )
                    pts_previstos_4112 = opcoes_4112[val_selecionado_4112]

                with col2:
                    link_evidencia_4112 = st.text_area(
                        "Link/Evidência (4.1.1.2):",
                        value=evidencia_4112_salva,
                        key=chave_link_4112,
                        placeholder="Insira os links dos locais onde os resultados da avaliação do PPA foram publicados...",
                        height=140
                    )
                    placeholder_links_4112 = st.empty()
                    links_4112_visuais = re.findall(REGEX_PURE_URL, link_evidencia_4112 or "")
                    if links_4112_visuais:
                        placeholder_links_4112.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_4112_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("4.1.1.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.1.1.2", key=f"btn_salvar_4_1_1_2_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_4112.strip()

                    # Captura o comentário do estado ou do repositório local
                    comentario_para_salvar = st.session_state.get(chave_coment_4112, d4112.get("comentario", ""))

                    # Gravação no banco de dados / estado global
                    save_resp(
                        qid="4.1.1.2",
                        valor=val_selecionado_4112,
                        pontos=pts_previstos_4112,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Regra de encadeamento/dependência: Se marcar "Não", reseta a subquestão descendente 4.1.1.2.1
                    if "não" in val_selecionado_4112.lower():
                        save_resp("4.1.1.2.1", "Não aplicável", 0.0, "", "")
                        res_data["4.1.1.2.1"] = {"valor": "Não aplicável", "pontos": 0.0, "link": "", "comentario": ""}

                    # Atualiza a estrutura local res_data
                    res_data["4.1.1.2"] = {
                        "valor": val_selecionado_4112,
                        "pontos": pts_previstos_4112,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_4112_salva or "")]

                    if lnk_val != evidencia_4112_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 4.1.1.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação
                pts_atuais_4112 = d4112.get("pontos", 0.0)
                val_atual_4112 = d4112.get("valor", "Selecione...")

                if val_atual_4112 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_4112 = "#28a745" if pts_atuais_41112 > 0.0 else "#dc3545" if "não" in val_atual_4112.lower() else "#28a745"
                    st.markdown(
                        f"<span style='color:{cor_txt_4112}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.1.1.2: {pts_atuais_4112:.1f} / 4.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_4_1_1_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.1.1.2", st.session_state.get(f"links_pendentes_4_1_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_1_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.1.1.2.1 • LINK DE DIVULGAÇÃO DOS RESULTADOS DO PPA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_divulgacao_link_4_1_1_2_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.1.1.2.1 - Link de Divulgação dos Resultados ({ano_sel})", expanded=True):
                st.subheader("4.1.1.2.1 • Link de Divulgação")
                st.write("**Página eletrônica (link) de divulgação dos resultados (informe XYZ se não disponível):**")
                st.caption("ℹ *Informe o link direto para a publicação dos resultados, adicione observações nos comentários e clique em 'Salvar Questão 4.1.1.2.1'.*")

                # Resgate seguro dos dados da questão
                d41121 = res_data.get("4.1.1.2.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                if not isinstance(d41121, dict):
                    d41121 = {"valor": str(d41121), "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_41121 = d41121.get("valor", "") or d41121.get("link", "")
                
                # Chaves fixas por componente e ano
                chave_input_41121 = f"q41121_{ano_sel}"
                chave_coment_41121 = f"coment_4.1.1.2.1_{ano_sel}"

                # Campo para entrada da URL / 'XYZ'
                link_input_41121 = st.text_input(
                    "Link URL (PPA):",
                    value=v_salvo_41121,
                    key=chave_input_41121,
                    placeholder="https://... ou XYZ se não houver link disponível",
                    label_visibility="collapsed"
                )

                # Renderização e pré-visualização de links válidos detectados
                placeholder_links_41121 = st.empty()
                links_41121_visuais = re.findall(REGEX_PURE_URL, link_input_41121 or "")
                if links_41121_visuais:
                    placeholder_links_41121.markdown(
                        "**🔗 Links ativos detectados:** " + " | ".join(
                            [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_41121_visuais]
                        )
                    )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("4.1.1.2.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.1.1.2.1", key=f"btn_salvar_4_1_1_2_1_{ano_sel}", type="primary"):
                    val_lnk_41121 = link_input_41121.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_41121, d41121.get("comentario", ""))

                    # Gravação no banco de dados e atualização local
                    save_resp(
                        qid="4.1.1.2.1",
                        valor=val_lnk_41121,
                        pontos=0.0,
                        link=val_lnk_41121,
                        comentario=comentario_para_salvar
                    )

                    res_data["4.1.1.2.1"] = {
                        "valor": val_lnk_41121,
                        "pontos": 0.0,
                        "link": val_lnk_41121,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação e acionamento do modal de checagem de links
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_lnk_41121 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_41121 or "")]

                    if val_lnk_41121 != v_salvo_41121 and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_1_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_1_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Link de divulgação e comentários da Questão 4.1.1.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status informativo do quesito
                val_atual_41121 = d41121.get("valor", "")
                if not val_atual_41121:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Quesito informativo aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        "<span style='color:#17a2b8; font-weight:bold;'>"
                        "ℹ️ Quesito de caráter exclusivamente informativo (0,0 pontos)</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_4_1_1_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.1.1.2.1", st.session_state.get(f"links_pendentes_4_1_1_2_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_1_2_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.2 • COERÊNCIA DOS INDICADORES COM AS METAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_coerencia_indicadores_4_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.2 - Coerência dos Indicadores com as Metas ({ano_sel})", expanded=True):
                st.subheader("4.2 • Coerência dos Indicadores")
                st.write("**Os indicadores são mensuráveis e estão coerentes com as metas físico-financeiras estabelecidas?**")
                st.caption("ℹ *Selecione a opção desejada, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 4.2'.*")

                # Mapeamento oficial com pontuação padronizada no rótulo (Pontuação máxima: 25,0)
                opcoes_42 = {
                    "Selecione...": 0.0,
                    "Todos os indicadores do PPA – 25,0 pontos": 25.0,
                    "A maior parte dos indicadores – 17,0 pontos": 17.0,
                    "A menor parte dos indicadores – 8,0 pontos": 8.0,
                    "Nenhum indicador – 0,0 ponto": 0.0
                }

                # Resgate seguro dos dados e tratamento de versões legadas
                d42 = res_data.get("4.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_42 = str(d42.get("valor", "Selecione..."))
                if "todos os" in val_salvo_42.lower():
                    val_salvo_42 = "Todos os indicadores do PPA – 25,0 pontos"
                elif "maior parte" in val_salvo_42.lower():
                    val_salvo_42 = "A maior parte dos indicadores – 17,0 pontos"
                elif "menor parte" in val_salvo_42.lower():
                    val_salvo_42 = "A menor parte dos indicadores – 8,0 pontos"
                elif "nenhum" in val_salvo_42.lower():
                    val_salvo_42 = "Nenhum indicador – 0,0 ponto"
                else:
                    val_salvo_42 = "Selecione..."

                evidencia_42_salva = d42.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_42 = f"r_4_2_{ano_sel}"
                chave_link_42 = f"t_4_2_{ano_sel}"
                chave_coment_42 = f"coment_4.2_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_42 = list(opcoes_42.keys())
                    idx42 = lista_opcoes_42.index(val_salvo_42) if val_salvo_42 in lista_opcoes_42 else 0

                    val_selecionado_42 = st.radio(
                        "Selecione 4.2:",
                        options=lista_opcoes_42,
                        index=idx42,
                        key=chave_radio_42,
                        label_visibility="collapsed"
                    )
                    pts_previstos_42 = opcoes_42[val_selecionado_42]

                with col2:
                    link_evidencia_42 = st.text_area(
                        "Link/Evidência (4.2):",
                        value=evidencia_42_salva,
                        key=chave_link_42,
                        placeholder="Insira os links dos relatórios ou documentos que comprovam a mensurabilidade dos indicadores...",
                        height=140
                    )
                    placeholder_links_42 = st.empty()
                    links_42_visuais = re.findall(REGEX_PURE_URL, link_evidencia_42 or "")
                    if links_42_visuais:
                        placeholder_links_42.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_42_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("4.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.2", key=f"btn_salvar_4_2_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_42.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_42, d42.get("comentario", ""))

                    # Persistência no banco / banco de dados
                    save_resp(
                        qid="4.2",
                        valor=val_selecionado_42,
                        pontos=pts_previstos_42,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização na estrutura global local
                    res_data["4.2"] = {
                        "valor": val_selecionado_42,
                        "pontos": pts_previstos_42,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_42_salva or "")]

                    if lnk_val != evidencia_42_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 4.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição estilizada do impacto da pontuação
                pts_atuais_42 = d42.get("pontos", 0.0)
                val_atual_42 = d42.get("valor", "Selecione...")

                if val_atual_42 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento</span>", unsafe_allow_html=True)
                else:
                    cor_txt_42 = "#28a745" if pts_atuais_42 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_42}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.2: {pts_atuais_42:.1f} / 25.0 pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.2", st.session_state.get(f"links_pendentes_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 4.3 • PLANOS SETORIAIS INCORPORADOS NO PPA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_planos_setoriais_4_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.3 - Planos Setoriais Incorporados no PPA ({ano_sel})", expanded=True):
                st.subheader("4.3 • Planos Setoriais")
                st.write("**Assinale os Planos Setoriais que foram incorporados no Plano Plurianual (PPA):**")
                st.caption("ℹ *Selecione os planos aplicáveis, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 4.3'.*")

                # Tabela oficial de pontuação dos planos setoriais
                planos_pesos_43 = {
                    "Plano Diretor – 00": 0.0,
                    "Plano Municipal da Educação – 2,5": 2.5,
                    "Plano Municipal pela Primeira Infância – 00": 0.0,
                    "Plano Municipal da Saúde – 2,5": 2.5,
                    "Plano de Mobilidade Urbana – 00": 0.0,
                    "Plano de Saneamento Básico – 2,5": 2.5,
                    "Plano de Resíduos Sólidos – 2,5": 2.5,
                    "Plano de Contingência Municipal – PLANCON de Defesa Civil – 2,5": 2.5,
                    "Plano Diretor de Tecnologia da Informação – 2,5": 2.5,
                    "Não incorporou nenhum dos planos acima – -10 (perde 10 pontos)": -10.0
                }

                # Resgate seguro dos dados
                d43 = res_data.get("4.3") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                try:
                    lista_salva_43 = ast.literal_eval(d43.get("valor", "[]"))
                    if not isinstance(lista_salva_43, list):
                        lista_salva_43 = []
                except Exception:
                    lista_salva_43 = []

                evidencia_43_salva = d43.get("link", "")

                # Chaves fixas por componente e ano
                chave_link_43 = f"t_4_3_{ano_sel}"
                chave_coment_43 = f"coment_4.3_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_atual_selecao_43 = []
                    for idx, (plano, pt) in enumerate(planos_pesos_43.items()):
                        key_chk = f"chk_43_{idx}_{ano_sel}"
                        is_checked = st.checkbox(
                            plano,
                            value=(plano in lista_salva_43),
                            key=key_chk
                        )
                        if is_checked:
                            lista_atual_selecao_43.append(plano)

                    # Regra de cálculo de pontuação
                    if any("Não incorporou" in p for p in lista_atual_selecao_43):
                        pts_calculados_43 = -10.0
                    else:
                        pts_calculados_43 = sum(planos_pesos_43[p] for p in lista_atual_selecao_43)

                with col2:
                    link_evidencia_43 = st.text_area(
                        "Link/Evidência (4.3):",
                        value=evidencia_43_salva,
                        key=chave_link_43,
                        placeholder="Insira os links dos documentos ou publicações dos planos setoriais incorporados...",
                        height=260
                    )
                    placeholder_links_43 = st.empty()
                    links_43_visuais = re.findall(REGEX_PURE_URL, link_evidencia_43 or "")
                    if links_43_visuais:
                        placeholder_links_43.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_43_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("4.3", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 4.3", key=f"btn_salvar_4_3_{ano_sel}", type="primary"):
                    lnk_val = link_evidencia_43.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_43, d43.get("comentario", ""))

                    # Recálculo definitivo para persistência
                    if any("Não incorporou" in p for p in lista_atual_selecao_43):
                        pts_finais_43 = -10.0
                    else:
                        pts_finais_43 = sum(planos_pesos_43[p] for p in lista_atual_selecao_43)

                    valor_para_salvar = str(lista_atual_selecao_43)

                    # Persistência na base de dados
                    save_resp(
                        qid="4.3",
                        valor=valor_para_salvar,
                        pontos=float(pts_finais_43),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização na estrutura global local
                    res_data["4.3"] = {
                        "valor": valor_para_salvar,
                        "pontos": float(pts_finais_43),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_43_salva or "")]

                    if lnk_val != evidencia_43_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 4.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição estilizada do impacto da pontuação
                pts_atuais_43 = d43.get("pontos", 0.0)

                if not lista_salva_43:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando seleção</span>", unsafe_allow_html=True)
                else:
                    if pts_atuais_43 < 0:
                        cor_txt_43 = "#dc3545"
                        sufixo_txt_43 = " (Penalidade aplicada)"
                    elif pts_atuais_43 > 0:
                        cor_txt_43 = "#28a745"
                        sufixo_txt_43 = ""
                    else:
                        cor_txt_43 = "#6c757d"
                        sufixo_txt_43 = ""

                    st.markdown(
                        f"<span style='color:{cor_txt_43}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 4.3: {pts_atuais_43:.1f} pontos{sufixo_txt_43}</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_4_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.3", st.session_state.get(f"links_pendentes_4_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 5.0 • ESTUDO DE PREVISÃO DE RECEITAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_previsao_receitas_5_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.0 - Estudo de Previsão de Receitas ({ano_sel})", expanded=True):
                st.subheader("5.0 • Previsão de Receitas")
                st.write(
                    "**É realizado estudo/análise para previsão de receitas, no mínimo, anualmente? "
                    "Aplicação de índice inflacionário ao valor arrecadado do exercício anterior NÃO é estudo/análise de previsão de receita.**"
                )
                st.caption("ℹ *Selecione a opção aplicável, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 5.0'.*")

                opcoes_50 = {
                    "Selecione...": 0.0,
                    "Sim – 06": 6.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados
                d50 = res_data.get("5.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                v_salvo_50 = d50.get("valor", "Selecione...")
                evidencia_50_salva = d50.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_50 = f"r_5_0_{ano_sel}"
                chave_link_50 = f"t_5_0_{ano_sel}"
                chave_coment_50 = f"coment_5.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_50 = list(opcoes_50.keys())
                    idx50 = 0
                    if v_salvo_50 in opcoes_50:
                        idx50 = lista_opcoes_50.index(v_salvo_50)
                    elif v_salvo_50:
                        if "Sim" in v_salvo_50:
                            idx50 = lista_opcoes_50.index("Sim – 06")
                        elif "Não" in v_salvo_50:
                            idx50 = lista_opcoes_50.index("Não – 00")

                    sel_5_0 = st.radio(
                        "Selecione 5.0:",
                        options=lista_opcoes_50,
                        index=idx50,
                        key=chave_radio_50,
                        label_visibility="collapsed"
                    )

                with col2:
                    link_evidencia_50 = st.text_area(
                        "Link/Evidência (5.0):",
                        value=evidencia_50_salva,
                        key=chave_link_50,
                        placeholder="Insira os links dos documentos ou estudos de previsão de receitas...",
                        height=130
                    )
                    placeholder_links_50 = st.empty()
                    links_50_visuais = re.findall(REGEX_PURE_URL, link_evidencia_50 or "")
                    if links_50_visuais:
                        placeholder_links_50.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_50_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("5.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 5.0", key=f"btn_salvar_5_0_{ano_sel}", type="primary"):
                    opcao_selecionada_50 = st.session_state.get(chave_radio_50, "Selecione...")
                    pts_finais_50 = opcoes_50.get(opcao_selecionada_50, 0.0)
                    lnk_val = link_evidencia_50.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_50, d50.get("comentario", ""))

                    # Persistência na base de dados
                    save_resp(
                        qid="5.0",
                        valor=opcao_selecionada_50,
                        pontos=float(pts_finais_50),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização na estrutura global local
                    res_data["5.0"] = {
                        "valor": opcao_selecionada_50,
                        "pontos": float(pts_finais_50),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_50_salva or "")]

                    if lnk_val != evidencia_50_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 5.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição estilizada do impacto da pontuação
                pts_atuais_50 = d50.get("pontos", 0.0)
                opcao_salva_exibicao = d50.get("valor", "Selecione...")

                if opcao_salva_exibicao == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando seleção</span>", unsafe_allow_html=True)
                else:
                    cor_txt_50 = "#28a745" if pts_atuais_50 > 0 else "#6c757d"
                    st.markdown(
                        f"<span style='color:{cor_txt_50}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 5.0: {pts_atuais_50:.1f} pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 5.1 • TIPOS DE TRIBUTOS E REPASSES AVALIADOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_tributos_5_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.1 - Tipos de Tributos e Repasses Avaliados ({ano_sel})", expanded=True):
                st.subheader("5.1 • Análise e Estudo da Previsão da Receita")
                st.write("**Assinale os tipos de tributos e repasses/transferências avaliados na análise e estudo da previsão da receita:**")
                st.caption("ℹ *Selecione as opções aplicáveis, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 5.1'.*")

                tribs_51 = {
                    "Imposto sobre a Propriedade Predial e Territorial Urbano (IPTU) – 0,5": 0.5,
                    "Imposto sobre a Transmissão de Bens Imóveis (ITBI) – 0,5": 0.5,
                    "Imposto Sobre Serviços de Qualquer Natureza (ISSQN) – 0,5": 0.5,
                    "Taxas – 0,25": 0.25,
                    "Contribuições – 0,25": 0.25,
                    "Transferências Obrigatórias Recebidas da União. Ex.: FPM, CIDE, ITR, Royalties e FUNDEB. – 01": 1.0,
                    "Transferências Obrigatórias Recebidas do Estado. Ex.: ICMS, IPVA. – 01": 1.0,
                    "Outros - 0,0": 0.0
                }

                # Resgate seguro dos dados
                d51 = res_data.get("5.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                try:
                    lista_salva_51 = ast.literal_eval(d51.get("valor", "[]"))
                    if not isinstance(lista_salva_51, list):
                        lista_salva_51 = []
                except Exception:
                    lista_salva_51 = []

                evidencia_51_salva = d51.get("link", "")

                # Chaves fixas por componente e ano
                chave_link_51 = f"t_5_1_{ano_sel}"
                chave_coment_51 = f"coment_5.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    for idx, (t, pt) in enumerate(tribs_51.items()):
                        key_chk = f"chk_51_{idx}_{ano_sel}"
                        st.checkbox(
                            t,
                            value=t in lista_salva_51,
                            key=key_chk
                        )

                with col2:
                    link_evidencia_51 = st.text_area(
                        "Link/Evidência (5.1):",
                        value=evidencia_51_salva,
                        key=chave_link_51,
                        placeholder="Insira os links dos documentos com os tipos de tributos e repasses avaliados...",
                        height=220
                    )
                    placeholder_links_51 = st.empty()
                    links_51_visuais = re.findall(REGEX_PURE_URL, link_evidencia_51 or "")
                    if links_51_visuais:
                        placeholder_links_51.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_51_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("5.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 5.1", key=f"btn_salvar_5_1_{ano_sel}", type="primary"):
                    sel_51 = []
                    pts_finais_51 = 0.0

                    for idx, (t, pt) in enumerate(tribs_51.items()):
                        key_chk = f"chk_51_{idx}_{ano_sel}"
                        if st.session_state.get(key_chk, False):
                            sel_51.append(t)
                            pts_finais_51 += pt

                    lnk_val = link_evidencia_51.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_51, d51.get("comentario", ""))

                    # Persistência na base de dados
                    save_resp(
                        qid="5.1",
                        valor=str(sel_51),
                        pontos=float(pts_finais_51),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização na estrutura global local
                    res_data["5.1"] = {
                        "valor": str(sel_51),
                        "pontos": float(pts_finais_51),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_51_salva or "")]

                    if lnk_val != evidencia_51_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição estilizada do impacto da pontuação
                pts_atuais_51 = d51.get("pontos", 0.0)
                valor_salvo_raw_51 = d51.get("valor", "[]")

                try:
                    lista_atuais_51 = ast.literal_eval(valor_salvo_raw_51)
                except Exception:
                    lista_atuais_51 = []

                if not lista_atuais_51:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando seleção</span>", unsafe_allow_html=True)
                else:
                    cor_txt_51 = "#28a745" if pts_atuais_51 > 0 else "#6c757d"
                    st.markdown(
                        f"<span style='color:{cor_txt_51}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 5.1: {pts_atuais_51:.2f} pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.1", st.session_state.get(f"links_pendentes_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 5.1.1 • PREVISÃO DE REPASSE DO ICMS ESTADUAL
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_estimativa_icms_5_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.1.1 - Previsão de Repasse do ICMS Estadual ({ano_sel})", expanded=True):
                st.subheader("5.1.1 • Estimativa de Transferências Obrigatórias")
                st.write("**A estimativa de transferências obrigatórias leva em consideração o cálculo de previsão de repasse do ICMS realizado periodicamente pela Fazenda Pública Estadual?**")
                st.caption("ℹ *Selecione uma opção, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 5.1.1'.*")

                opc511 = {
                    "Selecione...": 0.0,
                    "Sim, com reestimativa da receita prevista na LOA no decorrer da execução orçamentária-financeira – 02": 2.0,
                    "Sim, somente para elaborar a LOA – 01": 1.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados
                d511 = res_data.get("5.1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                valor_salvo_511 = d511.get("valor", "Selecione...")
                evidencia_511_salva = d511.get("link", "")

                # Resolução do índice selecionado
                lista_opcoes_511 = list(opc511.keys())
                idx511 = 0
                if valor_salvo_511 in opc511:
                    idx511 = lista_opcoes_511.index(valor_salvo_511)
                elif valor_salvo_511:
                    if "decorrer da execução" in valor_salvo_511:
                        idx511 = lista_opcoes_511.index("Sim, com reestimativa da receita prevista na LOA no decorrer da execução orçamentária-financeira – 02")
                    elif "somente para elaborar" in valor_salvo_511:
                        idx511 = lista_opcoes_511.index("Sim, somente para elaborar a LOA – 01")
                    elif "Não" in valor_salvo_511:
                        idx511 = lista_opcoes_511.index("Não – 00")

                # Chaves fixas por componente e ano
                chave_radio_511 = f"r_5_1_1_{ano_sel}"
                chave_link_511 = f"t_5_1_1_{ano_sel}"
                chave_coment_511 = f"coment_5.1.1_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    sel_5_1_1 = st.radio(
                        "Selecione a opção para o Quesito 5.1.1:",
                        options=lista_opcoes_511,
                        index=idx511,
                        key=chave_radio_511,
                        label_visibility="collapsed"
                    )

                with col2:
                    link_evidencia_511 = st.text_area(
                        "Link/Evidência (5.1.1):",
                        value=evidencia_511_salva,
                        key=chave_link_511,
                        placeholder="Insira os links dos documentos comprobatórios sobre a estimativa do ICMS...",
                        height=130
                    )
                    placeholder_links_511 = st.empty()
                    links_511_visuais = re.findall(REGEX_PURE_URL, link_evidencia_511 or "")
                    if links_511_visuais:
                        placeholder_links_511.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_511_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("5.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 5.1.1", key=f"btn_salvar_5_1_1_{ano_sel}", type="primary"):
                    val_selecionado = st.session_state.get(chave_radio_511, "Selecione...")
                    pts_finais_511 = opc511.get(val_selecionado, 0.0)
                    lnk_val = link_evidencia_511.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_511, d511.get("comentario", ""))

                    # Persistência na base de dados
                    save_resp(
                        qid="5.1.1",
                        valor=val_selecionado,
                        pontos=float(pts_finais_511),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização na estrutura global local
                    res_data["5.1.1"] = {
                        "valor": val_selecionado,
                        "pontos": float(pts_finais_511),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_511_salva or "")]

                    if lnk_val != evidencia_511_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 5.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição estilizada do impacto da pontuação
                pts_atuais_511 = d511.get("pontos", 0.0)
                val_atual_511 = d511.get("valor", "Selecione...")

                if val_atual_511 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando seleção</span>", unsafe_allow_html=True)
                else:
                    cor_txt_511 = "#28a745" if pts_atuais_511 > 0 else "#6c757d"
                    st.markdown(
                        f"<span style='color:{cor_txt_511}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 5.1.1: {pts_atuais_511:.1f} pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_5_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.1.1", st.session_state.get(f"links_pendentes_5_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 6.0 • ITENS QUE A LDO DISPÕE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_itens_ldo_6_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 6.0 - Itens que a LDO Dispõe ({ano_sel})", expanded=True):
                st.subheader("6.0 • Disposições da LDO")
                st.write("**Assinale os itens que a LDO dispõe:**")
                st.caption("ℹ *Selecione os itens correspondentes, informe o link de evidência, adicione seus comentários e clique em 'Salvar Questão 6.0'.*")

                itens_ldo_60 = {
                    "Custos estimados, indicadores e metas físicas que se correlacionam com as ações do governo municipal – 0,5": 0.5,
                    "Critérios para limitação desempenho e movimentação financeira; ressalvados os pagamentos do serviço da dívida, os relativos à inovação e ao desenvolvimento científico e tecnológico custeadas por fundo criado para tal finalidade. – 0,5": 0.5,
                    "Critérios para repasses a entidades do terceiro setor – 00": 0.0,
                    "Critérios para ajuda financeira a entidades da Administração indireta – 00": 0.0,
                    "Critérios para o Poder Executivo estabelecer a programação financeira mensal para todo o Município, nele incluído a Câmara – 01": 1.0,
                    "Percentual da Receita Corrente Líquida que será retido, na peça orçamentária, enquanto Reserva de Contingência, destinada a passivos contingentes e outros riscos fiscais – 01": 1.0,
                    "Critérios para contratação de horas extras quando o Poder superar o limite prudencial para pessoal: Executivo, 51,30% da RCL; Legislativo, 5,7% da RCL – 0,5": 0.5,
                    "Determinação do índice de preços para atualização monetária do principal da Dívida Mobiliária Refinanciada – 00": 0.0,
                    "Autorização para o Município auxiliar o custeio de despesas próprias do Estado e da União – 00": 0.0,
                    "Requisitos para início de novos projetos, após o adequado atendimento/manutenção dos que estão em andamento – 0,5": 0.5,
                    "Dispor sobre pagamento de servidor ou empregado público com recursos vinculados à parceria firmada com o terceiro setor – 00": 0.0
                }

                # Resgate seguro dos dados
                d60 = res_data.get("6.0") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                evidencia_60_salva = d60.get("link", "")

                try:
                    lista_salva_60 = ast.literal_eval(d60.get("valor", "[]"))
                    if not isinstance(lista_salva_60, list):
                        lista_salva_60 = []
                except Exception:
                    lista_salva_60 = []

                # Chaves fixas por componente e ano
                chave_link_60 = f"t_6_0_{ano_sel}"
                chave_coment_60 = f"coment_6.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    st.write("**Itens Selecionáveis:**")
                    # Renderização individual dos Checkboxes
                    for idx, (item_texto, pt) in enumerate(itens_ldo_60.items()):
                        key_chk = f"chk_60_{idx}_{ano_sel}"
                        st.checkbox(
                            item_texto,
                            value=item_texto in lista_salva_60,
                            key=key_chk
                        )

                with col2:
                    link_evidencia_60 = st.text_area(
                        "Link/Evidência (6.0):",
                        value=evidencia_60_salva,
                        key=chave_link_60,
                        placeholder="Insira os links dos documentos comprobatórios dos itens dispostos na LDO...",
                        height=250
                    )
                    placeholder_links_60 = st.empty()
                    links_60_visuais = re.findall(REGEX_PURE_URL, link_evidencia_60 or "")
                    if links_60_visuais:
                        placeholder_links_60.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_60_visuais]
                            )
                        )

                # Renderização do bloco unificado de comentários
                bloco_comentarios("6.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 6.0", key=f"btn_salvar_6_0_{ano_sel}", type="primary"):
                    itens_selecionados_60 = []
                    pts_calculados_60 = 0.0

                    # Varredura dos estados dos checkboxes no session_state
                    for idx, (item_texto, pt) in enumerate(itens_ldo_60.items()):
                        key_chk = f"chk_60_{idx}_{ano_sel}"
                        if st.session_state.get(key_chk, False):
                            itens_selecionados_60.append(item_texto)
                            pts_calculados_60 += pt

                    str_valor_60 = str(itens_selecionados_60)
                    lnk_val = link_evidencia_60.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_60, d60.get("comentario", ""))

                    # Persistência na base de dados
                    save_resp(
                        qid="6.0",
                        valor=str_valor_60,
                        pontos=float(pts_calculados_60),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização na estrutura global local
                    res_data["6.0"] = {
                        "valor": str_valor_60,
                        "pontos": float(pts_calculados_60),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_60_salva or "")]

                    if lnk_val != evidencia_60_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários da Questão 6.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição estilizada do impacto da pontuação
                pts_atuais_60 = d60.get("pontos", 0.0)
                valor_salvo_60_str = d60.get("valor", "[]")

                if valor_salvo_60_str == "[]" or not valor_salvo_60_str:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada</span>", unsafe_allow_html=True)
                else:
                    cor_txt_60 = "#28a745" if pts_atuais_60 > 0 else "#6c757d"
                    st.markdown(
                        f"<span style='color:{cor_txt_60}; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação na Questão 6.0: {pts_atuais_60:.2f} pontos</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL DE EVIDÊNCIAS
        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 7.0 • ALTERAÇÕES ORÇAMENTÁRIAS POR DECRETO
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_alteracao_decreto_7_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 7.0 - Alteração Orçamentária por Decreto ({ano_sel})", expanded=True):
                st.subheader("7.0 • Alterações Orçamentárias por Decreto")
                st.write("**7.0 Houve alteração orçamentária decorrente de remanejamento, transposição ou transferência de uma categoria de programação para outra ou de um órgão para outro por decreto?**")
                st.caption("ℹ *Selecione a resposta, informe a evidência e clique em 'Salvar Questão 7.0'.*")

                opcoes_70 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados de 7.0
                d70 = res_data.get("7.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_70_salva = d70.get("link", "")
                v_salvo_70 = d70.get("valor", "Selecione...")

                # Chaves fixas por componente
                chave_radio_70 = f"r_7_0_{ano_sel}"
                chave_link_70 = f"t_7_0_{ano_sel}"
                chave_coment_70 = f"coment_7.0_{ano_sel}"

                col1, col2 = st.columns([1, 1])

                with col1:
                    lista_opcoes_70 = list(opcoes_70.keys())
                    idx70 = lista_opcoes_70.index(v_salvo_70) if v_salvo_70 in lista_opcoes_70 else 0

                    sel_7_0 = st.radio(
                        "Selecione a resposta para o Quesito 7.0:",
                        options=lista_opcoes_70,
                        index=idx70,
                        key=chave_radio_70
                    )

                with col2:
                    link_evidencia_70 = st.text_area(
                        "Link/Evidência (7.0):",
                        value=evidencia_70_salva,
                        key=chave_link_70,
                        placeholder="Insira os links dos decretos ou documentos comprobatórios...",
                        height=120
                    )
                    placeholder_links_70 = st.empty()
                    links_70_visuais = re.findall(REGEX_PURE_URL, link_evidencia_70 or "")
                    if links_70_visuais:
                        placeholder_links_70.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_70_visuais]
                            )
                        )

                # Bloco de comentários do 7.0
                bloco_comentarios("7.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 7.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 7.0", key=f"btn_salvar_7_0_{ano_sel}", type="primary"):
                    val_70 = st.session_state.get(chave_radio_70, "Selecione...")
                    lnk_val_70 = link_evidencia_70.strip()
                    comentario_para_salvar_70 = st.session_state.get(chave_coment_70, d70.get("comentario", ""))

                    save_resp(
                        qid="7.0",
                        valor=val_70,
                        pontos=0.0,
                        link=lnk_val_70,
                        comentario=comentario_para_salvar_70
                    )
                    res_data["7.0"] = {
                        "valor": val_70,
                        "pontos": 0.0,
                        "link": lnk_val_70,
                        "comentario": comentario_para_salvar_70
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_70 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_70_salva or "")]

                    if lnk_val_70 != evidencia_70_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 7.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status 7.0
                if v_salvo_70 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Seleção pendente no Quesito 7.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação (Quesito 7.0): 0.0 pontos</span>", unsafe_allow_html=True)

        # Modal de Evidências do 7.0
        if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 7.1 • CLASSIFICAÇÃO FUNCIONAL DA DESPESA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_alteracao_decreto_7_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 7.1 - Classificação Funcional das Alterações ({ano_sel})", expanded=True):
                st.subheader("7.1 • Classificação Funcional da Despesa")
                st.write("**7.1 Assinale a classificação funcional da despesa, objeto de alterações orçamentárias decorrentes de remanejamento, transposição e transferências realizadas por decreto:**")
                st.caption("ℹ *Selecione as funções afetadas, informe a evidência e clique em 'Salvar Questão 7.1'.*")

                funcs_alt_71 = {
                    "10 - Saúde – -05 (perde 05 pontos)": -5.0,
                    "12 - Educação – -05 (perde 05 pontos)": -5.0,
                    "17 - Saneamento – -05 (perde 05 pontos)": -5.0,
                    "19 - Ciência e Tecnologia – 00": 0.0,
                    "26 - Transporte – -05 (perde 05 pontos)": -5.0,
                    "Outras – -05 (perde 05 pontos)": -5.0
                }

                # Resgate seguro dos dados de 7.1
                d71 = res_data.get("7.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_71_salva = d71.get("link", "")

                try:
                    lista_salva_71 = ast.literal_eval(d71.get("valor", "[]"))
                    if not isinstance(lista_salva_71, list):
                        lista_salva_71 = []
                except Exception:
                    lista_salva_71 = []

                chave_link_71 = f"t_7_1_{ano_sel}"
                chave_coment_71 = f"coment_7.1_{ano_sel}"

                col1_71, col2_71 = st.columns([1, 1])

                with col1_71:
                    st.markdown("**Selecione uma ou mais funções afetadas:**")
                    for idx, (item_texto, pt) in enumerate(funcs_alt_71.items()):
                        key_chk_71 = f"chk_71_{idx}_{ano_sel}"
                        st.checkbox(
                            item_texto,
                            value=item_texto in lista_salva_71,
                            key=key_chk_71
                        )

                with col2_71:
                    link_evidencia_71 = st.text_area(
                        "Link/Evidência (7.1):",
                        value=evidencia_71_salva,
                        key=chave_link_71,
                        placeholder="Insira os links comprobatórios referente às funções selecionadas...",
                        height=150
                    )
                    placeholder_links_71 = st.empty()
                    links_71_visuais = re.findall(REGEX_PURE_URL, link_evidencia_71 or "")
                    if links_71_visuais:
                        placeholder_links_71.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_71_visuais]
                            )
                        )

                # Bloco de comentários do 7.1
                bloco_comentarios("7.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 7.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 7.1", key=f"btn_salvar_7_1_{ano_sel}", type="primary"):
                    lnk_val_71 = link_evidencia_71.strip()
                    comentario_para_salvar_71 = st.session_state.get(chave_coment_71, d71.get("comentario", ""))

                    itens_selecionados_71 = []
                    pts_calculados_71 = 0.0

                    for idx, (item_texto, pt) in enumerate(funcs_alt_71.items()):
                        key_chk_71 = f"chk_71_{idx}_{ano_sel}"
                        if st.session_state.get(key_chk_71, False):
                            itens_selecionados_71.append(item_texto)
                            pts_calculados_71 += pt

                    str_valor_71 = str(itens_selecionados_71)

                    save_resp(
                        qid="7.1",
                        valor=str_valor_71,
                        pontos=float(pts_calculados_71),
                        link=lnk_val_71,
                        comentario=comentario_para_salvar_71
                    )
                    res_data["7.1"] = {
                        "valor": str_valor_71,
                        "pontos": float(pts_calculados_71),
                        "link": lnk_val_71,
                        "comentario": comentario_para_salvar_71
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_71 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_71_salva or "")]

                    if lnk_val_71 != evidencia_71_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 7.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status / Impacto 7.1
                pts_atuais_71 = d71.get("pontos", 0.0)
                cor_txt_71 = "#dc3545" if pts_atuais_71 < 0 else "#28a745"
                sufixo_pen = " (Penalidades aplicadas)" if pts_atuais_71 < 0 else ""
                st.markdown(
                    f"<span style='color:{cor_txt_71}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação (Quesito 7.1): {pts_atuais_71:.1f} pontos{sufixo_pen}</span>",
                    unsafe_allow_html=True
                )

        # Modal de Evidências do 7.1
        if st.session_state.get(f"gatilho_modal_7_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.1", st.session_state.get(f"links_pendentes_7_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 8.0 • ANEXO DE METAS FISCAIS NA LDO
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_metas_fiscais_8_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 8.0 - Anexo de Metas Fiscais na LDO ({ano_sel})", expanded=True):
                st.subheader("8.0 • Anexo de Metas Fiscais")
                st.write("**8.0 O Anexo de Metas Fiscais integra a Lei de Diretrizes Orçamentárias (LDO), nos termos exigidos pela Lei de Responsabilidade Fiscal?**")
                st.caption("ℹ *Estabelecidas metas anuais, em valores correntes e constantes, relativas a receitas, despesas, resultados nominal e primário e montante da dívida pública, para o exercício a que se referirem e para os dois seguintes. Caso não esteja disponível na internet, recomendamos anexar o Anexo de Metas Fiscais (MDF), conforme Instrução de Preenchimento (IP) no Sistema de Questionários.*")
                st.caption("ℹ *Selecione a resposta, informe a evidência, comente se necessário e clique em 'Salvar Questão 8.0'.*")

                opcoes_80 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados de 8.0
                d80 = res_data.get("8.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_80_salva = d80.get("link", "")
                v_salvo_80 = d80.get("valor", "Selecione...")

                # Chaves fixas por componente e ano
                chave_radio_80 = f"r_8_0_{ano_sel}"
                chave_link_80 = f"t_8_0_{ano_sel}"
                chave_coment_80 = f"coment_8.0_{ano_sel}"

                c80_1, c80_2 = st.columns([1, 1])

                with c80_1:
                    lista_opcoes_80 = list(opcoes_80.keys())
                    idx80 = lista_opcoes_80.index(v_salvo_80) if v_salvo_80 in lista_opcoes_80 else 0

                    sel_8_0 = st.radio(
                        "Selecione a resposta para o Quesito 8.0:",
                        options=lista_opcoes_80,
                        index=idx80,
                        key=chave_radio_80
                    )

                with c80_2:
                    link_evidencia_80 = st.text_area(
                        "Link/Evidência (8.0):",
                        value=evidencia_80_salva,
                        key=chave_link_80,
                        placeholder="Insira os links comprobatórios do Anexo de Metas Fiscais...",
                        height=120
                    )
                    placeholder_links_80 = st.empty()
                    links_80_visuais = re.findall(REGEX_PURE_URL, link_evidencia_80 or "")
                    if links_80_visuais:
                        placeholder_links_80.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_80_visuais]
                            )
                        )

                # Bloco de comentários do 8.0
                bloco_comentarios("8.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 8.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 8.0", key=f"btn_salvar_8_0_{ano_sel}", type="primary"):
                    val_80 = st.session_state.get(chave_radio_80, "Selecione...")
                    lnk_val_80 = link_evidencia_80.strip()
                    comentario_para_salvar_80 = st.session_state.get(chave_coment_80, d80.get("comentario", ""))

                    save_resp(
                        qid="8.0",
                        valor=val_80,
                        pontos=0.0,
                        link=lnk_val_80,
                        comentario=comentario_para_salvar_80
                    )
                    res_data["8.0"] = {
                        "valor": val_80,
                        "pontos": 0.0,
                        "link": lnk_val_80,
                        "comentario": comentario_para_salvar_80
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_80 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_80_salva or "")]

                    if lnk_val_80 != evidencia_80_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 8.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                if v_salvo_80 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Seleção pendente no Quesito 8.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação (Quesito 8.0): 0.0 pontos</span>", unsafe_allow_html=True)

        # Modal de Evidências do 8.0
        if st.session_state.get(f"gatilho_modal_8_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.0", st.session_state.get(f"links_pendentes_8_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 8.1 • LINK DE DIVULGAÇÃO DAS METAS FISCAIS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_url_metas_8_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 8.1 - Link de Divulgação das Metas Fiscais ({ano_sel})", expanded=True):
                st.subheader("8.1 • URL do Anexo de Metas Fiscais")
                st.write("**8.1 Informe a página eletrônica (link na internet) de divulgação do Anexo de Metas Fiscais (XYZ se não disponível):**")
                st.caption("ℹ *Informe o link da página eletrônica ou 'XYZ' se não estiver disponível, preencha a evidência/comentários e clique em 'Salvar Questão 8.1'.*")

                # Resgate seguro dos dados de 8.1
                d81 = res_data.get("8.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_81_salva = d81.get("link", "")
                v_salvo_81 = d81.get("valor", "")

                # Chaves fixas por componente e ano
                chave_input_81 = f"inp_81_{ano_sel}"
                chave_link_81 = f"t_8_1_{ano_sel}"
                chave_coment_81 = f"coment_8.1_{ano_sel}"

                c81_1, c81_2 = st.columns([1, 1])

                with c81_1:
                    val_8_1 = st.text_input(
                        "Página eletrônica (link ou XYZ):",
                        value=v_salvo_81,
                        key=chave_input_81,
                        placeholder="http://... ou XYZ"
                    )

                with c81_2:
                    link_evidencia_81 = st.text_area(
                        "Link/Evidência (8.1):",
                        value=evidencia_81_salva,
                        key=chave_link_81,
                        placeholder="Insira os links comprobatórios referente ao Quesito 8.1...",
                        height=100
                    )
                    placeholder_links_81 = st.empty()
                    links_81_visuais = re.findall(REGEX_PURE_URL, link_evidencia_81 or "")
                    if links_81_visuais:
                        placeholder_links_81.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_81_visuais]
                            )
                        )

                # Bloco de comentários do 8.1
                bloco_comentarios("8.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 8.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 8.1", key=f"btn_salvar_8_1_{ano_sel}", type="primary"):
                    val_input_81 = st.session_state.get(chave_input_81, "").strip()
                    lnk_val_81 = link_evidencia_81.strip()
                    comentario_para_salvar_81 = st.session_state.get(chave_coment_81, d81.get("comentario", ""))

                    # Regra de pontuação
                    if val_input_81.upper() == "XYZ":
                        pts_81 = -10.0
                    else:
                        pts_81 = 0.0

                    save_resp(
                        qid="8.1",
                        valor=val_input_81,
                        pontos=float(pts_81),
                        link=lnk_val_81,
                        comentario=comentario_para_salvar_81
                    )
                    res_data["8.1"] = {
                        "valor": val_input_81,
                        "pontos": float(pts_81),
                        "link": lnk_val_81,
                        "comentario": comentario_para_salvar_81
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_81 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_81_salva or "")]

                    if lnk_val_81 != evidencia_81_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 8.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                v81_check = d81.get("valor", "").strip()
                pts_atuais_81 = d81.get("pontos", 0.0)

                if not v81_check:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Preenchimento pendente no Quesito 8.1</span>", unsafe_allow_html=True)
                elif v81_check.upper() == "XYZ":
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"❌ Impacto de Pontuação (Quesito 8.1): {pts_atuais_81:.1f} pontos (AMF Não Disponível - Penalidade Aplicada)</span>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Impacto de Pontuação (Quesito 8.1): {pts_atuais_81:.1f} pontos (Link Registrado)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 8.1
        if st.session_state.get(f"gatilho_modal_8_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.1", st.session_state.get(f"links_pendentes_8_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 8.2 • DEMONSTRATIVOS DA AMF (CHECKBOXES MULTIPLAS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_demonstrativos_amf_8_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 8.2 - Demonstrativos Contidos no Anexo de Metas Fiscais ({ano_sel})", expanded=True):
                st.subheader("8.2 • Demonstrativos da AMF")
                st.write("**8.2 Assinale os demonstrativos contidos no Anexo de Metas Fiscais:**")
                st.caption("ℹ *Selecione os demonstrativos aplicáveis, informe os links e comentários, e clique em 'Salvar Questão 8.2'.*")

                demonstrativos_82 = {
                    "Metas Anuais – 0,7": 0.7,
                    "Avaliação do Cumprimento das Metas Fiscais do Exercício Anterior – 0,7": 0.7,
                    "Metas Fiscais Atuais Comparadas com as Metas Fiscais Fixadas nos três exercícios anteriores – 0,7": 0.7,
                    "Evolução do Patrimônio Líquido – 0,7": 0.7,
                    "Origem e Aplicação dos Recursos Obtidos com a Alienação de Ativos – 00": 0.0,
                    "Avaliação da Situação Financeira e Atuarial do RPPS – 00": 0.0,
                    "Estimativa e Compensação da Renúncia de Receita – 00": 0.0,
                    "Margem de Expansão das Despesas Obrigatórias de Caráter Continuado – 1,2": 1.2,
                    "Outros – 00": 0.0
                }

                # Resgate seguro dos dados de 8.2
                d82 = res_data.get("8.2") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_82_salva = d82.get("link", "")
                v_salvo_82 = d82.get("valor", "[]")

                try:
                    lista_salva_82 = ast.literal_eval(v_salvo_82)
                    if not isinstance(lista_salva_82, list):
                        lista_salva_82 = []
                except Exception:
                    lista_salva_82 = []

                # Chaves fixas por componente e ano
                chave_link_82 = f"t_8_2_{ano_sel}"
                chave_coment_82 = f"coment_8.2_{ano_sel}"

                c82_1, c82_2 = st.columns([1, 1])

                with c82_1:
                    st.write("**Demonstrativos Disponíveis:**")
                    # Renderização dos checkboxes sem callbacks on_change
                    for idx, (item, pt) in enumerate(demonstrativos_82.items()):
                        key_chk = f"chk_82_{idx}_{ano_sel}"
                        st.checkbox(
                            item,
                            value=item in lista_salva_82,
                            key=key_chk
                        )

                with c82_2:
                    link_evidencia_82 = st.text_area(
                        "Link/Evidência (8.2):",
                        value=evidencia_82_salva,
                        key=chave_link_82,
                        placeholder="Insira os links comprobatórios referente ao Quesito 8.2...",
                        height=250
                    )
                    placeholder_links_82 = st.empty()
                    links_82_visuais = re.findall(REGEX_PURE_URL, link_evidencia_82 or "")
                    if links_82_visuais:
                        placeholder_links_82.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_82_visuais]
                            )
                        )

                # Bloco de comentários do 8.2
                bloco_comentarios("8.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 8.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 8.2", key=f"btn_salvar_8_2_{ano_sel}", type="primary"):
                    # Coleta dos checkboxes selecionados no momento do clique
                    sel_82 = []
                    pts_total_82 = 0.0

                    for idx, (item, pt) in enumerate(demonstrativos_82.items()):
                        key_chk = f"chk_82_{idx}_{ano_sel}"
                        if st.session_state.get(key_chk, False):
                            sel_82.append(item)
                            pts_total_82 += pt

                    str_sel_82 = str(sel_82)
                    lnk_val_82 = link_evidencia_82.strip()
                    comentario_para_salvar_82 = st.session_state.get(chave_coment_82, d82.get("comentario", ""))

                    save_resp(
                        qid="8.2",
                        valor=str_sel_82,
                        pontos=float(pts_total_82),
                        link=lnk_val_82,
                        comentario=comentario_para_salvar_82
                    )
                    res_data["8.2"] = {
                        "valor": str_sel_82,
                        "pontos": float(pts_total_82),
                        "link": lnk_val_82,
                        "comentario": comentario_para_salvar_82
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_82 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_82_salva or "")]

                    if lnk_val_82 != evidencia_82_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 8.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                pts_atuais_82 = d82.get("pontos", 0.0)
                
                if not lista_salva_82:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhum demonstrativo selecionado no Quesito 8.2</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Impacto de Pontuação (Quesito 8.2): {pts_atuais_82:.2f} pontos</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 8.2
        if st.session_state.get(f"gatilho_modal_8_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.2", st.session_state.get(f"links_pendentes_8_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 9.0 • ANEXO DE RISCOS FISCAIS (SELEÇÃO ÚNICA VIA RADIO)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_riscos_fiscais_9_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 9.0 - Presença do Anexo de Riscos Fiscais na LDO ({ano_sel})", expanded=True):
                st.subheader("9.0 • Anexo de Riscos Fiscais")
                st.write("**9.0 O Anexo de Riscos Fiscais integra a Lei de Diretrizes Orçamentárias (LDO), nos termos exigidos pela Lei de Responsabilidade Fiscal?**")
                st.caption("ℹ *Avalia os passivos contingentes e outros riscos capazes de afetar as contas públicas, informando as providências a serem tomadas, caso se concretizem.*")
                st.caption("ℹ *Selecione a opção desejada, informe os links e comentários, e clique em 'Salvar Questão 9.0'.*")

                opcoes_90 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados de 9.0
                d90 = res_data.get("9.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_90_salva = d90.get("link", "")
                v_salvo_90 = d90.get("valor", "Selecione...")

                # Chaves fixas por componente e ano
                chave_radio_90 = f"r_9_0_{ano_sel}"
                chave_link_90 = f"t_9_0_{ano_sel}"
                chave_coment_90 = f"coment_9.0_{ano_sel}"

                c90_1, c90_2 = st.columns([1, 1])

                with c90_1:
                    lista_opcoes_90 = list(opcoes_90.keys())
                    idx90 = lista_opcoes_90.index(v_salvo_90) if v_salvo_90 in lista_opcoes_90 else 0

                    sel_9_0 = st.radio(
                        "Selecione a opção do Quesito 9.0:",
                        options=lista_opcoes_90,
                        index=idx90,
                        key=chave_radio_90,
                        label_visibility="collapsed"
                    )

                with c90_2:
                    link_evidencia_90 = st.text_area(
                        "Link/Evidência (9.0):",
                        value=evidencia_90_salva,
                        key=chave_link_90,
                        placeholder="Insira os links comprobatórios referente ao Quesito 9.0...",
                        height=100
                    )
                    placeholder_links_90 = st.empty()
                    links_90_visuais = re.findall(REGEX_PURE_URL, link_evidencia_90 or "")
                    if links_90_visuais:
                        placeholder_links_90.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_90_visuais]
                            )
                        )

                # Bloco de comentários do 9.0
                bloco_comentarios("9.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 9.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 9.0", key=f"btn_salvar_9_0_{ano_sel}", type="primary"):
                    val_radio_90 = st.session_state.get(chave_radio_90, "Selecione...")
                    lnk_val_90 = link_evidencia_90.strip()
                    comentario_para_salvar_90 = st.session_state.get(chave_coment_90, d90.get("comentario", ""))

                    pts_90 = opcoes_90.get(val_radio_90, 0.0)

                    save_resp(
                        qid="9.0",
                        valor=val_radio_90,
                        pontos=float(pts_90),
                        link=lnk_val_90,
                        comentario=comentario_para_salvar_90
                    )
                    res_data["9.0"] = {
                        "valor": val_radio_90,
                        "pontos": float(pts_90),
                        "link": lnk_val_90,
                        "comentario": comentario_para_salvar_90
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_90 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_90_salva or "")]

                    if lnk_val_90 != evidencia_90_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 9.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                v90_check = d90.get("valor", "Selecione...").strip()
                pts_atuais_90 = d90.get("pontos", 0.0)

                if v90_check in ["", "Selecione..."]:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Seleção pendente no Quesito 9.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção '{v90_check}' salva (Impacto: {pts_atuais_90:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 9.0
        if st.session_state.get(f"gatilho_modal_9_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.0", st.session_state.get(f"links_pendentes_9_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 9.1 • URL DO ANEXO DE RISCOS FISCAIS (TEXT INPUT COM REGRA XYZ)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_url_riscos_9_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 9.1 - Link Eletrônico do Anexo de Riscos Fiscais ({ano_sel})", expanded=True):
                st.subheader("9.1 • URL do Anexo de Riscos Fiscais")
                st.write("**9.1 Informe a página eletrônica (link na internet) de divulgação do Anexo de Riscos Fiscais (digite XYZ se não estiver disponível):**")
                st.caption("ℹ *Insira o link direto ou a sigla 'XYZ'. Preencha os links comprobatórios e comentários, e clique em 'Salvar Questão 9.1'.*")

                # Resgate seguro dos dados de 9.1
                d91 = res_data.get("9.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_91_salva = d91.get("link", "")
                v_salvo_91 = d91.get("valor", "")

                # Chaves fixas por componente e ano
                chave_input_91 = f"inp_91_{ano_sel}"
                chave_link_91 = f"t_9_1_{ano_sel}"
                chave_coment_91 = f"coment_9.1_{ano_sel}"

                c91_1, c91_2 = st.columns([1, 1])

                with c91_1:
                    url_91 = st.text_input(
                        "Página eletrônica (link):",
                        value=v_salvo_91,
                        key=chave_input_91,
                        placeholder="http://... ou XYZ"
                    )

                with c91_2:
                    link_evidencia_91 = st.text_area(
                        "Link/Evidência (9.1):",
                        value=evidencia_91_salva,
                        key=chave_link_91,
                        placeholder="Insira os links comprobatórios referente ao Quesito 9.1...",
                        height=100
                    )
                    placeholder_links_91 = st.empty()
                    links_91_visuais = re.findall(REGEX_PURE_URL, link_evidencia_91 or "")
                    if links_91_visuais:
                        placeholder_links_91.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_91_visuais]
                            )
                        )

                # Bloco de comentários do 9.1
                bloco_comentarios("9.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 9.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 9.1", key=f"btn_salvar_9_1_{ano_sel}", type="primary"):
                    val_input_91 = st.session_state.get(chave_input_91, "").strip()
                    lnk_val_91 = link_evidencia_91.strip()
                    comentario_para_salvar_91 = st.session_state.get(chave_coment_91, d91.get("comentario", ""))

                    # Regra de pontuação: XYZ penaliza em -10.0
                    pts_91 = -10.0 if val_input_91.upper() == "XYZ" else 0.0

                    save_resp(
                        qid="9.1",
                        valor=val_input_91,
                        pontos=float(pts_91),
                        link=lnk_val_91,
                        comentario=comentario_para_salvar_91
                    )
                    res_data["9.1"] = {
                        "valor": val_input_91,
                        "pontos": float(pts_91),
                        "link": lnk_val_91,
                        "comentario": comentario_para_salvar_91
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_91 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_91_salva or "")]

                    if lnk_val_91 != evidencia_91_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 9.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                v91_check = d91.get("valor", "").strip()
                pts_atuais_91 = d91.get("pontos", 0.0)

                if not v91_check:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento da URL/XYZ no Quesito 9.1</span>", unsafe_allow_html=True)
                elif v91_check.upper() == "XYZ":
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"❌ Status: Anexo Não Disponível (Penalidade: {pts_atuais_91:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Link do Anexo Salvo (Sem penalidades / Impacto: {pts_atuais_91:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 9.1
        if st.session_state.get(f"gatilho_modal_9_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.1", st.session_state.get(f"links_pendentes_9_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 9.2 • ETAPAS DE GERENCIAMENTO DA ARF (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_etapas_riscos_9_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 9.2 - Etapas para Gerenciamento de Riscos Fiscais ({ano_sel})", expanded=True):
                st.subheader("9.2 • Etapas de Gerenciamento da ARF")
                st.write("**9.2 Assinale as etapas para gerenciamento dos riscos contidas no Anexo de Riscos Fiscais:**")
                st.caption("ℹ *Selecione as etapas aplicáveis, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 9.2'.*")

                etapas_risco_92 = {
                    "Identificação do tipo de risco e da exposição ao risco – 0,5": 0.5,
                    "Mensuração ou quantificação dessa exposição – 0,5": 0.5,
                    "Estimativa do grau de tolerância das contas públicas ao comportamento frente ao risco – 0,5": 0.5,
                    "Decisão estratégica sobre as opções para enfrentar o risco – 0,5": 0.5,
                    "Implementação de condutas de mitigação do risco e de mecanismos de controle para prevenir perdas decorrentes do risco – 0,5": 0.5,
                    "Monitoramento contínuo da exposição ao longo do tempo, preferencialmente através de sistemas institucionalizados (Controle Interno) – 01": 1.0
                }

                # Resgate seguro dos dados de 9.2
                d92 = res_data.get("9.2") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d92 is None:
                    d92 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                try:
                    lista_salva_92 = ast.literal_eval(d92.get("valor", "[]"))
                    if not isinstance(lista_salva_92, list):
                        lista_salva_92 = []
                except Exception:
                    lista_salva_92 = []

                evidencia_92_salva = d92.get("link", "")

                # Chaves fixas por componente e ano
                chave_link_92 = f"t_9_2_{ano_sel}"
                chave_coment_92 = f"coment_9.2_{ano_sel}"

                c92_1, c92_2 = st.columns([1, 1])

                with c92_1:
                    st.write("**Selecione as etapas presentes:**")
                    estados_checkboxes_92 = {}
                    for idx, (item, pt) in enumerate(etapas_risco_92.items()):
                        key_chk = f"chk_92_{idx}_{ano_sel}"
                        estados_checkboxes_92[item] = st.checkbox(
                            item,
                            value=item in lista_salva_92,
                            key=key_chk
                        )

                with c92_2:
                    link_evidencia_92 = st.text_area(
                        "Link/Evidência (9.2):",
                        value=evidencia_92_salva,
                        key=chave_link_92,
                        placeholder="Insira os links comprobatórios referente ao Quesito 9.2...",
                        height=220
                    )
                    placeholder_links_92 = st.empty()
                    links_92_visuais = re.findall(REGEX_PURE_URL, link_evidencia_92 or "")
                    if links_92_visuais:
                        placeholder_links_92.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_92_visuais]
                            )
                        )

                # Bloco de comentários do 9.2
                bloco_comentarios("9.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 9.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 9.2", key=f"btn_salvar_9_2_{ano_sel}", type="primary"):
                    sel_atual_92 = []
                    pts_calculados_92 = 0.0

                    for item, pt in etapas_risco_92.items():
                        if estados_checkboxes_92.get(item, False):
                            sel_atual_92.append(item)
                            pts_calculados_92 += pt

                    lnk_val_92 = link_evidencia_92.strip()
                    comentario_para_salvar_92 = st.session_state.get(chave_coment_92, d92.get("comentario", ""))

                    save_resp(
                        qid="9.2",
                        valor=str(sel_atual_92),
                        pontos=float(pts_calculados_92),
                        link=lnk_val_92,
                        comentario=comentario_para_salvar_92
                    )
                    res_data["9.2"] = {
                        "valor": str(sel_atual_92),
                        "pontos": float(pts_calculados_92),
                        "link": lnk_val_92,
                        "comentario": comentario_para_salvar_92
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_92 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_92_salva or "")]

                    if lnk_val_92 != evidencia_92_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 9.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                pts_atuais_92 = d92.get("pontos", 0.0)
                try:
                    lista_verif_92 = ast.literal_eval(d92.get("valor", "[]"))
                except Exception:
                    lista_verif_92 = []

                if not lista_verif_92:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma etapa selecionada no Quesito 9.2</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: {len(lista_verif_92)} etapa(s) salva(s) (Pontuação: {pts_atuais_92:.2f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 9.2
        if st.session_state.get(f"gatilho_modal_9_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.2", st.session_state.get(f"links_pendentes_9_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 10.0 • COMPATIBILIDADE LOA X PPA X LDO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_compatibilidade_10_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 10.0 - Itens de Compatibilidade Orçamentária ({ano_sel})", expanded=True):
                st.subheader("10.0 • Compatibilidade LOA x PPA x LDO")
                st.write("**10.0 Assinale os itens capazes de atestar a compatibilidade entre a LOA, PPA e LDO:**")
                st.caption("ℹ *Selecione as opções aplicáveis, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 10.0'.*")

                compatibilidades_100 = {
                    "Programas constantes do PPA constam na LOA – 01": 1.0,
                    "Programas e ações constantes da LDO constam da LOA – 02": 2.0,
                    "As receitas e despesas da LOA são compatíveis com o Resultado Primário da LDO, incluindo, no máximo, a variação da inflação do interregno temporal dos referidos projetos de lei – 02": 2.0,
                    "O Resultado Nominal constante da LDO consta da LOA, com variação de no máximo a variação da inflação do interregno temporal dos referidos projetos de lei – 02": 2.0,
                    "A estimativa de renúncia fiscal prevista na LDO coincide com o estimado na LOA com variação limitada à variação da inflação – 02": 2.0,
                    "A estimativa de receita e respectivos critérios presentes na LOA são compatíveis com os previstos na LDO em relação à receita de IPTU – 02": 2.0,
                    "A estimativa de receita e respectivos critérios presentes na LOA são compatíveis com os previstos na LDO em relação à receita de ISSQN – 02": 2.0,
                    "A estimativa de receita e respectivos critérios presentes na LOA são compatíveis com os previstos na LDO em relação à receita de ITBI – 02": 2.0,
                    "Os investimentos, parte das despesas de capital, previstas na LOA e LDO are compatíveis com as previsões do PPA – 02": 2.0,
                    "A LDO e a LOA não são compatíveis com o PPA – -10 (perde 10 pontos)": -10.0
                }

                # Resgate seguro dos dados do 10.0
                d100 = res_data.get("10.0") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d100 is None:
                    d100 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                try:
                    lista_salva_100 = ast.literal_eval(d100.get("valor", "[]"))
                    if not isinstance(lista_salva_100, list):
                        lista_salva_100 = []
                except Exception:
                    lista_salva_100 = []

                evidencia_100_salva = d100.get("link", "")

                # Chaves fixas por componente e ano
                chave_link_100 = f"t_10_0_{ano_sel}"
                chave_coment_100 = f"coment_10.0_{ano_sel}"

                c100_1, c100_2 = st.columns([1, 1])

                with c100_1:
                    st.write("**Selecione os itens verificados:**")
                    estados_checkboxes_100 = {}
                    for idx, (item, pt) in enumerate(compatibilidades_100.items()):
                        key_chk = f"chk_100_{idx}_{ano_sel}"
                        estados_checkboxes_100[item] = st.checkbox(
                            item,
                            value=item in lista_salva_100,
                            key=key_chk
                        )

                with c100_2:
                    link_evidencia_100 = st.text_area(
                        "Link/Evidência (10.0):",
                        value=evidencia_100_salva,
                        key=chave_link_100,
                        placeholder="Insira os links comprobatórios referente ao Quesito 10.0...",
                        height=250
                    )
                    placeholder_links_100 = st.empty()
                    links_100_visuais = re.findall(REGEX_PURE_URL, link_evidencia_100 or "")
                    if links_100_visuais:
                        placeholder_links_100.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_100_visuais]
                            )
                        )

                # Bloco de comentários do 10.0
                bloco_comentarios("10.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 10.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 10.0", key=f"btn_salvar_10_0_{ano_sel}", type="primary"):
                    sel_atual_100 = []
                    pts_calculados_100 = 0.0
                    flag_anulacao = False

                    for item, pt in compatibilidades_100.items():
                        if estados_checkboxes_100.get(item, False):
                            sel_atual_100.append(item)
                            if "não são compatíveis" in item:
                                flag_anulacao = True
                            pts_calculados_100 += pt

                    # Regra de penalidade anulatória
                    pts_finais_100 = -10.0 if flag_anulacao else pts_calculados_100

                    lnk_val_100 = link_evidencia_100.strip()
                    comentario_para_salvar_100 = st.session_state.get(chave_coment_100, d100.get("comentario", ""))

                    save_resp(
                        qid="10.0",
                        valor=str(sel_atual_100),
                        pontos=float(pts_finais_100),
                        link=lnk_val_100,
                        comentario=comentario_para_salvar_100
                    )
                    res_data["10.0"] = {
                        "valor": str(sel_atual_100),
                        "pontos": float(pts_finais_100),
                        "link": lnk_val_100,
                        "comentario": comentario_para_salvar_100
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_100 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_100_salva or "")]

                    if lnk_val_100 != evidencia_100_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 10.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                pts_atuais_100 = d100.get("pontos", 0.0)
                try:
                    lista_verif_100 = ast.literal_eval(d100.get("valor", "[]"))
                except Exception:
                    lista_verif_100 = []

                if not lista_verif_100:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhum item selecionado no Quesito 10.0</span>", unsafe_allow_html=True)
                elif any("não são compatíveis" in item for item in lista_verif_100):
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"❌ Status: Incompatibilidade Declarada (Penalidade: {pts_atuais_100:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: {len(lista_verif_100)} item(ns) de compatibilidade salvo(s) (Pontuação: {pts_atuais_100:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 10.0
        if st.session_state.get(f"gatilho_modal_10_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("10.0", st.session_state.get(f"links_pendentes_10_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 11.0 • PREVISÃO DE CRÉDITOS ADICIONAIS NA LOA (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_creditos_11_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 11.0 - Previsão de Créditos Adicionais por Decreto ({ano_sel})", expanded=True):
                st.subheader("11.0 • Créditos Adicionais na LOA")
                st.write("**Na Lei Orçamentária Anual (LOA), há previsão para abertura de créditos adicionais por decreto?**")
                st.caption("ℹ *Selecione uma opção, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 11.0'.*")

                opcoes_110 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados do 11.0
                d110 = res_data.get("11.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d110 is None:
                    d110 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_110 = d110.get("valor", "Selecione...")
                evidencia_110_salva = d110.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_110 = f"r_11_0_{ano_sel}"
                chave_link_110 = f"t_11_0_{ano_sel}"
                chave_coment_110 = f"coment_11.0_{ano_sel}"

                c110_1, c110_2 = st.columns([1, 1])

                with c110_1:
                    lista_opcoes_110 = list(opcoes_110.keys())
                    idx110 = lista_opcoes_110.index(val_salvo_110) if val_salvo_110 in lista_opcoes_110 else 0

                    opcao_selecionada_110 = st.radio(
                        "Selecione 11.0:",
                        options=lista_opcoes_110,
                        index=idx110,
                        key=chave_radio_110,
                        label_visibility="collapsed"
                    )

                with c110_2:
                    link_evidencia_110 = st.text_area(
                        "Link/Evidência (11.0):",
                        value=evidencia_110_salva,
                        key=chave_link_110,
                        placeholder="Insira os links comprobatórios referente ao Quesito 11.0...",
                        height=120
                    )
                    placeholder_links_110 = st.empty()
                    links_110_visuais = re.findall(REGEX_PURE_URL, link_evidencia_110 or "")
                    if links_110_visuais:
                        placeholder_links_110.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_110_visuais]
                            )
                        )

                # Bloco de comentários do 11.0
                bloco_comentarios("11.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 11.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 11.0", key=f"btn_salvar_11_0_{ano_sel}", type="primary"):
                    val_para_salvar_110 = opcao_selecionada_110
                    pts_para_salvar_110 = opcoes_110.get(val_para_salvar_110, 0.0)
                    lnk_val_110 = link_evidencia_110.strip()
                    comentario_para_salvar_110 = st.session_state.get(chave_coment_110, d110.get("comentario", ""))

                    # Salvamento principal
                    save_resp(
                        qid="11.0",
                        valor=val_para_salvar_110,
                        pontos=float(pts_para_salvar_110),
                        link=lnk_val_110,
                        comentario=comentario_para_salvar_110
                    )
                    res_data["11.0"] = {
                        "valor": val_para_salvar_110,
                        "pontos": float(pts_para_salvar_110),
                        "link": lnk_val_110,
                        "comentario": comentario_para_salvar_110
                    }

                    # Regra de dependência: Se marcar "Não", reseta o quesito 11.1
                    if val_para_salvar_110 == "Não":
                        save_resp("11.1", "0.0|0.0", 0.0, "")
                        if "11.1" in res_data:
                            res_data["11.1"] = {"valor": "0.0|0.0", "pontos": 0.0, "link": "", "comentario": ""}

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_110 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_110_salva or "")]

                    if lnk_val_110 != evidencia_110_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 11.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição de Impacto de Pontuação
                val_atual_110 = d110.get("valor", "Selecione...")

                if val_atual_110 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 11.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_atual_110}' salva (Impacto: 0.0 pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 11.0
        if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 11.1 • PERCENTUAL DE CRÉDITO SUPLEMENTAR (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_suplementar_11_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 11.1 - Percentual Autorizado para Crédito Adicional Suplementar ({ano_sel})", expanded=True):
                st.subheader("11.1 • Percentual de Crédito Suplementar")
                st.write("**Qual o percentual autorizado na Lei Orçamentária Anual (LOA) para abertura de crédito adicional suplementar?**")
                st.caption("ℹ *Informe os percentuais, links comprobatórios e comentários, e clique em 'Salvar Questão 11.1'.*")

                # Resgate seguro dos dados do 11.1
                d111 = res_data.get("11.1") or {"valor": "0.0|0.0", "pontos": 0.0, "link": "", "comentario": ""}
                if d111 is None:
                    d111 = {"valor": "0.0|0.0", "pontos": 0.0, "link": "", "comentario": ""}

                try:
                    string_valores = d111.get("valor", "0.0|0.0")
                    if "|" not in string_valores:
                        string_valores = f"{string_valores}|0.0"
                    v_loa_salvo, v_inf_salvo = string_valores.split("|")
                    val_loa_inicial = float(v_loa_salvo)
                    val_inf_inicial = float(v_inf_salvo)
                except Exception:
                    val_loa_inicial = 0.0
                    val_inf_inicial = 0.0

                evidencia_111_salva = d111.get("link", "")

                # Chaves fixas por componente e ano
                chave_num_loa = f"q111_loa_{ano_sel}"
                chave_num_inf = f"q111_inf_{ano_sel}"
                chave_link_111 = f"t_11_1_{ano_sel}"
                chave_coment_111 = f"coment_11.1_{ano_sel}"

                c111_1, c111_2 = st.columns([1, 1])

                with c111_1:
                    val_loa_input = st.number_input(
                        "Percentual autorizado na LOA (%):",
                        min_value=0.0,
                        max_value=100.0,
                        value=val_loa_inicial,
                        step=0.01,
                        format="%.2f",
                        key=chave_num_loa
                    )
                    val_inf_input = st.number_input(
                        "Informe a inflação oficial do período (%):",
                        min_value=0.0,
                        max_value=100.0,
                        value=val_inf_inicial,
                        step=0.01,
                        format="%.2f",
                        key=chave_num_inf
                    )

                with c111_2:
                    link_evidencia_111 = st.text_area(
                        "Link/Evidência (11.1):",
                        value=evidencia_111_salva,
                        key=chave_link_111,
                        placeholder="Insira os links comprobatórios referente ao Quesito 11.1...",
                        height=140
                    )
                    placeholder_links_111 = st.empty()
                    links_111_visuais = re.findall(REGEX_PURE_URL, link_evidencia_111 or "")
                    if links_111_visuais:
                        placeholder_links_111.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_111_visuais]
                            )
                        )

                # Bloco de comentários do 11.1
                bloco_comentarios("11.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 11.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 11.1", key=f"btn_salvar_11_1_{ano_sel}", type="primary"):
                    v_loa = float(val_loa_input)
                    v_inf = float(val_inf_input)

                    # Lógica de negócio e pontuação
                    if v_loa == 0.0 and v_inf == 0.0:
                        pts_111 = 0.0
                    else:
                        pts_111 = 6.0 if v_loa <= v_inf else 0.0

                    valor_composto_111 = f"{v_loa}|{v_inf}"
                    lnk_val_111 = link_evidencia_111.strip()
                    comentario_para_salvar_111 = st.session_state.get(chave_coment_111, d111.get("comentario", ""))

                    save_resp(
                        qid="11.1",
                        valor=valor_composto_111,
                        pontos=float(pts_111),
                        link=lnk_val_111,
                        comentario=comentario_para_salvar_111
                    )
                    res_data["11.1"] = {
                        "valor": valor_composto_111,
                        "pontos": float(pts_111),
                        "link": lnk_val_111,
                        "comentario": comentario_para_salvar_111
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_111 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_111_salva or "")]

                    if lnk_val_111 != evidencia_111_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 11.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                v111_salvo = val_loa_inicial
                inf111_salvo = val_inf_inicial
                pts_salvos_111 = d111.get("pontos", 0.0)

                if v111_salvo == 0.0 and inf111_salvo == 0.0:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Aguardando preenchimento dos campos no Quesito 11.1</span>", unsafe_allow_html=True)
                elif v111_salvo <= inf111_salvo:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Salvo com Sucesso - Pontuação: {pts_salvos_111:.1f} pontos (% LOA [{v111_salvo:.2f}%] ≤ Inflação [{inf111_salvo:.2f}%])</span>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"❌ Status: Salvo com Sucesso - Pontuação: {pts_salvos_111:.1f} pontos (% LOA [{v111_salvo:.2f}%] > Inflação [{inf111_salvo:.2f}%])</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 11.1
        if st.session_state.get(f"gatilho_modal_11_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("11.1", st.session_state.get(f"links_pendentes_11_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 12.0 • ESTRUTURA DE PLANEJAMENTO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_estrutura_12_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.0 - Estrutura Administrativa de Planejamento ({ano_sel})", expanded=True):
                st.subheader("12.0 • Estrutura de Planejamento")
                st.write("**Há estrutura administrativa voltada para planejamento?**")
                st.caption("ℹ *Selecione uma opção, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 12.0'.*")

                opcoes_120 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados do 12.0
                d120 = res_data.get("12.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d120 is None:
                    d120 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_120 = d120.get("valor", "Selecione...")
                evidencia_120_salva = d120.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_120 = f"r_12_0_{ano_sel}"
                chave_link_120 = f"t_12_0_{ano_sel}"
                chave_coment_120 = f"coment_12.0_{ano_sel}"

                c120_1, c120_2 = st.columns([1, 1])

                with c120_1:
                    lista_opcoes_120 = list(opcoes_120.keys())
                    idx120 = lista_opcoes_120.index(val_salvo_120) if val_salvo_120 in lista_opcoes_120 else 0

                    opcao_selecionada_120 = st.radio(
                        "Selecione 12.0:",
                        options=lista_opcoes_120,
                        index=idx120,
                        key=chave_radio_120,
                        label_visibility="collapsed"
                    )

                with c120_2:
                    link_evidencia_120 = st.text_area(
                        "Link/Evidência (12.0):",
                        value=evidencia_120_salva,
                        key=chave_link_120,
                        placeholder="Insira os links comprobatórios referente ao Quesito 12.0...",
                        height=120
                    )
                    placeholder_links_120 = st.empty()
                    links_120_visuais = re.findall(REGEX_PURE_URL, link_evidencia_120 or "")
                    if links_120_visuais:
                        placeholder_links_120.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_120_visuais]
                            )
                        )

                # Bloco de comentários do 12.0
                bloco_comentarios("12.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 12.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 12.0", key=f"btn_salvar_12_0_{ano_sel}", type="primary"):
                    val_para_salvar_120 = opcao_selecionada_120
                    pts_para_salvar_120 = opcoes_120.get(val_para_salvar_120, 0.0)
                    lnk_val_120 = link_evidencia_120.strip()
                    comentario_para_salvar_120 = st.session_state.get(chave_coment_120, d120.get("comentario", ""))

                    # Salvamento principal
                    save_resp(
                        qid="12.0",
                        valor=val_para_salvar_120,
                        pontos=float(pts_para_salvar_120),
                        link=lnk_val_120,
                        comentario=comentario_para_salvar_120
                    )
                    res_data["12.0"] = {
                        "valor": val_para_salvar_120,
                        "pontos": float(pts_para_salvar_120),
                        "link": lnk_val_120,
                        "comentario": comentario_para_salvar_120
                    }

                    # Cascata de limpeza síncrona e segura se alterado para "Não"
                    if val_para_salvar_120 == "Não":
                        save_resp("12.1", "Não", 0.0, "")
                        save_resp("12.1.1", "", 0.0, "")
                        save_resp("12.1.2", "", 0.0, "")

                        if "12.1" in res_data:
                            res_data["12.1"] = {"valor": "Não", "pontos": 0.0, "link": "", "comentario": ""}
                        if "12.1.1" in res_data:
                            res_data["12.1.1"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                        if "12.1.2" in res_data:
                            res_data["12.1.2"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_120 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_120_salva or "")]

                    if lnk_val_120 != evidencia_120_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 12.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                val_atual_120 = d120.get("valor", "Selecione...")

                if val_atual_120 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 12.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_atual_120}' salva (Impacto: 0.0 pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 12.0
        if st.session_state.get(f"gatilho_modal_12_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.0", st.session_state.get(f"links_pendentes_12_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 12.1 • RH DE PLANEJAMENTO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_rh_planejamento_12_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.1 - Recursos Humanos para Atividades de Planejamento ({ano_sel})", expanded=True):
                st.subheader("12.1 • RH de Planejamento")
                st.write("**A prefeitura dispõe de recursos humanos para operacionalização das atividades de planejamento?**")
                st.caption("ℹ *Selecione uma opção, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 12.1'.*")

                opcoes_121 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados do 12.1
                d121 = res_data.get("12.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d121 is None:
                    d121 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_121 = d121.get("valor", "Selecione...")
                evidencia_121_salva = d121.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_121 = f"r_12_1_{ano_sel}"
                chave_link_121 = f"t_12_1_{ano_sel}"
                chave_coment_121 = f"coment_12.1_{ano_sel}"

                c121_1, c121_2 = st.columns([1, 1])

                with c121_1:
                    lista_opcoes_121 = list(opcoes_121.keys())
                    idx121 = lista_opcoes_121.index(val_salvo_121) if val_salvo_121 in lista_opcoes_121 else 0

                    opcao_selecionada_121 = st.radio(
                        "Selecione 12.1:",
                        options=lista_opcoes_121,
                        index=idx121,
                        key=chave_radio_121,
                        label_visibility="collapsed"
                    )

                with c121_2:
                    link_evidencia_121 = st.text_area(
                        "Link/Evidência (12.1):",
                        value=evidencia_121_salva,
                        key=chave_link_121,
                        placeholder="Insira os links comprobatórios referente ao Quesito 12.1...",
                        height=120
                    )
                    placeholder_links_121 = st.empty()
                    links_121_visuais = re.findall(REGEX_PURE_URL, link_evidencia_121 or "")
                    if links_121_visuais:
                        placeholder_links_121.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_121_visuais]
                            )
                        )

                # Bloco de comentários do 12.1
                bloco_comentarios("12.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 12.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 12.1", key=f"btn_salvar_12_1_{ano_sel}", type="primary"):
                    val_para_salvar_121 = opcao_selecionada_121
                    pts_para_salvar_121 = opcoes_121.get(val_para_salvar_121, 0.0)
                    lnk_val_121 = link_evidencia_121.strip()
                    comentario_para_salvar_121 = st.session_state.get(chave_coment_121, d121.get("comentario", ""))

                    # Salvamento principal
                    save_resp(
                        qid="12.1",
                        valor=val_para_salvar_121,
                        pontos=float(pts_para_salvar_121),
                        link=lnk_val_121,
                        comentario=comentario_para_salvar_121
                    )
                    res_data["12.1"] = {
                        "valor": val_para_salvar_121,
                        "pontos": float(pts_para_salvar_121),
                        "link": lnk_val_121,
                        "comentario": comentario_para_salvar_121
                    }

                    # Limpeza em cascata dos subníveis inferiores caso selecionado "Não"
                    if val_para_salvar_121 == "Não":
                        save_resp("12.1.1", "", 0.0, "")
                        save_resp("12.1.2", "", 0.0, "")

                        if "12.1.1" in res_data:
                            res_data["12.1.1"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                        if "12.1.2" in res_data:
                            res_data["12.1.2"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_121 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_121_salva or "")]

                    if lnk_val_121 != evidencia_121_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 12.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                val_atual_121 = d121.get("valor", "Selecione...")

                if val_atual_121 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 12.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_atual_121}' salva (Impacto: 0.0 pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 12.1
        if st.session_state.get(f"gatilho_modal_12_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.1", st.session_state.get(f"links_pendentes_12_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 12.1.1 • QUALIFICAÇÃO DA EQUIPE (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_rh_planejamento_12_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.1.1 - Qualificação Técnica da Equipe de Planejamento ({ano_sel})", expanded=True):
                st.subheader("12.1.1 • Qualificação da Equipe")
                st.write("**Os servidores da equipe de planejamento possuem qualificação técnica para o exercício das atividades de planejamento, gestão e orçamento?**")
                st.caption("ℹ *Selecione uma opção, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 12.1.1'.*")

                opcoes_1211 = {
                    "Selecione...": 0.0,
                    "Sim, todos os servidores possuem qualificação técnica – 00": 0.0,
                    "Sim, a maior parte dos servidores possuem qualificação técnica – -05 (perde 05 pontos)": -5.0,
                    "Sim, a menor parte dos servidores possuem qualificação técnica – -08 (perde 08 pontos)": -8.0,
                    "Não – -10 (perde 10 pontos)": -10.0
                }

                # Resgate seguro dos dados do 12.1.1
                d1211 = res_data.get("12.1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d1211 is None:
                    d1211 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1211 = d1211.get("valor", "Selecione...")
                evidencia_1211_salva = d1211.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_1211 = f"r_12_1_1_{ano_sel}"
                chave_link_1211 = f"t_12_1_1_{ano_sel}"
                chave_coment_1211 = f"coment_12.1.1_{ano_sel}"

                c1211_1, c1211_2 = st.columns([1, 1])

                with c1211_1:
                    lista_opcoes_1211 = list(opcoes_1211.keys())
                    idx1211 = lista_opcoes_1211.index(val_salvo_1211) if val_salvo_1211 in lista_opcoes_1211 else 0

                    opcao_selecionada_1211 = st.radio(
                        "Selecione 12.1.1:",
                        options=lista_opcoes_1211,
                        index=idx1211,
                        key=chave_radio_1211,
                        label_visibility="collapsed"
                    )

                with c1211_2:
                    link_evidencia_1211 = st.text_area(
                        "Link/Evidência (12.1.1):",
                        value=evidencia_1211_salva,
                        key=chave_link_1211,
                        placeholder="Insira os links comprobatórios referente ao Quesito 12.1.1...",
                        height=120
                    )
                    placeholder_links_1211 = st.empty()
                    links_1211_visuais = re.findall(REGEX_PURE_URL, link_evidencia_1211 or "")
                    if links_1211_visuais:
                        placeholder_links_1211.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1211_visuais]
                            )
                        )

                # Bloco de comentários do 12.1.1
                bloco_comentarios("12.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 12.1.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 12.1.1", key=f"btn_salvar_12_1_1_{ano_sel}", type="primary"):
                    val_para_salvar_1211 = opcao_selecionada_1211
                    pts_para_salvar_1211 = opcoes_1211.get(val_para_salvar_1211, 0.0)
                    lnk_val_1211 = link_evidencia_1211.strip()
                    comentario_para_salvar_1211 = st.session_state.get(chave_coment_1211, d1211.get("comentario", ""))

                    # Salvamento principal
                    save_resp(
                        qid="12.1.1",
                        valor=val_para_salvar_1211,
                        pontos=float(pts_para_salvar_1211),
                        link=lnk_val_1211,
                        comentario=comentario_para_salvar_1211
                    )
                    res_data["12.1.1"] = {
                        "valor": val_para_salvar_1211,
                        "pontos": float(pts_para_salvar_1211),
                        "link": lnk_val_1211,
                        "comentario": comentario_para_salvar_1211
                    }

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1211 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1211_salva or "")]

                    if lnk_val_1211 != evidencia_1211_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 12.1.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                val_atual_1211 = d1211.get("valor", "Selecione...")
                pts_atuais_1211 = d1211.get("pontos", 0.0)

                if val_atual_1211 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 12.1.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_atual_1211}' salva (Impacto: {pts_atuais_1211:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 12.1.1
        if st.session_state.get(f"gatilho_modal_12_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.1.1", st.session_state.get(f"links_pendentes_12_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 12.1.2 • TREINAMENTO DE SERVIDORES (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_rh_planejamento_12_1_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.1.2 - Treinamento Periódico para Planejamento ({ano_sel})", expanded=True):
                st.subheader("12.1.2 • Treinamento de Servidores")
                st.write("**Os servidores responsáveis pelo planejamento recebem treinamento específico para a matéria? Treinamento periódico pelo menos 1 vez ao ano.**")
                st.caption("ℹ *Selecione uma opção, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 12.1.2'.*")

                opcoes_1212 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -10 (perde 10 pontos)": -10.0
                }

                # Resgate seguro dos dados do 12.1.2
                d1212 = res_data.get("12.1.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d1212 is None:
                    d1212 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1212 = d1212.get("valor", "Selecione...")
                evidencia_1212_salva = d1212.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_1212 = f"r_12_1_2_{ano_sel}"
                chave_link_1212 = f"t_12_1_2_{ano_sel}"
                chave_coment_1212 = f"coment_12.1.2_{ano_sel}"

                c1212_1, c1212_2 = st.columns([1, 1])

                with c1212_1:
                    lista_opcoes_1212 = list(opcoes_1212.keys())
                    idx1212 = lista_opcoes_1212.index(val_salvo_1212) if val_salvo_1212 in lista_opcoes_1212 else 0

                    opcao_selecionada_1212 = st.radio(
                        "Selecione 12.1.2:",
                        options=lista_opcoes_1212,
                        index=idx1212,
                        key=chave_radio_1212,
                        label_visibility="collapsed"
                    )

                with c1212_2:
                    link_evidencia_1212 = st.text_area(
                        "Link/Evidência (12.1.2):",
                        value=evidencia_1212_salva,
                        key=chave_link_1212,
                        placeholder="Insira os links comprobatórios referente ao Quesito 12.1.2...",
                        height=120
                    )
                    placeholder_links_1212 = st.empty()
                    links_1212_visuais = re.findall(REGEX_PURE_URL, link_evidencia_1212 or "")
                    if links_1212_visuais:
                        placeholder_links_1212.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1212_visuais]
                            )
                        )

                # Bloco de comentários do 12.1.2
                bloco_comentarios("12.1.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 12.1.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 12.1.2", key=f"btn_salvar_12_1_2_{ano_sel}", type="primary"):
                    val_para_salvar_1212 = opcao_selecionada_1212
                    pts_para_salvar_1212 = opcoes_1212.get(val_para_salvar_1212, 0.0)
                    lnk_val_1212 = link_evidencia_1212.strip()
                    comentario_para_salvar_1212 = st.session_state.get(chave_coment_1212, d1212.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="12.1.2",
                        valor=val_para_salvar_1212,
                        pontos=float(pts_para_salvar_1212),
                        link=lnk_val_1212,
                        comentario=comentario_para_salvar_1212
                    )
                    res_data["12.1.2"] = {
                        "valor": val_para_salvar_1212,
                        "pontos": float(pts_para_salvar_1212),
                        "link": lnk_val_1212,
                        "comentario": comentario_para_salvar_1212
                    }

                    # Detecção de novos links para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1212 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1212_salva or "")]

                    if lnk_val_1212 != evidencia_1212_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 12.1.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                val_atual_1212 = d1212.get("valor", "Selecione...")
                pts_atuais_1212 = d1212.get("pontos", 0.0)

                if val_atual_1212 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 12.1.2</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_atual_1212}' salva (Impacto: {pts_atuais_1212:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 12.1.2
        if st.session_state.get(f"gatilho_modal_12_1_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.1.2", st.session_state.get(f"links_pendentes_12_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = False
