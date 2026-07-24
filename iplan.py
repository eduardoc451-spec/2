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

        # -----------------------------------------------------------------------------
        # QUESITO 13.0 • ACOMPANHAMENTO DA EXECUÇÃO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_acompanhamento_13_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.0 - Acompanhamento da Execução do Planejamento ({ano_sel})", expanded=True):
                st.subheader("13.0 • Acompanhamento da Execução")
                st.write("**Há acompanhamento da execução do planejamento?**")
                st.caption("ℹ *Selecione uma opção, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 13.0'.*")

                opcoes_130 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados do 13.0
                d130 = res_data.get("13.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d130 is None:
                    d130 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_130 = d130.get("valor", "Selecione...")
                evidencia_130_salva = d130.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_130 = f"r_13_0_{ano_sel}"
                chave_link_130 = f"t_13_0_{ano_sel}"
                chave_coment_130 = f"coment_13.0_{ano_sel}"

                c130_1, c130_2 = st.columns([1, 1])

                with c130_1:
                    lista_opcoes_130 = list(opcoes_130.keys())
                    idx130 = lista_opcoes_130.index(val_salvo_130) if val_salvo_130 in lista_opcoes_130 else 0

                    opcao_selecionada_130 = st.radio(
                        "Selecione 13.0:",
                        options=lista_opcoes_130,
                        index=idx130,
                        key=chave_radio_130,
                        label_visibility="collapsed"
                    )

                with c130_2:
                    link_evidencia_130 = st.text_area(
                        "Link/Evidência (13.0):",
                        value=evidencia_130_salva,
                        key=chave_link_130,
                        placeholder="Insira os links comprobatórios referente ao Quesito 13.0...",
                        height=120
                    )
                    placeholder_links_130 = st.empty()
                    links_130_visuais = re.findall(REGEX_PURE_URL, link_evidencia_130 or "")
                    if links_130_visuais:
                        placeholder_links_130.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_130_visuais]
                            )
                        )

                # Bloco de comentários do 13.0
                bloco_comentarios("13.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 13.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 13.0", key=f"btn_salvar_13_0_{ano_sel}", type="primary"):
                    val_para_salvar_130 = opcao_selecionada_130
                    pts_para_salvar_130 = opcoes_130.get(val_para_salvar_130, 0.0)
                    lnk_val_130 = link_evidencia_130.strip()
                    comentario_para_salvar_130 = st.session_state.get(chave_coment_130, d130.get("comentario", ""))

                    # Salvamento principal
                    save_resp(
                        qid="13.0",
                        valor=val_para_salvar_130,
                        pontos=float(pts_para_salvar_130),
                        link=lnk_val_130,
                        comentario=comentario_para_salvar_130
                    )
                    res_data["13.0"] = {
                        "valor": val_para_salvar_130,
                        "pontos": float(pts_para_salvar_130),
                        "link": lnk_val_130,
                        "comentario": comentario_para_salvar_130
                    }

                    # Regra de limpeza em cascata para subníveis inferiores caso selecionado "Não"
                    if val_para_salvar_130 == "Não":
                        save_resp(qid="13.1", valor="[]", pontos=0.0, link="", comentario="")
                        save_resp(qid="13.1.1", valor="[]", pontos=0.0, link="", comentario="")
                        save_resp(qid="13.1.1.1", valor="", pontos=0.0, link="", comentario="")

                        if "13.1" in res_data:
                            res_data["13.1"] = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                        if "13.1.1" in res_data:
                            res_data["13.1.1"] = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                        if "13.1.1.1" in res_data:
                            res_data["13.1.1.1"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                    # Verificação de alteração de links para disparo do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_130 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_130_salva or "")]

                    if lnk_val_130 != evidencia_130_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 13.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                val_atual_130 = d130.get("valor", "Selecione...")
                pts_atuais_130 = d130.get("pontos", 0.0)

                if val_atual_130 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 13.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_atual_130}' salva (Impacto: {pts_atuais_130:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 13.0
        if st.session_state.get(f"gatilho_modal_13_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.0", st.session_state.get(f"links_pendentes_13_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 13.1 • AUDIÊNCIAS PÚBLICAS DE METAS FISCAIS (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_metas_fiscais_13_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.1 - Audiências Públicas de Metas Fiscais ({ano_sel})", expanded=True):
                st.subheader("13.1 • Metas Fiscais e Audiências")
                st.write("**A prefeitura demonstra e avalia, com periodicidade quadrimestral, o cumprimento das metas fiscais em audiências públicas?** *(Art. 9º, § 4º, da LRF)*")
                st.caption("ℹ *Selecione as opções cabíveis, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 13.1'.*")

                opc131 = {
                    "Realizou Audiência pública do 1º Quadrimestre até o final do mês de maio de 2025 – 02": 2.0,
                    "Realizou Audiência pública do 2º Quadrimestre até o final do mês de setembro de 2025 – 02": 2.0,
                    "Realizou Audiência pública do 3º Quadrimestre até o final do mês de fevereiro de 2026 – 02": 2.0,
                    "Não realizou audiência pública quadrimestral dentro do prazo – 00": 0.0,
                    "Não realizou nenhuma audiência pública quadrimestral na Câmara Municipal – -10 (perde 10 pontos)": -10.0
                }

                # Resgate seguro dos dados do 13.1
                d131 = res_data.get("13.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d131 is None:
                    d131 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_131 = d131.get("valor", "[]")
                evidencia_131_salva = d131.get("link", "")

                # Desserialização segura da lista salva
                try:
                    lista_salva_131 = ast.literal_eval(val_salvo_131)
                    if not isinstance(lista_salva_131, list):
                        lista_salva_131 = []
                except Exception:
                    lista_salva_131 = []

                # Chaves fixas por componente e ano
                chave_link_131 = f"t_131_{ano_sel}"
                chave_coment_131 = f"coment_13.1_{ano_sel}"

                c131_1, c131_2 = st.columns([1, 1])

                with c131_1:
                    sel131_atuais = []
                    for idx, (opt, pt) in enumerate(opc131.items()):
                        v_antigo = opt in lista_salva_131
                        chave_ck = f"ck_131_opt_{idx}_{ano_sel}"
                        v_novo = st.checkbox(opt, value=v_antigo, key=chave_ck)
                        if v_novo:
                            sel131_atuais.append(opt)

                with c131_2:
                    link_evidencia_131 = st.text_area(
                        "Link/Evidência (13.1):",
                        value=evidencia_131_salva,
                        key=chave_link_131,
                        placeholder="Insira os links comprobatórios referente ao Quesito 13.1...",
                        height=140
                    )
                    placeholder_links_131 = st.empty()
                    links_131_visuais = re.findall(REGEX_PURE_URL, link_evidencia_131 or "")
                    if links_131_visuais:
                        placeholder_links_131.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_131_visuais]
                            )
                        )

                # Bloco de comentários do 13.1
                bloco_comentarios("13.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 13.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 13.1", key=f"btn_salvar_13_1_{ano_sel}", type="primary"):
                    # Cálculo da regra de negócio do 13.1 no momento do salvamento
                    if any("Não realizou nenhuma" in p for p in sel131_atuais):
                        pts131_salvar = -10.0
                    elif any("dentro do prazo" in p for p in sel131_atuais):
                        pts131_salvar = 0.0
                    else:
                        pts131_salvar = sum(opc131[p] for p in sel131_atuais)

                    str_sel131_salvar = str(sel131_atuais)
                    lnk_val_131 = link_evidencia_131.strip()
                    comentario_para_salvar_131 = st.session_state.get(chave_coment_131, d131.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="13.1",
                        valor=str_sel131_salvar,
                        pontos=float(pts131_salvar),
                        link=lnk_val_131,
                        comentario=comentario_para_salvar_131
                    )
                    res_data["13.1"] = {
                        "valor": str_sel131_salvar,
                        "pontos": float(pts131_salvar),
                        "link": lnk_val_131,
                        "comentario": comentario_para_salvar_131
                    }

                    # Detecção de novos links para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_131 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_131_salva or "")]

                    if lnk_val_131 != evidencia_131_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 13.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                pts_atuais_131 = d131.get("pontos", 0.0)

                if val_salvo_131 == "[]" or not lista_salva_131:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 13.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção(ões) salva(s) com sucesso (Impacto: {pts_atuais_131:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 13.1
        if st.session_state.get(f"gatilho_modal_13_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.1", st.session_state.get(f"links_pendentes_13_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 13.1.1 • RELATÓRIOS QUADRIMESTRAIS (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_relatorios_13_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.1.1 - Elaboração de Relatórios Quadrimestrais ({ano_sel})", expanded=True):
                st.subheader("13.1.1 • Relatórios Quadrimestrais")
                st.write("**Foram elaborados os Relatórios Quadrimestrais das metas fiscais para as audiências públicas?**")
                st.caption("ℹ *Selecione as opções cabíveis, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 13.1.1'.*")

                opc1311 = {
                    "Relatório da Audiência pública do 1º Quadrimestre – 01": 1.0,
                    "Relatório da Audiência pública do 2º Quadrimestre – 01": 1.0,
                    "Relatório da Audiência pública do 3º Quadrimestre – 01": 1.0,
                    "Não elaborou relatório de nenhuma audiência pública quadrimestral – 00": 0.0
                }

                # Resgate seguro dos dados do 13.1.1
                d1311 = res_data.get("13.1.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d1311 is None:
                    d1311 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1311 = d1311.get("valor", "[]")
                evidencia_1311_salva = d1311.get("link", "")

                # Desserialização segura da lista salva
                try:
                    lista_salva_1311 = ast.literal_eval(val_salvo_1311)
                    if not isinstance(lista_salva_1311, list):
                        lista_salva_1311 = []
                except Exception:
                    lista_salva_1311 = []

                # Chaves fixas por componente e ano
                chave_link_1311 = f"t_1311_{ano_sel}"
                chave_coment_1311 = f"coment_13.1.1_{ano_sel}"

                c1311_1, c1311_2 = st.columns([1, 1])

                with c1311_1:
                    sel1311_atuais = []
                    for idx, (opt, pt) in enumerate(opc1311.items()):
                        v_antigo = opt in lista_salva_1311
                        chave_ck = f"ck_1311_opt_{idx}_{ano_sel}"
                        v_novo = st.checkbox(opt, value=v_antigo, key=chave_ck)
                        if v_novo:
                            sel1311_atuais.append(opt)

                with c1311_2:
                    link_evidencia_1311 = st.text_area(
                        "Link/Evidência (13.1.1):",
                        value=evidencia_1311_salva,
                        key=chave_link_1311,
                        placeholder="Insira os links comprobatórios referente ao Quesito 13.1.1...",
                        height=140
                    )
                    placeholder_links_1311 = st.empty()
                    links_1311_visuais = re.findall(REGEX_PURE_URL, link_evidencia_1311 or "")
                    if links_1311_visuais:
                        placeholder_links_1311.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1311_visuais]
                            )
                        )

                # Bloco de comentários do 13.1.1
                bloco_comentarios("13.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 13.1.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 13.1.1", key=f"btn_salvar_13_1_1_{ano_sel}", type="primary"):
                    # Cálculo da regra de negócio no momento do salvamento
                    if any("Não elaborou" in p for p in sel1311_atuais):
                        pts1311_salvar = 0.0
                    else:
                        pts1311_salvar = sum(opc1311[p] for p in sel1311_atuais)

                    str_sel1311_salvar = str(sel1311_atuais)
                    lnk_val_1311 = link_evidencia_1311.strip()
                    comentario_para_salvar_1311 = st.session_state.get(chave_coment_1311, d1311.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="13.1.1",
                        valor=str_sel1311_salvar,
                        pontos=float(pts1311_salvar),
                        link=lnk_val_1311,
                        comentario=comentario_para_salvar_1311
                    )
                    res_data["13.1.1"] = {
                        "valor": str_sel1311_salvar,
                        "pontos": float(pts1311_salvar),
                        "link": lnk_val_1311,
                        "comentario": comentario_para_salvar_1311
                    }

                    # Detecção de novos links para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1311 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1311_salva or "")]

                    if lnk_val_1311 != evidencia_1311_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 13.1.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                pts_atuais_1311 = d1311.get("pontos", 0.0)

                if val_salvo_1311 == "[]" or not lista_salva_1311:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 13.1.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção(ões) salva(s) com sucesso (Impacto: {pts_atuais_1311:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 13.1.1
        if st.session_state.get(f"gatilho_modal_13_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.1.1", st.session_state.get(f"links_pendentes_13_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 13.1.1.1 • PÁGINA ELETRÔNICA DE DIVULGAÇÃO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_url_divulgacao_13_1_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.1.1.1 - Página Eletrônica de Divulgação ({ano_sel})", expanded=True):
                st.subheader("13.1.1.1 • URL de Divulgação")
                st.write("**Informe a página eletrônica (link na internet) de divulgação dos Relatórios Quadrimestrais de Metas Fiscais:** *(Insira XYZ se indisponível)*")
                st.caption("ℹ *Informe a URL de divulgação, acrescente os links comprobatórios e comentários, e clique em 'Salvar Questão 13.1.1.1'.*")

                # Resgate seguro dos dados do 13.1.1.1
                d13111 = res_data.get("13.1.1.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                if d13111 is None:
                    d13111 = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_13111 = d13111.get("valor", "")
                evidencia_13111_salva = d13111.get("link", "")

                # Chaves fixas por componente e ano
                chave_input_13111 = f"i_13111_{ano_sel}"
                chave_link_13111 = f"t_13111_{ano_sel}"
                chave_coment_13111 = f"coment_13.1.1.1_{ano_sel}"

                c13111_1, c13111_2 = st.columns([1, 1])

                with c13111_1:
                    url_divulgacao_13111 = st.text_input(
                        "Link URL (Relatórios):",
                        value=val_salvo_13111,
                        key=chave_input_13111,
                        placeholder="https://... ou XYZ"
                    )

                with c13111_2:
                    link_evidencia_13111 = st.text_area(
                        "Link/Evidência (13.1.1.1):",
                        value=evidencia_13111_salva,
                        key=chave_link_13111,
                        placeholder="Insira os links comprobatórios referente ao Quesito 13.1.1.1...",
                        height=100
                    )
                    placeholder_links_13111 = st.empty()
                    links_13111_visuais = re.findall(REGEX_PURE_URL, link_evidencia_13111 or "")
                    if links_13111_visuais:
                        placeholder_links_13111.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_13111_visuais]
                            )
                        )

                # Bloco de comentários do 13.1.1.1
                bloco_comentarios("13.1.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 13.1.1.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 13.1.1.1", key=f"btn_salvar_13_1_1_1_{ano_sel}", type="primary"):
                    val_input_trim = url_divulgacao_13111.strip()

                    # Regra de negócio: 2.0 pontos se preenchido e diferente de "XYZ"
                    if val_input_trim and val_input_trim.upper() != "XYZ":
                        pts13111_salvar = 2.0
                    else:
                        pts13111_salvar = 0.0

                    lnk_val_13111 = link_evidencia_1311.strip()
                    comentario_para_salvar_13111 = st.session_state.get(chave_coment_13111, d13111.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="13.1.1.1",
                        valor=val_input_trim,
                        pontos=float(pts13111_salvar),
                        link=lnk_val_13111,
                        comentario=comentario_para_salvar_13111
                    )
                    res_data["13.1.1.1"] = {
                        "valor": val_input_trim,
                        "pontos": float(pts13111_salvar),
                        "link": lnk_val_13111,
                        "comentario": comentario_para_salvar_13111
                    }

                    # Detecção de novos links para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_13111 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_13111_salva or "")]

                    if lnk_val_13111 != evidencia_13111_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_1_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 13.1.1.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                pts_atuais_13111 = d13111.get("pontos", 0.0)

                if not val_salvo_1311:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma URL de divulgação cadastrada no Quesito 13.1.1.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: URL salva com sucesso (Impacto: {pts_atuais_13111:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 13.1.1.1
        if st.session_state.get(f"gatilho_modal_13_1_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.1.1.1", st.session_state.get(f"links_pendentes_13_1_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 13.2 • ACOMPANHAMENTO MENSAL (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_acompanhamento_13_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.2 - Acompanhamento Mensal com Participação do Prefeito ({ano_sel})", expanded=True):
                st.subheader("13.2 • Acompanhamento Mensal")
                st.write("**Houve acompanhamento mensal da execução orçamentária com participação do Prefeito?**")
                st.caption("ℹ *Selecione a opção desejada, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 13.2'.*")

                opcoes_132 = {
                    "Selecione...": 0.0,
                    "Sim – 04": 4.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 13.2
                d132 = res_data.get("13.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d132 is None:
                    d132 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_132 = d132.get("valor", "Selecione...")
                evidencia_132_salva = d132.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_132 = f"r_132_{ano_sel}"
                chave_link_132 = f"t_132_{ano_sel}"
                chave_coment_132 = f"coment_13.2_{ano_sel}"

                c132_1, c132_2 = st.columns([1, 1])

                with c132_1:
                    lista_opcoes_132 = list(opcoes_132.keys())
                    idx132 = lista_opcoes_132.index(val_salvo_132) if val_salvo_132 in lista_opcoes_132 else 0

                    sel_radio_132 = st.radio(
                        "Selecione 13.2:",
                        options=lista_opcoes_132,
                        index=idx132,
                        key=chave_radio_132,
                        label_visibility="collapsed"
                    )

                with c132_2:
                    link_evidencia_132 = st.text_area(
                        "Link/Evidência (13.2):",
                        value=evidencia_132_salva,
                        key=chave_link_132,
                        placeholder="Insira os links comprobatórios referente ao Quesito 13.2...",
                        height=100
                    )
                    placeholder_links_132 = st.empty()
                    links_132_visuais = re.findall(REGEX_PURE_URL, link_evidencia_132 or "")
                    if links_132_visuais:
                        placeholder_links_132.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_132_visuais]
                            )
                        )

                # Bloco de comentários do 13.2
                bloco_comentarios("13.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 13.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 13.2", key=f"btn_salvar_13_2_{ano_sel}", type="primary"):
                    pts132_salvar = opcoes_132.get(sel_radio_132, 0.0)
                    lnk_val_132 = link_evidencia_132.strip()
                    comentario_para_salvar_132 = st.session_state.get(chave_coment_132, d132.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="13.2",
                        valor=sel_radio_132,
                        pontos=float(pts132_salvar),
                        link=lnk_val_132,
                        comentario=comentario_para_salvar_132
                    )
                    res_data["13.2"] = {
                        "valor": sel_radio_132,
                        "pontos": float(pts132_salvar),
                        "link": lnk_val_132,
                        "comentario": comentario_para_salvar_132
                    }

                    # Detecção de novos links para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_132 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_132_salva or "")]

                    if lnk_val_132 != evidencia_132_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 13.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                pts_atuais_132 = d132.get("pontos", 0.0)

                if val_salvo_132 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 13.2</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_132:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 13.2
        if st.session_state.get(f"gatilho_modal_13_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.2", st.session_state.get(f"links_pendentes_13_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 13.3 • RETROALIMENTAÇÃO DO REPLANEJAMENTO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_retroalimentacao_13_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.3 - Retroalimentação do Replanejamento Orçamentário ({ano_sel})", expanded=True):
                st.subheader("13.3 • Retroalimentação para o Replanejamento")
                st.write("**O acompanhamento e avaliação da execução orçamentária serve de retroalimentação para o replanejamento dos programas e metas das peças orçamentárias?**")
                st.caption("ℹ *Selecione a opção desejada, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 13.3'.*")

                opcoes_133 = {
                    "Selecione...": 0.0,
                    "Sim, com emissão de relatórios e ciência do prefeito – 20": 20.0,
                    "Sim, com emissão de relatório e sem ciência do prefeito – 10": 10.0,
                    "Sim, sem emissão de relatório e sem ciência do prefeito – 05": 5.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 13.3
                d133 = res_data.get("13.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d133 is None:
                    d133 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_133 = d133.get("valor", "Selecione...")
                evidencia_133_salva = d133.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_133 = f"r_133_{ano_sel}"
                chave_link_133 = f"t_133_{ano_sel}"
                chave_coment_133 = f"coment_13.3_{ano_sel}"

                c133_1, c133_2 = st.columns([1, 1])

                with c133_1:
                    lista_opcoes_133 = list(opcoes_133.keys())
                    idx133 = lista_opcoes_133.index(val_salvo_133) if val_salvo_133 in lista_opcoes_133 else 0

                    sel_radio_133 = st.radio(
                        "Selecione 13.3:",
                        options=lista_opcoes_133,
                        index=idx133,
                        key=chave_radio_133,
                        label_visibility="collapsed"
                    )

                with c133_2:
                    link_evidencia_133 = st.text_area(
                        "Link/Evidência (13.3):",
                        value=evidencia_133_salva,
                        key=chave_link_133,
                        placeholder="Insira os links comprobatórios referente ao Quesito 13.3...",
                        height=120
                    )
                    placeholder_links_133 = st.empty()
                    links_133_visuais = re.findall(REGEX_PURE_URL, link_evidencia_133 or "")
                    if links_133_visuais:
                        placeholder_links_133.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_133_visuais]
                            )
                        )

                # Bloco de comentários do 13.3
                bloco_comentarios("13.3", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 13.3
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 13.3", key=f"btn_salvar_13_3_{ano_sel}", type="primary"):
                    pts133_salvar = opcoes_133.get(sel_radio_133, 0.0)
                    lnk_val_133 = link_evidencia_133.strip()
                    comentario_para_salvar_133 = st.session_state.get(chave_coment_133, d133.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="13.3",
                        valor=sel_radio_133,
                        pontos=float(pts133_salvar),
                        link=lnk_val_133,
                        comentario=comentario_para_salvar_133
                    )
                    res_data["13.3"] = {
                        "valor": sel_radio_133,
                        "pontos": float(pts133_salvar),
                        "link": lnk_val_133,
                        "comentario": comentario_para_salvar_133
                    }

                    # Detecção de novos links para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_133 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_133_salva or "")]

                    if lnk_val_133 != evidencia_133_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 13.3 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto da Pontuação
                pts_atuais_133 = d133.get("pontos", 0.0)

                if val_salvo_133 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 13.3</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_133:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 13.3
        if st.session_state.get(f"gatilho_modal_13_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.3", st.session_state.get(f"links_pendentes_13_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_3_{ano_sel}"] = False

        # =============================================================================
        # SEÇÃO 14: SISTEMA DE CONTROLE INTERNO
        # =============================================================================

        # --- QUESITO 14.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_controle_interno_14_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.0 - Instituição e Regulamentação do Sistema de Controle Interno ({ano_sel})", expanded=True):
                st.subheader("14.0 • Sistema de Controle Interno")
                st.write("**Houve a instituição e regulamentação das operações do Sistema de Controle Interno?**")
                st.caption("ℹ *Selecione a opção desejada, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 14.0'.*")

                opcoes_140 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados do 14.0
                d140 = res_data.get("14.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d140 is None:
                    d140 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_140 = d140.get("valor", "Selecione...")
                evidencia_140_salva = d140.get("link", "")

                # Chaves estáticas e seguras por componente e ano
                chave_radio_140 = f"r_140_{ano_sel}"
                chave_link_140 = f"t_140_{ano_sel}"
                chave_coment_140 = f"coment_14.0_{ano_sel}"

                c140_1, c140_2 = st.columns([1, 1])

                with c140_1:
                    lista_opcoes_140 = list(opcoes_140.keys())
                    idx140 = lista_opcoes_140.index(val_salvo_140) if val_salvo_140 in lista_opcoes_140 else 0

                    sel_radio_140 = st.radio(
                        "Selecione 14.0:",
                        options=lista_opcoes_140,
                        index=idx140,
                        key=chave_radio_140,
                        label_visibility="collapsed"
                    )

                with c140_2:
                    link_evidencia_140 = st.text_area(
                        "Link/Evidência (14.0):",
                        value=evidencia_140_salva,
                        key=chave_link_140,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.0...",
                        height=100
                    )
                    placeholder_links_140 = st.empty()
                    links_140_visuais = re.findall(REGEX_PURE_URL, link_evidencia_140 or "")
                    if links_140_visuais:
                        placeholder_links_140.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_140_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.0
                bloco_comentarios("14.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.0", key=f"btn_salvar_14_0_{ano_sel}", type="primary"):
                    pts140_salvar = opcoes_140.get(sel_radio_140, 0.0)
                    lnk_val_140 = link_evidencia_140.strip()
                    comentario_para_salvar_140 = st.session_state.get(chave_coment_140, d140.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="14.0",
                        valor=sel_radio_140,
                        pontos=float(pts140_salvar),
                        link=lnk_val_140,
                        comentario=comentario_para_salvar_140
                    )
                    res_data["14.0"] = {
                        "valor": sel_radio_140,
                        "pontos": float(pts140_salvar),
                        "link": lnk_val_140,
                        "comentario": comentario_para_salvar_140
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_140 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_140_salva or "")]

                    if lnk_val_140 != evidencia_140_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_140 = d140.get("pontos", 0.0)

                if val_salvo_140 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_140:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.0
        if st.session_state.get(f"gatilho_modal_14_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.0", st.session_state.get(f"links_pendentes_14_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.1 • INSTRUMENTO NORMATIVO DE REGULAMENTAÇÃO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_regulamentacao_14_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.1 - Instrumento Normativo de Regulamentação ({ano_sel})", expanded=True):
                st.subheader("14.1 • Instrumento Normativo")
                st.write("**Informe o instrumento normativo de regulamentação do Sistema de Controle Interno, Número e Data da publicação:**")
                st.caption("ℹ *Preencha os campos abaixo, informe os links comprobatórios e comentários, e clique em 'Salvar Questão 14.1'.*")

                # Resgate seguro dos dados do 14.1
                d141 = res_data.get("14.1") or {"valor": "||", "pontos": 0.0, "link": "", "comentario": ""}
                if d141 is None:
                    d141 = {"valor": "||", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_141 = d141.get("valor", "||")
                evidencia_141_salva = d141.get("link", "")

                # Decomposição segura do valor composto
                try:
                    partes_141 = val_salvo_141.split("|")
                    inst_inicial = partes_141[0] if len(partes_141) > 0 else ""
                    num_inicial = partes_141[1] if len(partes_141) > 1 else ""
                    data_inicial = partes_141[2] if len(partes_141) > 2 else ""
                except Exception:
                    inst_inicial, num_inicial, data_inicial = "", "", ""

                # Chaves estáticas e seguras por componente e ano
                chave_inst_141 = f"q141_inst_{ano_sel}"
                chave_num_141 = f"q141_num_{ano_sel}"
                chave_data_141 = f"q141_data_{ano_sel}"
                chave_link_141 = f"t_141_{ano_sel}"
                chave_coment_141 = f"coment_14.1_{ano_sel}"

                c141_1, c141_2 = st.columns([1, 1])

                with c141_1:
                    v_inst_input = st.text_input(
                        "Instrumento Normativo (Ex: Lei, Decreto):",
                        value=inst_inicial,
                        key=chave_inst_141,
                        placeholder="Ex: Lei Municipal, Decreto..."
                    )
                    v_num_input = st.text_input(
                        "Número do instrumento:",
                        value=num_inicial,
                        key=chave_num_141,
                        placeholder="Ex: 1234/2023"
                    )
                    v_data_input = st.text_input(
                        "Data da publicação (DD/MM/AAAA):",
                        value=data_inicial,
                        key=chave_data_141,
                        placeholder="Ex: 15/03/2023"
                    )

                with c141_2:
                    link_evidencia_141 = st.text_area(
                        "Link/Evidência (14.1):",
                        value=evidencia_141_salva,
                        key=chave_link_141,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.1...",
                        height=210
                    )
                    placeholder_links_141 = st.empty()
                    links_141_visuais = re.findall(REGEX_PURE_URL, link_evidencia_141 or "")
                    if links_141_visuais:
                        placeholder_links_141.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_141_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.1
                bloco_comentarios("14.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.1", key=f"btn_salvar_14_1_{ano_sel}", type="primary"):
                    valor_composto = f"{v_inst_input.strip()}|{v_num_input.strip()}|{v_data_input.strip()}"
                    lnk_val_141 = link_evidencia_141.strip()
                    comentario_para_salvar_141 = st.session_state.get(chave_coment_141, d141.get("comentario", ""))

                    # Persistência no banco/sessão (impacto 0.0 pontos)
                    save_resp(
                        qid="14.1",
                        valor=valor_composto,
                        pontos=0.0,
                        link=lnk_val_141,
                        comentario=comentario_para_salvar_141
                    )
                    res_data["14.1"] = {
                        "valor": valor_composto,
                        "pontos": 0.0,
                        "link": lnk_val_141,
                        "comentario": comentario_para_salvar_141
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_141 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_141_salva or "")]

                    if lnk_val_141 != evidencia_141_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_141 = d141.get("pontos", 0.0)
                tem_preenchimento = any([v_inst_input.strip(), v_num_input.strip(), v_data_input.strip()])

                if not tem_preenchimento:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhum dado do instrumento normativo informado no Quesito 14.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Instrumento normativo salvo com sucesso (Impacto: {pts_atuais_141:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.1
        if st.session_state.get(f"gatilho_modal_14_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.1", st.session_state.get(f"links_pendentes_14_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.2 • PÁGINA ELETRÔNICA DE DIVULGAÇÃO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_url_divulgacao_14_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.2 - Página Eletrônica de Divulgação da Regulamentação ({ano_sel})", expanded=True):
                st.subheader("14.2 • Página Eletrônica de Divulgação")
                st.write("**Página eletrônica (link na internet) de divulgação do instrumento de regulamentação do sistema de controle interno (XYZ se não disponível):**")
                st.caption("ℹ *Informe a URL de divulgação, insira os links de evidência/comentários e clique em 'Salvar Questão 14.2'.*")

                # Resgate seguro dos dados do 14.2
                d142 = res_data.get("14.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                if d142 is None:
                    d142 = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                if not isinstance(d142, dict):
                    d142 = {"valor": str(d142), "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_142 = d142.get("valor", "")
                evidencia_142_salva = d142.get("link", "")

                # Chaves estáticas e seguras por componente e ano
                chave_txt_142 = f"q142_txt_{ano_sel}"
                chave_link_142 = f"t_142_{ano_sel}"
                chave_coment_142 = f"coment_14.2_{ano_sel}"

                c142_1, c142_2 = st.columns([1, 1])

                with c142_1:
                    v_input_142 = st.text_input(
                        "Página eletrônica (link) 14.2:",
                        value=val_salvo_142,
                        key=chave_txt_142,
                        placeholder="https://... ou XYZ se não disponível"
                    )

                with c142_2:
                    link_evidencia_142 = st.text_area(
                        "Link/Evidência (14.2):",
                        value=evidencia_142_salva,
                        key=chave_link_142,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.2...",
                        height=100
                    )
                    placeholder_links_142 = st.empty()
                    links_142_visuais = re.findall(REGEX_PURE_URL, link_evidencia_142 or "")
                    if links_142_visuais:
                        placeholder_links_142.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_142_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.2
                bloco_comentarios("14.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.2", key=f"btn_salvar_14_2_{ano_sel}", type="primary"):
                    val_para_salvar_142 = v_input_142.strip()
                    lnk_val_142 = link_evidencia_142.strip()
                    comentario_para_salvar_142 = st.session_state.get(chave_coment_142, d142.get("comentario", ""))

                    # Persistência no banco/sessão (impacto 0.0 pontos)
                    save_resp(
                        qid="14.2",
                        valor=val_para_salvar_142,
                        pontos=0.0,
                        link=lnk_val_142,
                        comentario=comentario_para_salvar_142
                    )
                    res_data["14.2"] = {
                        "valor": val_para_salvar_142,
                        "pontos": 0.0,
                        "link": lnk_val_142,
                        "comentario": comentario_para_salvar_142
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_142 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_142_salva or "")]

                    if lnk_val_142 != evidencia_142_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_142 = d142.get("pontos", 0.0)

                if not v_input_142.strip():
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma URL ou 'XYZ' informada no Quesito 14.2</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Página eletrônica salva com sucesso (Impacto: {pts_atuais_142:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.2
        if st.session_state.get(f"gatilho_modal_14_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.2", st.session_state.get(f"links_pendentes_14_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.3 • FUNÇÕES DO CONTROLE INTERNO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_funcoes_14_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.3 - Funções Atribuídas ao Sistema de Controle Interno ({ano_sel})", expanded=True):
                st.subheader("14.3 • Funções do Controle Interno")
                st.write("**Assinale as funções atribuídas ao sistema de controle interno:**")
                st.caption("ℹ *Selecione as opções desejadas, insira os links de evidência/comentários e clique em 'Salvar Questão 14.3'.*")

                opcoes_143 = {
                    "Avaliar o cumprimento das metas físicas e financeiras dos planos orçamentários, bem como a eficiência de seus resultados – 01": 1.0,
                    "Comprovar a legalidade da gestão orçamentária, financeira e patrimonial – 01": 1.0,
                    "Comprovar a legalidade dos repasses a entidades do terceiro setor, avaliando a eficácia e a eficiência dos resultados alcançados – 01": 1.0,
                    "Exercer o controle das operações de crédito, avais e garantias, bem como dos direitos e haveres do Município – 01": 1.0,
                    "Em conjunto com autoridades da Administração Financeira do Município, assinar o Relatório de Gestão Fiscal – 01": 1.0,
                    "Atestar a regularidade da tomada de contas dos ordenadores de despesa, recebedores, tesoureiros, pagadores ou assemelhados – 01": 1.0,
                    "Apoiar o Tribunal de Contas no exercício de sua missão institucional – 01": 1.0,
                    "Comprovar a eficácia e a eficiência da gestão orçamentária, financeira e patrimonial – 01": 1.0,
                    "Acompanhar as metas de superávit orçamentário, primário e nominal – 01": 1.0,
                    "Observar se as operações de créditos sujeitam-se aos limites e condições das Resoluções 40 e 43/2001, do Senado – 01": 1.0,
                    "Verificar se os empréstimos e financiamentos vêm sendo pagos tal qual previsto nos respectivos contratos – 01": 1.0,
                    "Verificar se está sendo providenciada a recondução da despesa de pessoal e da dívida consolidada a seus limites fiscais – 01": 1.0,
                    "Comprovar se os recursos da alienação de ativos estão sendo despendidos em gastos de capital e, não, em despesas correntes – 01": 1.0,
                    "Constatar se está sendo satisfeito o limite para gastos totais das Câmaras Municipais – 01": 1.0,
                    "Verificar a fidelidade funcional dos responsáveis por bens e valores públicos – 01": 1.0
                }

                # Resgate seguro dos dados do 14.3
                d143 = res_data.get("14.3") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d143 is None or not isinstance(d143, dict):
                    d143 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_143 = d143.get("valor", "[]")
                evidencia_143_salva = d143.get("link", "")

                try:
                    lista_salva_143 = ast.literal_eval(val_salvo_143)
                    if not isinstance(lista_salva_143, list):
                        lista_salva_143 = []
                except Exception:
                    lista_salva_143 = []

                # Chaves estáticas
                chave_link_143 = f"t_143_{ano_sel}"
                chave_coment_143 = f"coment_14.3_{ano_sel}"

                c143_1, c143_2 = st.columns([1.2, 0.8])

                with c143_1:
                    st.write("**Opções Selecionáveis:**")
                    for idx, (item_txt, pts_item) in enumerate(opcoes_143.items()):
                        st.checkbox(
                            item_txt,
                            value=item_txt in lista_salva_143,
                            key=f"chk_143_{idx}_{ano_sel}"
                        )

                with c143_2:
                    link_143 = st.text_area(
                        "Link/Evidência (14.3):",
                        value=evidencia_143_salva,
                        key=chave_link_143,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.3...",
                        height=250
                    )
                    placeholder_links_143 = st.empty()
                    links_143_visuais = re.findall(REGEX_PURE_URL, link_143 or "")
                    if links_143_visuais:
                        placeholder_links_143.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_143_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.3
                bloco_comentarios("14.3", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.3
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.3", key=f"btn_salvar_14_3_{ano_sel}", type="primary"):
                    sel_143 = []
                    for idx, (item_txt, pts_item) in enumerate(opcoes_143.items()):
                        if st.session_state.get(f"chk_143_{idx}_{ano_sel}", False):
                            sel_143.append(item_txt)

                    pts_calc_143 = sum(opcoes_143[p] for p in sel_143)
                    val_para_salvar_143 = str(sel_143)
                    lnk_val_143 = link_143.strip()
                    comentario_para_salvar_143 = st.session_state.get(chave_coment_143, d143.get("comentario", ""))

                    # Persistência no banco/sessão
                    save_resp(
                        qid="14.3",
                        valor=val_para_salvar_143,
                        pontos=pts_calc_143,
                        link=lnk_val_143,
                        comentario=comentario_para_salvar_143
                    )
                    res_data["14.3"] = {
                        "valor": val_para_salvar_143,
                        "pontos": pts_calc_143,
                        "link": lnk_val_143,
                        "comentario": comentario_para_salvar_143
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_143 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_143_salva or "")]

                    if lnk_val_143 != evidencia_143_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.3 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_143 = d143.get("pontos", 0.0)
                qtd_selecionados = len(lista_salva_143)

                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"✅ Status: {qtd_selecionados} de {len(opcoes_143)} função(ões) selecionada(s) "
                    f"(Pontuação Total: {pts_atuais_143:.1f} pts)</span>",
                    unsafe_allow_html=True
                )

        # Modal de Evidências do 14.3
        if st.session_state.get(f"gatilho_modal_14_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.3", st.session_state.get(f"links_pendentes_14_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_3_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4 • RECURSOS HUMANOS (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_recursos_humanos_14_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4 - Recursos Humanos no Controle Interno ({ano_sel})", expanded=True):
                st.subheader("14.4 • Recursos Humanos")
                st.write("**A prefeitura dispõe de recursos humanos para operacionalização das atividades do sistema de controle interno?**")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4'.*")

                opcoes_144 = {
                    "Selecione...": 0.0,
                    "Sim – 0,5": 0.5,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 14.4
                d144 = res_data.get("14.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d144 is None or not isinstance(d144, dict):
                    d144 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_144 = d144.get("valor", "Selecione...")
                if val_salvo_144 not in opcoes_144:
                    val_salvo_144 = "Selecione..."

                evidencia_144_salva = d144.get("link", "")

                # Chaves estáticas
                chave_radio_144 = f"r_144_{ano_sel}"
                chave_link_144 = f"t_144_{ano_sel}"
                chave_coment_144 = f"coment_14.4_{ano_sel}"

                lista_opcoes_144 = list(opcoes_144.keys())
                idx_144 = lista_opcoes_144.index(val_salvo_144)

                c144_1, c144_2 = st.columns([1, 1])

                with c144_1:
                    v_input_144 = st.radio(
                        "Selecione 14.4:",
                        options=lista_opcoes_144,
                        index=idx_144,
                        key=chave_radio_144,
                        label_visibility="collapsed"
                    )

                with c144_2:
                    link_144 = st.text_area(
                        "Link/Evidência (14.4):",
                        value=evidencia_144_salva,
                        key=chave_link_144,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4...",
                        height=120
                    )
                    placeholder_links_144 = st.empty()
                    links_144_visuais = re.findall(REGEX_PURE_URL, link_144 or "")
                    if links_144_visuais:
                        placeholder_links_144.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_144_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4
                bloco_comentarios("14.4", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4", key=f"btn_salvar_14_4_{ano_sel}", type="primary"):
                    val_para_salvar_144 = v_input_144
                    pts_calc_144 = opcoes_144.get(val_para_salvar_144, 0.0)
                    lnk_val_144 = link_144.strip()
                    comentario_para_salvar_144 = st.session_state.get(chave_coment_144, d144.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4",
                        valor=val_para_salvar_144,
                        pontos=pts_calc_144,
                        link=lnk_val_144,
                        comentario=comentario_para_salvar_144
                    )
                    res_data["14.4"] = {
                        "valor": val_para_salvar_144,
                        "pontos": pts_calc_144,
                        "link": lnk_val_144,
                        "comentario": comentario_para_salvar_144
                    }

                    # Limpeza em cascata dos subníveis inferiores caso selecionado "Não" ou "Selecione..."
                    if val_para_salvar_144 in ["Não – 00", "Selecione..."]:
                        for sub_q in ["14.4.1", "14.4.2", "14.4.3", "14.4.4"]:
                            save_resp(sub_q, "Selecione...", 0.0, "", "")
                            res_data[sub_q] = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_144 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_144_salva or "")]

                    if lnk_val_144 != evidencia_144_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_144 = d144.get("pontos", 0.0)

                if v_input_144 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_144:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4
        if st.session_state.get(f"gatilho_modal_14_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4", st.session_state.get(f"links_pendentes_14_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.1 • RESPONSÁVEL PELA UCCI EM CARGO EFETIVO (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_cargo_efetivo_14_4_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.1 - Responsável pela UCCI em Cargo Efetivo ({ano_sel})", expanded=True):
                st.subheader("14.4.1 • Responsável pela UCCI em Cargo Efetivo")
                st.write("**O responsável pela Unidade Central de Controle Interno (UCCI) ocupa cargo efetivo na Administração Municipal?** *(Responsável = controlador interno ou controlador geral)*")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.1'.*")

                opcoes_1441 = {
                    "Selecione...": 0.0,
                    "Sim – 05": 5.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 14.4.1
                d1441 = res_data.get("14.4.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d1441 is None or not isinstance(d1441, dict):
                    d1441 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1441 = d1441.get("valor", "Selecione...")
                if val_salvo_1441 not in opcoes_1441:
                    val_salvo_1441 = "Selecione..."

                evidencia_1441_salva = d1441.get("link", "")

                # Chaves estáticas
                chave_radio_1441 = f"r_1441_{ano_sel}"
                chave_link_1441 = f"t_1441_{ano_sel}"
                chave_coment_1441 = f"coment_14.4.1_{ano_sel}"

                lista_opcoes_1441 = list(opcoes_1441.keys())
                idx_1441 = lista_opcoes_1441.index(val_salvo_1441)

                c1441_1, c1441_2 = st.columns([1, 1])

                with c1441_1:
                    v_input_1441 = st.radio(
                        "Selecione 14.4.1:",
                        options=lista_opcoes_1441,
                        index=idx_1441,
                        key=chave_radio_1441,
                        label_visibility="collapsed"
                    )

                with c1441_2:
                    link_1441 = st.text_area(
                        "Link/Evidência (14.4.1):",
                        value=evidencia_1441_salva,
                        key=chave_link_1441,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.1...",
                        height=120
                    )
                    placeholder_links_1441 = st.empty()
                    links_1441_visuais = re.findall(REGEX_PURE_URL, link_1441 or "")
                    if links_1441_visuais:
                        placeholder_links_1441.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1441_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.1
                bloco_comentarios("14.4.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.1", key=f"btn_salvar_14_4_1_{ano_sel}", type="primary"):
                    val_para_salvar_1441 = v_input_1441
                    pts_calc_1441 = opcoes_1441.get(val_para_salvar_1441, 0.0)
                    lnk_val_1441 = link_1441.strip()
                    comentario_para_salvar_1441 = st.session_state.get(chave_coment_1441, d1441.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.1",
                        valor=val_para_salvar_1441,
                        pontos=pts_calc_1441,
                        link=lnk_val_1441,
                        comentario=comentario_para_salvar_1441
                    )
                    res_data["14.4.1"] = {
                        "valor": val_para_salvar_1441,
                        "pontos": pts_calc_1441,
                        "link": lnk_val_1441,
                        "comentario": comentario_para_salvar_1441
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1441 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1441_salva or "")]

                    if lnk_val_1441 != evidencia_1441_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_1441 = d1441.get("pontos", 0.0)

                if v_input_1441 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_1441:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.1
        if st.session_state.get(f"gatilho_modal_14_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.1", st.session_state.get(f"links_pendentes_14_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.2 • TREINAMENTO DO QUADRO FUNCIONAL (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_treinamento_14_4_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.2 - Treinamento do Quadro Funcional ({ano_sel})", expanded=True):
                st.subheader("14.4.2 • Treinamento Periódico")
                st.write("**O quadro funcional do Sistema de Controle Interno recebe treinamento específico para execução das atividades inerentes ao cargo?** *(Treinamento periódico pelo menos 1 vez ao ano)*")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.2'.*")

                opcoes_1442 = {
                    "Selecione...": 0.0,
                    "Sim – 06": 6.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 14.4.2
                d1442 = res_data.get("14.4.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d1442 is None or not isinstance(d1442, dict):
                    d1442 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1442 = d1442.get("valor", "Selecione...")
                if val_salvo_1442 not in opcoes_1442:
                    val_salvo_1442 = "Selecione..."

                evidencia_1442_salva = d1442.get("link", "")

                # Chaves estáticas
                chave_radio_1442 = f"r_1442_{ano_sel}"
                chave_link_1442 = f"t_1442_{ano_sel}"
                chave_coment_1442 = f"coment_14.4.2_{ano_sel}"

                lista_opcoes_1442 = list(opcoes_1442.keys())
                idx_1442 = lista_opcoes_1442.index(val_salvo_1442)

                c1442_1, c1442_2 = st.columns([1, 1])

                with c1442_1:
                    v_input_1442 = st.radio(
                        "Selecione 14.4.2:",
                        options=lista_opcoes_1442,
                        index=idx_1442,
                        key=chave_radio_1442,
                        label_visibility="collapsed"
                    )

                with c1442_2:
                    link_1442 = st.text_area(
                        "Link/Evidência (14.4.2):",
                        value=evidencia_1442_salva,
                        key=chave_link_1442,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.2...",
                        height=120
                    )
                    placeholder_links_1442 = st.empty()
                    links_1442_visuais = re.findall(REGEX_PURE_URL, link_1442 or "")
                    if links_1442_visuais:
                        placeholder_links_1442.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1442_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.2
                bloco_comentarios("14.4.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.2", key=f"btn_salvar_14_4_2_{ano_sel}", type="primary"):
                    val_para_salvar_1442 = v_input_1442
                    pts_calc_1442 = opcoes_1442.get(val_para_salvar_1442, 0.0)
                    lnk_val_1442 = link_1442.strip()
                    comentario_para_salvar_1442 = st.session_state.get(chave_coment_1442, d1442.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.2",
                        valor=val_para_salvar_1442,
                        pontos=pts_calc_1442,
                        link=lnk_val_1442,
                        comentario=comentario_para_salvar_1442
                    )
                    res_data["14.4.2"] = {
                        "valor": val_para_salvar_1442,
                        "pontos": pts_calc_1442,
                        "link": lnk_val_1442,
                        "comentario": comentario_para_salvar_1442
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1442 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1442_salva or "")]

                    if lnk_val_1442 != evidencia_1442_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_1442 = d1442.get("pontos", 0.0)

                if v_input_1442 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.2</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_1442:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.2
        if st.session_state.get(f"gatilho_modal_14_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.2", st.session_state.get(f"links_pendentes_14_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.3 • SEGREGAÇÃO DE FUNÇÕES (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_segregacao_14_4_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.3 - Segregação de Funções Financeiras e de Controle ({ano_sel})", expanded=True):
                st.subheader("14.4.3 • Segregação de Funções")
                st.write("**Na Prefeitura existe formalização da segregação de funções financeiras e de controle?**")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.3'.*")

                opcoes_1443 = {
                    "Selecione...": 0.0,
                    "Sim – 05": 5.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 14.4.3
                d1443 = res_data.get("14.4.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d1443 is None or not isinstance(d1443, dict):
                    d1443 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1443 = d1443.get("valor", "Selecione...")
                if val_salvo_1443 not in opcoes_1443:
                    val_salvo_1443 = "Selecione..."

                evidencia_1443_salva = d1443.get("link", "")

                # Chaves estáticas
                chave_radio_1443 = f"r_1443_{ano_sel}"
                chave_link_1443 = f"t_1443_{ano_sel}"
                chave_coment_1443 = f"coment_14.4.3_{ano_sel}"

                lista_opcoes_1443 = list(opcoes_1443.keys())
                idx_1443 = lista_opcoes_1443.index(val_salvo_1443)

                c1443_1, c1443_2 = st.columns([1, 1])

                with c1443_1:
                    v_input_1443 = st.radio(
                        "Selecione 14.4.3:",
                        options=lista_opcoes_1443,
                        index=idx_1443,
                        key=chave_radio_1443,
                        label_visibility="collapsed"
                    )

                with c1443_2:
                    link_1443 = st.text_area(
                        "Link/Evidência (14.4.3):",
                        value=evidencia_1443_salva,
                        key=chave_link_1443,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.3...",
                        height=120
                    )
                    placeholder_links_1443 = st.empty()
                    links_1443_visuais = re.findall(REGEX_PURE_URL, link_1443 or "")
                    if links_1443_visuais:
                        placeholder_links_1443.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1443_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.3
                bloco_comentarios("14.4.3", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.3
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.3", key=f"btn_salvar_14_4_3_{ano_sel}", type="primary"):
                    val_para_salvar_1443 = v_input_1443
                    pts_calc_1443 = opcoes_1443.get(val_para_salvar_1443, 0.0)
                    lnk_val_1443 = link_1443.strip()
                    comentario_para_salvar_1443 = st.session_state.get(chave_coment_1443, d1443.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.3",
                        valor=val_para_salvar_1443,
                        pontos=pts_calc_1443,
                        link=lnk_val_1443,
                        comentario=comentario_para_salvar_1443
                    )
                    res_data["14.4.3"] = {
                        "valor": val_para_salvar_1443,
                        "pontos": pts_calc_1443,
                        "link": lnk_val_1443,
                        "comentario": comentario_para_salvar_1443
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1443 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1443_salva or "")]

                    if lnk_val_1443 != evidencia_1443_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.3 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_1443 = d1443.get("pontos", 0.0)

                if v_input_1443 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.3</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_1443:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.3
        if st.session_state.get(f"gatilho_modal_14_4_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.3", st.session_state.get(f"links_pendentes_14_4_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_3_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.4 • AUTONOMIA E INDEPENDÊNCIA DA UCCI (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_autonomia_14_4_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.4 - Autonomia e Independência da UCCI ({ano_sel})", expanded=True):
                st.subheader("14.4.4 • Autonomia e Independência")
                st.write("**A Unidade Central de Controle Interno (UCCI) possui autonomia e independência para o exercício de suas funções?**")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.4'.*")

                opcoes_1444 = {
                    "Selecione...": 0.0,
                    "Sim – 06": 6.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 14.4.4
                d1444 = res_data.get("14.4.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d1444 is None or not isinstance(d1444, dict):
                    d1444 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1444 = d1444.get("valor", "Selecione...")
                if val_salvo_1444 not in opcoes_1444:
                    val_salvo_1444 = "Selecione..."

                evidencia_1444_salva = d1444.get("link", "")

                # Chaves estáticas
                chave_radio_1444 = f"r_1444_{ano_sel}"
                chave_link_1444 = f"t_1444_{ano_sel}"
                chave_coment_1444 = f"coment_14.4.4_{ano_sel}"

                lista_opcoes_1444 = list(opcoes_1444.keys())
                idx_1444 = lista_opcoes_1444.index(val_salvo_1444)

                c1444_1, c1444_2 = st.columns([1, 1])

                with c1444_1:
                    v_input_1444 = st.radio(
                        "Selecione 14.4.4:",
                        options=lista_opcoes_1444,
                        index=idx_1444,
                        key=chave_radio_1444,
                        label_visibility="collapsed"
                    )

                with c1444_2:
                    link_1444 = st.text_area(
                        "Link/Evidência (14.4.4):",
                        value=evidencia_1444_salva,
                        key=chave_link_1444,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.4...",
                        height=120
                    )
                    placeholder_links_1444 = st.empty()
                    links_1444_visuais = re.findall(REGEX_PURE_URL, link_1444 or "")
                    if links_1444_visuais:
                        placeholder_links_1444.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1444_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.4
                bloco_comentarios("14.4.4", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.4
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.4", key=f"btn_salvar_14_4_4_{ano_sel}", type="primary"):
                    val_para_salvar_1444 = v_input_1444
                    pts_calc_1444 = opcoes_1444.get(val_para_salvar_1444, 0.0)
                    lnk_val_1444 = link_1444.strip()
                    comentario_para_salvar_1444 = st.session_state.get(chave_coment_1444, d1444.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.4",
                        valor=val_para_salvar_1444,
                        pontos=pts_calc_1444,
                        link=lnk_val_1444,
                        comentario=comentario_para_salvar_1444
                    )
                    res_data["14.4.4"] = {
                        "valor": val_para_salvar_1444,
                        "pontos": pts_calc_1444,
                        "link": lnk_val_1444,
                        "comentario": comentario_para_salvar_1444
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1444 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1444_salva or "")]

                    if lnk_val_1444 != evidencia_1444_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.4 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_1444 = d1444.get("pontos", 0.0)

                if v_input_1444 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.4</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_1444:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.4
        if st.session_state.get(f"gatilho_modal_14_4_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.4", st.session_state.get(f"links_pendentes_14_4_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_4_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.4.1 • SUBORDINAÇÃO ORGANIZACIONAL DA UCCI (PADRÃO 1.0 - 8 ESPAÇOS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_subordinacao_14_4_4_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.4.1 - Subordinação Organizacional da UCCI ({ano_sel})", expanded=True):
                st.subheader("14.4.4.1 • Vínculo Organizacional")
                st.write("**A estrutura organizacional da Unidade Central de Controle Interno (UCCI) está associada ou subordinada a qual secretaria/diretoria?**")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.4.1'.*")

                opc14441 = {
                    "Selecione...": 0.0,
                    "Administração – -06 (perde 06 pontos)": -6.0,
                    "Finanças/Fazenda – -06 (perde 06 pontos)": -6.0,
                    "Planejamento/Orçamento/Gestão – -06 (perde 06 pontos)": -6.0,
                    "Gabinete do Prefeito – 00": 0.0,
                    "Outra – -06 (perde 06 pontos)": -6.0
                }

                # Resgate seguro dos dados do 14.4.4.1
                d14441 = res_data.get("14.4.4.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d14441 is None or not isinstance(d14441, dict):
                    d14441 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_14441 = d14441.get("valor", "Selecione...")
                if val_salvo_14441 not in opc14441:
                    val_salvo_14441 = "Selecione..."

                evidencia_14441_salva = d14441.get("link", "")

                # Chaves estáticas
                chave_radio_14441 = f"r_14441_{ano_sel}"
                chave_link_14441 = f"t_14441_{ano_sel}"
                chave_coment_14441 = f"coment_14.4.4.1_{ano_sel}"

                lista_opcoes_14441 = list(opc14441.keys())
                idx_14441 = lista_opcoes_14441.index(val_salvo_14441)

                c14441_1, c14441_2 = st.columns([1, 1])

                with c14441_1:
                    v_input_14441 = st.radio(
                        "Selecione 14.4.4.1:",
                        options=lista_opcoes_14441,
                        index=idx_14441,
                        key=chave_radio_14441,
                        label_visibility="collapsed"
                    )

                with c14441_2:
                    link_14441 = st.text_area(
                        "Link/Evidência (14.4.4.1):",
                        value=evidencia_14441_salva,
                        key=chave_link_14441,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.4.1...",
                        height=140
                    )
                    placeholder_links_14441 = st.empty()
                    links_14441_visuais = re.findall(REGEX_PURE_URL, link_14441 or "")
                    if links_14441_visuais:
                        placeholder_links_14441.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14441_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.4.1
                bloco_comentarios("14.4.4.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.4.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.4.1", key=f"btn_salvar_14_4_4_1_{ano_sel}", type="primary"):
                    val_para_salvar_14441 = v_input_14441
                    pts_calc_14441 = opc14441.get(val_para_salvar_14441, 0.0)
                    lnk_val_14441 = link_14441.strip()
                    comentario_para_salvar_14441 = st.session_state.get(chave_coment_14441, d14441.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.4.1",
                        valor=val_para_salvar_14441,
                        pontos=pts_calc_14441,
                        link=lnk_val_14441,
                        comentario=comentario_para_salvar_14441
                    )
                    res_data["14.4.4.1"] = {
                        "valor": val_para_salvar_14441,
                        "pontos": pts_calc_14441,
                        "link": lnk_val_14441,
                        "comentario": comentario_para_salvar_14441
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_14441 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_14441_salva or "")]

                    if lnk_val_14441 != evidencia_14441_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.4.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_14441 = d14441.get("pontos", 0.0)

                if v_input_14441 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.4.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_14441:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.4.1
        if st.session_state.get(f"gatilho_modal_14_4_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.4.1", st.session_state.get(f"links_pendentes_14_4_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_4_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.4.2 • COMUNICAÇÃO DE IRREGULARIDADES OU ILEGALIDADES (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_comunicacao_14_4_4_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.4.2 - Comunicação de Irregularidades ou Ilegalidades ({ano_sel})", expanded=True):
                st.subheader("14.4.4.2 • Comunicações Efetuadas")
                st.write(f"**A Unidade Central de Controle Interno (UCCI) procedeu com alguma comunicação de irregularidade ou ilegalidade em {ano_sel}?**")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.4.2'.*")

                opc14442 = {
                    "Selecione...": 0.0,
                    "Sim, houve comunicação da irregularidade ou ilegalidade – 00": 0.0,
                    "Houve irregularidade ou ilegalidade, mas não procedeu a comunicação – -03 (perde 03 pontos)": -3.0,
                    "Não houve irregularidades nem ilegalidades – 00": 0.0
                }

                # Resgate seguro dos dados do 14.4.4.2
                d14442 = res_data.get("14.4.4.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d14442 is None or not isinstance(d14442, dict):
                    d14442 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_14442 = d14442.get("valor", "Selecione...")
                if val_salvo_14442 not in opc14442:
                    val_salvo_14442 = "Selecione..."

                evidencia_14442_salva = d14442.get("link", "")

                # Chaves estáticas
                chave_radio_14442 = f"r_14442_{ano_sel}"
                chave_link_14442 = f"t_14442_{ano_sel}"
                chave_coment_14442 = f"coment_14.4.4.2_{ano_sel}"

                lista_opcoes_14442 = list(opc14442.keys())
                idx_14442 = lista_opcoes_14442.index(val_salvo_14442)

                c14442_1, c14442_2 = st.columns([1, 1])

                with c14442_1:
                    v_input_14442 = st.radio(
                        "Selecione 14.4.4.2:",
                        options=lista_opcoes_14442,
                        index=idx_14442,
                        key=chave_radio_14442,
                        label_visibility="collapsed"
                    )

                with c14442_2:
                    link_14442 = st.text_area(
                        "Link/Evidência (14.4.4.2):",
                        value=evidencia_14442_salva,
                        key=chave_link_14442,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.4.2...",
                        height=120
                    )
                    placeholder_links_14442 = st.empty()
                    links_14442_visuais = re.findall(REGEX_PURE_URL, link_14442 or "")
                    if links_14442_visuais:
                        placeholder_links_14442.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14442_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.4.2
                bloco_comentarios("14.4.4.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.4.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.4.2", key=f"btn_salvar_14_4_4_2_{ano_sel}", type="primary"):
                    val_para_salvar_14442 = v_input_14442
                    pts_calc_14442 = opc14442.get(val_para_salvar_14442, 0.0)
                    lnk_val_14442 = link_14442.strip()
                    comentario_para_salvar_14442 = st.session_state.get(chave_coment_14442, d14442.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.4.2",
                        valor=val_para_salvar_14442,
                        pontos=pts_calc_14442,
                        link=lnk_val_14442,
                        comentario=comentario_para_salvar_14442
                    )
                    res_data["14.4.4.2"] = {
                        "valor": val_para_salvar_14442,
                        "pontos": pts_calc_14442,
                        "link": lnk_val_14442,
                        "comentario": comentario_para_salvar_14442
                    }

                    # Cascata de limpeza dos subquesitos numéricos dependentes caso o gatilho "Sim" não seja selecionado
                    if val_para_salvar_14442 != "Sim, houve comunicação da irregularidade ou ilegalidade – 00":
                        for sub_composto in ["14.4.4.2.1_tcesp", "14.4.4.2.1_mpsp"]:
                            save_resp(sub_composto, "0", 0.0, "", "")
                            res_data[sub_composto] = {"valor": "0", "pontos": 0.0, "link": "", "comentario": ""}

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_14442 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_14442_salva or "")]

                    if lnk_val_14442 != evidencia_14442_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.4.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_14442 = d14442.get("pontos", 0.0)

                if v_input_14442 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.4.2</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_14442:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.4.2
        if st.session_state.get(f"gatilho_modal_14_4_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.4.2", st.session_state.get(f"links_pendentes_14_4_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_4_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.4.2.1 • QUANTITATIVOS INFORMADOS (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_quantitativos_14_4_4_2_1_final_{ano_sel}", border=True):
            with st.expander(f"📊 Quesito 14.4.4.2.1 - Quantidade de Irregularidades Comunicadas ({ano_sel})", expanded=True):
                st.subheader("14.4.4.2.1 • Quantitativos Informados")
                st.write(f"**Informe a quantidade de irregularidades ou ilegalidades comunicadas em {ano_sel} ao:**")
                st.caption("ℹ *Preencha os quantitativos, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.4.2.1'.*")

                # Resgate seguro dos dados dos subquesitos compostos
                d144421_tce = res_data.get("14.4.4.2.1_tcesp") or {"valor": "0", "pontos": 0.0, "link": "", "comentario": ""}
                d144421_mp = res_data.get("14.4.4.2.1_mpsp") or {"valor": "0", "pontos": 0.0, "link": "", "comentario": ""}

                if d144421_tce is None or not isinstance(d144421_tce, dict):
                    d144421_tce = {"valor": "0", "pontos": 0.0, "link": "", "comentario": ""}
                if d144421_mp is None or not isinstance(d144421_mp, dict):
                    d144421_mp = {"valor": "0", "pontos": 0.0, "link": "", "comentario": ""}

                # Valores numéricos iniciais
                val_tce_str = str(d144421_tce.get("valor", "0"))
                val_mp_str = str(d144421_mp.get("valor", "0"))

                v_ini_tce = int(val_tce_str) if val_tce_str.isdigit() else 0
                v_ini_mp = int(val_mp_str) if val_mp_str.isdigit() else 0

                evidencia_144421_salva = d144421_tce.get("link", "") or d144421_mp.get("link", "")

                # Chaves estáticas limpas sem injeção de estado dinâmico no nome da chave
                chave_num_tce = f"n_144421_tce_{ano_sel}"
                chave_num_mp = f"n_144421_mp_{ano_sel}"
                chave_link_144421 = f"t_144421_{ano_sel}"
                chave_coment_144421 = f"coment_14.4.4.2.1_{ano_sel}"

                c144421_1, c144421_2 = st.columns([1, 1])

                with c144421_1:
                    c_sub_tce, c_sub_mp = st.columns(2)
                    with c_sub_tce:
                        v_input_tce = st.number_input(
                            "TCESP:",
                            min_value=0,
                            step=1,
                            value=v_ini_tce,
                            key=chave_num_tce
                        )
                    with c_sub_mp:
                        v_input_mp = st.number_input(
                            "MPSP:",
                            min_value=0,
                            step=1,
                            value=v_ini_mp,
                            key=chave_num_mp
                        )

                with c144421_2:
                    link_144421 = st.text_area(
                        "Link/Evidência (14.4.4.2.1):",
                        value=evidencia_144421_salva,
                        key=chave_link_144421,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.4.2.1...",
                        height=100
                    )
                    placeholder_links_144421 = st.empty()
                    links_144421_visuais = re.findall(REGEX_PURE_URL, link_144421 or "")
                    if links_144421_visuais:
                        placeholder_links_144421.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_144421_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.4.2.1
                bloco_comentarios("14.4.4.2.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.4.2.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.4.2.1", key=f"btn_salvar_14_4_4_2_1_{ano_sel}", type="primary"):
                    val_para_salvar_tce = str(v_input_tce)
                    val_para_salvar_mp = str(v_input_mp)
                    lnk_val_144421 = link_144421.strip()
                    comentario_para_salvar_144421 = st.session_state.get(
                        chave_coment_144421,
                        d144421_tce.get("comentario", "") or d144421_mp.get("comentario", "")
                    )

                    # Persistência unificada no banco/sessão para ambas as chaves
                    save_resp(
                        qid="14.4.4.2.1_tcesp",
                        valor=val_para_salvar_tce,
                        pontos=0.0,
                        link=lnk_val_144421,
                        comentario=comentario_para_salvar_144421
                    )
                    save_resp(
                        qid="14.4.4.2.1_mpsp",
                        valor=val_para_salvar_mp,
                        pontos=0.0,
                        link=lnk_val_144421,
                        comentario=comentario_para_salvar_144421
                    )

                    res_data["14.4.4.2.1_tcesp"] = {
                        "valor": val_para_salvar_tce,
                        "pontos": 0.0,
                        "link": lnk_val_144421,
                        "comentario": comentario_para_salvar_144421
                    }
                    res_data["14.4.4.2.1_mpsp"] = {
                        "valor": val_para_salvar_mp,
                        "pontos": 0.0,
                        "link": lnk_val_144421,
                        "comentario": comentario_para_salvar_144421
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_144421 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_144421_salva or "")]

                    if lnk_val_144421 != evidencia_144421_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_4_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_4_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Quantitativos da Questão 14.4.4.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Status de Exibição do Quesito (Sem impacto direto de pontuação - Informativo)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"✅ Status: Quantitativos Registrados (TCESP: {v_input_tce} | MPSP: {v_input_mp}) — Impacto: 0.0 pontos</span>",
                    unsafe_allow_html=True
                )

        # Modal de Evidências do 14.4.4.2.1
        if st.session_state.get(f"gatilho_modal_14_4_4_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.4.2.1", st.session_state.get(f"links_pendentes_14_4_4_2_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_4_2_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.5 • RELATÓRIOS PERIÓDICOS DO CONTROLE INTERNO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_relatorios_14_4_5_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.5 - Relatórios Periódicos do Controle Interno ({ano_sel})", expanded=True):
                st.subheader("14.4.5 • Relatórios Periódicos")
                st.write(f"**O responsável pela Unidade Central de Controle Interno (UCCI) apresentou relatórios periódicos que demonstram efetivo exercício de suas atribuições em {ano_sel}?** *(Periodicidade mínima anual)*")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.5'.*")

                opcoes_1445 = {
                    "Selecione...": 0.0,
                    "Sim – 05": 5.0,
                    "Não – 00": 0.0
                }

                # Resgate seguro dos dados do 14.4.5
                d1445 = res_data.get("14.4.5") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d1445 is None or not isinstance(d1445, dict):
                    d1445 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1445 = d1445.get("valor", "Selecione...")
                if val_salvo_1445 not in opcoes_1445:
                    val_salvo_1445 = "Selecione..."

                evidencia_1445_salva = d1445.get("link", "")

                # Chaves estáticas limpas
                chave_radio_1445 = f"r_1445_{ano_sel}"
                chave_link_14445 = f"t_1445_{ano_sel}"
                chave_coment_1445 = f"coment_14.4.5_{ano_sel}"

                lista_opcoes_1445 = list(opcoes_1445.keys())
                idx1445 = lista_opcoes_1445.index(val_salvo_1445)

                c1445_1, c1445_2 = st.columns([1, 1])

                with c1445_1:
                    v_input_1445 = st.radio(
                        "Selecione 14.4.5:",
                        options=lista_opcoes_1445,
                        index=idx1445,
                        key=chave_radio_1445,
                        label_visibility="collapsed"
                    )

                with c1445_2:
                    link_1445 = st.text_area(
                        "Link/Evidência (14.4.5):",
                        value=evidencia_1445_salva,
                        key=chave_link_14445,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.5...",
                        height=100
                    )
                    placeholder_links_1445 = st.empty()
                    links_1445_visuais = re.findall(REGEX_PURE_URL, link_1445 or "")
                    if links_1445_visuais:
                        placeholder_links_1445.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1445_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.5
                bloco_comentarios("14.4.5", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.5
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.5", key=f"btn_salvar_14_4_5_{ano_sel}", type="primary"):
                    val_para_salvar_1445 = v_input_1445
                    pts_calc_1445 = opcoes_1445.get(val_para_salvar_1445, 0.0)
                    lnk_val_1445 = link_1445.strip()
                    comentario_para_salvar_1445 = st.session_state.get(chave_coment_1445, d1445.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.5",
                        valor=val_para_salvar_1445,
                        pontos=pts_calc_1445,
                        link=lnk_val_1445,
                        comentario=comentario_para_salvar_1445
                    )
                    res_data["14.4.5"] = {
                        "valor": val_para_salvar_1445,
                        "pontos": pts_calc_1445,
                        "link": lnk_val_1445,
                        "comentario": comentario_para_salvar_1445
                    }

                    # Cascata de limpeza dos subquesitos dependentes caso não seja selecionado "Sim"
                    if val_para_salvar_1445 in ["Não – 00", "Selecione..."]:
                        for sub_q in ["14.4.5.1", "14.4.5.1.1"]:
                            save_resp(qid=sub_q, valor="Selecione...", pontos=0.0, link="", comentario="")
                            res_data[sub_q] = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1445 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1445_salva or "")]

                    if lnk_val_1445 != evidencia_1445_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.5 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_1445 = d1445.get("pontos", 0.0)

                if v_input_1445 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.5</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_1445:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.5
        if st.session_state.get(f"gatilho_modal_14_4_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.5", st.session_state.get(f"links_pendentes_14_4_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_5_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.5.1 • PROVIDÊNCIAS DETERMINADAS PELO PREFEITO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_providencias_14_4_5_1_final_{ano_sel}", border=True):
            with st.expander(f"📋 Quesito 14.4.5.1 - Providências Determinadas pelo Prefeito ({ano_sel})", expanded=True):
                st.subheader("14.4.5.1 • Providências Determinadas")
                st.write(f"**Com base no relatório do Controle Interno, o Prefeito determinou as providências cabíveis diante das irregularidades e ilegalidades apontadas em {ano_sel}?**")
                st.caption("ℹ *Selecione uma opção, insira os links de evidência/comentários e clique em 'Salvar Questão 14.4.5.1'.*")

                opcoes_14451 = {
                    "Selecione...": 0.0,
                    "Sim - de todos os apontamentos – 06": 6.0,
                    "Sim - de parte dos apontamentos – 02": 2.0,
                    "Não – 00": 0.0,
                    "Não foram relatadas irregularidades – 06": 6.0
                }

                # Resgate seguro dos dados do 14.4.5.1
                d14451 = res_data.get("14.4.5.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d14451 is None or not isinstance(d14451, dict):
                    d14451 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_14451 = d14451.get("valor", "Selecione...")
                if val_salvo_14451 not in opcoes_14451:
                    val_salvo_14451 = "Selecione..."

                evidencia_14451_salva = d14451.get("link", "")

                # Chaves estáticas limpas sem injeção de estado no nome
                chave_radio_14451 = f"r_14451_{ano_sel}"
                chave_link_14451 = f"t_14451_{ano_sel}"
                chave_coment_14451 = f"coment_14.4.5.1_{ano_sel}"

                lista_opcoes_14451 = list(opcoes_14451.keys())
                idx14451 = lista_opcoes_14451.index(val_salvo_14451)

                c14451_1, c14451_2 = st.columns([1, 1])

                with c14451_1:
                    v_input_14451 = st.radio(
                        "Selecione 14.4.5.1:",
                        options=lista_opcoes_14451,
                        index=idx14451,
                        key=chave_radio_14451,
                        label_visibility="collapsed"
                    )

                with c14451_2:
                    link_14451 = st.text_area(
                        "Link/Evidência (14.4.5.1):",
                        value=evidencia_14451_salva,
                        key=chave_link_14451,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.5.1...",
                        height=120
                    )
                    placeholder_links_14451 = st.empty()
                    links_14451_visuais = re.findall(REGEX_PURE_URL, link_14451 or "")
                    if links_14451_visuais:
                        placeholder_links_14451.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14451_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.5.1
                bloco_comentarios("14.4.5.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.5.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.5.1", key=f"btn_salvar_14_4_5_1_{ano_sel}", type="primary"):
                    val_para_salvar_14451 = v_input_14451
                    pts_calc_14451 = opcoes_14451.get(val_para_salvar_14451, 0.0)
                    lnk_val_14451 = link_14451.strip()
                    comentario_para_salvar_14451 = st.session_state.get(chave_coment_14451, d14451.get("comentario", ""))

                    # Persistência principal no banco/sessão
                    save_resp(
                        qid="14.4.5.1",
                        valor=val_para_salvar_14451,
                        pontos=pts_calc_14451,
                        link=lnk_val_14451,
                        comentario=comentario_para_salvar_14451
                    )
                    res_data["14.4.5.1"] = {
                        "valor": val_para_salvar_14451,
                        "pontos": pts_calc_14451,
                        "link": lnk_val_14451,
                        "comentario": comentario_para_salvar_14451
                    }

                    # Cascata de limpeza para o subquesito filho (14.4.5.1.1) caso não haja providências de parte/todos ou se resetar
                    if val_para_salvar_14451 in ["Não – 00", "Não foram relatadas irregularidades – 06", "Selecione..."]:
                        save_resp(qid="14.4.5.1.1", valor="Selecione...", pontos=0.0, link="", comentario="")
                        res_data["14.4.5.1.1"] = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_14451 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_14451_salva or "")]

                    if lnk_val_14451 != evidencia_14451_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.5.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_14451 = d14451.get("pontos", 0.0)

                if v_input_14451 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.5.1</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_14451:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.5.1
        if st.session_state.get(f"gatilho_modal_14_4_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.5.1", st.session_state.get(f"links_pendentes_14_4_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_5_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.4.5.1.1 • ACOMPANHAMENTO DE MEDIDAS E PRAZOS (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_prazos_14_4_5_1_1_final_{ano_sel}", border=True):
            with st.expander(f"🔍 Quesito 14.4.5.1.1 - Acompanhamento de Prazos ({ano_sel})", expanded=True):
                st.subheader("14.4.5.1.1 • Medidas e Prazos")
                st.write(f"**O Controle Interno acompanhou as medidas e os prazos das providências determinadas pelo Prefeito diante dos apontamentos do relatório do Controle Interno em {ano_sel}?**")
                st.caption("ℹ *Atenção: Este quesito possui pontuação redutora (penalidade de -3.0 pts se assinalado 'Não'). Selecione a opção, preencha os dados e clique em 'Salvar Questão 14.4.5.1.1'.*")

                opcoes_144511 = {
                    "Selecione...": 0.0,
                    "Sim - de todas as providências determinadas pelo Prefeito – 00": 0.0,
                    "Sim - de parte das providências determinadas pelo Prefeito – 00": 0.0,
                    "Não – -03 (perde 03 pontos)": -3.0
                }

                # Resgate seguro dos dados do 14.4.5.1.1
                d144511 = res_data.get("14.4.5.1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d144511 is None or not isinstance(d144511, dict):
                    d144511 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_144511 = d144511.get("valor", "Selecione...")
                if val_salvo_144511 not in opcoes_144511:
                    val_salvo_144511 = "Selecione..."

                evidencia_144511_salva = d144511.get("link", "")

                # Chaves estáticas limpas
                chave_radio_144511 = f"r_144511_{ano_sel}"
                chave_link_144511 = f"t_144511_{ano_sel}"
                chave_coment_144511 = f"coment_14.4.5.1.1_{ano_sel}"

                lista_opcoes_144511 = list(opcoes_144511.keys())
                idx144511 = lista_opcoes_144511.index(val_salvo_144511)

                c144511_1, c144511_2 = st.columns([1, 1])

                with c144511_1:
                    v_input_144511 = st.radio(
                        "Selecione 14.4.5.1.1:",
                        options=lista_opcoes_144511,
                        index=idx144511,
                        key=chave_radio_144511,
                        label_visibility="collapsed"
                    )

                with c144511_2:
                    link_144511 = st.text_area(
                        "Link/Evidência (14.4.5.1.1):",
                        value=evidencia_144511_salva,
                        key=chave_link_144511,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.4.5.1.1...",
                        height=120
                    )
                    placeholder_links_144511 = st.empty()
                    links_144511_visuais = re.findall(REGEX_PURE_URL, link_144511 or "")
                    if links_144511_visuais:
                        placeholder_links_144511.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_144511_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.4.5.1.1
                bloco_comentarios("14.4.5.1.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.4.5.1.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.4.5.1.1", key=f"btn_salvar_14_4_5_1_1_{ano_sel}", type="primary"):
                    val_para_salvar_144511 = v_input_144511
                    pts_calc_144511 = opcoes_144511.get(val_para_salvar_144511, 0.0)
                    lnk_val_144511 = link_144511.strip()
                    comentario_para_salvar_144511 = st.session_state.get(chave_coment_144511, d144511.get("comentario", ""))

                    # Persistência no banco de dados e na sessão
                    save_resp(
                        qid="14.4.5.1.1",
                        valor=val_para_salvar_144511,
                        pontos=pts_calc_144511,
                        link=lnk_val_144511,
                        comentario=comentario_para_salvar_144511
                    )
                    res_data["14.4.5.1.1"] = {
                        "valor": val_para_salvar_144511,
                        "pontos": pts_calc_144511,
                        "link": lnk_val_144511,
                        "comentario": comentario_para_salvar_144511
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_144511 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_144511_salva or "")]

                    if lnk_val_144511 != evidencia_144511_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_4_5_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_4_5_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.4.5.1.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_144511 = d144511.get("pontos", 0.0)

                if v_input_144511 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.4.5.1.1</span>", unsafe_allow_html=True)
                else:
                    cor_status = "#dc3545" if pts_atuais_144511 < 0 else "#28a745"
                    st.markdown(
                        f"<span style='color:{cor_status}; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_144511:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.4.5.1.1
        if st.session_state.get(f"gatilho_modal_14_4_5_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.4.5.1.1", st.session_state.get(f"links_pendentes_14_4_5_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_5_1_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.5 • PLANO OPERATIVO ANUAL (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_plano_14_5_final_{ano_sel}", border=True):
            with st.expander(f"📈 Quesito 14.5 - Plano Operativo Anual ({ano_sel})", expanded=True):
                st.subheader("14.5 • Plano Operativo Anual")
                st.write(f"**Houve a operação de Plano Operativo Anual em {ano_sel}?** *(Obs.: Plano Operativo Anual consiste no planejamento das atividades a serem executadas no exercício seguinte a sua elaboração).*")
                st.caption("ℹ *Selecione uma opção, preencha os campos e clique em 'Salvar Questão 14.5'. Se selecionado 'Não' ou 'Selecione...', o subquesito dependente (14.5.1) será redefinido.*")

                opcoes_145 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados do 14.5
                d145 = res_data.get("14.5") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d145 is None or not isinstance(d145, dict):
                    d145 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_145 = d145.get("valor", "Selecione...")
                if val_salvo_145 not in opcoes_145:
                    val_salvo_145 = "Selecione..."

                evidencia_145_salva = d145.get("link", "")

                # Chaves estáticas e limpas
                chave_radio_145 = f"r_145_{ano_sel}"
                chave_link_145 = f"t_145_{ano_sel}"
                chave_coment_145 = f"coment_14.5_{ano_sel}"

                lista_opcoes_145 = list(opcoes_145.keys())
                idx145 = lista_opcoes_145.index(val_salvo_145)

                c145_1, c145_2 = st.columns([1, 1])

                with c145_1:
                    v_input_145 = st.radio(
                        "Selecione 14.5:",
                        options=lista_opcoes_145,
                        index=idx145,
                        key=chave_radio_145,
                        label_visibility="collapsed"
                    )

                with c145_2:
                    link_145 = st.text_area(
                        "Link/Evidência (14.5):",
                        value=evidencia_145_salva,
                        key=chave_link_145,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.5...",
                        height=100
                    )
                    placeholder_links_145 = st.empty()
                    links_145_visuais = re.findall(REGEX_PURE_URL, link_145 or "")
                    if links_145_visuais:
                        placeholder_links_145.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_145_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.5
                bloco_comentarios("14.5", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.5
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.5", key=f"btn_salvar_14_5_{ano_sel}", type="primary"):
                    val_para_salvar_145 = v_input_145
                    pts_calc_145 = opcoes_145.get(val_para_salvar_145, 0.0)
                    lnk_val_145 = link_145.strip()
                    comentario_para_salvar_145 = st.session_state.get(chave_coment_145, d145.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="14.5",
                        valor=val_para_salvar_145,
                        pontos=pts_calc_145,
                        link=lnk_val_145,
                        comentario=comentario_para_salvar_145
                    )
                    res_data["14.5"] = {
                        "valor": val_para_salvar_145,
                        "pontos": pts_calc_145,
                        "link": lnk_val_145,
                        "comentario": comentario_para_salvar_145
                    }

                    # Cascata de limpeza para o subquesito filho (14.5.1) caso não seja "Sim"
                    if val_para_salvar_145 in ["Não", "Selecione..."]:
                        save_resp(qid="14.5.1", valor="Selecione...", pontos=0.0, link="", comentario="")
                        res_data["14.5.1"] = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_145 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_145_salva or "")]

                    if lnk_val_145 != evidencia_145_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.5 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_145 = d145.get("pontos", 0.0)

                if v_input_145 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 14.5</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_145:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.5
        if st.session_state.get(f"gatilho_modal_14_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.5", st.session_state.get(f"links_pendentes_14_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_5_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 14.5.1 • ATIVIDADES DO PLANO OPERATIVO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_atividades_plano_14_5_1_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 14.5.1 - Atividades Previstas no Plano Operativo ({ano_sel})", expanded=True):
                st.subheader("14.5.1 • Atividades do Plano Operativo")
                st.write(f"**Assinale as atividades previstas no Plano Operativo Anual em {ano_sel}:**")
                st.caption("ℹ *A pontuação é calculada por faixas baseada na quantidade de itens selecionados (1-5: 1.0 pt | 6-10: 3.0 pts | 11+: 5.0 pts). Marque as opções, insira as evidências/comentários e clique em 'Salvar Questão 14.5.1'.*")

                opcoes_1451 = [
                    "Receitas", "Despesas", "Administração de pessoal", "Estoques e almoxarifados",
                    "Administração do patrimônio",
                    "Cumprimento das metas do PPA e a execução dos programas de governo e dos orçamentos (LOA e LDO)",
                    "Cumprimento das metas fiscais, físicas e de resultados dos programas de governo, no que tange a eficiência, eficácia e efetividade",
                    "Aplicação de recursos públicos por entidades de direito público",
                    "Aplicação de recursos públicos por entidades de direito privado",
                    "Os limites e condições para a inscrição de despesas em Restos a Pagar",
                    "Cumprimento da legislação de licitações e fiscalização de contratos",
                    "Cumprimento do limite de gastos totais dos legislativos municipais, inclusive no que se refere ao atingimento de metas fiscais (Gestão Fiscal)",
                    "Transferência para o Legislativo Municipal (Repasses de Duodécimos)",
                    "Contabilidade", "Transparência", "Lei de Acesso à Informação", "Outros"
                ]

                # Resgate seguro dos dados do 14.5.1
                d1451 = res_data.get("14.5.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d1451 is None or not isinstance(d1451, dict):
                    d1451 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_raw_1451 = d1451.get("valor", "[]")
                try:
                    lista_salva_1451 = json.loads(val_raw_1451) if isinstance(val_raw_1451, str) else val_raw_1451
                    if not isinstance(lista_salva_1451, list):
                        lista_salva_1451 = []
                except Exception:
                    try:
                        lista_salva_1451 = eval(val_raw_1451) if isinstance(val_raw_1451, str) else []
                        if not isinstance(lista_salva_1451, list):
                            lista_salva_1451 = []
                    except Exception:
                        lista_salva_1451 = []

                evidencia_1451_salva = d1451.get("link", "")

                # Chaves estáticas limpas
                chave_link_1451 = f"t_1451_{ano_sel}"
                chave_coment_1451 = f"coment_14.5.1_{ano_sel}"

                c1451_1, c1451_2 = st.columns([1, 1])

                with c1451_1:
                    st.markdown("**Selecione as atividades previstas:**")
                    itens_selecionados_1451 = []
                    for idx_item, item in enumerate(opcoes_1451):
                        chk_key = f"chk_1451_{idx_item}_{ano_sel}"
                        is_checked = st.checkbox(
                            item,
                            value=(item in lista_salva_1451),
                            key=chk_key
                        )
                        if is_checked:
                            itens_selecionados_1451.append(item)

                with c1451_2:
                    link_1451 = st.text_area(
                        "Link/Evidência (14.5.1):",
                        value=evidencia_1451_salva,
                        key=chave_link_1451,
                        placeholder="Insira os links comprobatórios referente ao Quesito 14.5.1...",
                        height=220
                    )
                    placeholder_links_1451 = st.empty()
                    links_1451_visuais = re.findall(REGEX_PURE_URL, link_1451 or "")
                    if links_1451_visuais:
                        placeholder_links_1451.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1451_visuais]
                            )
                        )

                # Bloco de comentários integrado do 14.5.1
                bloco_comentarios("14.5.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 14.5.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 14.5.1", key=f"btn_salvar_14_5_1_{ano_sel}", type="primary"):
                    val_str_1451 = json.dumps(itens_selecionados_1451, ensure_ascii=False)
                    qtd = len(itens_selecionados_1451)

                    # Cálculo da pontuação por faixas
                    if qtd == 0:
                        pts_calc_1451 = 0.0
                    elif 1 <= qtd <= 5:
                        pts_calc_1451 = 1.0
                    elif 6 <= qtd <= 10:
                        pts_calc_1451 = 3.0
                    else:
                        pts_calc_1451 = 5.0

                    lnk_val_1451 = link_1451.strip()
                    comentario_para_salvar_1451 = st.session_state.get(chave_coment_1451, d1451.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="14.5.1",
                        valor=val_str_1451,
                        pontos=pts_calc_1451,
                        link=lnk_val_1451,
                        comentario=comentario_para_salvar_1451
                    )
                    res_data["14.5.1"] = {
                        "valor": val_str_1451,
                        "pontos": pts_calc_1451,
                        "link": lnk_val_1451,
                        "comentario": comentario_para_salvar_1451
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1451 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1451_salva or "")]

                    if lnk_val_1451 != evidencia_1451_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 14.5.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição da Pontuação e Contagem
                qtd_atual = len(itens_selecionados_1451)
                pts_atuais_1451 = d1451.get("pontos", 0.0)

                if qtd_atual == 0:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma atividade selecionada no Quesito 14.5.1 (0.0 pontos)</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso — {qtd_atual} atividade(s) selecionada(s) (Impacto: {pts_atuais_1451:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 14.5.1
        if st.session_state.get(f"gatilho_modal_14_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.5.1", st.session_state.get(f"links_pendentes_14_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_5_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO MASTER 15.0 • CRIAÇÃO DA OUVIDORIA PÚBLICA (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_ouvidoria_master_15_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 15.0 - Criação da Ouvidoria Pública ({ano_sel})", expanded=True):
                st.subheader("15.0 • Ouvidoria Pública Executiva")
                st.write(f"**Houve a criação da ouvidoria pública no âmbito do Poder Executivo Municipal em {ano_sel}?**")
                st.caption("ℹ *Selecione uma opção, preencha os campos e clique em 'Salvar Questão 15.0'. Se modificado para 'Não' ou 'Selecione...', toda a árvore de subquesitos dependentes (15.1 a 15.5) será redefinida no banco de dados.*")

                opcoes_150 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                # Resgate seguro dos dados do 15.0
                d150 = res_data.get("15.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d150 is None or not isinstance(d150, dict):
                    d150 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_150 = d150.get("valor", "Selecione...")
                if val_salvo_150 not in opcoes_150:
                    val_salvo_150 = "Selecione..."

                evidencia_150_salva = d150.get("link", "")

                # Chaves estáticas e limpas
                chave_radio_150 = f"r_150_{ano_sel}"
                chave_link_150 = f"t_150_{ano_sel}"
                chave_coment_150 = f"coment_15.0_{ano_sel}"

                lista_opcoes_150 = list(opcoes_150.keys())
                idx150 = lista_opcoes_150.index(val_salvo_150)

                c150_1, c150_2 = st.columns([1, 1])

                with c150_1:
                    v_input_150 = st.radio(
                        "Selecione 15.0:",
                        options=lista_opcoes_150,
                        index=idx150,
                        key=chave_radio_150,
                        label_visibility="collapsed"
                    )

                with c150_2:
                    link_150 = st.text_area(
                        "Link/Evidência (15.0):",
                        value=evidencia_150_salva,
                        key=chave_link_150,
                        placeholder="Insira os links comprobatórios referente ao Quesito 15.0...",
                        height=100
                    )
                    placeholder_links_150 = st.empty()
                    links_150_visuais = re.findall(REGEX_PURE_URL, link_150 or "")
                    if links_150_visuais:
                        placeholder_links_150.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_150_visuais]
                            )
                        )

                # Bloco de comentários integrado do 15.0
                bloco_comentarios("15.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.0", key=f"btn_salvar_15_0_{ano_sel}", type="primary"):
                    val_para_salvar_150 = v_input_150
                    pts_calc_150 = opcoes_150.get(val_para_salvar_150, 0.0)
                    lnk_val_150 = link_150.strip()
                    comentario_para_salvar_150 = st.session_state.get(chave_coment_150, d150.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="15.0",
                        valor=val_para_salvar_150,
                        pontos=pts_calc_150,
                        link=lnk_val_150,
                        comentario=comentario_para_salvar_150
                    )
                    res_data["15.0"] = {
                        "valor": val_para_salvar_150,
                        "pontos": pts_calc_150,
                        "link": lnk_val_150,
                        "comentario": comentario_para_salvar_150
                    }

                    # Cascata de limpeza completa para a árvore filha (15.1 a 15.5) caso não seja "Sim"
                    if val_para_salvar_150 in ["Não", "Selecione..."]:
                        limpeza_grupo_15 = {
                            "15.1": "Selecione...",
                            "15.2": "Selecione...",
                            "15.3": "[]",
                            "15.4": "Selecione...",
                            "15.4.1": "[]",
                            "15.4.2": "Selecione...",
                            "15.5": "[]"
                        }
                        for sub_q, d_val in limpeza_grupo_15.items():
                            save_resp(qid=sub_q, valor=d_val, pontos=0.0, link="", comentario="")
                            res_data[sub_q] = {"valor": d_val, "pontos": 0.0, "link": "", "comentario": ""}

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_150 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_150_salva or "")]

                    if lnk_val_150 != evidencia_150_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_150 = d150.get("pontos", 0.0)

                if v_input_150 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 15.0</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Opção salva com sucesso (Impacto: {pts_atuais_150:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 15.0
        if st.session_state.get(f"gatilho_modal_15_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.0", st.session_state.get(f"links_pendentes_15_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO TEXTO 15.1 • INSTRUMENTO NORMATIVO DE CRIAÇÃO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_norma_ouvidoria_15_1_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.1 - Instrumento Normativo de Criação ({ano_sel})", expanded=True):
                st.subheader("15.1 • Instrumento Normativo")
                st.write(f"**Informe o instrumento normativo de criação da ouvidoria pública, número e data da publicação em {ano_sel}:**")
                st.info("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o Instrumento Normativo no Sistema de Questionários.*")

                # Resgate seguro dos dados do 15.1
                d151 = res_data.get("15.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                if d151 is None or not isinstance(d151, dict):
                    d151 = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_151 = d151.get("valor", "")
                evidencia_151_salva = d151.get("link", "")

                # Chaves estáticas e limpas
                chave_input_151 = f"q151_{ano_sel}"
                chave_link_151 = f"l151_{ano_sel}"
                chave_coment_151 = f"coment_15.1_{ano_sel}"

                c151_1, c151_2 = st.columns([1, 1])

                with c151_1:
                    v_input_151 = st.text_input(
                        "Instrumento, número e data:",
                        value=val_salvo_151,
                        key=chave_input_151,
                        placeholder="Ex: Lei Municipal nº 1.234, de 10/05/2020"
                    )

                with c151_2:
                    link_151 = st.text_area(
                        "Link/Evidência (15.1):",
                        value=evidencia_151_salva,
                        key=chave_link_151,
                        placeholder="Insira os links comprobatórios referente ao Quesito 15.1...",
                        height=100
                    )
                    placeholder_links_151 = st.empty()
                    links_151_visuais = re.findall(REGEX_PURE_URL, link_151 or "")
                    if links_151_visuais:
                        placeholder_links_151.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_151_visuais]
                            )
                        )

                # Bloco de comentários integrado do 15.1
                bloco_comentarios("15.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.1", key=f"btn_salvar_15_1_{ano_sel}", type="primary"):
                    val_para_salvar_151 = v_input_151.strip()
                    pts_calc_151 = 0.0
                    lnk_val_151 = link_151.strip()
                    comentario_para_salvar_151 = st.session_state.get(chave_coment_151, d151.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="15.1",
                        valor=val_para_salvar_151,
                        pontos=pts_calc_151,
                        link=lnk_val_151,
                        comentario=comentario_para_salvar_151
                    )
                    res_data["15.1"] = {
                        "valor": val_para_salvar_151,
                        "pontos": pts_calc_151,
                        "link": lnk_val_151,
                        "comentario": comentario_para_salvar_151
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_151 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_151_salva or "")]

                    if lnk_val_151 != evidencia_151_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição da Informação do Quesito
                pts_atuais_151 = d151.get("pontos", 0.0)

                if not v_input_151.strip():
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma informação preenchida no Quesito 15.1 (0.0 pontos)</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Informação salva com sucesso (Impacto: {pts_atuais_151:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 15.1
        if st.session_state.get(f"gatilho_modal_15_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.1", st.session_state.get(f"links_pendentes_15_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO TEXTO/LINK 15.2 • PÁGINA ELETRÔNICA DO INSTRUMENTO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_pagina_eletronica_15_2_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.2 - Página Eletrônica do Instrumento ({ano_sel})", expanded=True):
                st.subheader("15.2 • Página Eletrônica de Divulgação")
                st.write(f"**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo de criação da Ouvidoria Pública em {ano_sel}:**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ** no campo abaixo.*")

                # Resgate seguro dos dados do 15.2
                d152 = res_data.get("15.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                if d152 is None or not isinstance(d152, dict):
                    d152 = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_152 = d152.get("valor", "")
                evidencia_152_salva = d152.get("link", val_salvo_152)

                # Chaves estáticas limpas
                chave_input_152 = f"q152_{ano_sel}"
                chave_coment_152 = f"coment_15.2_{ano_sel}"

                c152_1, c152_2 = st.columns([1, 1])

                with c152_1:
                    v_input_152 = st.text_input(
                        "Página eletrônica / Link:",
                        value=val_salvo_152,
                        key=chave_input_152,
                        placeholder="Ex: https://... ou XYZ"
                    )

                with c152_2:
                    placeholder_links_152 = st.empty()
                    links_152_visuais = re.findall(REGEX_PURE_URL, v_input_152 or "")
                    if links_152_visuais:
                        placeholder_links_152.markdown(
                            "**🔗 Links ativos detectados:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_152_visuais]
                            )
                        )
                    elif v_input_152.strip().upper() == "XYZ":
                        placeholder_links_152.markdown("ℹ️ *Declarado como indisponível na internet (**XYZ**).*")
                    else:
                        placeholder_links_152.markdown("*Nenhum link ativo detectado no campo ou definido como XYZ.*")

                # Bloco de comentários integrado do 15.2
                bloco_comentarios("15.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.2", key=f"btn_salvar_15_2_{ano_sel}", type="primary"):
                    val_para_salvar_152 = v_input_152.strip()
                    pts_calc_152 = 0.0
                    
                    # No quesito 15.2, o próprio valor informado serve como link de evidência
                    lnk_val_152 = val_para_salvar_152
                    comentario_para_salvar_152 = st.session_state.get(chave_coment_152, d152.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="15.2",
                        valor=val_para_salvar_152,
                        pontos=pts_calc_152,
                        link=lnk_val_152,
                        comentario=comentario_para_salvar_152
                    )
                    res_data["15.2"] = {
                        "valor": val_para_salvar_152,
                        "pontos": pts_calc_152,
                        "link": lnk_val_152,
                        "comentario": comentario_para_salvar_152
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_152 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_152_salva or "")]

                    if lnk_val_152 != evidencia_152_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Estado
                pts_atuais_152 = d152.get("pontos", 0.0)

                if not v_input_152.strip():
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma informação preenchida no Quesito 15.2 (0.0 pontos)</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"✅ Status: Informação salva com sucesso (Impacto: {pts_atuais_152:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 15.2
        if st.session_state.get(f"gatilho_modal_15_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.2", st.session_state.get(f"links_pendentes_15_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 15.3 • CARACTERÍSTICAS (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_caracteristicas_15_3_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.3 - Características Estruturais Disponíveis ({ano_sel})", expanded=True):
                st.subheader("15.3 • Características da Ouvidoria")
                st.write(f"**Assinale as características que a ouvidoria dispõe para a execução de suas atribuições em {ano_sel}:**")
                st.caption("ℹ *Cada característica obrigatória não assinalada subtrai -0.5 pontos (Limite máximo de perda: -2.5).*")

                caracteristicas_obrigatorias = ["Independência", "Isenção", "Acessibilidade", "Transparência", "Confidencialidade"]

                # Resgate seguro dos dados do 15.3
                d153 = res_data.get("15.3") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d153 is None or not isinstance(d153, dict):
                    d153 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_153 = d153.get("valor", "[]")
                evidencia_153_salva = d153.get("link", "")

                # Desserialização segura do valor salvo
                try:
                    if isinstance(val_salvo_153, str):
                        lista_salva_153 = json.loads(val_salvo_153)
                    elif isinstance(val_salvo_153, list):
                        lista_salva_153 = val_salvo_153
                    else:
                        lista_salva_153 = []
                except Exception:
                    try:
                        lista_salva_153 = eval(val_salvo_153) if isinstance(val_salvo_153, str) else []
                    except Exception:
                        lista_salva_153 = []

                if not isinstance(lista_salva_153, list):
                    lista_salva_153 = []

                # Chaves estáticas e limpas
                chave_link_153 = f"l153_{ano_sel}"
                chave_coment_153 = f"coment_15.3_{ano_sel}"

                c153_1, c153_2 = st.columns([1, 1])

                with c153_1:
                    dict_chk_153 = {}
                    for item in caracteristicas_obrigatorias:
                        dict_chk_153[item] = st.checkbox(
                            item,
                            value=item in lista_salva_153,
                            key=f"chk_153_{item}_{ano_sel}"
                        )
                    dict_chk_153["Outros"] = st.checkbox(
                        "Outros",
                        value="Outros" in lista_salva_153,
                        key=f"chk_153_outros_{ano_sel}"
                    )

                with c153_2:
                    link_153 = st.text_area(
                        "Link/Evidência (15.3):",
                        value=evidencia_153_salva,
                        key=chave_link_153,
                        placeholder="Insira os links comprobatórios referente ao Quesito 15.3...",
                        height=180
                    )
                    placeholder_links_153 = st.empty()
                    links_153_visuais = re.findall(REGEX_PURE_URL, link_153 or "")
                    if links_153_visuais:
                        placeholder_links_153.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_153_visuais]
                            )
                        )

                # Bloco de comentários integrado do 15.3
                bloco_comentarios("15.3", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.3
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.3", key=f"btn_salvar_15_3_{ano_sel}", type="primary"):
                    itens_checados_153 = [item for item, checado in dict_chk_153.items() if checado]

                    # Cálculo da penalidade subtrativa: -0.5 para cada obrigatória ausente (máx -2.5)
                    itens_nao_assinalados = sum(1 for x in caracteristicas_obrigatorias if x not in itens_checados_153)
                    pts_calc_153 = max(-(itens_nao_assinalados * 0.5), -2.5)

                    str_lista_153 = json.dumps(itens_checados_153, ensure_ascii=False)
                    lnk_val_153 = link_153.strip()
                    comentario_para_salvar_153 = st.session_state.get(chave_coment_153, d153.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="15.3",
                        valor=str_lista_153,
                        pontos=pts_calc_153,
                        link=lnk_val_153,
                        comentario=comentario_para_salvar_153
                    )
                    res_data["15.3"] = {
                        "valor": str_lista_153,
                        "pontos": pts_calc_153,
                        "link": lnk_val_153,
                        "comentario": comentario_para_salvar_153
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_153 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_153_salva or "")]

                    if lnk_val_153 != evidencia_153_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.3 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Impacto de Pontuação
                pts_atuais_153 = d153.get("pontos", 0.0)
                cor_txt_153 = "#28a745" if pts_atuais_153 == 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_153}; font-weight:bold;'>"
                    f"✅ Status: Opções salvas com sucesso (Impacto: {pts_atuais_153:.2f} pontos)</span>",
                    unsafe_allow_html=True
                )

        # Modal de Evidências do 15.3
        if st.session_state.get(f"gatilho_modal_15_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.3", st.session_state.get(f"links_pendentes_15_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_3_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO 15.4 • ELABORAÇÃO DO RELATÓRIO DE GESTÃO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_relatorio_gestao_15_4_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.4 - Elaboração do Relatório de Gestão ({ano_sel})", expanded=True):
                st.subheader("15.4 • Relatório de Gestão de Exercício")
                st.write(f"**A ouvidoria elaborou Relatório de Gestão do exercício de {ano_sel} contendo a consolidação das manifestações encaminhadas pelos usuários de serviços públicos, e com base nelas, apontou falhas e sugeriu melhorias em sua prestação?**")
                st.caption("ℹ *Caso selecionado 'Não', haverá penalização de -10.0 pontos e limpeza de dados nas subseções internas (15.4.1 e 15.4.2).*")

                opcoes_154 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": -10.0
                }

                # Resgate seguro dos dados do 15.4
                d154 = res_data.get("15.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d154 is None or not isinstance(d154, dict):
                    d154 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_154 = d154.get("valor", "Selecione...")
                evidencia_154_salva = d154.get("link", "")

                # Chaves estáticas e limpas
                chave_radio_154 = f"r_154_{ano_sel}"
                chave_link_154 = f"l154_{ano_sel}"
                chave_coment_154 = f"coment_15.4_{ano_sel}"

                lista_opcoes_154 = list(opcoes_154.keys())
                idx154 = lista_opcoes_154.index(val_salvo_154) if val_salvo_154 in opcoes_154 else 0

                c154_1, c154_2 = st.columns([1, 1])

                with c154_1:
                    v_radio_154 = st.radio(
                        "Selecione 15.4:",
                        options=lista_opcoes_154,
                        index=idx154,
                        key=chave_radio_154,
                        label_visibility="collapsed"
                    )

                with c154_2:
                    link_154 = st.text_area(
                        "Link/Evidência (15.4):",
                        value=evidencia_154_salva,
                        key=chave_link_154,
                        placeholder="Insira os links comprobatórios referente ao Quesito 15.4...",
                        height=100
                    )
                    placeholder_links_154 = st.empty()
                    links_154_visuais = re.findall(REGEX_PURE_URL, link_154 or "")
                    if links_154_visuais:
                        placeholder_links_154.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_154_visuais]
                            )
                        )

                # Bloco de comentários integrado do 15.4
                bloco_comentarios("15.4", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.4
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.4", key=f"btn_salvar_15_4_{ano_sel}", type="primary"):
                    val_para_salvar_154 = v_radio_154
                    pts_calc_154 = opcoes_154.get(val_para_salvar_154, 0.0)
                    lnk_val_154 = link_154.strip()
                    comentario_para_salvar_154 = st.session_state.get(chave_coment_154, d154.get("comentario", ""))

                    # Persistência do 15.4 no banco de dados e sessão
                    save_resp(
                        qid="15.4",
                        valor=val_para_salvar_154,
                        pontos=pts_calc_154,
                        link=lnk_val_154,
                        comentario=comentario_para_salvar_154
                    )
                    res_data["15.4"] = {
                        "valor": val_para_salvar_154,
                        "pontos": pts_calc_154,
                        "link": lnk_val_154,
                        "comentario": comentario_para_salvar_154
                    }

                    # Regra de Limpeza de Subseções / Dependentes caso "Não"
                    if val_para_salvar_154 == "Não":
                        save_resp(qid="15.4.1", valor="[]", pontos=0.0, link="", comentario="")
                        res_data["15.4.1"] = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                        save_resp(qid="15.4.2", valor="Selecione...", pontos=0.0, link="", comentario="")
                        res_data["15.4.2"] = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_154 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_154_salva or "")]

                    if lnk_val_154 != evidencia_154_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.4 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Estado
                pts_atuais_154 = d154.get("pontos", 0.0)

                if val_salvo_154 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 15.4 (0.0 pontos)</span>", unsafe_allow_html=True)
                else:
                    cor_txt_154 = "#28a745" if pts_atuais_154 == 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_154}; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_salvo_154}' salva com sucesso (Impacto: {pts_atuais_154:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 15.4
        if st.session_state.get(f"gatilho_modal_15_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.4", st.session_state.get(f"links_pendentes_15_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_4_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO MULTISSELEÇÃO SUBTRATIVO 15.4.1 • INFORMAÇÕES DOS RELATÓRIOS (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_info_relatorios_15_4_1_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.4.1 - Informações nos Relatórios Gerenciais ({ano_sel})", expanded=True):
                st.subheader("15.4.1 • Informações dos Relatórios")
                st.write(f"**Assinale as informações constantes nos relatórios gerenciais elaborados pela ouvidoria em {ano_sel}:**")
                st.caption("ℹ *Cada item obrigatório ausente subtrai -2.5 pontos.*")

                itens_obrigatorios_1541 = [
                    "Número de manifestações recebidas no exercício anterior",
                    "Motivos das Manifestações",
                    "Análise dos Pontos recorrentes",
                    "Providências adotadas pela administração pública nas soluções apresentadas"
                ]

                # Resgate seguro dos dados do 15.4.1
                d1541 = res_data.get("15.4.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d1541 is None or not isinstance(d1541, dict):
                    d1541 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1541 = d1541.get("valor", "[]")
                evidencia_1541_salva = d1541.get("link", "")

                # Desserialização segura do valor salvo
                try:
                    if isinstance(val_salvo_1541, str):
                        lista_salva_1541 = json.loads(val_salvo_1541)
                    elif isinstance(val_salvo_1541, list):
                        lista_salva_1541 = val_salvo_1541
                    else:
                        lista_salva_1541 = []
                except Exception:
                    try:
                        lista_salva_1541 = eval(val_salvo_1541) if isinstance(val_salvo_1541, str) else []
                    except Exception:
                        lista_salva_1541 = []

                if not isinstance(lista_salva_1541, list):
                    lista_salva_1541 = []

                # Chaves estáticas e limpas
                chave_link_1541 = f"l1541_{ano_sel}"
                chave_coment_1541 = f"coment_15.4.1_{ano_sel}"

                c1541_1, c1541_2 = st.columns([1, 1])

                with c1541_1:
                    dict_chk_1541 = {}
                    for item in itens_obrigatorios_1541:
                        dict_chk_1541[item] = st.checkbox(
                            item,
                            value=item in lista_salva_1541,
                            key=f"chk_1541_{item}_{ano_sel}"
                        )

                with c1541_2:
                    link_1541 = st.text_area(
                        "Link/Evidência (15.4.1):",
                        value=evidencia_1541_salva,
                        key=chave_link_1541,
                        placeholder="Insira os links comprobatórios referente ao Quesito 15.4.1...",
                        height=150
                    )
                    placeholder_links_1541 = st.empty()
                    links_1541_visuais = re.findall(REGEX_PURE_URL, link_1541 or "")
                    if links_1541_visuais:
                        placeholder_links_1541.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1541_visuais]
                            )
                        )

                # Bloco de comentários integrado do 15.4.1
                bloco_comentarios("15.4.1", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.4.1
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.4.1", key=f"btn_salvar_15_4_1_{ano_sel}", type="primary"):
                    itens_checados_1541 = [item for item, checado in dict_chk_1541.items() if checado]

                    # Cálculo da penalidade subtrativa: -2.5 para cada item obrigatório ausente
                    ausentes_1541 = sum(1 for x in itens_obrigatorios_1541 if x not in itens_checados_1541)
                    pts_calc_1541 = -(ausentes_1541 * 2.5)

                    str_lista_1541 = json.dumps(itens_checados_1541, ensure_ascii=False)
                    lnk_val_1541 = link_1541.strip()
                    comentario_para_salvar_1541 = st.session_state.get(chave_coment_1541, d1541.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="15.4.1",
                        valor=str_lista_1541,
                        pontos=pts_calc_1541,
                        link=lnk_val_1541,
                        comentario=comentario_para_salvar_1541
                    )
                    res_data["15.4.1"] = {
                        "valor": str_lista_1541,
                        "pontos": pts_calc_1541,
                        "link": lnk_val_1541,
                        "comentario": comentario_para_salvar_1541
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1541 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1541_salva or "")]

                    if lnk_val_1541 != evidencia_1541_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.4.1 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Estado
                pts_atuais_1541 = d1541.get("pontos", 0.0)
                cor_txt_1541 = "#28a745" if pts_atuais_1541 == 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_1541}; font-weight:bold;'>"
                    f"✅ Status: Opções salvas com sucesso (Impacto: {pts_atuais_1541:.1f} pontos)</span>",
                    unsafe_allow_html=True
                )

        # Modal de Evidências do 15.4.1
        if st.session_state.get(f"gatilho_modal_15_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.4.1", st.session_state.get(f"links_pendentes_15_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_4_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO TEXTO PUNITIVO 15.4.2 • PÁGINA ELETRÔNICA DO RELATÓRIO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_divulgacao_relatorio_15_4_2_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.4.2 - Link de Divulgação do Relatório de Gestão ({ano_sel})", expanded=True):
                st.subheader("15.4.2 • Página Eletrônica do Relatório de Gestão")
                st.write(f"**Informe a página eletrônica (link na internet) de divulgação do Relatório de Gestão do exercício de {ano_sel}:**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira explicitamente o texto **XYZ** para anexar manualmente. (Atenção: digitar XYZ aplica uma penalidade de -10.0 pontos).*")

                # Resgate seguro dos dados do 15.4.2
                d1542 = res_data.get("15.4.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                if d1542 is None or not isinstance(d1542, dict):
                    d1542 = {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_1542 = d1542.get("valor", "")
                evidencia_1542_salva = d1542.get("link", "")

                # Chaves estáticas e limpas
                chave_input_1542 = f"q1542_{ano_sel}"
                chave_coment_1542 = f"coment_15.4.2_{ano_sel}"

                c1542_1, c1542_2 = st.columns([1, 1])

                with c1542_1:
                    v1542 = st.text_input(
                        "Página eletrônica (Link ou XYZ):",
                        value=val_salvo_1542,
                        key=chave_input_1542,
                        placeholder="https://... ou XYZ"
                    )

                with c1542_2:
                    placeholder_links_1542 = st.empty()
                    links_1542_visuais = re.findall(REGEX_PURE_URL, v1542 or "")
                    if links_1542_visuais:
                        placeholder_links_1542.markdown(
                            "**🔗 Links Ativos Detectados:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1542_visuais]
                            )
                        )
                    else:
                        placeholder_links_1542.markdown("*Nenhum link ativo detectado no campo ou definido como XYZ.*")

                # Bloco de comentários integrado do 15.4.2
                bloco_comentarios("15.4.2", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.4.2
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.4.2", key=f"btn_salvar_15_4_2_{ano_sel}", type="primary"):
                    val_para_salvar_1542 = v1542.strip()

                    # Aplicação de penalidade (-10.0 pontos) caso o valor seja exatamente "XYZ"
                    pts_calc_1542 = -10.0 if val_para_salvar_1542.upper() == "XYZ" else 0.0
                    
                    # O próprio campo de texto serve como link/evidência se for URL
                    lnk_val_1542 = val_para_salvar_1542
                    comentario_para_salvar_1542 = st.session_state.get(chave_coment_1542, d1542.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="15.4.2",
                        valor=val_para_salvar_1542,
                        pontos=pts_calc_1542,
                        link=lnk_val_1542,
                        comentario=comentario_para_salvar_1542
                    )
                    res_data["15.4.2"] = {
                        "valor": val_para_salvar_1542,
                        "pontos": pts_calc_1542,
                        "link": lnk_val_1542,
                        "comentario": comentario_para_salvar_1542
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1542 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1542_salva or "")]

                    if lnk_val_1542 != evidencia_1542_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.4.2 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Estado
                pts_atuais_1542 = d1542.get("pontos", 0.0)

                if not val_salvo_1542:
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma informação inserida no Quesito 15.4.2 (0.0 pontos)</span>", unsafe_allow_html=True)
                else:
                    cor_txt_1542 = "#28a745" if pts_atuais_1542 == 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_1542}; font-weight:bold;'>"
                        f"✅ Status: Informação salva com sucesso (Impacto: {pts_atuais_1542:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 15.4.2
        if st.session_state.get(f"gatilho_modal_15_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.4.2", st.session_state.get(f"links_pendentes_15_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_4_2_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO MULTISSELEÇÃO SUBTRATIVO 15.5 • DIVULGAÇÃO E MOBILIZAÇÃO SOCIAL (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_mobilizacao_15_5_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.5 - Iniciativas de Divulgação e Mobilização Social ({ano_sel})", expanded=True):
                st.subheader("15.5 • Divulgação e Mobilização Social")
                st.write(f"**Assinale as iniciativas de divulgação e mobilização social das ouvidorias em {ano_sel}:**")
                st.caption("ℹ *Cada item do bloco penalizável ausente subtrai -0.5 pontos da nota total.*")

                itens_penalizaveis_155 = [
                    "Link da página eletrônica da ouvidoria no sítio da Prefeitura Municipal",
                    "Utilização de outras plataformas digitais para a divulgação da missão, do modo de trabalho das ouvidorias e incentivando a participação popular. Ex.: instagram, facebook, twiter etc."
                ]

                itens_neutros_155 = [
                    "Realização de palestras para grupos e instituições. Ex.: escolas, igrejas, associações civis, outros grupos organizados etc.",
                    "Realização de eventos que estimulem a participação e coleta das demandas sociais. Ex.: realização de audiências públicas para divulgação dos trabalhos desempenhados pela ouvidoria e ouvir as demandas da população."
                ]

                # Resgate seguro dos dados do 15.5
                d155 = res_data.get("15.5") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                if d155 is None or not isinstance(d155, dict):
                    d155 = {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_155 = d155.get("valor", "[]")
                evidencia_155_salva = d155.get("link", "")

                # Desserialização segura do valor salvo
                try:
                    if isinstance(val_salvo_155, str):
                        lista_salva_155 = json.loads(val_salvo_155)
                    elif isinstance(val_salvo_155, list):
                        lista_salva_155 = val_salvo_155
                    else:
                        lista_salva_155 = []
                except Exception:
                    try:
                        lista_salva_155 = eval(val_salvo_155) if isinstance(val_salvo_155, str) else []
                    except Exception:
                        lista_salva_155 = []

                if not isinstance(lista_salva_155, list):
                    lista_salva_155 = []

                # Chaves estáticas e limpas
                chave_link_155 = f"l155_{ano_sel}"
                chave_coment_155 = f"coment_15.5_{ano_sel}"

                c155_1, c155_2 = st.columns([1, 1])

                with c155_1:
                    dict_chk_penalizaveis_155 = {}
                    st.markdown("**Itens de Preenchimento Obrigatório (Sujeitos a Perda):**")
                    for idx, item in enumerate(itens_penalizaveis_155):
                        dict_chk_penalizaveis_155[item] = st.checkbox(
                            item,
                            value=item in lista_salva_155,
                            key=f"chk_155_pen_{idx}_{ano_sel}"
                        )

                    dict_chk_neutros_155 = {}
                    st.markdown("**Iniciativas Complementares (Neutras):**")
                    for idx, item in enumerate(itens_neutros_155):
                        dict_chk_neutros_155[item] = st.checkbox(
                            item,
                            value=item in lista_salva_155,
                            key=f"chk_155_neu_{idx}_{ano_sel}"
                        )

                    chk_outras_155 = st.checkbox(
                        "Outras",
                        value="Outras" in lista_salva_155,
                        key=f"chk_155_outras_{ano_sel}"
                    )

                with c155_2:
                    link_155 = st.text_area(
                        "Link/Evidência (15.5):",
                        value=evidencia_155_salva,
                        key=chave_link_155,
                        placeholder="Insira os links comprobatórios referente ao Quesito 15.5...",
                        height=200
                    )
                    placeholder_links_155 = st.empty()
                    links_155_visuais = re.findall(REGEX_PURE_URL, link_155 or "")
                    if links_155_visuais:
                        placeholder_links_155.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_155_visuais]
                            )
                        )

                # Bloco de comentários integrado do 15.5
                bloco_comentarios("15.5", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 15.5
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 15.5", key=f"btn_salvar_15_5_{ano_sel}", type="primary"):
                    itens_checados_155 = []

                    # Coleta dos itens penalizáveis marcados
                    for item, checado in dict_chk_penalizaveis_155.items():
                        if checado:
                            itens_checados_155.append(item)

                    # Coleta dos itens neutros marcados
                    for item, checado in dict_chk_neutros_155.items():
                        if checado:
                            itens_checados_155.append(item)

                    # Coleta de 'Outras'
                    if chk_outras_155:
                        itens_checados_155.append("Outras")

                    # Cálculo da penalidade subtrativa: -0.5 para cada item penalizável ausente
                    ausentes_155 = sum(1 for x in itens_penalizaveis_155 if x not in itens_checados_155)
                    pts_calc_155 = -(ausentes_155 * 0.5)

                    str_lista_155 = json.dumps(itens_checados_155, ensure_ascii=False)
                    lnk_val_155 = link_155.strip()
                    comentario_para_salvar_155 = st.session_state.get(chave_coment_155, d155.get("comentario", ""))

                    # Persistência no banco de dados e sessão
                    save_resp(
                        qid="15.5",
                        valor=str_lista_155,
                        pontos=pts_calc_155,
                        link=lnk_val_155,
                        comentario=comentario_para_salvar_155
                    )
                    res_data["15.5"] = {
                        "valor": str_lista_155,
                        "pontos": pts_calc_155,
                        "link": lnk_val_155,
                        "comentario": comentario_para_salvar_155
                    }

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_155 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_155_salva or "")]

                    if lnk_val_155 != evidencia_155_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 15.5 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Estado
                pts_atuais_155 = d155.get("pontos", 0.0)
                cor_txt_155 = "#28a745" if pts_atuais_155 == 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_155}; font-weight:bold;'>"
                    f"✅ Status: Opções salvas com sucesso (Impacto: {pts_atuais_155:.2f} pontos)</span>",
                    unsafe_allow_html=True
                )

        # Modal de Evidências do 15.5
        if st.session_state.get(f"gatilho_modal_15_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.5", st.session_state.get(f"links_pendentes_15_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_5_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # QUESITO MASTER 16.0 • CARTA DE SERVIÇO AO USUÁRIO (PADRÃO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_carta_master_16_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.0 - Elaboração da Carta de Serviços ({ano_sel})", expanded=True):
                st.subheader("16.0 • Carta de Serviço ao Usuário")
                st.write(f"**A prefeitura elaborou a \"Carta de Serviço ao Usuário\", que trata dos serviços prestados pelos seus órgãos e entidades, as formas de acesso a esses serviços e seus compromissos e padrões de qualidade de atendimento ao público, conforme artigo 7°, §§ 2º e 3º, da Lei Federal nº 13.460/2017?**")
                st.caption("ℹ *Se modificado para 'Não', o quesito filho 16.1 será limpo e preenchido com 'XYZ' internamente, mantendo-se visível.*")

                opc160 = {"Selecione...": 0.0, "Sim – 04": 4.0, "Não – 00": 0.0}

                # Resgate seguro dos dados do 16.0
                d160 = res_data.get("16.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                if d160 is None or not isinstance(d160, dict):
                    d160 = {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}

                val_salvo_160 = d160.get("valor", "Selecione...")
                evidencia_160_salva = d160.get("link", "")

                # Chaves estáticas e limpas
                chave_radio_160 = f"r_160_{ano_sel}"
                chave_link_160 = f"l160_{ano_sel}"
                chave_coment_160 = f"coment_16.0_{ano_sel}"

                c160_1, c160_2 = st.columns([1, 1])

                with c160_1:
                    lista_opcoes_160 = list(opc160.keys())
                    idx160 = lista_opcoes_160.index(val_salvo_160) if val_salvo_160 in opc160 else 0
                    v160 = st.radio(
                        "Selecione 16.0:",
                        options=lista_opcoes_160,
                        index=idx160,
                        key=chave_radio_160,
                        label_visibility="collapsed"
                    )

                with c160_2:
                    link_160 = st.text_area(
                        "Link/Evidência (16.0):",
                        value=evidencia_160_salva,
                        key=chave_link_160,
                        placeholder="Insira os links comprobatórios referente ao Quesito 16.0...",
                        height=100
                    )
                    placeholder_links_160 = st.empty()
                    links_160_visuais = re.findall(REGEX_PURE_URL, link_160 or "")
                    if links_160_visuais:
                        placeholder_links_160.markdown(
                            "**🔗 Links ativos:** " + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_160_visuais]
                            )
                        )

                # Bloco de comentários integrado do 16.0
                bloco_comentarios("16.0", res_data, ano_sel)

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL 16.0
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Questão 16.0", key=f"btn_salvar_16_0_{ano_sel}", type="primary"):
                    val_para_salvar_160 = v160
                    pts_calc_160 = opc160.get(val_para_salvar_160, 0.0)
                    lnk_val_160 = link_160.strip()
                    comentario_para_salvar_160 = st.session_state.get(chave_coment_160, d160.get("comentario", ""))

                    # Persistência do Quesito Master 16.0
                    save_resp(
                        qid="16.0",
                        valor=val_para_salvar_160,
                        pontos=pts_calc_160,
                        link=lnk_val_160,
                        comentario=comentario_para_salvar_160
                    )
                    res_data["16.0"] = {
                        "valor": val_para_salvar_160,
                        "pontos": pts_calc_160,
                        "link": lnk_val_160,
                        "comentario": comentario_para_salvar_160
                    }

                    # Regra de Dependência: Se selecionado "Não", limpa e marca o filho 16.1 com "XYZ"
                    if "Não" in val_para_salvar_160:
                        comentario_161 = res_data.get("16.1", {}).get("comentario", "") if isinstance(res_data.get("16.1"), dict) else ""
                        save_resp("16.1", "XYZ", 0.0, "", comentario_161)
                        res_data["16.1"] = {
                            "valor": "XYZ",
                            "pontos": 0.0,
                            "link": "",
                            "comentario": comentario_161
                        }
                        # Sincroniza a chave do session_state do quesito filho se existir
                        if f"q161_{ano_sel}" in st.session_state:
                            st.session_state[f"q161_{ano_sel}"] = "XYZ"

                    # Validação de novas evidências para gatilho de modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_160 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_160_salva or "")]

                    if lnk_val_160 != evidencia_160_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta da Questão 16.0 salva com sucesso!", icon="✅")
                    st.rerun()

                # Status e Exibição do Estado
                pts_atuais_160 = d160.get("pontos", 0.0)

                if val_salvo_160 == "Selecione...":
                    st.markdown("<span style='color:#ffc107; font-weight:bold;'>⚠️ Status: Nenhuma opção selecionada no Quesito 16.0 (0.0 pontos)</span>", unsafe_allow_html=True)
                else:
                    cor_txt_160 = "#28a745" if pts_atuais_160 > 0.0 else "#dc3545"
                    st.markdown(
                        f"<span style='color:{cor_txt_160}; font-weight:bold;'>"
                        f"✅ Status: Opção '{val_salvo_160}' salva com sucesso (Impacto: {pts_atuais_160:.1f} pontos)</span>",
                        unsafe_allow_html=True
                    )

        # Modal de Evidências do 16.0
        if st.session_state.get(f"gatilho_modal_16_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.0", st.session_state.get(f"links_pendentes_16_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 16.1 • PÁGINA ELETRÔNICA DA CARTA DE SERVIÇOS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_pagina_carta_16_1_final_{ano_sel}", border=True):
            with st.expander("🗂 Quesito 16.1 - Página Eletrônica de Divulgação da Carta", expanded=True):
                st.subheader("16.1 • Página Eletrônica da Carta de Serviços")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da \"Carta de Serviço ao Usuário\":**")
                st.warning("⚠️ *Se não estiver disponível, insira exatamente o texto **XYZ**.*")

                # Recuperação dos dados salvos no banco de dados
                d161 = res_data.get("16.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_161 = d161.get("valor", "")
                pts_salvos_161 = float(d161.get("pontos", 0.0))

                # Definindo chaves do Streamlit Session State
                chave_texto_161 = f"q161_{ano_sel}"
                chave_coment_161 = f"coment_16.1_{ano_sel}"

                c161_1, c161_2 = st.columns([1, 1])

                with c161_1:
                    v161 = st.text_input(
                        "Página eletrônica (Link ou XYZ):",
                        value=v_salvo_161,
                        key=chave_texto_161,
                        placeholder="https://... ou XYZ"
                    )

                    # Exibição da métrica do Quesito 16.1
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value=f"{pts_salvos_161:.1f} pts",
                        delta="2.0 pts aplicáveis" if pts_salvos_161 > 0 else None
                    )

                with c161_2:
                    placeholder_links_161 = st.empty()
                    links_161_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v161 or "")]
                    if links_161_visuais:
                        placeholder_links_161.markdown(
                            "**🔗 Links Ativos Detectados:** " + " | ".join([f"[{u}]({u})" for u in links_161_visuais])
                        )
                    else:
                        placeholder_links_161.markdown("*Nenhum link ativo detectado no campo ou definido como XYZ.*")

                # Renderiza o bloco de comentários do Quesito 16.1
                bloco_comentarios("16.1", res_data, ano_sel)

                # Feedback visual dinâmico do impacto salvo
                cor_txt_161 = "#28a745" if pts_salvos_161 > 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_161}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.1: {pts_salvos_161:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.1", key=f"btn_salvar_16_1_{ano_sel}", type="primary"):
                    val_161 = v161.strip()
                    
                    # Regra de pontuação: 2.0 pontos se preenchido e diferente de 'XYZ'
                    pts_calculados_161 = 2.0 if val_161 and val_161.upper() != "XYZ" else 0.0
                    
                    # Evidência/link assume o próprio valor inserido se for uma URL válida
                    link_161 = val_161 if re.findall(REGEX_PURE_URL, val_161) else ""
                    comentario_para_salvar = st.session_state.get(chave_coment_161, d161.get("comentario", ""))

                    # Persistência no banco de dados
                    save_resp(
                        qid="16.1",
                        valor=val_161,
                        pontos=float(pts_calculados_161),
                        link=link_161,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário em memória
                    res_data["16.1"] = {
                        "valor": val_161,
                        "pontos": float(pts_calculados_161),
                        "link": link_161,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_161 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_161 or "")]

                    if val_161 != v_salvo_161 and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Página Eletrônica do Quesito 16.1 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 16.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_16_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.1", st.session_state.get(f"links_pendentes_16_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 16.2 • ATUALIZAÇÃO DA CARTA DE SERVIÇOS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_carta_atualizada_16_2_final_{ano_sel}", border=True):
            with st.expander("🗂 Quesito 16.2 - Atualização da Carta de Serviços", expanded=True):
                st.subheader("16.2 • Atualização da Carta")
                st.write("**A 'Carta de Serviço ao Usuário' está atualizada?**")

                # Mapeamento oficial de opções e pontuações do Quesito 16.2
                map_opcoes_162 = {
                    "Selecione...": 0.0,
                    "Sim – 02": 2.0,
                    "Não – 00": 0.0
                }

                # Recuperação segura do banco de dados
                d162 = res_data.get("16.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_162 = d162.get("valor", "Selecione...")
                
                # Normalização do valor salvo para bater com as opções do radio
                if v_salvo_162 == "Sim":
                    v_salvo_162 = "Sim – 02"
                elif v_salvo_162 == "Não":
                    v_salvo_162 = "Não – 00"

                pts_salvos_162 = float(d162.get("pontos", 0.0))
                evidencia_162_salva = d162.get("link", "")

                # Chaves explícitas do Streamlit Session State
                chave_radio_162 = f"r_162_{ano_sel}"
                chave_link_162 = f"l162_{ano_sel}"
                chave_coment_162 = f"coment_16.2_{ano_sel}"

                c162_1, c162_2 = st.columns([1, 1])

                with c162_1:
                    lista_opcoes_162 = list(map_opcoes_162.keys())
                    idx162 = lista_opcoes_162.index(v_salvo_162) if v_salvo_162 in lista_opcoes_162 else 0

                    op_sel_162 = st.radio(
                        "Selecione 16.2:",
                        options=lista_opcoes_162,
                        index=idx162,
                        key=chave_radio_162,
                        label_visibility="collapsed"
                    )

                    # Exibição da métrica de impacto
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value=f"{pts_salvos_162:.1f} pts",
                        delta="2.0 pts aplicáveis" if pts_salvos_162 > 0 else None
                    )

                with c162_2:
                    link_162 = st.text_area(
                        "Link/Evidência (16.2):",
                        value=evidencia_162_salva,
                        key=chave_link_162,
                        placeholder="Inserir link(s) comprobatório(s)...",
                        height=100
                    )
                    placeholder_links_162 = st.empty()
                    links_162_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_162 or "")]
                    if links_162_visuais:
                        placeholder_links_162.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_162_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 16.2
                bloco_comentarios("16.2", res_data, ano_sel)

                # Feedback visual dinâmico do impacto salvo
                cor_txt_162 = "#28a745" if pts_salvos_162 > 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_162}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.2: {pts_salvos_162:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.2", key=f"btn_salvar_16_2_{ano_sel}", type="primary"):
                    val_radio = st.session_state.get(chave_radio_162, op_sel_162)
                    pts_calculados_162 = map_opcoes_162.get(val_radio, 0.0)
                    lnk_val = link_162.strip()

                    # Limpa a string da opção para salvar no formato padronizado no banco ("Sim", "Não", "Selecione...")
                    val_salvar = "Sim" if "Sim" in val_radio else ("Não" if "Não" in val_radio else "Selecione...")
                    comentario_para_salvar = st.session_state.get(chave_coment_162, d162.get("comentario", ""))

                    # Persistência no banco de dados
                    save_resp(
                        qid="16.2",
                        valor=val_salvar,
                        pontos=float(pts_calculados_162),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário em memória
                    res_data["16.2"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados_162),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_162_salva or "")]

                    if lnk_val != evidencia_162_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 16.2 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 16.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_16_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.2", st.session_state.get(f"links_pendentes_16_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_2_{ano_sel}"] = False

# =============================================================================
        # QUESITO 16.3 • REGULAMENTAÇÃO DA CARTA DE SERVIÇOS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_regulamentacao_16_3_final_{ano_sel}", border=True):
            with st.expander("📌 Quesito 16.3 - Regulamentação da Carta de Serviços", expanded=True):
                st.subheader("16.3 • Regulamentação da Carta")
                st.write("**A prefeitura regulamentou a operacionalização da Carta de Serviços ao Usuário, conforme o artigo 7°, § 5°, da Lei Federal n° 13.460/2017?**")
                st.caption("ℹ *Caso modificado para 'Não', haverá cascata de limpeza automática nas subseções internas (16.3.1 e 16.3.2).*")

                # Mapeamento oficial de opções e pontuações do Quesito 16.3
                opc163 = {
                    "Selecione...": 0.0,
                    "Sim – 04": 4.0,
                    "Não – 00": 0.0
                }

                # Recuperação segura dos dados salvos no banco
                d163 = res_data.get("16.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_163 = d163.get("valor", "Selecione...")

                # Normalização do valor salvo para bater com as opções do radio
                if v_salvo_163 == "Sim":
                    v_salvo_163 = "Sim – 04"
                elif v_salvo_163 == "Não":
                    v_salvo_163 = "Não – 00"

                pts_salvos_163 = float(d163.get("pontos", 0.0))
                evidencia_163_salva = d163.get("link", "")

                # Chaves explícitas do Streamlit Session State
                chave_radio_163 = f"r_163_{ano_sel}"
                chave_link_163 = f"l163_{ano_sel}"
                chave_coment_163 = f"coment_16.3_{ano_sel}"

                c163_1, c163_2 = st.columns([1, 1])

                with c163_1:
                    lista_opcoes_163 = list(opc163.keys())
                    idx163 = lista_opcoes_163.index(v_salvo_163) if v_salvo_163 in lista_opcoes_163 else 0

                    op_sel_163 = st.radio(
                        "Selecione 16.3:",
                        options=lista_opcoes_163,
                        index=idx163,
                        key=chave_radio_163,
                        label_visibility="collapsed"
                    )

                    # Exibição da métrica de impacto
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value=f"{pts_salvos_163:.1f} pts",
                        delta="4.0 pts aplicáveis" if pts_salvos_163 > 0 else None
                    )

                with c163_2:
                    link_163 = st.text_area(
                        "Link/Evidência (16.3):",
                        value=evidencia_163_salva,
                        key=chave_link_163,
                        placeholder="Inserir link do decreto ou norma de regulamentação...",
                        height=100
                    )
                    placeholder_links_163 = st.empty()
                    links_163_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_163 or "")]
                    if links_163_visuais:
                        placeholder_links_163.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_163_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 16.3
                bloco_comentarios("16.3", res_data, ano_sel)

                # Feedback visual dinâmico do impacto salvo
                cor_txt_163 = "#28a745" if pts_salvos_163 > 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_163}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.3: {pts_salvos_163:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL COM CASCATA (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.3", key=f"btn_salvar_16_3_{ano_sel}", type="primary"):
                    val_radio = st.session_state.get(chave_radio_163, op_sel_163)
                    pts_calculados_163 = opc163.get(val_radio, 0.0)
                    lnk_val = link_163.strip()

                    # Padronização da string salva no banco ("Sim", "Não", "Selecione...")
                    val_salvar = "Sim" if "Sim" in val_radio else ("Não" if "Não" in val_radio else "Selecione...")
                    comentario_para_salvar = st.session_state.get(chave_coment_163, d163.get("comentario", ""))

                    # Persistência do quesito pai no banco de dados
                    save_resp(
                        qid="16.3",
                        valor=val_salvar,
                        pontos=float(pts_calculados_163),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário em memória
                    res_data["16.3"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados_163),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Regra de Cascata: Se não for "Sim", reseta as subseções 16.3.1 e 16.3.2
                    if val_salvar != "Sim":
                        save_resp("16.3.1", "", 0.0, "")
                        save_resp("16.3.2", "", 0.0, "")

                        res_data["16.3.1"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": res_data.get("16.3.1", {}).get("comentario", "")}
                        res_data["16.3.2"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": res_data.get("16.3.2", {}).get("comentario", "")}

                    # Verificação de novos links para disparo do modal de validação
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_163_salva or "")]

                    if lnk_val != evidencia_163_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 16.3 e regras de cascata salvas com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 16.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_16_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.3", st.session_state.get(f"links_pendentes_16_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_3_{ano_sel}"] = False

# =============================================================================
        # QUESITO 16.3.1 • DETALHES DO INSTRUMENTO NORMATIVO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_norma_detalhe_16_3_1_final_{ano_sel}", border=True):
            with st.expander("📑 Quesito 16.3.1 - Detalhes do Instrumento Normativo", expanded=True):
                st.subheader("16.3.1 • Dados do Instrumento")
                st.write("**Informe o instrumento normativo que regulamentou a 'Carta de Serviço ao Usuário', Número e Data da publicação:**")
                st.info("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o Instrumento Normativo de regulamentação no Sistema de Questionários.*")

                # Recuperação segura dos dados do banco
                d1631 = res_data.get("16.3.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_1631 = d1631.get("valor", "")
                evidencia_1631_salva = d1631.get("link", "")

                # Chaves explícitas no Session State
                chave_input_1631 = f"q1631_{ano_sel}"
                chave_link_1631 = f"l1631_{ano_sel}"
                chave_coment_1631 = f"coment_16.3.1_{ano_sel}"

                c1631_1, c1631_2 = st.columns([1, 1])

                with c1631_1:
                    val_input_1631 = st.text_input(
                        "Instrumento normativo, número e data:",
                        value=v_salvo_1631,
                        key=chave_input_1631,
                        placeholder="Ex: Decreto nº 1.234/2023, publicado em 15/03/2023"
                    )

                    # Exibição da métrica informativa (0.0 pts)
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value="0.0 pts",
                        delta=None
                    )

                with c1631_2:
                    link_1631 = st.text_area(
                        "Link/Evidência (16.3.1):",
                        value=evidencia_1631_salva,
                        key=chave_link_1631,
                        placeholder="Inserir link(s) comprobatório(s)...",
                        height=100
                    )
                    placeholder_links_1631 = st.empty()
                    links_1631_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_1631 or "")]
                    if links_1631_visuais:
                        placeholder_links_1631.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_1631_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 16.3.1
                bloco_comentarios("16.3.1", res_data, ano_sel)

                # Feedback visual dinâmico
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.3.1: 0.0 pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.3.1", key=f"btn_salvar_16_3_1_{ano_sel}", type="primary"):
                    texto_norma = st.session_state.get(chave_input_1631, val_input_1631).strip()
                    lnk_val = link_1631.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_1631, d1631.get("comentario", ""))

                    # Persistência no banco de dados
                    save_resp(
                        qid="16.3.1",
                        valor=texto_norma,
                        pontos=0.0,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local
                    res_data["16.3.1"] = {
                        "valor": texto_norma,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1631_salva or "")]

                    if lnk_val != evidencia_1631_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 16.3.1 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 16.3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_16_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.3.1", st.session_state.get(f"links_pendentes_16_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_3_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 16.3.2 • ENDEREÇO ELETRÔNICO DA NORMA (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_url_norma_16_3_2_final_{ano_sel}", border=True):
            with st.expander("🔗 Quesito 16.3.2 - Endereço Eletrônico da Regulamentação", expanded=True):
                st.subheader("16.3.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo que regulamentou a 'Carta de Serviço ao Usuário':**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ** no campo abaixo.*")

                # Recuperação segura dos dados salvos no banco
                d1632 = res_data.get("16.3.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_1632 = d1632.get("valor", "")

                # Chaves explícitas no Session State
                chave_input_1632 = f"q1632_{ano_sel}"
                chave_coment_1632 = f"coment_16.3.2_{ano_sel}"

                c1632_1, c1632_2 = st.columns([1, 1])

                with c1632_1:
                    v_campo_1632 = st.text_input(
                        "Página eletrônica (Link ou XYZ) do instrumento:",
                        value=v_salvo_1632,
                        key=chave_input_1632,
                        placeholder="Ex: https://... ou XYZ"
                    )

                    # Exibição da métrica informativa (0.0 pts)
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value="0.0 pts",
                        delta=None
                    )

                with c1632_2:
                    placeholder_links_1632 = st.empty()
                    links_1632_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_campo_1632 or "")]
                    if links_1632_visuais:
                        placeholder_links_1632.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_1632_visuais])
                        )
                    else:
                        placeholder_links_1632.markdown("*Nenhum link ativo detectado no campo.*")

                # Renderiza o bloco de comentários do Quesito 16.3.2
                bloco_comentarios("16.3.2", res_data, ano_sel)

                # Feedback visual dinâmico
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.3.2: 0.0 pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.3.2", key=f"btn_salvar_16_3_2_{ano_sel}", type="primary"):
                    v_txt = st.session_state.get(chave_input_1632, v_campo_1632).strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_1632, d1632.get("comentario", ""))

                    # No quesito 16.3.2, o valor do texto informado atua simultaneamente como link/evidência
                    save_resp(
                        qid="16.3.2",
                        valor=v_txt,
                        pontos=0.0,
                        link=v_txt,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local em memória
                    res_data["16.3.2"] = {
                        "valor": v_txt,
                        "pontos": 0.0,
                        "link": v_txt,
                        "comentario": comentario_para_salvar
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_txt or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_1632 or "")]

                    if v_txt != v_salvo_1632 and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_3_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_3_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 16.3.2 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 16.3.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_16_3_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.3.2", st.session_state.get(f"links_pendentes_16_3_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_3_2_{ano_sel}"] = False

