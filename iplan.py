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
        # BLOCO DE QUESITOS - 1.0 (I-PLAN)
        # =============================================================================

        # =============================================================================
        # QUESITO 1.0 • AUDIÊNCIAS PÚBLICAS ORÇAMENTÁRIAS
        # =============================================================================
        with st.container(key=f"container_bloco_audiencias_orcamentarias_1_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.0 - Audiências Públicas Orçamentárias", expanded=True):
                st.subheader("1.0 • Audiências Públicas Orçamentárias")
                st.write("**A Prefeitura realizou audiências públicas para elaboração das peças orçamentárias?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opts_1_0 = {"Selecione...": 0.0, "Sim": 0.0, "Não": 0.0}
                d10 = res_data.get("1.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d10 is None: d10 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_10 = d10.get("valor", "Selecione...")
                chave_radio_10 = f"r_1_0_{v_salvo_10}_{ano_sel}"

                regex_pure_url = r'(https?://[^\s<>"]+?)(?=[.,;:]?(\s|$))'

                def cb_radio_1_0():
                    val = st.session_state[chave_radio_10]
                    pts = opts_1_0[val]
                    lnk = st.session_state.get(f"t_1_0_{ano_sel}", d10.get("link", ""))
                    save_resp("1.0", val, pts, lnk)
                    res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_1_0():
                    lnk = st.session_state[f"t_1_0_{ano_sel}"]
                    val = st.session_state.get(chave_radio_10, d10.get("valor", "Selecione..."))
                    pts = opts_1_0.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d10.get("link", "") or "")]
                    
                    mudou_opcao_10 = val != d10.get("valor", "")
                    mudou_link_10 = lnk != d10.get("link", "")
                    
                    if mudou_opcao_10 or mudou_link_10:
                        save_resp("1.0", val, pts, lnk)
                        res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if mudou_link_10 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                c10_1, c10_2 = st.columns([1, 1])
                with c10_1:
                    lista_opcoes = list(opts_1_0.keys())
                    idx_salvo = lista_opcoes.index(d10["valor"]) if d10["valor"] in opts_1_0 else 0
                    sel_1_0 = st.radio("Selecione 1.0:", options=lista_opcoes, index=idx_salvo, key=chave_radio_10, on_change=cb_radio_1_0, label_visibility="collapsed")
                    pts_1_0 = opts_1_0[sel_1_0]
                    
                with c10_2:
                    link_1_0 = st.text_area("Link/Evidência (1.0):", value=d10.get("link", ""), key=f"t_1_0_{ano_sel}", on_change=cb_text_1_0, height=130)
                    placeholder_links_10 = st.empty()
                    links_1_0_visuais = [u[0] for u in re.findall(regex_pure_url, link_1_0 or "")]
                    if links_1_0_visuais:
                        placeholder_links_10.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1_0_visuais]))
                
                txt_score_10 = f"📊 Pontuação Aplicada no Quesito 1.0: {pts_1_0:.1f} pontos"
                if sel_1_0 == "Selecione...": txt_score_10 += " (Aguardando seleção)"
                st.code(txt_score_10, language="text")
                bloco_comentarios("1.0", res_data)

        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
            modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False