# =============================================================================
        # QUESITO MASTER 17.0 • REGULAMENTAÇÃO DO CONSELHO DE USUÁRIOS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_conselho_master_17_0_final_{ano_sel}", border=True):
            with st.expander("📌 Quesito 17.0 - Regulamentação do Conselho de Usuários", expanded=True):
                st.subheader("17.0 • Regulamentação e Instituição")
                st.write("**A prefeitura regulamentou e instituiu o Conselho de Usuários, nos termos definidos nos artigos 18 a 21 da Lei Federal nº 13.460/2017?**")
                st.caption("ℹ *Se modificado para 'Não' ou 'Selecione...', as subseções filhas (17.1 e 17.2) serão automaticamente limpas via cascata.*")

                # Mapeamento oficial de opções e pontuações do Quesito 17.0
                opc170 = {
                    "Selecione...": 0.0,
                    "Sim – 04": 4.0,
                    "Não – 00": 0.0
                }

                # Recuperação segura dos dados salvos no banco
                d170 = res_data.get("17.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_170 = d170.get("valor", "Selecione...")

                # Normalização do valor salvo para bater com as opções do radio
                if v_salvo_170 == "Sim":
                    v_salvo_170 = "Sim – 04"
                elif v_salvo_170 == "Não":
                    v_salvo_170 = "Não – 00"

                pts_salvos_170 = float(d170.get("pontos", 0.0))
                evidencia_170_salva = d170.get("link", "")

                # Chaves explícitas no Session State
                chave_radio_170 = f"r_170_{ano_sel}"
                chave_link_170 = f"l170_final_txt_{ano_sel}"
                chave_coment_170 = f"coment_17.0_exclusivo_g17_{ano_sel}"

                c170_1, c170_2 = st.columns([1, 1])

                with c170_1:
                    lista_opcoes_170 = list(opc170.keys())
                    idx170 = lista_opcoes_170.index(v_salvo_170) if v_salvo_170 in lista_opcoes_170 else 0

                    op_sel_170 = st.radio(
                        "Selecione 17.0:",
                        options=lista_opcoes_170,
                        index=idx170,
                        key=chave_radio_170,
                        label_visibility="collapsed"
                    )

                    # Exibição da métrica de impacto de pontuação
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value=f"{pts_salvos_170:.1f} pts",
                        delta="4.0 pts aplicáveis" if pts_salvos_170 > 0 else None
                    )

                with c170_2:
                    link_170 = st.text_area(
                        "Link/Evidência (17.0):",
                        value=evidencia_170_salva,
                        key=chave_link_170,
                        placeholder="Inserir link da norma de regulamentação do Conselho de Usuários...",
                        height=100
                    )
                    placeholder_links_170 = st.empty()
                    links_170_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_170 or "")]
                    if links_170_visuais:
                        placeholder_links_170.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_170_visuais])
                        )

                # Renderiza o bloco de comentários específico do Quesito 17.0
                bloco_comentarios("17.0_exclusivo_g17", res_data, ano_sel)

                # Feedback visual dinâmico do impacto salvo
                cor_txt_170 = "#28a745" if pts_salvos_170 > 0.0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_170}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 17.0: {pts_salvos_170:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL COM CASCATA (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 17.0", key=f"btn_salvar_17_0_{ano_sel}", type="primary"):
                    val_radio = st.session_state.get(chave_radio_170, op_sel_170)
                    pts_calculados_170 = opc170.get(val_radio, 0.0)
                    lnk_val = link_170.strip()

                    # Padronização da string salva ("Sim", "Não", "Selecione...")
                    val_salvar = "Sim" if "Sim" in val_radio else ("Não" if "Não" in val_radio else "Selecione...")
                    comentario_para_salvar = st.session_state.get(chave_coment_170, d170.get("comentario", ""))

                    # Persistência no banco de dados
                    save_resp(
                        qid="17.0",
                        valor=val_salvar,
                        pontos=float(pts_calculados_170),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local em memória
                    res_data["17.0"] = {
                        "valor": val_salvar,
                        "pontos": float(pts_calculados_170),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Regra de Cascata: Se não for "Sim", reseta as subseções 17.1 e 17.2
                    if val_salvar != "Sim":
                        save_resp("17.1", "", 0.0, "")
                        save_resp("17.2", "", 0.0, "")

                        res_data["17.1"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": res_data.get("17.1", {}).get("comentario", "")}
                        res_data["17.2"] = {"valor": "", "pontos": 0.0, "link": "", "comentario": res_data.get("17.2", {}).get("comentario", "")}

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_170_salva or "")]

                    if lnk_val != evidencia_170_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_17_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 17.0 e regras de cascata salvas com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 17.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_17_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.0", st.session_state.get(f"links_pendentes_17_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = False

# =============================================================================
        # QUESITO TEXTUAL FILHO 17.1 • DETALHES DO INSTRUMENTO NORMATIVO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_norma_conselho_17_1_final_{ano_sel}", border=True):
            with st.expander("📑 Quesito 17.1 - Detalhes do Instrumento Normativo do Conselho", expanded=True):
                st.subheader("17.1 • Dados do Instrumento")
                st.write("**Informe o instrumento normativo que regulamentou os Conselhos de Usuários, Número e Data da publicação:**")
                st.info("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o Instrumento Normativo no Sistema de Questionários.*")

                # Recuperação segura dos dados salvos
                d171 = res_data.get("17.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_171 = d171.get("valor", "")
                evidencia_171_salva = d171.get("link", "")

                # Chaves explícitas no Session State
                chave_input_171 = f"q171_final_input_{ano_sel}"
                chave_link_171 = f"l171_final_input_{ano_sel}"
                chave_coment_171 = f"coment_17.1_exclusivo_g17_{ano_sel}"

                c171_1, c171_2 = st.columns([1, 1])

                with c171_1:
                    val_input_171 = st.text_input(
                        "Instrumento normativo, número e data:",
                        value=v_salvo_171,
                        key=chave_input_171,
                        placeholder="Ex: Decreto nº 5.678/2023, publicado em 10/05/2023"
                    )

                    # Exibição da métrica informativa (0.0 pts)
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value="0.0 pts",
                        delta=None
                    )

                with c171_2:
                    link_171 = st.text_area(
                        "Link/Evidência (17.1):",
                        value=evidencia_171_salva,
                        key=chave_link_171,
                        placeholder="Inserir link(s) comprobatório(s)...",
                        height=100
                    )
                    placeholder_links_171 = st.empty()
                    links_171_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_171 or "")]
                    if links_171_visuais:
                        placeholder_links_171.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_171_visuais])
                        )

                # Renderiza o bloco de comentários do Quesito 17.1
                bloco_comentarios("17.1_exclusivo_g17", res_data, ano_sel)

                # Feedback visual dinâmico
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 17.1: 0.0 pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 17.1", key=f"btn_salvar_17_1_{ano_sel}", type="primary"):
                    texto_norma_171 = st.session_state.get(chave_input_171, val_input_171).strip()
                    lnk_val_171 = link_171.strip()
                    comentario_para_salvar_171 = st.session_state.get(chave_coment_171, d171.get("comentario", ""))

                    # Persistência no banco de dados
                    save_resp(
                        qid="17.1",
                        valor=texto_norma_171,
                        pontos=0.0,
                        link=lnk_val_171,
                        comentario=comentario_para_salvar_171
                    )

                    # Atualização no dicionário local em memória
                    res_data["17.1"] = {
                        "valor": texto_norma_171,
                        "pontos": 0.0,
                        "link": lnk_val_171,
                        "comentario": comentario_para_salvar_171
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais_171 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_171 or "")]
                    links_antigos_171 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_171_salva or "")]

                    if lnk_val_171 != evidencia_171_salva and links_atuais_171 and links_atuais_171 != links_antigos_171:
                        st.session_state[f"links_pendentes_17_1_{ano_sel}"] = links_atuais_171
                        st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 17.1 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 17.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_17_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.1", st.session_state.get(f"links_pendentes_17_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO TEXTUAL FILHO 17.2 • ENDEREÇO ELETRÔNICO DO CONSELHO (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_url_conselho_17_2_final_{ano_sel}", border=True):
            with st.expander("🔗 Quesito 17.2 - Endereço Eletrônico do Conselho", expanded=True):
                st.subheader("17.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da regulamentação do Conselho de Usuários:**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ** no campo abaixo.*")

                # Recuperação segura dos dados salvos
                d172 = res_data.get("17.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_172 = d172.get("valor", "")

                # Chaves explícitas no Session State
                chave_input_172 = f"q172_final_input_{ano_sel}"
                chave_coment_172 = f"coment_17.2_exclusivo_g17_{ano_sel}"

                c172_1, c172_2 = st.columns([1, 1])

                with c172_1:
                    v_campo_172 = st.text_input(
                        "Página eletrônica (Link ou XYZ):",
                        value=v_salvo_172,
                        key=chave_input_172,
                        placeholder="Ex: https://... ou XYZ"
                    )

                    # Exibição da métrica informativa (0.0 pts)
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value="0.0 pts",
                        delta=None
                    )

                with c172_2:
                    placeholder_links_172 = st.empty()
                    links_172_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_campo_172 or "")]
                    if links_172_visuais:
                        placeholder_links_172.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_172_visuais])
                        )
                    else:
                        placeholder_links_172.markdown("*Nenhum link ativo detectado no campo.*")

                # Renderiza o bloco de comentários do Quesito 17.2
                bloco_comentarios("17.2_exclusivo_g17", res_data, ano_sel)

                # Feedback visual dinâmico
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 17.2: 0.0 pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 17.2", key=f"btn_salvar_17_2_{ano_sel}", type="primary"):
                    v_txt_172 = st.session_state.get(chave_input_172, v_campo_172).strip()
                    comentario_para_salvar_172 = st.session_state.get(chave_coment_172, d172.get("comentario", ""))

                    # No quesito 17.2, o valor do texto informado atua simultaneamente como link/evidência
                    save_resp(
                        qid="17.2",
                        valor=v_txt_172,
                        pontos=0.0,
                        link=v_txt_172,
                        comentario=comentario_para_salvar_172
                    )

                    # Atualização no dicionário local em memória
                    res_data["17.2"] = {
                        "valor": v_txt_172,
                        "pontos": 0.0,
                        "link": v_txt_172,
                        "comentario": comentario_para_salvar_172
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais_172 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_txt_172 or "")]
                    links_antigos_172 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_172 or "")]

                    if v_txt_172 != v_salvo_172 and links_atuais_172 and links_atuais_172 != links_antigos_172:
                        st.session_state[f"links_pendentes_17_2_{ano_sel}"] = links_atuais_172
                        st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 17.2 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 17.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_17_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.2", st.session_state.get(f"links_pendentes_17_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 18.0 • ELABORAÇÃO DO PLANO DIREITOR (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_plano_diretor_master_18_0_final_{ano_sel}", border=True):
            with st.expander("📌 Quesito 18.0 - Elaboração do Plano Diretor", expanded=True):
                st.subheader("18.0 • Elaboração")
                st.write("**O município elaborou Plano Diretor conforme Lei nº 10.257/01?**")
                st.caption("ℹ *Se modificado para um valor diferente de 'Sim', a data de atualização do quesito filho 18.1 será automaticamente limpa via cascata.*")

                # Oções oficiais do Quesito 18.0 (Todas com impacto 0.0)
                opc180 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0,
                    "Não se aplica": 0.0
                }

                # Recuperação segura dos dados salvos no banco
                d180 = res_data.get("18.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_180 = d180.get("valor", "Selecione...")
                evidencia_180_salva = d180.get("link", "")

                # Chaves explícitas no Session State
                chave_radio_180 = f"r_180_{ano_sel}"
                chave_link_180 = f"l80_txt_final_{ano_sel}"
                chave_coment_180 = f"coment_18.0_exclusivo_g8_{ano_sel}"

                c180_1, c180_2 = st.columns([1, 1])

                with c180_1:
                    lista_opcoes_180 = list(opc180.keys())
                    idx180 = lista_opcoes_180.index(v_salvo_180) if v_salvo_180 in lista_opcoes_180 else 0

                    op_sel_180 = st.radio(
                        "Selecione 18.0:",
                        options=lista_opcoes_180,
                        index=idx180,
                        key=chave_radio_180,
                        label_visibility="collapsed"
                    )

                    # Exibição da métrica informativa (0.0 pts)
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value="0.0 pts",
                        delta=None
                    )

                with c180_2:
                    link_180 = st.text_area(
                        "Link/Evidência (18.0):",
                        value=evidencia_180_salva,
                        key=chave_link_180,
                        placeholder="Inserir link da norma/página do Plano Diretor...",
                        height=100
                    )
                    placeholder_links_180 = st.empty()
                    links_180_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_180 or "")]
                    if links_180_visuais:
                        placeholder_links_180.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_180_visuais])
                        )

                # Renderiza o bloco de comentários específico do Quesito 18.0
                bloco_comentarios("18.0_exclusivo_g8", res_data, ano_sel)

                # Feedback visual dinâmico
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 18.0: 0.0 pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL COM CASCATA (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 18.0", key=f"btn_salvar_18_0_{ano_sel}", type="primary"):
                    val_radio = st.session_state.get(chave_radio_180, op_sel_180)
                    lnk_val = link_180.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_180, d180.get("comentario", ""))

                    # Persistência no banco de dados
                    save_resp(
                        qid="18.0",
                        valor=val_radio,
                        pontos=0.0,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local em memória
                    res_data["18.0"] = {
                        "valor": val_radio,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Regra de Cascata: Se for diferente de "Sim", reseta a data do quesito filho 18.1
                    if val_radio != "Sim":
                        save_resp("18.1", "", 0.0, "")
                        res_data["18.1"] = {
                            "valor": "",
                            "pontos": 0.0,
                            "link": "",
                            "comentario": res_data.get("18.1", {}).get("comentario", "")
                        }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_180_salva or "")]

                    if lnk_val != evidencia_180_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_18_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 18.0 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 18.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_18_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.0", st.session_state.get(f"links_pendentes_18_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO DATA FILHO 18.1 • DATA DE ATUALIZAÇÃO DO PLANO DIREITOR (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_data_plano_18_1_final_{ano_sel}", border=True):
            with st.expander("📅 Quesito 18.1 - Data de Atualização do Plano Diretor", expanded=True):
                st.subheader("18.1 • Última Atualização")
                st.write("**Informe a data da última atualização do Plano Diretor:**")
                st.info("ℹ️ **Fórmula de Cálculo:**\n* 📅 **Até 31/12/2015:** -10.0 pontos.\n* 📅 **A partir de 01/01/2016:** 0.0 ponto.")

                # Recuperação segura dos dados salvos no banco
                d181 = res_data.get("18.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_181 = d181.get("valor", "")
                pts_salvos_181 = float(d181.get("pontos", 0.0))
                evidencia_181_salva = d181.get("link", "")

                # Parseamento seguro da data armazenada
                try:
                    dt_inicial_181 = datetime.strptime(v_salvo_181, "%Y-%m-%d").date() if v_salvo_181 else date.today()
                except Exception:
                    dt_inicial_181 = date.today()

                # Chaves explícitas no Session State
                chave_date_181 = f"dt181_{ano_sel}"
                chave_link_181 = f"l181_{ano_sel}"
                chave_coment_181 = f"coment_18.1_exclusivo_g8_{ano_sel}"

                c181_1, c181_2 = st.columns([1, 1])

                with c181_1:
                    dt_sel_181 = st.date_input(
                        "Data da última atualização:",
                        value=dt_inicial_181,
                        key=chave_date_181,
                        format="DD/MM/YYYY"
                    )

                    # Exibição da métrica de impacto da pontuação salva
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value=f"{pts_salvos_181:.1f} pts",
                        delta="-10.0 pts aplicados" if pts_salvos_181 == -10.0 else None
                    )

                with c181_2:
                    link_181 = st.text_area(
                        "Justificativa / Link de Evidência (18.1):",
                        value=evidencia_181_salva,
                        key=chave_link_181,
                        placeholder="Inserir justificativa e link da norma de atualização...",
                        height=100
                    )
                    placeholder_links_181 = st.empty()
                    links_181_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_181 or "")]
                    if links_181_visuais:
                        placeholder_links_181.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_181_visuais])
                        )

                # Renderiza o bloco de comentários específico do Quesito 18.1
                bloco_comentarios("18.1_exclusivo_g8", res_data, ano_sel)

                # Feedback visual dinâmico do impacto salvo
                cor_txt_181 = "#dc3545" if pts_salvos_181 == -10.0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_txt_181}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 18.1: {pts_salvos_181:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 18.1", key=f"btn_salvar_18_1_{ano_sel}", type="primary"):
                    dt_informada = st.session_state.get(chave_date_181, dt_sel_181)
                    
                    # Regra de negócio: Cálculo do impacto de pontos com base na data
                    pts_calculados_181 = -10.0 if dt_informada <= date(2015, 12, 31) else 0.0
                    
                    str_data_salvar = str(dt_informada)
                    lnk_val = link_181.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_181, d181.get("comentario", ""))

                    # Persistência no banco de dados
                    save_resp(
                        qid="18.1",
                        valor=str_data_salvar,
                        pontos=float(pts_calculados_181),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local em memória
                    res_data["18.1"] = {
                        "valor": str_data_salvar,
                        "pontos": float(pts_calculados_181),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_181_salva or "")]

                    if lnk_val != evidencia_181_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_18_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta do Quesito 18.1 salva com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 18.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_18_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.1", st.session_state.get(f"links_pendentes_18_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO INFORMATIVO TEXTUAL 19.0 • FEEDBACK SOBRE O QUESTIONÁRIO (Padrão iGov)
        # =============================================================================
        st.markdown("---", unsafe_allow_html=True)
        with st.container(key=f"container_bloco_feedback_19_0_final_{ano_sel}", border=True):
            with st.expander("💬 Quesito 19.0 - Encerramento e Feedback", expanded=True):
                st.subheader("19.0 • Feedback sobre o Questionário")
                st.write("**Gostaria de registrar suas impressões, comentários e sugestões a respeito do presente questionário?**")

                # Recuperação segura dos dados salvos no banco
                d190 = res_data.get("19.0") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_190_salva = d190.get("link", "") or d190.get("valor", "")

                # Chaves explícitas no Session State
                chave_link_190 = f"l190_text_{ano_sel}"
                chave_coment_190 = f"coment_19.0_exclusivo_g19_{ano_sel}"

                c190_1, c190_2 = st.columns([1, 1])

                with c190_1:
                    st.info(
                        "💡 **Quesito Informativo**\n\n"
                        "Este espaço é destinado à melhoria contínua dos nossos processos. "
                        "Suas respostas não alteram a nota final do município."
                    )

                    # Exibição da métrica informativa (0.0 pts)
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value="0.0 pts",
                        delta=None
                    )

                with c190_2:
                    link_190 = st.text_area(
                        "Utilize o espaço abaixo para registrar suas observações:",
                        value=evidencia_190_salva,
                        key=chave_link_190,
                        placeholder="Digite aqui suas observações, críticas ou sugestões...",
                        height=140
                    )
                    placeholder_links_190 = st.empty()
                    links_190_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_190 or "")]
                    if links_190_visuais:
                        placeholder_links_190.markdown(
                            "**🔗 Links Detectados:** " + " | ".join([f"[{u}]({u})" for u in links_190_visuais])
                        )

                # Renderiza o bloco de comentários específico do Quesito 19.0
                bloco_comentarios("19.0_exclusivo_g19", res_data, ano_sel)

                # Feedback visual dinâmico
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 19.0: 0.0 pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 19.0", key=f"btn_salvar_19_0_{ano_sel}", type="primary"):
                    lnk_val = link_190.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_190, d190.get("comentario", ""))

                    # Persistência no banco de dados (valor e link recebem o texto por ser quesito textual)
                    save_resp(
                        qid="19.0",
                        valor=lnk_val,
                        pontos=0.0,
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local em memória
                    res_data["19.0"] = {
                        "valor": lnk_val,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_190_salva or "")]

                    if lnk_val != evidencia_190_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_19_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Feedback do Quesito 19.0 salvo com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 19.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_19_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.0", st.session_state.get(f"links_pendentes_19_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO P1 • COERÊNCIA ENTRE RESULTADOS (Pontuação Manual + Alternativa 0)
        # =============================================================================
        with st.container(key=f"container_bloco_p1_coerencia_{ano_sel}", border=True):
            with st.expander("📌 Quesito P1 - Coerência entre Resultados dos Indicadores e Metas", expanded=True):
                st.subheader("P1 • Coerência entre Indicadores e Metas")
                st.write("**Avaliação da coerência entre os resultados dos indicadores dos programas e as metas das ações:**")
                st.caption("ℹ *Este quesito aceita digitação manual de nota ou atribuição direta de 0.0 ponto.*")

                # Recuperação segura dos dados salvos no banco
                dP1 = res_data.get("P1") or {"valor": "0.0", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_P1 = dP1.get("valor", "0.0")
                pts_salvos_P1 = float(dP1.get("pontos", 0.0))
                evidencia_P1_salva = dP1.get("link", "")

                # Chaves explícitas no Session State
                chave_num_P1 = f"num_p1_{ano_sel}"
                chave_zerar_P1 = f"btn_zerar_p1_{ano_sel}"
                chave_link_P1 = f"l_p1_text_{ano_sel}"
                chave_coment_P1 = f"coment_P1_exclusivo_{ano_sel}"

                cP1_1, cP1_2 = st.columns([1, 1])

                with cP1_1:
                    # Campo para inserção manual de pontuação
                    nota_input_P1 = st.number_input(
                        "Digite a pontuação manual:",
                        min_value=0.0,
                        max_value=100.0,
                        value=pts_salvos_P1,
                        step=0.5,
                        format="%.1f",
                        key=chave_num_P1
                    )

                    # Exibição da métrica de pontuação salva
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value=f"{pts_salvos_P1:.1f} pts",
                        delta=None
                    )

                with cP1_2:
                    link_P1 = st.text_area(
                        "Justificativa / Link de Evidência (P1):",
                        value=evidencia_P1_salva,
                        key=chave_link_P1,
                        placeholder="Inserir justificativa da nota atribuída e links de evidência...",
                        height=120
                    )
                    placeholder_links_P1 = st.empty()
                    links_P1_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_P1 or "")]
                    if links_P1_visuais:
                        placeholder_links_P1.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_P1_visuais])
                        )

                # Renderiza o bloco de comentários específico do Quesito P1
                bloco_comentarios("P1_exclusivo", res_data, ano_sel)

                # Feedback visual dinâmico
                cor_txt_P1 = "#28a745" if pts_salvos_P1 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_P1}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito P1: {pts_salvos_P1:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito P1", key=f"btn_salvar_p1_{ano_sel}", type="primary"):
                    pts_digita = st.session_state.get(chave_num_P1, nota_input_P1)
                    lnk_val = link_P1.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_P1, dP1.get("comentario", ""))

                    str_valor = f"{pts_digita:.1f}"

                    # Persistência no banco de dados
                    save_resp(
                        qid="P1",
                        valor=str_valor,
                        pontos=float(pts_digita),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local em memória
                    res_data["P1"] = {
                        "valor": str_valor,
                        "pontos": float(pts_digita),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_P1_salva or "")]

                    if lnk_val != evidencia_P1_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_p1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_p1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast(f"Quesito P1 salvo com sucesso ({pts_digita:.1f} pts)!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL P1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_p1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("P1", st.session_state.get(f"links_pendentes_p1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_p1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO P2 • CONFRONTO ENTRE RESULTADO FÍSICO E RECURSOS FINANCEIROS (Padrão iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_p2_confronto_{ano_sel}", border=True):
            with st.expander("📌 Quesito P2 - Confronto entre Resultado Físico e Recursos Financeiros", expanded=True):
                st.subheader("P2 • Confronto entre Resultado Físico e Recursos Financeiros")
                st.write("**Confronto entre o resultado físico alcançado pelas metas das ações e os recursos financeiros utilizados:**")
                st.caption("ℹ *Este quesito aceita digitação manual de nota ou atribuição direta de 0.0 ponto.*")

                # Recuperação segura dos dados salvos no banco
                dP2 = res_data.get("P2") or {"valor": "0.0", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_P2 = dP2.get("valor", "0.0")
                pts_salvos_P2 = float(dP2.get("pontos", 0.0))
                evidencia_P2_salva = dP2.get("link", "")

                # Chaves explícitas no Session State
                chave_num_P2 = f"num_p2_{ano_sel}"
                chave_link_P2 = f"l_p2_text_{ano_sel}"
                chave_coment_P2 = f"coment_P2_exclusivo_{ano_sel}"

                cP2_1, cP2_2 = st.columns([1, 1])

                with cP2_1:
                    # Campo para inserção manual de pontuação
                    nota_input_P2 = st.number_input(
                        "Digite a pontuação manual:",
                        min_value=0.0,
                        max_value=100.0,
                        value=pts_salvos_P2,
                        step=0.5,
                        format="%.1f",
                        key=chave_num_P2
                    )

                    # Exibição da métrica de pontuação salva
                    st.metric(
                        label="Impacto na Pontuação (Salvo)",
                        value=f"{pts_salvos_P2:.1f} pts",
                        delta=None
                    )

                with cP2_2:
                    link_P2 = st.text_area(
                        "Justificativa / Link de Evidência (P2):",
                        value=evidencia_P2_salva,
                        key=chave_link_P2,
                        placeholder="Inserir justificativa da nota atribuída e links de evidência...",
                        height=120
                    )
                    placeholder_links_P2 = st.empty()
                    links_P2_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_P2 or "")]
                    if links_P2_visuais:
                        placeholder_links_P2.markdown(
                            "**🔗 Links Ativos:** " + " | ".join([f"[{u}]({u})" for u in links_P2_visuais])
                        )

                # Renderiza o bloco de comentários específico do Quesito P2
                bloco_comentarios("P2_exclusivo", res_data, ano_sel)

                # Feedback visual dinâmico
                cor_txt_P2 = "#28a745" if pts_salvos_P2 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_txt_P2}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito P2: {pts_salvos_P2:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL (Padrão iGov)
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito P2", key=f"btn_salvar_p2_{ano_sel}", type="primary"):
                    pts_digita = st.session_state.get(chave_num_P2, nota_input_P2)
                    lnk_val = link_P2.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_P2, dP2.get("comentario", ""))

                    str_valor = f"{pts_digita:.1f}"

                    # Persistência no banco de dados
                    save_resp(
                        qid="P2",
                        valor=str_valor,
                        pontos=float(pts_digita),
                        link=lnk_val,
                        comentario=comentario_para_salvar
                    )

                    # Atualização no dicionário local em memória
                    res_data["P2"] = {
                        "valor": str_valor,
                        "pontos": float(pts_digita),
                        "link": lnk_val,
                        "comentario": comentario_para_salvar
                    }

                    # Detecção de alteração de links para acionamento do modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_P2_salva or "")]

                    if lnk_val != evidencia_P2_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_p2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_p2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast(f"Quesito P2 salvo com sucesso ({pts_digita:.1f} pts)!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL P2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_p2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("P2", st.session_state.get(f"links_pendentes_p2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_p2_{ano_sel}"] = False




