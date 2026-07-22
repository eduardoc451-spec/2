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

# Constante global de expressão regular para captura de URLs em qualquer quesito
REGEX_PURE_URL = r'((https?://[^\s<>"]+))'

CATEGORIAS_MAP = {
    "planejamento":   {"label": "Planejamento",    "qids": ["1.0", "1.3", "1.4"]},
    "gestao_fiscal":  {"label": "Gestão Fiscal",   "qids": ["2.0", "2.1", "2.2", "10.0", "C1.1"]},
    "educacao":       {"label": "Educação",         "qids": ["3.0", "3.1", "11.1", "11.1.1", "11.2"]},
    "saude":          {"label": "Saúde",            "qids": ["4.2", "12.1", "12.1.3"]},
    "meio_ambiente":  {"label": "Meio Ambiente",    "qids": ["5.0", "5.1.1", "5.2", "14.0"]},
    "cidades_proteg": {"label": "Cidades Proteg.",  "qids": ["6.0", "15.0"]},
    "governanca_ti":  {"label": "Governança TI",    "qids": ["7.0", "7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "16.0"]},
    "transparencia":  {"label": "Transparência",    "qids": ["8.0", "8.1.1.1", "8.2", "9.0"]},
}

PONTUACOES_MAX = {
    "1.0": 40, "1.3": 5, "1.4": 50, "2.0": 20, "2.1": 30, "2.2": 10, 
    "3.0": 10, "3.1.1": 10, "5.0": 200, "7.0": 50, "7.1": 5, "7.2": 80, 
    "7.3": 50, "7.4": 50, "7.5": 10, "7.6": 10, "8.0": 50, "8.1.1.1": 20, 
    "8.2": 50, "9.0": 100, "15.0": 50, "16.0": 50, "C1.1": 50
}

FAIXA_CORES = {"C": "#ef4444", "C+": "#f97316", "B": "#eab308", "B+": "#22c55e", "A": "#16a34a"}

# =============================================================================
# CONEXÃO OTIMIZADA E SEGURA COM O NEON (POSTGRESQL)
# =============================================================================
import os
import logging
import psycopg2
import streamlit as st

def get_db_url():
    """Recupera e valida a URL de conexão do Neon."""
    db_url = os.environ.get("DATABASE_URL") or st.secrets.get("DATABASE_URL")
    if not db_url:
        st.error("❌ A variável DATABASE_URL do Neon não foi configurada nos Segredos ou Ambiente!")
        st.stop()
    
    # Garante suporte a SSL exigido pelo Neon
    if "sslmode=require" not in db_url:
        db_url += ("&" if "?" in db_url else "?") + "sslmode=require"
        
    return db_url

class get_connection:
    """Context manager seguro para conexões diretas com o Neon."""
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
                # Fecha a conexão após o uso (deixa o pooler do Neon gerenciar no backend)
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
# 1. FUNÇÕES DE BANCO DE DADOS (NEON POSTGRESQL)
# =============================================================================

def init_db():
    """Cria a estrutura de tabelas no PostgreSQL/Neon se não existir."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS respostas (
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
            conn.commit()  # <-- OBRIGATÓRIO PARA SALVAR A TABELA
    except Exception as e:
        logging.error(f"Erro ao inicializar o banco: {e}")
        raise e  # Lança o erro para você ver no log do Streamlit

def save_resp(qid, valor, pontos, link, comentarios=None):
    """Salva/Atualiza a resposta no Neon apenas no momento em que o botão for clicado."""
    ano_sel = st.session_state.get("ano_referencia_global")
    if not ano_sel:
        return
    
    dados_atuais = load_respostas(ano_sel)
    if comentarios is None:
        comentarios = dados_atuais.get(qid, {}).get("comentarios", [])

    comentarios_json = json.dumps(comentarios, ensure_ascii=False)
    timestamp_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO respostas (id, ano, valor, pontos, link, comentarios, atualizado_em)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (id, ano) DO UPDATE SET
                        valor = EXCLUDED.valor,
                        pontos = EXCLUDED.pontos,
                        link = EXCLUDED.link,
                        comentarios = EXCLUDED.comentarios,
                        atualizado_em = EXCLUDED.atualizado_em;
                """, (qid, ano_sel, str(valor), float(pontos), str(link), comentarios_json, timestamp_atual))
        
        # Invalida o cache para que a interface leia os novos dados salvos
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar {qid}: {e}")

# =============================================================================
# 2. COMPONENTE OTIMIZADO PARA RENDERIZAR E SALVAR QUESTÕES
# =============================================================================

def renderizar_questao(qid, res_data):
    """Renderiza a questão de forma performática com botão manual de salvamento."""
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
            
            # O BANCO DE DADOS SÓ É ACIONADO NESTE BOTÃO
            if st.button("💾 Salvar Questão", key=f"btn_save_{qid}", type="primary", use_container_width=True):
                # Verifica links no texto de evidência antes de salvar
                links = re.findall(r'https?://[^\s]+', novo_valor) + re.findall(r'https?://[^\s]+', novo_link)
                
                save_resp(
                    qid=qid, 
                    valor=novo_valor, 
                    pontos=novos_pontos, 
                    link=novo_link
                )
                
                st.toast(f"Questão {qid} salva com sucesso!", icon="✅")
                
                if links:
                    modal_aviso_link(qid, links)

        # Diálogo Interno (Comentários)
        bloco_comentarios(qid, res_data)

def bloco_comentarios(questao_id, res_data, sufixo=None):
    """Gera o diálogo interno avançado com histórico e status."""
    ano_sel = st.session_state.get("ano_referencia_global", date.today().year)
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_{id_chave}_{ano_sel}"
    
    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False
        
    dados_questao = res_data.get(questao_id, {})
    historico = dados_questao.get("comentarios", [])
    
    status_global = "Resolvido"
    for com in historico:
        if isinstance(com, dict) and "status_definido" in com:
            status_global = com["status_definido"]
            
    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    
    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global)
        
        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=f"rad_status_{id_chave}_{ano_sel}"
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
# 3. FUNÇÕES DE ANÁLISE E HISTÓRICO
# =============================================================================

@st.cache_data(ttl=60)
def get_all_years_data():
    all_data = {}
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id, ano, valor, pontos, link, comentarios FROM respostas ORDER BY ano DESC")
            rows = cursor.fetchall()
            for row in rows:
                qid, ano = row["id"], row["ano"]
                comentarios = row["comentarios"] if row["comentarios"] is not None else []
                if isinstance(comentarios, str):
                    try:
                        comentarios = json.loads(comentarios)
                    except Exception:
                        comentarios = []

                if ano not in all_data:
                    all_data[ano] = {}
                all_data[ano][qid] = {
                    "valor": row["valor"], 
                    "pontos": row["pontos"], 
                    "link": row["link"], 
                    "comentarios": comentarios
                }
    return all_data

def analyze_performance(res_data):
    pontos_fortes = []
    criticos_zero = {"Alta": [], "Média": [], "Baixa": []}
    criticos_negativos = {"Alta": [], "Média": [], "Baixa": []}

    pontuacoes_referencia = {
        "1.0": {"max": 40}, "1.3": {"max": 5}, "1.4": {"max": 50},
        "2.0": {"max": 20}, "2.1": {"max": 30}, "2.2": {"max": 10},
        "3.0": {"max": 10}, "3.1": {"max": 10}, "4.2": {"max": 10},
        "5.0": {"max": 30}, "5.1.1": {"max": 20}, "5.2": {"max": 10},
        "6.0": {"max": 30}, "7.0": {"max": 30}, "7.1": {"max": 10},
        "7.2": {"max": 80}, "7.3": {"max": 10}, "7.4": {"max": 10},
        "7.5": {"max": 10}, "7.6": {"max": 10}, "8.0": {"max": 30},
        "8.1.1.1": {"max": 20}, "8.2": {"max": 10}, "9.0": {"max": 30},
        "10.0": {"max": 0}, "11.1": {"max": 20}, "11.1.1": {"max": 10},
        "11.2": {"max": 10}, "12.1": {"max": 20}, "12.1.3": {"max": 10},
        "14.0": {"max": 30}, "15.0": {"max": 30}, "16.0": {"max": 30},
        "C1.1": {"max": 0}
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
        if qid.startswith("COM_") or qid not in pontuacoes_referencia:
            continue

        pontos_atuais = info.get("pontos", 0)
        max_pontos = pontuacoes_referencia[qid]["max"]

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

def analyze_recurrence(ano_atual, res_data_atual):
    reincidencias = []
    all_data = get_all_years_data()

    qids_pontuaveis = [
        "1.0", "1.3", "1.4", "2.0", "2.1", "2.2", "3.0", "3.1", "4.2",
        "5.0", "5.1.1", "5.2", "6.0", "7.0", "7.1", "7.2", "7.3", "7.4",
        "7.5", "7.6", "8.0", "8.1.1.1", "8.2", "9.0", "10.0", "11.1",
        "11.1.1", "11.2", "12.1", "12.1.3", "14.0", "15.0", "16.0", "C1.1"
    ]

    anos_anteriores = sorted([a for a in all_data.keys() if a < ano_atual], reverse=True)

    for qid_atual, info_atual in res_data_atual.items():
        if qid_atual.startswith("COM_") or qid_atual not in qids_pontuaveis:
            continue
        pontos_atual = info_atual.get("pontos", 0)
        if pontos_atual <= 0:
            for ano_anterior in anos_anteriores:
                if qid_atual in all_data[ano_anterior]:
                    pontos_anterior = all_data[ano_anterior][qid_atual].get("pontos", 0)
                    if pontos_anterior <= 0:
                        reincidencias.append((qid_atual, ano_anterior, pontos_anterior, pontos_atual))
                        break
    return reincidencias

import os
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
        [Paragraph("6. Série Histórica do I-cidade", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
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
    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    def calcular_percentual_checklist(resposta_bruta, total_itens):
        if not resposta_bruta: return 0.0
        itens = [i.strip().lower() for i in str(resposta_bruta).split(",") if i.strip()]
        itens_validos = [i for i in itens if "outros" not in i]
        return min((len(itens_validos) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0

    analise_ods = []
    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): continue
        resp = str(info.get("valor", "")).strip(); resp_l = resp.lower(); metas = ""; status = ""
        if qid == "1.0": metas = "11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "1.4": metas = "11.5, 16.6"; status = "Não Atendido" if "não atuam de forma sistêmica" in resp_l else "Atendido"
        elif qid == "2.0": metas = "11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "3.0": metas = "11.5, 16.7, 16.10, 17.0"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "3.1": metas = "11b, 11.5, 16.7, 16.10"; status = f"{calcular_percentual_checklist(resp, 6):.1f}% Atendido"
        elif qid == "4.0": metas = "1.5, 11.5, 11b"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "5.0": metas = "1.5, 11.5, 16b"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "5.1": metas = "11b, 11.5, 16.7, 16.10"; status = f"{calcular_percentual_checklist(resp, 8):.1f}% Atendido"
        elif qid == "5.1.1": metas = "11b, 11.5, 16.6, 16.10"; status = "Atendido" if ("sim, integralmente" in resp_l or "sim, parcialmente" in resp_l) else "Não Atendido"
        elif qid == "5.1.1.1": metas = "11b, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "5.1.2": metas = "11b, 11.5, 16.6"; status = "Atendido" if "não" in resp_l else "Não Atendido"
        elif qid == "5.2": metas = "11b, 11.5, 16.6"; status = "Atendido" if ("sim" in resp_l or "parcialmente" in resp_l) else "Não Atendido"
        elif qid == "7.0": metas = "11b, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.3": metas = "11b, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.3.1": metas = "11b, 11.5, 16.6"; status = f"{calcular_percentual_checklist(resp, 7):.1f}% Atendido"
        elif qid == "7.4": metas = "11b, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.4.1": metas = "11.5, 16.6"; status = f"{calcular_percentual_checklist(resp, 7):.1f}% Atendido"
        elif qid == "7.5": metas = "1.5, 11.5, 16.6"; status = "Atendido" if ("sim, atualizado" in resp_l or "sim, mas não está atualizado" in resp_l) else "Não Atendido"
        elif qid == "7.6": metas = "1.5, 11.5, 16.6"; status = "Atendido" if ("sim, atualizado" in resp_l or "sim, mas não está atualizado" in resp_l) else "Não Atendido"
        elif qid in ["8", "8.0"]: metas = "1.5, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "8.1": metas = "1.5, 11.5, 16.6"; status = f"{calcular_percentual_checklist(resp, 6):.1f}% Atendido"
        elif qid == "8.1.1": metas = "1.5, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "8.1.1.1": metas = "1.5, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "8.2": metas = "1.5, 11.5, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "9.0": metas = "1.5, 11.5, 16.6"; status = "Atendido" if ("todas as escolas" in resp_l or "maior parte" in resp_l) else "Não Atendido"
        elif qid in ["10", "10.0"]: metas = "11.2, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["11", "11.0"]: metas = "11.2, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "11.1": metas = "11.2, 16.6"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "12.0": metas = "11.2, 17.0"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "12.1.3": metas = "11.2, 17.0"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["13", "13.0"]: metas = "11.2, 11.7, 12.5"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.0": metas = "11.2, 17.14"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["15", "15.0"]: metas = "11.2, 17.14"; status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["16", "16.0"]: metas = "11.2, 17.14"; status = "Atendido" if "sim" in resp_l else "Não Atendido"

        if metas: analise_ods.append({"qid": qid, "status": status, "metas": metas, "resp": resp[:50]})

    if analise_ods:
        data_ods = [["Quesito", "Resposta Informada", "Vínculo Metas ODS", "Status de Cumprimento"]]
        style_td_ods = ParagraphStyle('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        for item in sorted(analise_ods, key=lambda x: [float(i) if i.replace('.','',1).isdigit() else 999 for i in x['qid'].split('.')]):
            st_txt = item["status"]
            if "Não Atendido" in st_txt: st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt: st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else: st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
            data_ods.append([item["qid"], Paragraph(item["resp"], styles["Normal"]), item["metas"], st_p])
        tabela_ods = Table(data_ods, colWidths=[60, 200, 115, 110])
        tabela_ods.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f9d58")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (0, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#0f9d58")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 6. SÉRIE HISTÓRICA DO I-CIDADE
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
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

# =============================================================================
# 4. SIDEBAR
# =============================================================================

def zerar_questionario(ano):
    """Deleta todas as respostas do ano selecionado no Neon PostgreSQL."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM respostas WHERE ano = %s", (ano,))
        st.cache_data.clear()  # Limpa o cache após deletar
    except Exception as e:
        st.error(f"Erro ao zerar questionário: {e}")

# Janela pop-up de confirmação definida no escopo global
@st.dialog("🔒 Confirmação de Segurança")
def confirmar_zerar_dialog(ano):
    st.warning(f"Você está prestes a apagar todas as respostas de {ano}. Esta ação é irreversível!")
    
    senha = st.text_input("Digite a senha de administrador:", type="password")
    
    col_Sim, col_Nao = st.columns(2)
    with col_Sim:
        if st.button("Confirmar e Zerar", type="primary", use_container_width=True):
            if senha == "fidelios":
                zerar_questionario(ano)
                st.success(f"✅ Questionário de {ano} foi zerado!")
                st.rerun()
            else:
                st.error("❌ Senha incorreta!")
    with col_Nao:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()

def render_sidebar():
    st.sidebar.title("🛠️ Painel de Controle")
    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
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
# 5. GRÁFICOS COMPARATIVOS
# =============================================================================

def get_faixa(total):
    if total <= 500:  return "C"
    if total <= 599:  return "C+"
    if total <= 749:  return "B"
    if total <= 899:  return "B+"
    return "A"


def calcular_pontos_por_categoria(res_data):
    resultado = {}
    for cat_key, cat_info in CATEGORIAS_MAP.items():
        resultado[cat_key] = sum(
            res_data.get(qid, {}).get("pontos", 0) for qid in cat_info["qids"]
        )
    return resultado


def calcular_max_por_categoria():
    resultado = {}
    for cat_key, cat_info in CATEGORIAS_MAP.items():
        resultado[cat_key] = sum(PONTUACOES_MAX.get(qid, 0) for qid in cat_info["qids"])
    return resultado


def grafico_comparativo_total(all_data):
    anos = sorted(all_data.keys())
    totais, faixas, cores = [], [], []
    for ano in anos:
        res = all_data[ano]
        total = sum(v.get("pontos", 0) for k, v in res.items() if not k.startswith("COM_"))
        faixa = get_faixa(total)
        totais.append(total)
        faixas.append(faixa)
        cores.append(FAIXA_CORES[faixa])

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[str(a) for a in anos],
        y=totais,
        marker_color=cores,
        text=[f"{t} pts<br>Faixa {f}" for t, f in zip(totais, faixas)],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
    ))
    for y_val, label, cor in [
        (500, "C→C+", "#f97316"), (600, "C+→B", "#eab308"),
        (750, "B→B+", "#22c55e"), (900, "B+→A", "#16a34a")
    ]:
        fig.add_hline(y=y_val, line_dash="dash", line_color=cor,
                      annotation_text=label, annotation_position="right")
    fig.update_layout(
        title="Pontuação Total por Ano",
        xaxis_title="Ano", yaxis_title="Pontos",
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False, height=400,
    )
    return fig


def grafico_evolucao_categorias(all_data):
    anos = sorted(all_data.keys())
    CORES_CAT = ["#1e3a5f","#0ea5e9","#22c55e","#f97316","#ef4444","#8b5cf6","#ec4899","#6b7280"]
    fig = go.Figure()
    for idx, (cat_key, cat_info) in enumerate(CATEGORIAS_MAP.items()):
        valores = [
            sum(all_data.get(ano, {}).get(qid, {}).get("pontos", 0) for qid in cat_info["qids"])
            for ano in anos
        ]
        fig.add_trace(go.Scatter(
            x=[str(a) for a in anos], y=valores,
            mode="lines+markers", name=cat_info["label"],
            line=dict(color=CORES_CAT[idx % len(CORES_CAT)], width=2),
            marker=dict(size=7),
        ))
    fig.update_layout(
        title="Evolução por Categoria ao Longo dos Anos",
        xaxis_title="Ano", yaxis_title="Pontos",
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=-0.4),
        height=450,
    )
    return fig


def grafico_radar_categorias(res_data, ano):
    maximos = calcular_max_por_categoria()
    pontos  = calcular_pontos_por_categoria(res_data)
    labels  = [CATEGORIAS_MAP[k]["label"] for k in CATEGORIAS_MAP]
    valores_pct = [
        round(max(0, pontos.get(k, 0) / maximos[k] * 100), 1) if maximos[k] > 0 else 0
        for k in CATEGORIAS_MAP
    ]
    labels_fechado  = labels + [labels[0]]
    valores_fechado = valores_pct + [valores_pct[0]]
    fig = go.Figure(go.Scatterpolar(
        r=valores_fechado, theta=labels_fechado,
        fill="toself", fillcolor="rgba(30,58,95,0.15)",
        line=dict(color="#1e3a5f", width=2),
        hovertemplate="%{theta}: %{r:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title=f"Radar de Categorias — {ano}",
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False, height=420, paper_bgcolor="white",
    )
    return fig


def grafico_quesitos_barra(res_data, ano):
    qids_pontuaveis = sorted([q for q, v in PONTUACOES_MAX.items() if v > 0])
    qids, obtido, maximo, cores = [], [], [], []
    for qid in qids_pontuaveis:
        pts = res_data.get(qid, {}).get("pontos", 0)
        mx  = PONTUACOES_MAX[qid]
        qids.append(qid)
        obtido.append(pts)
        maximo.append(mx)
        if pts == mx:   cores.append("#16a34a")
        elif pts < 0:   cores.append("#ef4444")
        elif pts == 0:  cores.append("#9ca3af")
        else:           cores.append("#0ea5e9")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Máximo", x=maximo, y=qids, orientation="h",
        marker_color="rgba(200,200,200,0.35)", hoverinfo="skip",
    ))
    fig.add_trace(go.Bar(
        name="Obtido", x=obtido, y=qids, orientation="h",
        marker_color=cores,
        hovertemplate="<b>%{y}</b><br>Obtido: %{x} pts<extra></extra>",
    ))
    fig.update_layout(
        title=f"Pontuação por Quesito — {ano}",
        barmode="overlay", xaxis_title="Pontos",
        plot_bgcolor="white", paper_bgcolor="white",
        height=max(500, len(qids) * 22),
        legend=dict(orientation="h"),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def grafico_pontos_por_ano(all_data):
    """Gráfico de barras vertical com pontos totais por ano."""
    anos = sorted(all_data.keys())
    totais = []
    cores = []
    
    for ano in anos:
        res = all_data[ano]
        total = sum(v.get("pontos", 0) for k, v in res.items() if not k.startswith("COM_"))
        totais.append(total)
        
        # Definir cor baseado na faixa
        if total <= 500:   cores.append("#ef4444")  # C - Vermelho
        elif total <= 599: cores.append("#f97316")  # C+ - Laranja
        elif total <= 749: cores.append("#eab308")  # B - Amarelo
        elif total <= 899: cores.append("#22c55e")  # B+ - Verde Claro
        else:              cores.append("#16a34a")  # A - Verde
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[str(a) for a in anos],
        y=totais,
        marker_color=cores,
        text=[f"{t} pts" for t in totais],
        textposition="outside",
        hovertemplate="<b>Ano: %{x}</b><br>Pontos: %{y}<extra></extra>",
    ))
    
    fig.update_layout(
        title="Pontuação Total por Ano",
        xaxis_title="Ano",
        yaxis_title="Pontos",
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        height=400,
    )
    
    return fig

def render_graficos(res_data_atual, ano_sel):
    st.header("📊 Gráfico de Pontuação")
    
    all_data = get_all_years_data()
    
    if not all_data:
        st.info("Nenhum dado registrado ainda. Preencha os quesitos para ver o gráfico.")
        return

    st.plotly_chart(grafico_pontos_por_ano(all_data), use_container_width=True)

# =============================================================================
# 6. FORMULÁRIO PRINCIPAL
# =============================================================================

def mostrar_formulario_cidade():
    # Caso render_sidebar() retorne None por algum motivo
    dados_sidebar = render_sidebar()
    
    if dados_sidebar and len(dados_sidebar) == 3:
        total_pts, res_data, ano_sel = dados_sidebar
    else:
        total_pts, res_data, ano_sel = 0, {}, "2026"  # Valor padrão de fallback

    st.title(f"🏙️ Preenchimento do IEG-M - {ano_sel}")

    # -------------------------------------------------------------------------
    # ABAS PRINCIPAIS
    # -------------------------------------------------------------------------
    aba_questionario, aba_graficos = st.tabs(["📋 Questionário", "📊 Gráficos"])

    with aba_questionario:
        st.info("Preencha os quesitos abaixo usando o componente de renderização.")
        
        # Exemplo de chamada utilizando a função otimizada de renderização/salvamento:
        # renderizar_questao("1.0", res_data)
        # renderizar_questao("1.3", res_data)

    with aba_graficos:
        render_graficos(res_data, ano_sel)
    # =============================================================================
    # QUESITO 1.0 • COORDENADORIA MUNICIPAL DE DEFESA CIVIL (COMPDEC)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_1_0_final_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.0 - Criação da COMPDEC ou Órgão Similar", expanded=True):
            st.subheader("1.0 • Defesa Civil Municipal")
            st.write(
                "**Foi criada a Coordenadoria Municipal de Proteção e Defesa Civil-COMPDEC "
                "ou órgão similar responsável pela execução, coordenação e mobilização de todas as ações de defesa civil no município?**"
            )
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.0' para registrar.*")

            opcoes_10 = {
                "Selecione...": 0.0,
                "Sim (40 pts)": 40.0,
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
                    "Selecione o status do órgão:",
                    options=lista_opcoes_10,
                    index=idx_10,
                    key=chave_radio_10,
                    label_visibility="collapsed"
                )

            with c10_2:
                link_10 = st.text_area(
                    "Link de Evidência / Decreto de Criação (1.0):",
                    value=d10.get("link", ""),
                    key=chave_link_10,
                    height=100
                )
                placeholder_links_10 = st.empty()
                links_10_visuais = [u[0] for u in re.findall(REGEX_PURE_URL, link_10 or "")]
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
                # A função bloco_comentarios geralmente usa uma chave padronizada
                comentario_para_salvar = st.session_state.get(chave_coment_10, d10.get("comentario", ""))
                
                # 2. Salva no banco/backend (certifique-se que save_resp aceita o argumento de comentário)
                save_resp("1.0", val_radio_10, pts_10, link_10, comentario_para_salvar)
                
                # 3. Atualiza o dicionário local para refletir na UI antes do rerun (opcional mas boa prática)
                res_data["1.0"] = {
                    "valor": val_radio_10, 
                    "pontos": pts_10, 
                    "link": link_10, 
                    "comentario": comentario_para_salvar
                }

                # 4. Validação/Processamento de links para exibição de modal
                links_atuais = [u[0] for u in re.findall(REGEX_PURE_URL, link_10 or "")]
                links_antigos = [u[0] for u in re.findall(REGEX_PURE_URL, d10.get("link", "") or "")]

                if link_10 != d10.get("link", "") and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                st.toast("Resposta e comentário do Quesito 1.0 salvos com sucesso!", icon="✅")
                
                # 5. FORÇA O RECARREGAMENTO DA TELA (Resolve o duplo clique e atualiza painéis)
                st.rerun()

            # Exibição da pontuação dentro do expander
            pts_atuais_10 = d10.get("pontos", 0.0)
            cor_txt_10 = "#28a745" if pts_atuais_10 == 40.0 else ("#dc3545" if v_salvo_10 != "Selecione..." else "#6c757d")
            st.markdown(
                f"<span style='color:{cor_txt_10}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 1.0: {pts_atuais_10:.1f} pontos</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 1.0 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
        modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False

    # Garante a exposição da variável r10 para dependências condicionais de outros quesitos
    r10 = v_salvo_10

    # =============================================================================
    # QUESITO 1.1 • INSTRUMENTO NORMATIVO COMPDEC (NOVO PADRÃO 1.0)
    # =============================================================================
    dq11 = res_data.get("1.1") or {"valor": "", "pontos": 0.0, "link": ""}
    v_salvo_11 = dq11.get("valor", "")
    l_salvo_11 = dq11.get("link", "")
    p_salvo_11 = float(dq11.get("pontos", 0.0))

    with st.container(key=f"container_bloco_compdec_1_1_final_{ano_sel}", border=True):
        st.markdown("#### Quesito: `1.1` - Dados do Instrumento Normativo COMPDEC")
        st.write("**Informe o Instrumento normativo, Número e Data da publicação da criação da COMPDEC ou órgão similar:**")

        col_txt_11, col_meta_11 = st.columns([3, 1])

        with col_txt_11:
            novo_valor_11 = st.text_area(
                "Dados do instrumento normativo / Evidência:",
                value=v_salvo_11,
                key=f"txt_val_1_1_{ano_sel}",
                height=100,
                placeholder="Ex: Decreto nº 123 de 01/01/2025"
            )
            novo_link_11 = st.text_input(
                "Link da Evidência / Diário Oficial (1.1):",
                value=l_salvo_11,
                key=f"txt_link_1_1_{ano_sel}"
            )

            # Exibição inline dos links detectados
            links_visuais_11 = [u[0] for u in re.findall(REGEX_PURE_URL, novo_link_11 or "")] + \
                               [u[0] for u in re.findall(REGEX_PURE_URL, novo_valor_11 or "")]
            if links_visuais_11:
                st.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_visuais_11]))

        with col_meta_11:
            # Mantido como 0.0 por ser um quesito meramente informativo
            novos_pontos_11 = st.number_input(
                "Pontuação (Informativo):",
                value=p_salvo_11,
                key=f"num_pts_1_1_{ano_sel}",
                disabled=True
            )

            st.markdown("<br>", unsafe_allow_html=True)

            # O BANCO DE DADOS SÓ É ACIONADO NESTE BOTÃO
            if st.button("💾 Salvar Questão", key=f"btn_save_1_1_{ano_sel}", type="primary", use_container_width=True):
                # Extrai links para validação do modal
                links_encontrados_11 = re.findall(r'https?://[^\s]+', novo_valor_11) + re.findall(r'https?://[^\s]+', novo_link_11)

                save_resp(
                    qid="1.1",
                    valor=novo_valor_11,
                    pontos=0.0,
                    link=novo_link_11
                )

                st.toast("Quesito 1.1 salvo com sucesso!", icon="✅")

                if links_encontrados_11:
                    modal_aviso_link("1.1", links_encontrados_11)

        st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)

        # Diálogo Interno (Comentários)
        bloco_comentarios("1.1", res_data, ano_sel)

    # =============================================================================
    # QUESITO 1.2 • PÁGINA ELETRÔNICA COMPDEC (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_1_2_final_{ano_sel}", border=True):
        with st.expander("📌 Quesito 1.2 - Endereço Eletrônico do Instrumento Normativo", expanded=True):
            st.subheader("1.2 • Página Eletrônica do Instrumento")
            st.write("**Informe a página eletrônica (link na internet) do instrumento normativo que criou a COMPDEC ou órgão similar:**")
            st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.2' para registrar.*")

            # Recupera o estado salvo no dicionário de dados
            dq12 = res_data.get("1.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
            v_salvo_12 = dq12.get("valor", "")

            # Chaves fixas por componente e ano
            chave_input_12 = f"v12_{ano_sel}"
            chave_link_12 = f"l_12_txt_{ano_sel}"
            chave_coment_12 = f"coment_1.2_{ano_sel}" # Chave padrão usada pela função bloco_comentarios

            c12_1, c12_2 = st.columns([1, 1])
            with c12_1:
                val_text_12 = st.text_input(
                    "Endereço eletrônico (URL):",
                    value=v_salvo_12,
                    key=chave_input_12,
                    placeholder="https://www.municipio.sp.gov.br/legislacao"
                )

            with c12_2:
                link_12 = st.text_area(
                    "Link de Evidência / Print do Portal (1.2):",
                    value=dq12.get("link", ""),
                    key=chave_link_12,
                    height=100
                )
                placeholder_links_12 = st.empty()
                links_12_visuais = [u[0] for u in re.findall(REGEX_PURE_URL, link_12 or "")]
                if links_12_visuais:
                    placeholder_links_12.markdown("**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_12_visuais]))

            # Renderiza o bloco de comentários dentro do expander
            bloco_comentarios("1.2", res_data, ano_sel)

            # -----------------------------------------------------------------
            # BOTÃO DE SALVAMENTO MANUAL
            # -----------------------------------------------------------------
            if st.button("💾 Salvar Quesito 1.2", key=f"btn_salvar_1_2_{ano_sel}", type="primary"):
                # Quesito informativo/textual, pontuação fixa em 0.0
                pts_12 = 0.0

                # 1. Captura o comentário atual do session_state antes do rerun
                comentario_para_salvar = st.session_state.get(chave_coment_12, dq12.get("comentario", ""))

                # 2. Salva no banco/backend
                save_resp("1.2", val_text_12, pts_12, link_12, comentario_para_salvar)

                # 3. Atualiza o dicionário local para refletir na UI
                res_data["1.2"] = {
                    "valor": val_text_12,
                    "pontos": pts_12,
                    "link": link_12,
                    "comentario": comentario_para_salvar
                }

                # 4. Validação/Processamento de links para exibição de modal
                links_atuais = [u[0] for u in re.findall(REGEX_PURE_URL, link_12 or "")]
                links_antigos = [u[0] for u in re.findall(REGEX_PURE_URL, dq12.get("link", "") or "")]

                if link_12 != dq12.get("link", "") and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                st.toast("Resposta e comentário do Quesito 1.2 salvos com sucesso!", icon="✅")

                # 5. FORÇA O RECARREGAMENTO DA TELA
                st.rerun()

            # Exibição da pontuação dentro do expander
            st.markdown(
                "<span style='color:#28a745; font-weight:bold;'>"
                "📊 Impacto de Pontuação no Quesito 1.2: 0.0 pontos (Informativo)</span>",
                unsafe_allow_html=True
            )

    # GATILHO DO MODAL 1.2 (Fora do container principal)
    if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
        modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False
       
   # =============================================================================
    # QUESITO 2.0 • TREINAMENTO E CAPACITAÇÃO EM DEFESA CIVIL (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_2_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 2.0 - Treinamento e Capacitação de Agentes", expanded=True):
            st.subheader("2.0 • Capacitação de Agentes")
            st.write("**Sobre treinamento e capacitação sobre Proteção e Defesa Civil, a Prefeitura capacita seus agentes para ações municipais de Defesa Civil?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações do quesito 2.0
            opcoes_20 = {
                "Selecione...": 0.0,
                "Sim (20 pts)": 20.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados
            d20 = res_data.get("2.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d20 is None: d20 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_20 = d20.get("valor", "Selecione...")
            chave_radio_20 = f"r_20_{v_salvo_20}_{ano_sel}"

            def cb_radio_20():
                val = st.session_state[chave_radio_20]
                pts = opcoes_20.get(val, 0.0)
                lnk = st.session_state.get(f"l_20_txt_{ano_sel}", d20.get("link", ""))
                
                save_resp("2.0", val, pts, lnk)
                res_data["2.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_20():
                lnk = st.session_state[f"l_20_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_20, v_salvo_20)
                pts = opcoes_20.get(val, 0.0)
                
                save_resp("2.0", val, pts, lnk)
                res_data["2.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d20.get("link", "") or "")]
                
                if lnk != d20.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

            c20_1, c20_2 = st.columns([1, 1])
            with c20_1:
                lista_opcoes_20 = list(opcoes_20.keys())
                idx_20 = lista_opcoes_20.index(v_salvo_20) if v_salvo_20 in lista_opcoes_20 else 0
                
                st.radio(
                    "Resposta 2.0:",
                    options=lista_opcoes_20,
                    index=idx_20,
                    key=chave_radio_20,
                    on_change=cb_radio_20,
                    label_visibility="collapsed"
                )
                
            with c20_2:
                link_20 = st.text_area("Justificativa e Evidência (2.0):", value=d20.get("link", ""), key=f"l_20_txt_{ano_sel}", on_change=cb_text_20, height=100)
                placeholder_links_20 = st.empty()
                links_20_visuais = [u[0] for u in re.findall(regex_pure_url, link_20 or "")]
                if links_20_visuais:
                    placeholder_links_20.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_20_visuais]))

            pts_atuais_20 = d20.get("pontos", 0.0)
            cor_txt_20 = "#28a745" if pts_atuais_20 == 20.0 else ("#dc3545" if v_salvo_20 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_20}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.0: {pts_atuais_20:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("2.0", res_data, ano_sel)

    # GATILHO DO MODAL 2.0
    if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
        modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 2.1 • DATA DA ÚLTIMA CAPACITAÇÃO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_2_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 2.1 - Data da Última Capacitação de Agentes", expanded=True):
            st.subheader("2.1 • Data da Última Capacitação")
            st.write("**Qual a data da última capacitação dos agentes municipais para ações de Defesa Civil?**")
            
            st.info(f"""
            **Regra de Pontuação:**
            * ✅ **Data a partir de 01/01/{ano_sel}:** 30 pontos.
            * ⚠️ **Data até 31/12/{ano_sel - 1}:** 00 pontos.
            * 🚫 **Capacitações em {ano_sel + 1}:** Não pontuam (00 pontos).
            """)
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera os dados do dicionário
            d21 = res_data.get("2.1", {"valor": None, "pontos": 0.0, "link": ""})
            if d21 is None: d21 = {"valor": None, "pontos": 0.0, "link": ""}

            # Trata a data inicial recuperada do banco
            v_salvo_21 = d21.get("valor", None)
            try:
                dt_i = datetime.strptime(v_salvo_21, '%Y-%m-%d').date() if v_salvo_21 else date(ano_sel, 1, 1)
            except:
                dt_i = date(ano_sel, 1, 1)

            chave_date_21 = f"dt_21_{v_salvo_21}_{ano_sel}"

            def cb_date_21():
                dt_sel = st.session_state[chave_date_21]
                # Regra de cálculo dinâmico de pontuação
                if dt_sel >= date(ano_sel, 1, 1) and dt_sel.year == ano_sel:
                    pts = 30.0
                else:
                    pts = 0.0
                
                val = str(dt_sel)
                lnk = st.session_state.get(f"l_21_txt_{ano_sel}", d21.get("link", ""))
                
                save_resp("2.1", val, pts, lnk)
                res_data["2.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_21():
                lnk = st.session_state[f"l_21_txt_{ano_sel}"]
                dt_sel = st.session_state.get(chave_date_21, dt_i)
                
                if dt_sel >= date(ano_sel, 1, 1) and dt_sel.year == ano_sel:
                    pts = 30.0
                else:
                    pts = 0.0
                    
                val = str(dt_sel)
                save_resp("2.1", val, pts, lnk)
                res_data["2.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d21.get("link", "") or "")]
                
                if lnk != d21.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = True

            col_d21, col_j21 = st.columns([1, 1])
            with col_d21:
                data_sel = st.date_input(
                    "Selecione a data:",
                    value=dt_i,
                    key=chave_date_21,
                    on_change=cb_date_21,
                    format="DD/MM/YYYY"
                )
                
                # Exibição visual da pontuação atual recalculada
                if data_sel >= date(ano_sel, 1, 1) and data_sel.year == ano_sel:
                    st.success(f"Pontuação Calculada: 30 pts ({data_sel.strftime('%d/%m/%Y')})")
                else:
                    st.warning(f"Pontuação Calculada: 00 pts ({data_sel.strftime('%d/%m/%Y')})")
                
            with col_j21:
                link_21 = st.text_area("Justificativa e Evidência (2.1):", value=d21.get("link", ""), key=f"l_21_txt_{ano_sel}", on_change=cb_text_21, height=100, placeholder="Cole o link do certificado ou portaria aqui...")
                placeholder_links_21 = st.empty()
                links_21_visuais = [u[0] for u in re.findall(regex_pure_url, link_21 or "")]
                if links_21_visuais:
                    placeholder_links_21.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_21_visuais]))

            pts_atuais_21 = d21.get("pontos", 0.0)
            cor_txt_21 = "#28a745" if pts_atuais_21 == 30.0 else "#dc3545"
            st.markdown(f"<span style='color:{cor_txt_21}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.1: {pts_atuais_21:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("2.1", res_data, ano_sel)

    # GATILHO DO MODAL 2.1
    if st.session_state.get(f"gatilho_modal_2_1_{ano_sel}", False):
        modal_aviso_link("2.1", st.session_state.get(f"links_pendentes_2_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 2.2 • PÚBLICO-ALVO DOS CURSOS E TREINAMENTOS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_2_2_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 2.2 - Público Alvo de Cursos e Treinamentos", expanded=True):
            st.subheader("2.2 • Público dos Treinamentos")
            st.write("**A Prefeitura Municipal ofereceu cursos/treinamento sobre Proteção e Defesa Civil para qual público?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados
            d22 = res_data.get("2.2", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d22 is None: d22 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_22 = d22.get("valor", "[]")
            
            # Definição das chaves únicas de estado para os checkboxes
            chk_key_1 = f"c22a_chk_{ano_sel}"
            chk_key_2 = f"c22b_chk_{ano_sel}"
            chk_key_3 = f"c22c_chk_{ano_sel}"
            chk_key_4 = f"c22d_chk_{ano_sel}"

            def cb_checkbox_22():
                # Captura os estados atuais das caixas de seleção na tela
                c1 = st.session_state.get(chk_key_1, False)
                c2 = st.session_state.get(chk_key_2, False)
                c3 = st.session_state.get(chk_key_3, False)
                c4 = st.session_state.get(chk_key_4, False)
                
                sel22 = []
                p22 = 0.0
                
                # Regra de negócio acumulativa ou exclusão mútua por "Nenhum"
                if c4:
                    sel22 = ["Nenhum"]
                    p22 = 0.0
                else:
                    if c1: p22 += 5.0; sel22.append("Escolas")
                    if c2: p22 += 3.0; sel22.append("Secretarias")
                    if c3: p22 += 2.0; sel22.append("Munícipes")
                
                lnk = st.session_state.get(f"l_22_txt_{ano_sel}", d22.get("link", ""))
                val_str = str(sel22)
                
                save_resp("2.2", val_str, p22, lnk)
                res_data["2.2"] = {"valor": val_str, "pontos": p22, "link": lnk}

            def cb_text_22():
                lnk = st.session_state[f"l_22_txt_{ano_sel}"]
                
                # Reconstrói os pontos baseado nas seleções salvas para manter a consistência no texto
                c1 = st.session_state.get(chk_key_1, "Escolas" in valor_salvo_22)
                c2 = st.session_state.get(chk_key_2, "Secretarias" in valor_salvo_22)
                c3 = st.session_state.get(chk_key_3, "Munícipes" in valor_salvo_22)
                c4 = st.session_state.get(chk_key_4, "Nenhum" in valor_salvo_22)
                
                sel22 = []
                p22 = 0.0
                if c4:
                    sel22 = ["Nenhum"]
                else:
                    if c1: p22 += 5.0; sel22.append("Escolas")
                    if c2: p22 += 3.0; sel22.append("Secretarias")
                    if c3: p22 += 2.0; sel22.append("Munícipes")
                
                val_str = str(sel22)
                save_resp("2.2", val_str, p22, lnk)
                res_data["2.2"] = {"valor": val_str, "pontos": p22, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d22.get("link", "") or "")]
                
                if lnk != d22.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_2_{ano_sel}"] = True

            c22_1, c22_2 = st.columns([1, 1])
            with c22_1:
                st.checkbox("Para escolas – 05 pts", value="Escolas" in valor_salvo_22, key=chk_key_1, on_change=cb_checkbox_22)
                st.checkbox("Para outras secretarias / entidades municipais – 03 pts", value="Secretarias" in valor_salvo_22, key=chk_key_2, on_change=cb_checkbox_22)
                st.checkbox("Para munícipes ou empresas – 02 pts", value="Munícipes" in valor_salvo_22, key=chk_key_3, on_change=cb_checkbox_22)
                st.checkbox("Não ofereceu nenhum curso/treinamento no ano – 00 pts", value="Nenhum" in valor_salvo_22, key=chk_key_4, on_change=cb_checkbox_22)
                
            with c22_2:
                link_22 = st.text_area("Evidência 2.2:", value=d22.get("link", ""), key=f"l_22_txt_{ano_sel}", on_change=cb_text_22, height=140)
                placeholder_links_22 = st.empty()
                links_22_visuais = [u[0] for u in re.findall(regex_pure_url, link_22 or "")]
                if links_22_visuais:
                    placeholder_links_22.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_22_visuais]))

            pts_atuais_22 = d22.get("pontos", 0.0)
            cor_txt_22 = "#28a745" if pts_atuais_22 > 0.0 else ("#dc3545" if "Nenhum" in valor_salvo_22 else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_22}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.2: {pts_atuais_22:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("2.2", res_data, ano_sel)

    # GATILHO DO MODAL 2.2
    if st.session_state.get(f"gatilho_modal_2_2_{ano_sel}", False):
        modal_aviso_link("2.2", st.session_state.get(f"links_pendentes_2_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_2_2_{ano_sel}"] = False
    
    # =============================================================================
    # QUESITO 3.0 • PARTICIPAÇÃO DA SOCIEDADE CIVIL (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_3_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 3.0 - Participação da Sociedade Civil e Entidades", expanded=True):
            st.subheader("3.0 • Sociedade Civil e Entidades")
            st.write("**O Município realiza ações para estabelecer a participação de entidades privadas, associações de voluntários, clubes de serviços, organizações não governamentais e associações de classe e comunitárias nas ações de proteção e defesa civil?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações do quesito 3.0
            opcoes_30 = {
                "Selecione...": 0.0,
                "Sim – 10 pts": 10.0,
                "Não – 00 pts": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados
            d30 = res_data.get("3.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d30 is None: d30 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_30 = d30.get("valor", "Selecione...")
            chave_radio_30 = f"r_30_{v_salvo_30}_{ano_sel}"

            def cb_radio_30():
                val = st.session_state[chave_radio_30]
                pts = opcoes_30.get(val, 0.0)
                lnk = st.session_state.get(f"l_30_txt_{ano_sel}", d30.get("link", ""))
                
                save_resp("3.0", val, pts, lnk)
                res_data["3.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_30():
                lnk = st.session_state[f"l_30_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_30, v_salvo_30)
                pts = opcoes_30.get(val, 0.0)
                
                save_resp("3.0", val, pts, lnk)
                res_data["3.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d30.get("link", "") or "")]
                
                if lnk != d30.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

            c30_1, c30_2 = st.columns([1, 1])
            with c30_1:
                lista_opcoes_30 = list(opcoes_30.keys())
                idx_30 = lista_opcoes_30.index(v_salvo_30) if v_salvo_30 in lista_opcoes_30 else 0
                
                st.radio(
                    "Escolha 3.0:",
                    options=lista_opcoes_30,
                    index=idx_30,
                    key=chave_radio_30,
                    on_change=cb_radio_30,
                    label_visibility="collapsed"
                )
                
            with c30_2:
                link_30 = st.text_area("Evidência 3.0:", value=d30.get("link", ""), key=f"l_30_txt_{ano_sel}", on_change=cb_text_30, height=100)
                placeholder_links_30 = st.empty()
                links_30_visuais = [u[0] for u in re.findall(regex_pure_url, link_30 or "")]
                if links_30_visuais:
                    placeholder_links_30.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_30_visuais]))

            pts_atuais_30 = d30.get("pontos", 0.0)
            cor_txt_30 = "#28a745" if pts_atuais_30 == 10.0 else ("#dc3545" if v_salvo_30 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_30}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.0: {pts_atuais_30:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("3.0", res_data, ano_sel)

    # GATILHO DO MODAL 3.0
    if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
        modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.1 • AÇÕES REALIZADAS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_3_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 3.1 - Ações Realizadas para Participação da Sociedade", expanded=True):
            st.subheader("3.1 • Ações Realizadas")
            st.write("**Assinale quais ações foram realizadas:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados
            d31 = res_data.get("3.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d31 is None: d31 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_31 = d31.get("valor", "[]")
            
            opcoes_31 = [
                "Workshop / Palestra",
                "Reunião",
                "Conferência",
                "Congresso",
                "Discussão na Câmara Municipal",
                "Treinamentos",
                "Outros"
            ]

            def cb_checkbox_31():
                # Coleta dinamicamente todas as opções marcadas na tela usando o session_state
                selecionados_31 = []
                for opcao in opcoes_31:
                    if st.session_state.get(f"chk_31_{opcao}_{ano_sel}", False):
                        selecionados_31.append(opcao)
                
                pts = 0.0  # Quesito informativo/textual, pontuação fixa em 0.0
                lnk = st.session_state.get(f"l_31_txt_{ano_sel}", d31.get("link", ""))
                val_str = str(selecionados_31)
                
                save_resp("3.1", val_str, pts, lnk)
                res_data["3.1"] = {"valor": val_str, "pontos": pts, "link": lnk}

            def cb_text_31():
                lnk = st.session_state[f"l_31_txt_{ano_sel}"]
                
                # Reconstrói os selecionados para persistência correta do estado do texto
                selecionados_31 = []
                for opcao in opcoes_31:
                    if st.session_state.get(f"chk_31_{opcao}_{ano_sel}", opcao in valor_salvo_31):
                        selecionados_31.append(opcao)
                        
                val_str = str(selecionados_31)
                save_resp("3.1", val_str, 0.0, lnk)
                res_data["3.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d31.get("link", "") or "")]
                
                if lnk != d31.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

            c31_1, c31_2 = st.columns([1, 1])
            with c31_1:
                # Renderiza cada checkbox mapeado com sua respectiva chave e callback assíncrono
                for opcao in opcoes_31:
                    st.checkbox(
                        opcao,
                        value=opcao in valor_salvo_31,
                        key=f"chk_31_{opcao}_{ano_sel}",
                        on_change=cb_checkbox_31
                    )
                
            with c31_2:
                link_31 = st.text_area("Evidências das ações (3.1):", value=d31.get("link", ""), key=f"l_31_txt_{ano_sel}", on_change=cb_text_31, height=210)
                placeholder_links_31 = st.empty()
                links_31_visuais = [u[0] for u in re.findall(regex_pure_url, link_31 or "")]
                if links_31_visuais:
                    placeholder_links_31.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_31_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("3.1", res_data, ano_sel)

    # GATILHO DO MODAL 3.1
    if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
        modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 3.1.1 • DATA DE TREINAMENTO DINÂMICA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_3_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 3.1.1 - Data do Último Treinamento de Voluntários", expanded=True):
            st.subheader("3.1.1 • Treinamento de Voluntários")
            st.write("**Qual a data do último treinamento de associações de voluntários?**")
            
            st.info(f"""
            **Fórmula de Cálculo:**
            * 📅 **Até 31/12/{ano_sel - 1}:** 00 pontos.
            * 📅 **A partir de 01/01/{ano_sel}:** 10 pontos.
            * 🚫 **Observação:** Treinamentos em {ano_sel + 1} não pontuam.
            """)
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera os dados históricos salvos no dicionário
            d311 = res_data.get("3.1.1", {"valor": None, "pontos": 0.0, "link": ""})
            if d311 is None: d311 = {"valor": None, "pontos": 0.0, "link": ""}

            v_salvo_311 = d311.get("valor", None)
            try:
                dt_i_311 = datetime.strptime(v_salvo_311, '%Y-%m-%d').date() if v_salvo_311 else date(ano_sel, 1, 1)
            except:
                dt_i_311 = date(ano_sel, 1, 1)

            chave_date_311 = f"dt_311_{v_salvo_311}_{ano_sel}"

            def cb_date_311():
                dt_sel = st.session_state[chave_date_311]
                # Lógica matemática de pontuação baseada no ano selecionado
                if dt_sel >= date(ano_sel, 1, 1) and dt_sel.year == ano_sel:
                    pts = 10.0
                else:
                    pts = 0.0
                
                val = str(dt_sel)
                lnk = st.session_state.get(f"l_311_txt_{ano_sel}", d311.get("link", ""))
                
                save_resp("3.1.1", val, pts, lnk)
                res_data["3.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_311():
                lnk = st.session_state[f"l_311_txt_{ano_sel}"]
                dt_sel = st.session_state.get(chave_date_311, dt_i_311)
                
                if dt_sel >= date(ano_sel, 1, 1) and dt_sel.year == ano_sel:
                    pts = 10.0
                else:
                    pts = 0.0
                    
                val = str(dt_sel)
                save_resp("3.1.1", val, pts, lnk)
                res_data["3.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d311.get("link", "") or "")]
                
                if lnk != d311.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_1_{ano_sel}"] = True

            col_d311, col_j311 = st.columns([1, 1])
            with col_d311:
                data_sel_311 = st.date_input(
                    "Data do treinamento:",
                    value=dt_i_311,
                    key=chave_date_311,
                    on_change=cb_date_311,
                    format="DD/MM/YYYY"
                )
                
                # feedback visual do cálculo em tempo real
                if data_sel_311 >= date(ano_sel, 1, 1) and data_sel_311.year == ano_sel:
                    st.success(f"Pontuação Calculada: 10 pts ({data_sel_311.strftime('%d/%m/%Y')})")
                else:
                    st.warning(f"Pontuação Calculada: 00 pts ({data_sel_311.strftime('%d/%m/%Y')})")
                
            with col_j311:
                link_311 = st.text_area("Justificativa (3.1.1):", value=d311.get("link", ""), key=f"l_311_txt_{ano_sel}", on_change=cb_text_311, height=100)
                placeholder_links_311 = st.empty()
                links_311_visuais = [u[0] for u in re.findall(regex_pure_url, link_311 or "")]
                if links_311_visuais:
                    placeholder_links_311.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_311_visuais]))

            pts_atuais_311 = d311.get("pontos", 0.0)
            cor_txt_311 = "#28a745" if pts_atuais_311 == 10.0 else "#dc3545"
            st.markdown(f"<span style='color:{cor_txt_311}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.1.1: {pts_atuais_311:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("3.1.1", res_data, ano_sel)

    # GATILHO DO MODAL 3.1.1
    if st.session_state.get(f"gatilho_modal_3_1_1_{ano_sel}", False):
        modal_aviso_link("3.1.1", st.session_state.get(f"links_pendentes_3_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_3_1_1_{ano_sel}"] = False

   # =============================================================================
    # QUESITO 4.0 • CARTA GEOTÉCNICA DE SUSCETIBILIDADE (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_4_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 4.0 - Carta Geotécnica de Suscetibilidade", expanded=True):
            st.subheader("4.0 • Carta Geotécnica")
            st.write("**O Município recebeu a Carta Geotécnica de Suscetibilidade, Aptidão à Urbanização e Risco?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações do quesito 4.0
            opcoes_40 = {
                "Selecione...": 0.0,
                "Sim": 10.0,
                "Não": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados
            d40 = res_data.get("4.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d40 is None: d40 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_40 = d40.get("valor", "Selecione...")
            chave_radio_40 = f"r_40_{v_salvo_40}_{ano_sel}"

            def cb_radio_40():
                val = st.session_state[chave_radio_40]
                pts = opcoes_40.get(val, 0.0)
                lnk = st.session_state.get(f"l_40_txt_{ano_sel}", d40.get("link", ""))
                
                save_resp("4.0", val, pts, lnk)
                res_data["4.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_40():
                lnk = st.session_state[f"l_40_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_40, v_salvo_40)
                pts = opcoes_40.get(val, 0.0)
                
                save_resp("4.0", val, pts, lnk)
                res_data["4.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d40.get("link", "") or "")]
                
                if lnk != d40.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

            col_r40, col_j40 = st.columns([1, 1])
            with col_r40:
                lista_opcoes_40 = list(opcoes_40.keys())
                idx_40 = lista_opcoes_40.index(v_salvo_40) if v_salvo_40 in lista_opcoes_40 else 0
                
                st.radio(
                    "Resposta 4.0:",
                    options=lista_opcoes_40,
                    index=idx_40,
                    key=chave_radio_40,
                    on_change=cb_radio_40,
                    label_visibility="collapsed"
                )
                
            with col_j40:
                link_40 = st.text_area("Evidência (4.0):", value=d40.get("link", ""), key=f"l_40_txt_{ano_sel}", on_change=cb_text_40, height=100)
                placeholder_links_40 = st.empty()
                links_40_visuais = [u[0] for u in re.findall(regex_pure_url, link_40 or "")]
                if links_40_visuais:
                    placeholder_links_40.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_40_visuais]))

            pts_atuais_40 = d40.get("pontos", 0.0)
            cor_txt_40 = "#28a745" if pts_atuais_40 == 10.0 else ("#dc3545" if v_salvo_40 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_40}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 4.0: {pts_atuais_40:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("4.0", res_data, ano_sel)

    # GATILHO DO MODAL 4.0
    if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
        modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 4.1 • AMEAÇAS IDENTIFICADAS NA CARTA GEOTÉCNICA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_4_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 4.1 - Ameaças Potenciais da Carta Geotécnica", expanded=True):
            st.subheader("4.1 • Ameaças Potenciais")
            st.write("**Assinale quais os tipos de ameaças potenciais identificadas na Carta Geotécnica:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados
            d41 = res_data.get("4.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d41 is None: d41 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_41 = d41.get("valor", "[]")
            
            ameacas_cobrade = [
                "Riscos Geológicos", 
                "Riscos Hidrológicos", 
                "Riscos Meteorológicos",
                "Riscos Climatológicos", 
                "Riscos Biológicos", 
                "Riscos Tecnológicos"
            ]

            def cb_checkbox_41():
                # Coleta as opções marcadas dinamicamente usando as chaves de estado do session_state
                selecionados_41 = []
                for ameaca in ameacas_cobrade:
                    if st.session_state.get(f"chk_41_{ameaca}_{ano_sel}", False):
                        selecionados_41.append(ameaca)
                
                pts = 0.0  # Quesito estrutural/informativo
                lnk = st.session_state.get(f"l_41_txt_{ano_sel}", d41.get("link", ""))
                val_str = str(selecionados_41)
                
                save_resp("4.1", val_str, pts, lnk)
                res_data["4.1"] = {"valor": val_str, "pontos": pts, "link": lnk}

            def cb_text_41():
                lnk = st.session_state[f"l_41_txt_{ano_sel}"]
                
                # Reconstrói a lista para garantir a integridade textual no dicionário local
                selecionados_41 = []
                for ameaca in ameacas_cobrade:
                    if st.session_state.get(f"chk_41_{ameaca}_{ano_sel}", ameaca in valor_salvo_41):
                        selecionados_41.append(ameaca)
                        
                val_str = str(selecionados_41)
                save_resp("4.1", val_str, 0.0, lnk)
                res_data["4.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d41.get("link", "") or "")]
                
                if lnk != d41.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = True

            col_c41, col_j41 = st.columns([1, 1])
            with col_c41:
                # Renderização assíncrona baseada nos checkboxes individuais mapeados
                for ameaca in ameacas_cobrade:
                    st.checkbox(
                        ameaca,
                        value=ameaca in valor_salvo_41,
                        key=f"chk_41_{ameaca}_{ano_sel}",
                        on_change=cb_checkbox_41
                    )
                
            with col_j41:
                link_41 = st.text_area("Justificativa (4.1):", value=d41.get("link", ""), key=f"l_41_txt_{ano_sel}", on_change=cb_text_41, height=185)
                placeholder_links_41 = st.empty()
                links_41_visuais = [u[0] for u in re.findall(regex_pure_url, link_41 or "")]
                if links_41_visuais:
                    placeholder_links_41.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_41_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 4.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("4.1", res_data, ano_sel)

    # GATILHO DO MODAL 4.1
    if st.session_state.get(f"gatilho_modal_4_1_{ano_sel}", False):
        modal_aviso_link("4.1", st.session_state.get(f"links_pendentes_4_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 4.2 • CARTA GEOTÉCNICA NO PLANO DIRETOR (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_4_2_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 4.2 - Carta Geotécnica no Plano Diretor", expanded=True):
            st.subheader("4.2 • Plano Diretor")
            st.write("**A Carta Geotécnica de Suscetibilidade, Aptidão à Urbanização e Risco consta no Plano Diretor?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações (incluindo pontuação negativa)
            opcoes_42 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-50 pts)": -50.0,
                "Não se aplica o Plano Diretor (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados
            d42 = res_data.get("4.2", {"valor": "Selecione...", "pontos": -50.0, "link": ""})
            if d42 is None: d42 = {"valor": "Selecione...", "pontos": -50.0, "link": ""}
            
            v_salvo_42 = d42.get("valor", "Selecione...")
            chave_radio_42 = f"r_42_{v_salvo_42}_{ano_sel}"

            def cb_radio_42():
                val = st.session_state[chave_radio_42]
                pts = opcoes_42.get(val, 0.0)
                lnk = st.session_state.get(f"l_42_txt_{ano_sel}", d42.get("link", ""))
                
                save_resp("4.2", val, pts, lnk)
                res_data["4.2"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_42():
                lnk = st.session_state[f"l_42_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_42, v_salvo_42)
                pts = opcoes_42.get(val, 0.0)
                
                save_resp("4.2", val, pts, lnk)
                res_data["4.2"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d42.get("link", "") or "")]
                
                if lnk != d42.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = True

            col_r42, col_j42 = st.columns([1, 1])
            with col_r42:
                lista_opcoes_42 = list(opcoes_42.keys())
                idx_42 = lista_opcoes_42.index(v_salvo_42) if v_salvo_42 in lista_opcoes_42 else 0
                
                st.radio(
                    "Situação:",
                    options=lista_opcoes_42,
                    index=idx_42,
                    key=chave_radio_42,
                    on_change=cb_radio_42,
                    label_visibility="collapsed"
                )
                
            with col_j42:
                link_42 = st.text_area("Evidência (4.2):", value=d42.get("link", ""), key=f"l_42_txt_{ano_sel}", on_change=cb_text_42, height=135)
                placeholder_links_42 = st.empty()
                links_42_visuais = [u[0] for u in re.findall(regex_pure_url, link_42 or "")]
                if links_42_visuais:
                    placeholder_links_42.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_42_visuais]))

            pts_atuais_42 = d42.get("pontos", 0.0)
            cor_txt_42 = "#28a745" if pts_atuais_42 == 0.0 and v_salvo_42 != "Selecione..." else ("#dc3545" if pts_atuais_42 < 0.0 else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_42}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 4.2: {pts_atuais_42:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("4.2", res_data, ano_sel)

    # GATILHO DO MODAL 4.2
    if st.session_state.get(f"gatilho_modal_4_2_{ano_sel}", False):
        modal_aviso_link("4.2", st.session_state.get(f"links_pendentes_4_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = False

# =============================================================================
    # QUESITO 5.0 • MAPEAMENTO PRÓPRIO DE AMEAÇAS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_5_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 5.0 - Mapeamento Próprio de Ameaças", expanded=True):
            st.subheader("5.0 • Mapeamento de Ameaças")
            st.write("**O Município realizou, por conta própria, o mapeamento e identificação das principais ameaças existentes em seu território?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações
            opcoes_50 = {
                "Selecione...": 0.0,
                "Sim (200 pts)": 200.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados
            d50 = res_data.get("5.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d50 is None: d50 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_50 = d50.get("valor", "Selecione...")
            chave_radio_50 = f"r_50_{v_salvo_50}_{ano_sel}"

            def cb_radio_50():
                val = st.session_state[chave_radio_50]
                pts = opcoes_50.get(val, 0.0)
                lnk = st.session_state.get(f"l_50_txt_{ano_sel}", d50.get("link", ""))
                
                save_resp("5.0", val, pts, lnk)
                res_data["5.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_50():
                lnk = st.session_state[f"l_50_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_50, v_salvo_50)
                pts = opcoes_50.get(val, 0.0)
                
                save_resp("5.0", val, pts, lnk)
                res_data["5.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d50.get("link", "") or "")]
                
                if lnk != d50.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

            col_r50, col_j50 = st.columns([1, 1])
            with col_r50:
                lista_opcoes_50 = list(opcoes_50.keys())
                idx_50 = lista_opcoes_50.index(v_salvo_50) if v_salvo_50 in lista_opcoes_50 else 0
                
                st.radio(
                    "Resposta 5.0:",
                    options=lista_opcoes_50,
                    index=idx_50,
                    key=chave_radio_50,
                    on_change=cb_radio_50,
                    label_visibility="collapsed"
                )
                
            with col_j50:
                link_50 = st.text_area("Justificativa Técnica (5.0):", value=d50.get("link", ""), key=f"l_50_txt_{ano_sel}", on_change=cb_text_50, height=100)
                placeholder_links_50 = st.empty()
                links_50_visuais = [u[0] for u in re.findall(regex_pure_url, link_50 or "")]
                if links_50_visuais:
                    placeholder_links_50.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_50_visuais]))

            pts_atuais_50 = d50.get("pontos", 0.0)
            cor_txt_50 = "#28a745" if pts_atuais_50 == 200.0 else ("#dc3545" if v_salvo_50 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_50}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.0: {pts_atuais_50:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("5.0", res_data, ano_sel)

    # GATILHO DO MODAL 5.0
    if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
        modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 5.1 • PRINCIPAIS AMEAÇAS IDENTIFICADAS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_5_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 5.1 - Principais Ameaças Identificadas", expanded=True):
            st.subheader("5.1 • Principais Ameaças")
            st.write("**Assinale as principais ameaças identificadas:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados
            d51 = res_data.get("5.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d51 is None: d51 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_51 = d51.get("valor", "[]")
            
            ameacas_51 = [
                "Epidemias", 
                "Estiagem", 
                "Incêndios (urbanos e florestais)",
                "Ondas de calor ou ondas de frio", 
                "Inundações", 
                "Infestações e Pragas",
                "Ameaças radioativas", 
                "Deslizamentos", 
                "Outros"
            ]

            def cb_checkbox_51():
                # Varre os estados atuais de cada checkbox no session_state para montar a lista atualizada
                selecionados_51 = []
                for ameaca in ameacas_51:
                    ameaca_id = ameaca.replace(" ", "_").lower()
                    if st.session_state.get(f"chk51_{ameaca_id}_{ano_sel}", False):
                        selecionados_51.append(ameaca)
                
                pts = 0.0  # Quesito informativo/estrutural
                lnk = st.session_state.get(f"l_51_txt_{ano_sel}", d51.get("link", ""))
                val_str = str(selecionados_51)
                
                save_resp("5.1", val_str, pts, lnk)
                res_data["5.1"] = {"valor": val_str, "pontos": pts, "link": lnk}

            def cb_text_51():
                lnk = st.session_state[f"l_51_txt_{ano_sel}"]
                
                # Reconstrói a lista de marcados para garantir a consistência de persistência do texto
                selecionados_51 = []
                for ameaca in ameacas_51:
                    ameaca_id = ameaca.replace(" ", "_").lower()
                    if st.session_state.get(f"chk51_{ameaca_id}_{ano_sel}", ameaca in valor_salvo_51):
                        selecionados_51.append(ameaca)
                        
                val_str = str(selecionados_51)
                save_resp("5.1", val_str, 0.0, lnk)
                res_data["5.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d51.get("link", "") or "")]
                
                if lnk != d51.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

            col_c51, col_j51 = st.columns([1, 1])
            with col_c51:
                # Geração dinâmica dos elementos de checkbox mapeados e atrelados ao callback
                for ameaca in ameacas_51:
                    ameaca_id = ameaca.replace(" ", "_").lower()
                    st.checkbox(
                        ameaca,
                        value=ameaca in valor_salvo_51,
                        key=f"chk51_{ameaca_id}_{ano_sel}",
                        on_change=cb_checkbox_51
                    )
                
            with col_j51:
                link_51 = st.text_area(
                    "Descrição / Evidências (5.1):", 
                    value=d51.get("link", ""), 
                    key=f"l_51_txt_{ano_sel}", 
                    on_change=cb_text_51, 
                    placeholder="Se marcou 'Outros', especifique aqui...", 
                    height=240
                )
                placeholder_links_51 = st.empty()
                links_51_visuais = [u[0] for u in re.findall(regex_pure_url, link_51 or "")]
                if links_51_visuais:
                    placeholder_links_51.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_51_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("5.1", res_data, ano_sel)

    # GATILHO DO MODAL 5.1
    if st.session_state.get(f"gatilho_modal_5_1_{ano_sel}", False):
        modal_aviso_link("5.1", st.session_state.get(f"links_pendentes_5_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 5.1.1 • FISCALIZAÇÃO DE ÁREAS DE RISCO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_5_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 5.1.1 - Fiscalização das Áreas de Risco", expanded=True):
            st.subheader("5.1.1 • Fiscalização de Áreas de Risco")
            st.write("**As secretarias setoriais realizaram a fiscalização das áreas de risco?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações (incluindo pontuação negativa)
            opcoes_511 = {
                "Selecione...": 0.0,
                "Sim, integralmente (00 pts)": 0.0,
                "Sim, parcialmente (00 pts)": 0.0,
                "Não houve fiscalização (-100 pts)": -100.0
            }
            
            # Recupera o estado salvo no dicionário de dados
            d511 = res_data.get("5.1.1", {"valor": "Selecione...", "pontos": -100.0, "link": ""})
            if d511 is None: d511 = {"valor": "Selecione...", "pontos": -100.0, "link": ""}
            
            v_salvo_511 = d511.get("valor", "Selecione...")
            chave_radio_511 = f"r_511_{v_salvo_511}_{ano_sel}"

            def cb_radio_511():
                val = st.session_state[chave_radio_511]
                pts = opcoes_511.get(val, 0.0)
                lnk = st.session_state.get(f"l_511_txt_{ano_sel}", d511.get("link", ""))
                
                save_resp("5.1.1", val, pts, lnk)
                res_data["5.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_511():
                lnk = st.session_state[f"l_511_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_511, v_salvo_511)
                pts = opcoes_511.get(val, 0.0)
                
                save_resp("5.1.1", val, pts, lnk)
                res_data["5.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d511.get("link", "") or "")]
                
                if lnk != d511.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_1_{ano_sel}"] = True

            col_r511, col_j511 = st.columns([1, 1])
            with col_r511:
                lista_opcoes_511 = list(opcoes_511.keys())
                idx_511 = lista_opcoes_511.index(v_salvo_511) if v_salvo_511 in lista_opcoes_511 else 0
                
                st.radio(
                    "Status da Fiscalização:",
                    options=lista_opcoes_511,
                    index=idx_511,
                    key=chave_radio_511,
                    on_change=cb_radio_511,
                    label_visibility="collapsed"
                )
                
            with col_j511:
                link_511 = st.text_area("Evidência (5.1.1):", value=d511.get("link", ""), key=f"l_511_txt_{ano_sel}", on_change=cb_text_511, height=135)
                placeholder_links_511 = st.empty()
                links_511_visuais = [u[0] for u in re.findall(regex_pure_url, link_511 or "")]
                if links_511_visuais:
                    placeholder_links_511.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_511_visuais]))

            pts_atuais_511 = d511.get("pontos", 0.0)
            cor_txt_511 = "#28a745" if pts_atuais_511 == 0.0 and v_salvo_511 != "Selecione..." else ("#dc3545" if pts_atuais_511 < 0.0 else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_511}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.1.1: {pts_atuais_511:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("5.1.1", res_data, ano_sel)

    # GATILHO DO MODAL 5.11
    if st.session_state.get(f"gatilho_modal_5_1_1_{ano_sel}", False):
        modal_aviso_link("5.1.1", st.session_state.get(f"links_pendentes_5_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_5_1_1_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 5.1.2 • ÁREAS DE RISCO COM RISCO DE INVASÃO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_5_1_2_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 5.1.2 - Possibilidade de Ocupação/Invasão em Áreas de Risco", expanded=True):
            st.subheader("5.1.2 • Risco de Ocupação/Invasão")
            st.write("**O município possui áreas de risco com possibilidade de ocupação/invasão?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações (informativo)
            opcoes_512 = {
                "Selecione...": 0.0,
                "Sim": 0.0,
                "Não": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados
            d512 = res_data.get("5.1.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d512 is None: d512 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_512 = d512.get("valor", "Selecione...")
            chave_radio_512 = f"r_512_{v_salvo_512}_{ano_sel}"

            def cb_radio_512():
                val = st.session_state[chave_radio_512]
                pts = 0.0  # Quesito estrutural/informativo
                lnk = st.session_state.get(f"l_512_txt_{ano_sel}", d512.get("link", ""))
                
                save_resp("5.1.2", val, pts, lnk)
                res_data["5.1.2"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_512():
                lnk = st.session_state[f"l_512_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_512, v_salvo_512)
                
                save_resp("5.1.2", val, 0.0, lnk)
                res_data["5.1.2"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d512.get("link", "") or "")]
                
                if lnk != d512.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_2_{ano_sel}"] = True

            col_r512, col_j512 = st.columns([1, 1])
            with col_r512:
                lista_opcoes_512 = list(opcoes_512.keys())
                idx_512 = lista_opcoes_512.index(v_salvo_512) if v_salvo_512 in lista_opcoes_512 else 0
                
                st.radio(
                    "Possui áreas com risco de invasão?",
                    options=lista_opcoes_512,
                    index=idx_512,
                    key=chave_radio_512,
                    on_change=cb_radio_512,
                    label_visibility="collapsed"
                )
                
            with col_j512:
                link_512 = st.text_area("Justificativa (5.1.2):", value=d512.get("link", ""), key=f"l_512_txt_{ano_sel}", on_change=cb_text_512, height=100)
                placeholder_links_512 = st.empty()
                links_512_visuais = [u[0] for u in re.findall(regex_pure_url, link_512 or "")]
                if links_512_visuais:
                    placeholder_links_512.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_512_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.1.2: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("5.1.2", res_data, ano_sel)

    # GATILHO DO MODAL 5.12
    if st.session_state.get(f"gatilho_modal_5_1_2_{ano_sel}", False):
        modal_aviso_link("5.1.2", st.session_state.get(f"links_pendentes_5_1_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_5_1_2_{ano_sel}"] = False

   # =============================================================================
    # QUESITO 5.1.2.1 • MECANISMOS CONTRA NOVAS OCUPAÇÕES (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_5_1_2_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 5.1.2.1 - Mecanismos para Vedar Novas Ocupações", expanded=True):
            st.subheader("5.1.2.1 • Mecanismos de Vedação")
            st.write("**Assinale os mecanismos para vedar novas ocupações nas áreas de riscos:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados
            d5121 = res_data.get("5.1.2.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d5121 is None: d5121 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_5121 = d5121.get("valor", "[]")
            
            mecanismos = [
                "Aplicação de sanções monetárias (multas)", 
                "Monitoramento (fiscalização)",
                "Notificação dos infratores", 
                "Interdição do local e remoção das famílias",
                "Demolição das ocupações", 
                "Outros"
            ]

            def cb_checkbox_5121():
                # Coleta as opções marcadas em tempo real usando o session_state
                selecionados_5121 = []
                for mec in mecanismos:
                    mec_id = mec.replace(" ", "_").replace("(", "").replace(")", "").lower()
                    if st.session_state.get(f"chk5121_{mec_id}_{ano_sel}", False):
                        selecionados_5121.append(mec)
                
                pts = 0.0  # Quesito estrutural / informativo
                lnk = st.session_state.get(f"l_5121_txt_{ano_sel}", d5121.get("link", ""))
                val_str = str(selecionados_5121)
                
                save_resp("5.1.2.1", val_str, pts, lnk)
                res_data["5.1.2.1"] = {"valor": val_str, "pontos": pts, "link": lnk}

            def cb_text_5121():
                lnk = st.session_state[f"l_5121_txt_{ano_sel}"]
                
                # Reconstrói a lista para consistência e integridade da persistência do texto
                selecionados_5121 = []
                for mec in mecanismos:
                    mec_id = mec.replace(" ", "_").replace("(", "").replace(")", "").lower()
                    if st.session_state.get(f"chk5121_{mec_id}_{ano_sel}", mec in valor_salvo_5121):
                        selecionados_5121.append(mec)
                        
                val_str = str(selecionados_5121)
                save_resp("5.1.2.1", val_str, 0.0, lnk)
                res_data["5.1.2.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d5121.get("link", "") or "")]
                
                if lnk != d5121.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_2_1_{ano_sel}"] = True

            col_c5121, col_j5121 = st.columns([1, 1])
            with col_c5121:
                # Renderização assíncrona baseada nos checkboxes mapeados individualmente
                for mec in mecanismos:
                    mec_id = mec.replace(" ", "_").replace("(", "").replace(")", "").lower()
                    st.checkbox(
                        mec,
                        value=mec in valor_salvo_5121,
                        key=f"chk5121_{mec_id}_{ano_sel}",
                        on_change=cb_checkbox_5121
                    )
                
            with col_j5121:
                link_5121 = st.text_area("Evidências dos Mecanismos (5.1.2.1):", value=d5121.get("link", ""), key=f"l_5121_txt_{ano_sel}", on_change=cb_text_5121, height=185)
                placeholder_links_5121 = st.empty()
                links_5121_visuais = [u[0] for u in re.findall(regex_pure_url, link_5121 or "")]
                if links_5121_visuais:
                    placeholder_links_5121.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_5121_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.1.2.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("5.1.2.1", res_data, ano_sel)

    # GATILHO DO MODAL 5.1.2.1
    if st.session_state.get(f"gatilho_modal_5_1_2_1_{ano_sel}", False):
        modal_aviso_link("5.1.2.1", st.session_state.get(f"links_pendentes_5_1_2_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_5_1_2_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 5.2 • INFORMAÇÃO À POPULAÇÃO SOBRE AMEAÇAS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_5_2_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 5.2 - Informação à População sobre Ameaças", expanded=True):
            st.subheader("5.2 • Informação à População")
            st.write("**A população foi informada sobre todas as ameaças identificadas pelo município?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações (incluindo pontuação negativa flutuante)
            opcoes_52 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Parcialmente (00 pts)": 0.0,
                "Não (-50 pts)": -50.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d52 = res_data.get("5.2", {"valor": "Selecione...", "pontos": -50.0, "link": ""})
            if d52 is None: d52 = {"valor": "Selecione...", "pontos": -50.0, "link": ""}
            
            v_salvo_52 = d52.get("valor", "Selecione...")
            chave_radio_52 = f"r_52_{v_salvo_52}_{ano_sel}"

            def cb_radio_52():
                val = st.session_state[chave_radio_52]
                pts = opcoes_52.get(val, 0.0)
                lnk = st.session_state.get(f"l_52_txt_{ano_sel}", d52.get("link", ""))
                
                save_resp("5.2", val, pts, lnk)
                res_data["5.2"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_52():
                lnk = st.session_state[f"l_52_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_52, v_salvo_52)
                pts = opcoes_52.get(val, 0.0)
                
                save_resp("5.2", val, pts, lnk)
                res_data["5.2"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d52.get("link", "") or "")]
                
                if lnk != d52.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = True

            col_r52, col_j52 = st.columns([1, 1])
            with col_r52:
                lista_opcoes_52 = list(opcoes_52.keys())
                idx_52 = lista_opcoes_52.index(v_salvo_52) if v_salvo_52 in lista_opcoes_52 else 0
                
                st.radio(
                    "Informação à população:",
                    options=lista_opcoes_52,
                    index=idx_52,
                    key=chave_radio_52,
                    on_change=cb_radio_52,
                    label_visibility="collapsed"
                )
                
            with col_j52:
                link_52 = st.text_area(
                    "Meios de comunicação utilizados / Evidência (5.2):", 
                    value=d52.get("link", ""), 
                    key=f"l_52_txt_{ano_sel}", 
                    on_change=cb_text_52, 
                    height=135
                )
                placeholder_links_52 = st.empty()
                links_52_visuais = [u[0] for u in re.findall(regex_pure_url, link_52 or "")]
                if links_52_visuais:
                    placeholder_links_52.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_52_visuais]))

            pts_atuais_52 = d52.get("pontos", 0.0)
            cor_txt_52 = "#28a745" if pts_atuais_52 == 0.0 and v_salvo_52 != "Selecione..." else ("#dc3545" if pts_atuais_52 < 0.0 else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_52}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.2: {pts_atuais_52:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("5.2", res_data, ano_sel)

    # GATILHO DO MODAL 5.2
    if st.session_state.get(f"gatilho_modal_5_2_{ano_sel}", False):
        modal_aviso_link("5.2", st.session_state.get(f"links_pendentes_5_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = False

# =============================================================================
    # QUESITO 6.0 • VISTORIAS EM EDIFICAÇÕES VULNERÁVEIS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_6_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 6.0 - Vistorias em Edificações Vulneráveis", expanded=True):
            st.subheader("6.0 • Vistorias Preventivas")
            st.write("**A Secretaria responsável realizou vistorias em edificações vulneráveis com o objetivo de identificar a necessidade de intervenção preventiva nos imóveis?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações (incluindo pontuação negativa flutuante)
            opcoes_60 = {
                "Selecione...": 0.0,
                "Sim, de acordo com um cronograma preestabelecido (00 pts)": 0.0,
                "Sim, de acordo com a demanda (00 pts)": 0.0,
                "Não foram vistoriadas (-50 pts)": -50.0,
                "Não houve casos de edificações vulneráveis (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d60 = res_data.get("6.0", {"valor": "Selecione...", "pontos": -50.0, "link": ""})
            if d60 is None: d60 = {"valor": "Selecione...", "pontos": -50.0, "link": ""}
            
            v_salvo_60 = d60.get("valor", "Selecione...")
            chave_radio_60 = f"r_60_{v_salvo_60}_{ano_sel}"

            def cb_radio_60():
                val = st.session_state[chave_radio_60]
                pts = opcoes_60.get(val, 0.0)
                lnk = st.session_state.get(f"l_60_txt_{ano_sel}", d60.get("link", ""))
                
                save_resp("6.0", val, pts, lnk)
                res_data["6.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_60():
                lnk = st.session_state[f"l_60_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_60, v_salvo_60)
                pts = opcoes_60.get(val, 0.0)
                
                save_resp("6.0", val, pts, lnk)
                res_data["6.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d60.get("link", "") or "")]
                
                if lnk != d60.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

            col_r60, col_j60 = st.columns([1, 1])
            with col_r60:
                lista_opcoes_60 = list(opcoes_60.keys())
                idx_60 = lista_opcoes_60.index(v_salvo_60) if v_salvo_60 in lista_opcoes_60 else 0
                
                st.radio(
                    "Status das Vistorias:",
                    options=lista_opcoes_60,
                    index=idx_60,
                    key=chave_radio_60,
                    on_change=cb_radio_60,
                    label_visibility="collapsed"
                )
                
            with col_j60:
                link_60 = st.text_area(
                    "Relatórios de Vistoria / Evidências (6.0):", 
                    value=d60.get("link", ""), 
                    key=f"l_60_txt_{ano_sel}", 
                    on_change=cb_text_60, 
                    height=165
                )
                placeholder_links_60 = st.empty()
                links_60_visuais = [u[0] for u in re.findall(regex_pure_url, link_60 or "")]
                if links_60_visuais:
                    placeholder_links_60.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_60_visuais]))

            pts_atuais_60 = d60.get("pontos", 0.0)
            cor_txt_60 = "#28a745" if pts_atuais_60 == 0.0 and v_salvo_60 != "Selecione..." else ("#dc3545" if pts_atuais_60 < 0.0 else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_60}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.0: {pts_atuais_60:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("6.0", res_data, ano_sel)

    # GATILHO DO MODAL 6.0
    if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
        modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 7.0 • PLANCON DE DEFESA CIVIL (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.0 - Plano de Contingência Municipal (PLANCON)", expanded=True):
            st.subheader("7.0 • PLANCON")
            st.write("**O Município possui Plano de Contingência Municipal – PLANCON de Defesa Civil?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações
            opcoes_70 = {
                "Selecione...": 0.0,
                "Sim (50 pts)": 50.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d70 = res_data.get("7.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d70 is None: d70 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_70 = d70.get("valor", "Selecione...")
            chave_radio_70 = f"r_70_{v_salvo_70}_{ano_sel}"

            def cb_radio_70():
                val = st.session_state[chave_radio_70]
                pts = opcoes_70.get(val, 0.0)
                lnk = st.session_state.get(f"l_70_txt_{ano_sel}", d70.get("link", ""))
                
                save_resp("7.0", val, pts, lnk)
                res_data["7.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_70():
                lnk = st.session_state[f"l_70_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_70, v_salvo_70)
                pts = opcoes_70.get(val, 0.0)
                
                save_resp("7.0", val, pts, lnk)
                res_data["7.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d70.get("link", "") or "")]
                
                if lnk != d70.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

            col_r70, col_j70 = st.columns([1, 1])
            with col_r70:
                lista_opcoes_70 = list(opcoes_70.keys())
                idx_70 = lista_opcoes_70.index(v_salvo_70) if v_salvo_70 in lista_opcoes_70 else 0
                
                st.radio(
                    "Possui PLANCON?",
                    options=lista_opcoes_70,
                    index=idx_70,
                    key=chave_radio_70,
                    on_change=cb_radio_70,
                    label_visibility="collapsed"
                )
                
            with col_j70:
                link_70 = st.text_area(
                    "Link do PLANCON / Decreto (7.0):", 
                    value=d70.get("link", ""), 
                    key=f"l_70_txt_{ano_sel}", 
                    on_change=cb_text_70, 
                    height=100
                )
                placeholder_links_70 = st.empty()
                links_70_visuais = [u[0] for u in re.findall(regex_pure_url, link_70 or "")]
                if links_70_visuais:
                    placeholder_links_70.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_70_visuais]))

            pts_atuais_70 = d70.get("pontos", 0.0)
            cor_txt_70 = "#28a745" if pts_atuais_70 == 50.0 else ("#dc3545" if v_salvo_70 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_70}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.0: {pts_atuais_70:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("7.0", res_data, ano_sel)

    # GATILHO DO MODAL 7.0
    if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
        modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = False


  # =============================================================================
    # QUESITO 7.1 • ABRANGÊNCIA DO PLANCON POR AMEAÇA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.1 - Elaboração de PLANCON por Ameaça", expanded=True):
            st.subheader("7.1 • Especificidade do PLANCON")
            st.write("**Foi elaborado um PLANCON específico para cada ameaça identificada?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações progressivas
            opcoes_71 = {
                "Selecione...": 0.0,
                "Sim, cada ameaça mapeada possui um PLANCON diferente (05 pts)": 5.0,
                "Sim, parte das ameaças possuem PLANCON diferentes (03 pts)": 3.0,
                "Existe apenas um PLANCON que abrange todas as ameaças (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d71 = res_data.get("7.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d71 is None: d71 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_71 = d71.get("valor", "Selecione...")
            chave_radio_71 = f"r_71_{v_salvo_71}_{ano_sel}"

            def cb_radio_71():
                val = st.session_state[chave_radio_71]
                pts = opcoes_71.get(val, 0.0)
                lnk = st.session_state.get(f"l_71_txt_{ano_sel}", d71.get("link", ""))
                
                save_resp("7.1", val, pts, lnk)
                res_data["7.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_71():
                lnk = st.session_state[f"l_71_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_71, v_salvo_71)
                pts = opcoes_71.get(val, 0.0)
                
                save_resp("7.1", val, pts, lnk)
                res_data["7.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d71.get("link", "") or "")]
                
                if lnk != d71.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = True

            col_r71, col_j71 = st.columns([1, 1])
            with col_r71:
                lista_opcoes_71 = list(opcoes_71.keys())
                idx_71 = lista_opcoes_71.index(v_salvo_71) if v_salvo_71 in lista_opcoes_71 else 0
                
                st.radio(
                    "Abrangência do PLANCON:",
                    options=lista_opcoes_71,
                    index=idx_71,
                    key=chave_radio_71,
                    on_change=cb_radio_71,
                    label_visibility="collapsed"
                )
                
            with col_j71:
                link_71 = st.text_area(
                    "Evidências/Links dos planos específicos (7.1):", 
                    value=d71.get("link", ""), 
                    key=f"l_71_txt_{ano_sel}", 
                    on_change=cb_text_71, 
                    height=135
                )
                placeholder_links_71 = st.empty()
                links_71_visuais = [u[0] for u in re.findall(regex_pure_url, link_71 or "")]
                if links_71_visuais:
                    placeholder_links_71.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_71_visuais]))

            pts_atuais_71 = d71.get("pontos", 0.0)
            cor_txt_71 = "#28a745" if pts_atuais_71 > 0.0 else ("#dc3545" if v_salvo_71 == "Existe apenas um PLANCON que abrange todas as ameaças (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_71}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.1: +{pts_atuais_71:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("7.1", res_data, ano_sel)

    # GATILHO DO MODAL 7.1
    if st.session_state.get(f"gatilho_modal_7_1_{ano_sel}", False):
        modal_aviso_link("7.1", st.session_state.get(f"links_pendentes_7_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 7.2 • EXERCÍCIOS SIMULADOS DO PLANCON (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_2_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.2 - Exercícios Simulados para Contingências", expanded=True):
            st.subheader("7.2 • Exercícios Simulados")
            st.write("**São realizados regularmente exercícios simulados para as contingências previstas no PLANCON?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações
            opcoes_72 = {
                "Selecione...": 0.0,
                "Sim (80 pts)": 80.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d72 = res_data.get("7.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d72 is None: d72 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_72 = d72.get("valor", "Selecione...")
            chave_radio_72 = f"r_72_{v_salvo_72}_{ano_sel}"

            def cb_radio_72():
                val = st.session_state[chave_radio_72]
                pts = opcoes_72.get(val, 0.0)
                lnk = st.session_state.get(f"l_72_txt_{ano_sel}", d72.get("link", ""))
                
                save_resp("7.2", val, pts, lnk)
                res_data["7.2"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_72():
                lnk = st.session_state[f"l_72_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_72, v_salvo_72)
                pts = opcoes_72.get(val, 0.0)
                
                save_resp("7.2", val, pts, lnk)
                res_data["7.2"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d72.get("link", "") or "")]
                
                if lnk != d72.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = True

            col_r72, col_j72 = st.columns([1, 1])
            with col_r72:
                lista_opcoes_72 = list(opcoes_72.keys())
                idx_72 = lista_opcoes_72.index(v_salvo_72) if v_salvo_72 in lista_opcoes_72 else 0
                
                st.radio(
                    "Realiza simulados?",
                    options=lista_opcoes_72,
                    index=idx_72,
                    key=chave_radio_72,
                    on_change=cb_radio_72,
                    label_visibility="collapsed"
                )
                
            with col_j72:
                link_72 = st.text_area(
                    "Cronograma/Relatório dos Simulados (7.2):", 
                    value=d72.get("link", ""), 
                    key=f"l_72_txt_{ano_sel}", 
                    on_change=cb_text_72, 
                    height=100
                )
                placeholder_links_72 = st.empty()
                links_72_visuais = [u[0] for u in re.findall(regex_pure_url, link_72 or "")]
                if links_72_visuais:
                    placeholder_links_72.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_72_visuais]))

            pts_atuais_72 = d72.get("pontos", 0.0)
            cor_txt_72 = "#28a745" if pts_atuais_72 == 80.0 else ("#dc3545" if v_salvo_72 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_72}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.2: {pts_atuais_72:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("7.2", res_data, ano_sel)

    # GATILHO DO MODAL 7.2
    if st.session_state.get(f"gatilho_modal_7_2_{ano_sel}", False):
        modal_aviso_link("7.2", st.session_state.get(f"links_pendentes_7_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 7.3 • SISTEMA DE ALERTA PARA DESASTRES (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_3_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.3 - Sistema de Alerta para Desastres", expanded=True):
            st.subheader("7.3 • Sistema de Alerta")
            st.write("**O Município possui sistema de alerta para desastres?**")
            st.caption("ℹ *Objetivo: avisar a população vulnerável antes de ocorrer o evento.*")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações
            opcoes_73 = {
                "Selecione...": 0.0,
                "Sim (50 pts)": 50.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d73 = res_data.get("7.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d73 is None: d73 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_73 = d73.get("valor", "Selecione...")
            chave_radio_73 = f"r_73_{v_salvo_73}_{ano_sel}"

            def cb_radio_73():
                val = st.session_state[chave_radio_73]
                pts = opcoes_73.get(val, 0.0)
                lnk = st.session_state.get(f"l_73_txt_{ano_sel}", d73.get("link", ""))
                
                save_resp("7.3", val, pts, lnk)
                res_data["7.3"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_73():
                lnk = st.session_state[f"l_73_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_73, v_salvo_73)
                pts = opcoes_73.get(val, 0.0)
                
                save_resp("7.3", val, pts, lnk)
                res_data["7.3"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d73.get("link", "") or "")]
                
                if lnk != d73.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = True

            col_r73, col_j73 = st.columns([1, 1])
            with col_r73:
                lista_opcoes_73 = list(opcoes_73.keys())
                idx_73 = lista_opcoes_73.index(v_salvo_73) if v_salvo_73 in lista_opcoes_73 else 0
                
                st.radio(
                    "Possui sistema de alerta?",
                    options=lista_opcoes_73,
                    index=idx_73,
                    key=chave_radio_73,
                    on_change=cb_radio_73,
                    label_visibility="collapsed"
                )
                
            with col_j73:
                link_73 = st.text_area(
                    "Descrição do sistema (SMS, Sirenes, etc) (7.3):", 
                    value=d73.get("link", ""), 
                    key=f"l_73_txt_{ano_sel}", 
                    on_change=cb_text_73, 
                    height=100
                )
                placeholder_links_73 = st.empty()
                links_73_visuais = [u[0] for u in re.findall(regex_pure_url, link_73 or "")]
                if links_73_visuais:
                    placeholder_links_73.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_73_visuais]))

            pts_atuais_73 = d73.get("pontos", 0.0)
            cor_txt_73 = "#28a745" if pts_atuais_73 == 50.0 else ("#dc3545" if v_salvo_73 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_73}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3: {pts_atuais_73:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("7.3", res_data, ano_sel)

    # GATILHO DO MODAL 7.3
    if st.session_state.get(f"gatilho_modal_7_3_{ano_sel}", False):
        modal_aviso_link("7.3", st.session_state.get(f"links_pendentes_7_3_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 7.3.1 • TIPOS DE SISTEMAS DE ALERTA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_3_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.3.1 - Tipos de Sistemas de Alerta Utilizados", expanded=True):
            st.subheader("7.3.1 • Tipos de Alerta")
            st.write("**Assinale os tipos de sistemas de alerta utilizados pelo Município:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados históricos
            d731 = res_data.get("7.3.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d731 is None: d731 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_731 = d731.get("valor", "[]")
            
            tipos_alerta = [
                "Alerta via SMS",
                "Anúncio por rádio/Televisão",
                "Placas de identificação de área de risco",
                "Aviso por telefone / Aplicativo de mensagens",
                "Aviso por email",
                "Aviso aos membros do Nupdec",
                "Outro"
            ]

            def cb_checkbox_731():
                # Coleta as opções marcadas em tempo real usando o session_state
                sel_731 = []
                for t in tipos_alerta:
                    t_key = t.replace("/", "_").replace(" ", "_").replace("-", "_").lower()
                    if st.session_state.get(f"chk731_{t_key}_{ano_sel}", False):
                        sel_731.append(t)
                
                pts = 0.0  # Quesito informativo / estrutural
                lnk = st.session_state.get(f"l_731_txt_{ano_sel}", d731.get("link", ""))
                val_str = str(sel_731)
                
                save_resp("7.3.1", val_str, pts, lnk)
                res_data["7.3.1"] = {"valor": val_str, "pontos": pts, "link": lnk}

            def cb_text_731():
                lnk = st.session_state[f"l_731_txt_{ano_sel}"]
                
                # Reconstrói a lista para consistência e integridade da persistência do texto
                sel_731 = []
                for t in tipos_alerta:
                    t_key = t.replace("/", "_").replace(" ", "_").replace("-", "_").lower()
                    if st.session_state.get(f"chk731_{t_key}_{ano_sel}", t in valor_salvo_731):
                        sel_731.append(t)
                        
                val_str = str(sel_731)
                save_resp("7.3.1", val_str, 0.0, lnk)
                res_data["7.3.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d731.get("link", "") or "")]
                
                if lnk != d731.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_3_1_{ano_sel}"] = True

            col_c731, col_j731 = st.columns([1, 1])
            with col_c731:
                # Renderização assíncrona baseada nos checkboxes mapeados individualmente
                for t in tipos_alerta:
                    t_key = t.replace("/", "_").replace(" ", "_").replace("-", "_").lower()
                    st.checkbox(
                        t,
                        value=t in valor_salvo_731,
                        key=f"chk731_{t_key}_{ano_sel}",
                        on_change=cb_checkbox_731
                    )
                
            with col_j731:
                link_731 = st.text_area(
                    "Justificativa / Detalhes (7.3.1):", 
                    value=d731.get("link", ""), 
                    key=f"l_731_txt_{ano_sel}", 
                    on_change=cb_text_731, 
                    height=200
                )
                placeholder_links_731 = st.empty()
                links_731_visuais = [u[0] for u in re.findall(regex_pure_url, link_731 or "")]
                if links_731_visuais:
                    placeholder_links_731.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_731_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("7.3.1", res_data, ano_sel)

    # GATILHO DO MODAL 7.3.1
    if st.session_state.get(f"gatilho_modal_7_3_1_{ano_sel}", False):
        modal_aviso_link("7.3.1", st.session_state.get(f"links_pendentes_7_3_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_3_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 7.4 • SISTEMA DE ALARME PARA DESASTRES (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_4_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.4 - Dispositivo ou Sistema de Alarme", expanded=True):
            st.subheader("7.4 • Sistema de Alarme")
            st.write("**O Município dispõe de sinal, dispositivo ou sistema de alarme para desastres?**")
            st.caption("ℹ *Objetivo: avisar a população sobre o evento que ESTÁ OCORRENDO.*")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações
            opcoes_74 = {
                "Selecione...": 0.0,
                "Sim (50 pts)": 50.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d74 = res_data.get("7.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d74 is None: d74 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_74 = d74.get("valor", "Selecione...")
            chave_radio_74 = f"r_74_{v_salvo_74}_{ano_sel}"

            def cb_radio_74():
                val = st.session_state[chave_radio_74]
                pts = opcoes_74.get(val, 0.0)
                lnk = st.session_state.get(f"l_74_txt_{ano_sel}", d74.get("link", ""))
                
                save_resp("7.4", val, pts, lnk)
                res_data["7.4"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_74():
                lnk = st.session_state[f"l_74_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_74, v_salvo_74)
                pts = opcoes_74.get(val, 0.0)
                
                save_resp("7.4", val, pts, lnk)
                res_data["7.4"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d74.get("link", "") or "")]
                
                if lnk != d74.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_4_{ano_sel}"] = True

            col_r74, col_j74 = st.columns([1, 1])
            with col_r74:
                lista_opcoes_74 = list(opcoes_74.keys())
                idx_74 = lista_opcoes_74.index(v_salvo_74) if v_salvo_74 in lista_opcoes_74 else 0
                
                st.radio(
                    "Possui sistema de alarme?",
                    options=lista_opcoes_74,
                    index=idx_74,
                    key=chave_radio_74,
                    on_change=cb_radio_74,
                    label_visibility="collapsed"
                )
                
            with col_j74:
                link_74 = st.text_area(
                    "Evidência do sistema de alarme (7.4):", 
                    value=d74.get("link", ""), 
                    key=f"l_74_txt_{ano_sel}", 
                    on_change=cb_text_74, 
                    height=100
                )
                placeholder_links_74 = st.empty()
                links_74_visuais = [u[0] for u in re.findall(regex_pure_url, link_74 or "")]
                if links_74_visuais:
                    placeholder_links_74.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_74_visuais]))

            pts_atuais_74 = d74.get("pontos", 0.0)
            cor_txt_74 = "#28a745" if pts_atuais_74 == 50.0 else ("#dc3545" if v_salvo_74 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_74}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.4: {pts_atuais_74:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("7.4", res_data, ano_sel)

    # GATILHO DO MODAL 7.4
    if st.session_state.get(f"gatilho_modal_7_4_{ano_sel}", False):
        modal_aviso_link("7.4", st.session_state.get(f"links_pendentes_7_4_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_4_{ano_sel}"] = False

   # =============================================================================
    # QUESITO 7.4.1 • TIPOS DE SISTEMAS DE ALARME (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_4_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.4.1 - Tipos de Sinais ou Alarmes Utilizados", expanded=True):
            st.subheader("7.4.1 • Tipos de Alarme")
            st.write("**Assinale os tipos de sinal, dispositivo ou sistema de alarme utilizado:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados históricos
            d741 = res_data.get("7.4.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d741 is None: d741 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_741 = d741.get("valor", "[]")
            
            tipos_alarme = [
                "Sinal sonoro (sirene)",
                "Sinal luminoso",
                "Carros de emergência com sirenes",
                "Carros de emergência com alto-falantes",
                "Aviso aos membros do Nupdec",
                "Aviso por telefone / Aplicativo de mensagens",
                "Uso da imprensa (TV, rádio, internet)",
                "Outro"
            ]

            def cb_checkbox_741():
                # Coleta as opções marcadas em tempo real usando o session_state
                sel_741 = []
                for ta in tipos_alarme:
                    ta_id = ta.replace('(', '').replace(')', '').replace('/', '_').replace(' ', '_').replace(',', '_').lower()
                    if st.session_state.get(f"chk741_{ta_id}_{ano_sel}", False):
                        sel_741.append(ta)
                
                pts = 0.0  # Quesito informativo / estrutural
                lnk = st.session_state.get(f"l_741_txt_{ano_sel}", d741.get("link", ""))
                val_str = str(sel_741)
                
                save_resp("7.4.1", val_str, pts, lnk)
                res_data["7.4.1"] = {"valor": val_str, "pontos": pts, "link": lnk}

            def cb_text_741():
                lnk = st.session_state[f"l_741_txt_{ano_sel}"]
                
                # Reconstrói a lista para consistência e integridade da persistência do texto
                sel_741 = []
                for ta in tipos_alarme:
                    ta_id = ta.replace('(', '').replace(')', '').replace('/', '_').replace(' ', '_').replace(',', '_').lower()
                    if st.session_state.get(f"chk741_{ta_id}_{ano_sel}", ta in valor_salvo_741):
                        sel_741.append(ta)
                        
                val_str = str(sel_741)
                save_resp("7.4.1", val_str, 0.0, lnk)
                res_data["7.4.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d741.get("link", "") or "")]
                
                if lnk != d741.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_4_1_{ano_sel}"] = True

            col_c741, col_j741 = st.columns([1, 1])
            with col_c741:
                # Renderização assíncrona baseada nos checkboxes mapeados individualmente
                for ta in tipos_alarme:
                    ta_id = ta.replace('(', '').replace(')', '').replace('/', '_').replace(' ', '_').replace(',', '_').lower()
                    st.checkbox(
                        ta,
                        value=ta in valor_salvo_741,
                        key=f"chk741_{ta_id}_{ano_sel}",
                        on_change=cb_checkbox_741
                    )
                
            with col_j741:
                link_741 = st.text_area(
                    "Justificativa / Detalhes (7.4.1):", 
                    value=d741.get("link", ""), 
                    key=f"l_741_txt_{ano_sel}", 
                    on_change=cb_text_741, 
                    height=225
                )
                placeholder_links_741 = st.empty()
                links_741_visuais = [u[0] for u in re.findall(regex_pure_url, link_741 or "")]
                if links_741_visuais:
                    placeholder_links_741.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_741_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.4.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("7.4.1", res_data, ano_sel)

    # GATILHO DO MODAL 7.4.1
    if st.session_state.get(f"gatilho_modal_7_4_1_{ano_sel}", False):
        modal_aviso_link("7.4.1", st.session_state.get(f"links_pendentes_7_4_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_4_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 7.5 • CADASTRO DE ABRIGOS CEPDEC (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_5_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.5 - Cadastro de Locais para Abrigo (CEPDEC)", expanded=True):
            st.subheader("7.5 • Cadastro de Abrigos")
            st.write("**Possui cadastro dos locais para abrigo à população em situação de desastre junto à Coordenadoria Estadual de Proteção e Defesa Civil (CEPDEC)?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações progressivas
            opcoes_75 = {
                "Selecione...": 0.0,
                "Sim, atualizado (10 pts)": 10.0,
                "Sim, mas não está atualizado (03 pts)": 3.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d75 = res_data.get("7.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d75 is None: d75 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_75 = d75.get("valor", "Selecione...")
            chave_radio_75 = f"r_75_{v_salvo_75}_{ano_sel}"

            def cb_radio_75():
                val = st.session_state[chave_radio_75]
                pts = opcoes_75.get(val, 0.0)
                lnk = st.session_state.get(f"l_75_txt_{ano_sel}", d75.get("link", ""))
                
                save_resp("7.5", val, pts, lnk)
                res_data["7.5"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_75():
                lnk = st.session_state[f"l_75_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_75, v_salvo_75)
                pts = opcoes_75.get(val, 0.0)
                
                save_resp("7.5", val, pts, lnk)
                res_data["7.5"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d75.get("link", "") or "")]
                
                if lnk != d75.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_5_{ano_sel}"] = True

            col_r75, col_j75 = st.columns([1, 1])
            with col_r75:
                lista_opcoes_75 = list(opcoes_75.keys())
                idx_75 = lista_opcoes_75.index(v_salvo_75) if v_salvo_75 in lista_opcoes_75 else 0
                
                st.radio(
                    "Cadastro de Abrigos (CEPDEC):",
                    options=lista_opcoes_75,
                    index=idx_75,
                    key=chave_radio_75,
                    on_change=cb_radio_75,
                    label_visibility="collapsed"
                )
                
            with col_j75:
                link_75 = st.text_area(
                    "Evidência do Cadastro/Protocolo (7.5):", 
                    value=d75.get("link", ""), 
                    key=f"l_75_txt_{ano_sel}", 
                    on_change=cb_text_75, 
                    height=135
                )
                placeholder_links_75 = st.empty()
                links_75_visuais = [u[0] for u in re.findall(regex_pure_url, link_75 or "")]
                if links_75_visuais:
                    placeholder_links_75.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_75_visuais]))

            pts_atuais_75 = d75.get("pontos", 0.0)
            cor_txt_75 = "#28a745" if pts_atuais_75 > 0.0 else ("#dc3545" if v_salvo_75 == "Não (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_75}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.5: +{pts_atuais_75:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("7.5", res_data, ano_sel)

    # GATILHO DO MODAL 7.5
    if st.session_state.get(f"gatilho_modal_7_5_{ano_sel}", False):
        modal_aviso_link("7.5", st.session_state.get(f"links_pendentes_7_5_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_5_{ano_sel}"] = False
# =============================================================================
    # QUESITO 7.6 • FORNECEDORES DE AJUDA HUMANITÁRIA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_7_6_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.6 - Cadastro de Fornecedores de Ajuda Humanitária", expanded=True):
            st.subheader("7.6 • Lista de Fornecedores")
            st.write("**O Município possui cadastro da lista de fornecedores para coleta e distribuição de suprimentos de ajuda humanitária para o caso de desastre?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações progressivas
            opcoes_76 = {
                "Selecione...": 0.0,
                "Sim, atualizado (10 pts)": 10.0,
                "Sim, mas não está atualizado (03 pts)": 3.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d76 = res_data.get("7.6", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d76 is None: d76 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_76 = d76.get("valor", "Selecione...")
            chave_radio_76 = f"r_76_{v_salvo_76}_{ano_sel}"

            def cb_radio_76():
                val = st.session_state[chave_radio_76]
                pts = opcoes_76.get(val, 0.0)
                lnk = st.session_state.get(f"l_76_txt_{ano_sel}", d76.get("link", ""))
                
                save_resp("7.6", val, pts, lnk)
                res_data["7.6"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_76():
                lnk = st.session_state[f"l_76_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_76, v_salvo_76)
                pts = opcoes_76.get(val, 0.0)
                
                save_resp("7.6", val, pts, lnk)
                res_data["7.6"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d76.get("link", "") or "")]
                
                if lnk != d76.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_6_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_6_{ano_sel}"] = True

            col_r76, col_j76 = st.columns([1, 1])
            with col_r76:
                lista_opcoes_76 = list(opcoes_76.keys())
                idx_76 = lista_opcoes_76.index(v_salvo_76) if v_salvo_76 in lista_opcoes_76 else 0
                
                st.radio(
                    "Lista de Fornecedores:",
                    options=lista_opcoes_76,
                    index=idx_76,
                    key=chave_radio_76,
                    on_change=cb_radio_76,
                    label_visibility="collapsed"
                )
                
            with col_j76:
                link_76 = st.text_area(
                    "Evidência da lista/cadastro (7.6):", 
                    value=d76.get("link", ""), 
                    key=f"l_76_txt_{ano_sel}", 
                    on_change=cb_text_76, 
                    height=135
                )
                placeholder_links_76 = st.empty()
                links_76_visuais = [u[0] for u in re.findall(regex_pure_url, link_76 or "")]
                if links_76_visuais:
                    placeholder_links_76.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_76_visuais]))

            pts_atuais_76 = d76.get("pontos", 0.0)
            cor_txt_76 = "#28a745" if pts_atuais_76 > 0.0 else ("#dc3545" if v_salvo_76 == "Não (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_76}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.6: +{pts_atuais_76:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("7.6", res_data, ano_sel)

    # GATILHO DO MODAL 7.6
    if st.session_state.get(f"gatilho_modal_7_6_{ano_sel}", False):
        modal_aviso_link("7.6", st.session_state.get(f"links_pendentes_7_6_{ano_sel}", []))
        st.session_state[f"gatilho_modal_7_6_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 7.7 • DATA DA ÚLTIMA ATUALIZAÇÃO DO PLANCON (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_7_7_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 7.7 - Data da Última Atualização do PLANCON", expanded=True):
            st.subheader("7.7 • Vigência do PLANCON")
            st.write("**Qual a data da última atualização do PLANCON?**")
            st.caption("ℹ *Se não houve atualização, informar a data do início da vigência.*")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado.*")
            
            # Recupera o estado salvo no dicionário de dados históricos
            d77 = res_data.get("7.7", {"valor": "", "pontos": 0.0, "link": ""})
            if d77 is None: d77 = {"valor": "", "pontos": 0.0, "link": ""}
            
            valor_salvo_77 = d77.get("valor", "")
            chave_texto_77 = f"q77_date_txt_{ano_sel}"

            def cb_text_77():
                dat_val = st.session_state[chave_texto_77]
                pts = 0.0  # Quesito cronológico / informativo
                lnk = d77.get("link", "")
                
                save_resp("7.7", dat_val, pts, lnk)
                res_data["7.7"] = {"valor": dat_val, "pontos": pts, "link": lnk}

            col_r77, col_j77 = st.columns([1, 1])
            with col_r77:
                st.text_input(
                    "Data de Atualização/Vigência (DD/MM/AAAA):",
                    value=valor_salvo_77,
                    key=chave_texto_77,
                    placeholder="Ex: 15/05/2024",
                    on_change=cb_text_77
                )
                
            with col_j77:
                # Espaçamento estético para alinhamento horizontal com a coluna de entrada
                st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
                if valor_salvo_77:
                    st.info(f"📅 Data registrada para análise técnica: **{valor_salvo_77}**")
                else:
                    st.warning("⚠️ Nenhuma data preenchida ainda.")

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.7: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("7.7", res_data, ano_sel)


    # =============================================================================
    # QUESITO 8.0 • CANAL DE ATENDIMENTO DE EMERGÊNCIA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_8_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 8.0 - Canal de Atendimento de Emergência", expanded=True):
            st.subheader("8.0 • Canal de Emergência")
            st.write("**O Município possui um canal de atendimento de emergência à população para registro de ocorrências de desastres?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações
            opcoes_80 = {
                "Selecione...": 0.0,
                "Sim (50 pts)": 50.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d80 = res_data.get("8.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d80 is None: d80 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_80 = d80.get("valor", "Selecione...")
            chave_radio_80 = f"r_80_{v_salvo_80}_{ano_sel}"

            def cb_radio_80():
                val = st.session_state[chave_radio_80]
                pts = opcoes_80.get(val, 0.0)
                lnk = st.session_state.get(f"l_80_txt_{ano_sel}", d80.get("link", ""))
                
                save_resp("8.0", val, pts, lnk)
                res_data["8.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_80():
                lnk = st.session_state[f"l_80_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_80, v_salvo_80)
                pts = opcoes_80.get(val, 0.0)
                
                save_resp("8.0", val, pts, lnk)
                res_data["8.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d80.get("link", "") or "")]
                
                if lnk != d80.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

            col_r80, col_j80 = st.columns([1, 1])
            with col_r80:
                lista_opcoes_80 = list(opcoes_80.keys())
                idx_80 = lista_opcoes_80.index(v_salvo_80) if v_salvo_80 in lista_opcoes_80 else 0
                
                st.radio(
                    "Possui canal de emergência?",
                    options=lista_opcoes_80,
                    index=idx_80,
                    key=chave_radio_80,
                    on_change=cb_radio_80,
                    label_visibility="collapsed"
                )
                
            with col_j80:
                link_80 = st.text_area(
                    "Descrição/Evidência do Canal (8.0):", 
                    value=d80.get("link", ""), 
                    key=f"l_80_txt_{ano_sel}", 
                    on_change=cb_text_80, 
                    placeholder="Ex: Telefone 199, WhatsApp oficial, Site de chamados...",
                    height=100
                )
                placeholder_links_80 = st.empty()
                links_80_visuais = [u[0] for u in re.findall(regex_pure_url, link_80 or "")]
                if links_80_visuais:
                    placeholder_links_80.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_80_visuais]))

            pts_atuais_80 = d80.get("pontos", 0.0)
            cor_txt_80 = "#28a745" if pts_atuais_80 == 50.0 else ("#dc3545" if v_salvo_80 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_80}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.0: {pts_atuais_80:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("8.0", res_data, ano_sel)

    # GATILHO DO MODAL 8.0
    if st.session_state.get(f"gatilho_modal_8_0_{ano_sel}", False):
        modal_aviso_link("8.0", st.session_state.get(f"links_pendentes_8_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = False

# =============================================================================
    # QUESITO 8.1 • CANAIS DE ATENDIMENTO DISPONÍVEIS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_8_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 8.1 - Canais de Comunicação Disponíveis", expanded=True):
            st.subheader("8.1 • Detalhamento dos Canais")
            st.write("**Assinale os canais que o município possui:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            d81 = res_data.get("8.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d81 is None: d81 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            valor_salvo_81 = d81.get("valor", "[]")
            
            canais = [
                "Telefone de emergências", "Aplicativo de mensagens",
                "Correio eletrônico (e-mail)", "Aplicativo da Prefeitura",
                "Site da Prefeitura", "Redes sociais", "Outros"
            ]

            def cb_checkbox_81():
                sel_81 = []
                for c in canais:
                    c_key = c.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").lower()
                    if st.session_state.get(f"chk81_{c_key}_{ano_sel}", False):
                        sel_81.append(c)
                
                pts = 0.0
                lnk = st.session_state.get(f"l_81_txt_{ano_sel}", d81.get("link", ""))
                val_str = str(sel_81)
                
                save_resp("8.1", val_str, pts, lnk)
                res_data["8.1"] = {"valor": val_str, "pontos": pts, "link": lnk}

            def cb_text_81():
                lnk = st.session_state[f"l_81_txt_{ano_sel}"]
                sel_81 = []
                for c in canais:
                    c_key = c.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").lower()
                    if st.session_state.get(f"chk81_{c_key}_{ano_sel}", c in valor_salvo_81):
                        sel_81.append(c)
                        
                val_str = str(sel_81)
                save_resp("8.1", val_str, 0.0, lnk)
                res_data["8.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d81.get("link", "") or "")]
                
                if lnk != d81.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

            col_c81, col_j81 = st.columns([1, 1])
            with col_c81:
                for c in canais:
                    c_key = c.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").lower()
                    st.checkbox(
                        c,
                        value=c in valor_salvo_81,
                        key=f"chk81_{c_key}_{ano_sel}",
                        on_change=cb_checkbox_81
                    )
                
            with col_j81:
                link_81 = st.text_area(
                    "Links/Números dos canais (8.1):", 
                    value=d81.get("link", ""), 
                    key=f"l_81_txt_{ano_sel}", 
                    on_change=cb_text_81, 
                    height=200
                )
                placeholder_links_81 = st.empty()
                links_81_visuais = [u[0] for u in re.findall(regex_pure_url, link_81 or "")]
                if links_81_visuais:
                    placeholder_links_81.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_81_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("8.1", res_data, ano_sel)

    if st.session_state.get(f"gatilho_modal_8_1_{ano_sel}", False):
        modal_aviso_link("8.1", st.session_state.get(f"links_pendentes_8_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 8.1.1 • UTILIZAÇÃO DO NÚMERO 199 (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_8_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 8.1.1 - Utilização do Número Nacional 199", expanded=True):
            st.subheader("8.1.1 • Linha Telefônica 199")
            st.write("**Sobre o número de telefone de emergência, utiliza o número 199 da Defesa Civil?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_811 = ["Selecione...", "Sim", "Não"]
            
            d811 = res_data.get("8.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d811 is None: d811 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_811 = d811.get("valor", "Selecione...")
            chave_radio_811 = f"r_811_{v_salvo_811}_{ano_sel}"

            def cb_radio_811():
                val = st.session_state[chave_radio_811]
                lnk = st.session_state.get(f"l_811_txt_{ano_sel}", d811.get("link", ""))
                save_resp("8.1.1", val, 0.0, lnk)
                res_data["8.1.1"] = {"valor": val, "pontos": 0.0, "link": lnk}

            def cb_text_811():
                lnk = st.session_state[f"l_811_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_811, v_salvo_811)
                
                save_resp("8.1.1", val, 0.0, lnk)
                res_data["8.1.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d811.get("link", "") or "")]
                
                if lnk != d811.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_1_1_{ano_sel}"] = True

            col_r811, col_j811 = st.columns([1, 1])
            with col_r811:
                idx_811 = opcoes_811.index(v_salvo_811) if v_salvo_811 in opcoes_811 else 0
                st.radio(
                    "Utiliza o 199?",
                    options=opcoes_811,
                    index=idx_811,
                    key=chave_radio_811,
                    on_change=cb_radio_811,
                    label_visibility="collapsed"
                )
                st.markdown("<div style='padding-top: 5px;'></div>", unsafe_allow_html=True)
                if v_salvo_811 == "Sim":
                    st.success("📞 Numeração padrão unificada ativa (199).")
                elif v_salvo_811 == "Não":
                    st.warning("⚠️ Adota canais locais alternativos.")

            with col_j811:
                link_811 = st.text_area(
                    "Evidência de Ativação do 199 (8.1.1):", 
                    value=d811.get("link", ""), 
                    key=f"l_811_txt_{ano_sel}", 
                    on_change=cb_text_811, 
                    placeholder="Ex: Decreto de criação, conta telefônica, print do painel...",
                    height=100
                )
                placeholder_links_811 = st.empty()
                links_811_visuais = [u[0] for u in re.findall(regex_pure_url, link_811 or "")]
                if links_811_visuais:
                    placeholder_links_811.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_811_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.1.1: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("8.1.1", res_data, ano_sel)

    if st.session_state.get(f"gatilho_modal_8_1_1_{ano_sel}", False):
        modal_aviso_link("8.1.1", st.session_state.get(f"links_pendentes_8_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_8_1_1_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 8.1.1.1 • DISPONIBILIDADE 24 HORAS DO 199 (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_8_1_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 8.1.1.1 - Atendimento Continuado 24 Horas", expanded=True):
            st.subheader("8.1.1.1 • Regime de Operação (24h)")
            st.write("**O telefone 199 tem atendimento 24 horas por dia?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_8111 = {
                "Selecione...": 0.0,
                "Sim (20 pts)": 20.0,
                "Não (00 pts)": 0.0
            }
            
            d8111 = res_data.get("8.1.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d8111 is None: d8111 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_8111 = d8111.get("valor", "Selecione...")
            chave_radio_8111 = f"r_8111_{v_salvo_8111}_{ano_sel}"

            def cb_radio_8111():
                val = st.session_state[chave_radio_8111]
                pts = opcoes_8111.get(val, 0.0)
                lnk = st.session_state.get(f"l_8111_txt_{ano_sel}", d8111.get("link", ""))
                save_resp("8.1.1.1", val, pts, lnk)
                res_data["8.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_8111():
                lnk = st.session_state[f"l_8111_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_8111, v_salvo_8111)
                pts = opcoes_8111.get(val, 0.0)
                
                save_resp("8.1.1.1", val, pts, lnk)
                res_data["8.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d8111.get("link", "") or "")]
                
                if lnk != d8111.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_1_1_1_{ano_sel}"] = True

            col_r8111, col_j8111 = st.columns([1, 1])
            with col_r8111:
                lista_opcoes_8111 = list(opcoes_8111.keys())
                idx_8111 = lista_opcoes_8111.index(v_salvo_8111) if v_salvo_8111 in lista_opcoes_8111 else 0
                st.radio(
                    "Atendimento 24h?",
                    options=lista_opcoes_8111,
                    index=idx_8111,
                    key=chave_radio_8111,
                    on_change=cb_radio_8111,
                    label_visibility="collapsed"
                )
            with col_j8111:
                link_8111 = st.text_area(
                    "Evidência do Regime de Escala/Plantonistas (8.1.1.1):", 
                    value=d8111.get("link", ""), 
                    key=f"l_8111_txt_{ano_sel}", 
                    on_change=cb_text_8111, 
                    placeholder="Ex: Escala de servidores, link do diário oficial...",
                    height=100
                )
                placeholder_links_8111 = st.empty()
                links_8111_visuais = [u[0] for u in re.findall(regex_pure_url, link_8111 or "")]
                if links_8111_visuais:
                    placeholder_links_8111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_8111_visuais]))

            pts_atuais_8111 = d8111.get("pontos", 0.0)
            cor_txt_8111 = "#28a745" if pts_atuais_8111 == 20.0 else ("#dc3545" if v_salvo_8111 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_8111}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.1.1.1: {pts_atuais_8111:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("8.1.1.1", res_data, ano_sel)

    if st.session_state.get(f"gatilho_modal_8_1_1_1_{ano_sel}", False):
        modal_aviso_link("8.1.1.1", st.session_state.get(f"links_pendentes_8_1_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_8_1_1_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 8.2 • REGISTRO ELETRÔNICO DE OCORRÊNCIAS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_8_2_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 8.2 - Registro Eletrônico de Ocorrências", expanded=True):
            st.subheader("8.2 • Registro Eletrônico")
            st.write("**O Município registra as ocorrências de Defesa Civil de forma eletrônica?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações
            opcoes_82 = {
                "Selecione...": 0.0,
                "Sim (50 pts)": 50.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d82 = res_data.get("8.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d82 is None: d82 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_82 = d82.get("valor", "Selecione...")
            chave_radio_82 = f"r_82_{v_salvo_82}_{ano_sel}"

            def cb_radio_82():
                val = st.session_state[chave_radio_82]
                pts = opcoes_82.get(val, 0.0)
                lnk = st.session_state.get(f"l_82_txt_{ano_sel}", d82.get("link", ""))
                
                save_resp("8.2", val, pts, lnk)
                res_data["8.2"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_82():
                lnk = st.session_state[f"l_82_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_82, v_salvo_82)
                pts = opcoes_82.get(val, 0.0)
                
                save_resp("8.2", val, pts, lnk)
                res_data["8.2"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d82.get("link", "") or "")]
                
                if lnk != d82.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

            col_r82, col_j82 = st.columns([1, 1])
            with col_r82:
                lista_opcoes_82 = list(opcoes_82.keys())
                idx_82 = lista_opcoes_82.index(v_salvo_82) if v_salvo_82 in lista_opcoes_82 else 0
                
                st.radio(
                    "Registro eletrônico?",
                    options=lista_opcoes_82,
                    index=idx_82,
                    key=chave_radio_82,
                    on_change=cb_radio_82,
                    label_visibility="collapsed"
                )
                
            with col_j82:
                link_82 = st.text_area(
                    "Evidência do Sistema (8.2):", 
                    value=d82.get("link", ""), 
                    key=f"l_82_txt_{ano_sel}", 
                    on_change=cb_text_82, 
                    placeholder="Ex: Link do sistema informatizado, prints das telas de cadastro, decreto de adoção...",
                    height=100
                )
                placeholder_links_82 = st.empty()
                links_82_visuais = [u[0] for u in re.findall(regex_pure_url, link_82 or "")]
                if links_82_visuais:
                    placeholder_links_82.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_82_visuais]))

            pts_atuais_82 = d82.get("pontos", 0.0)
            cor_txt_82 = "#28a745" if pts_atuais_82 == 50.0 else ("#dc3545" if v_salvo_82 != "Selecione..." else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_82}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.2: {pts_atuais_82:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("8.2", res_data, ano_sel)

    # GATILHO DO MODAL 8.2
    if st.session_state.get(f"gatilho_modal_8_2_{ano_sel}", False):
        modal_aviso_link("8.2", st.session_state.get(f"links_pendentes_8_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 9.0 • AVALIAÇÃO ESTRUTURAL DE ESCOLAS E SAÚDE (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_9_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 9.0 - Estudo de Estrutura de Escolas e Unidades de Saúde", expanded=True):
            st.subheader("9.0 • Escolas e Saúde")
            st.write("**O Município realizou um estudo de avaliação da estrutura de todas as escolas e unidades de saúde para garantir que, em caso de desastre, esses locais estejam preparados para abrigar e atender a população afetada?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações progressivas
            opcoes_90 = {
                "Selecione...": 0.0,
                "Sim, em todas as escolas e centros de saúde (100 pts)": 100.0,
                "Sim, na maior parte das escolas e centros de saúde (50 pts)": 50.0,
                "Sim, na menor parte das escolas e centros de saúde (20 pts)": 20.0,
                "Não (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d90 = res_data.get("9.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d90 is None: d90 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_90 = d90.get("valor", "Selecione...")
            chave_radio_90 = f"r_90_{v_salvo_90}_{ano_sel}"

            def cb_radio_90():
                val = st.session_state[chave_radio_90]
                pts = opcoes_90.get(val, 0.0)
                lnk = st.session_state.get(f"l_90_txt_{ano_sel}", d90.get("link", ""))
                
                save_resp("9.0", val, pts, lnk)
                res_data["9.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_90():
                lnk = st.session_state[f"l_90_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_90, v_salvo_90)
                pts = opcoes_90.get(val, 0.0)
                
                save_resp("9.0", val, pts, lnk)
                res_data["9.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d90.get("link", "") or "")]
                
                if lnk != d90.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

            col_r90, col_j90 = st.columns([1, 1])
            with col_r90:
                lista_opcoes_90 = list(opcoes_90.keys())
                idx_90 = lista_opcoes_90.index(v_salvo_90) if v_salvo_90 in lista_opcoes_90 else 0
                
                st.radio(
                    "Abrangência:",
                    options=lista_opcoes_90,
                    index=idx_90,
                    key=chave_radio_90,
                    on_change=cb_radio_90,
                    label_visibility="collapsed"
                )
                
            with col_j90:
                link_90 = st.text_area(
                    "Link do Estudo / Relatório (9.0):", 
                    value=d90.get("link", ""), 
                    key=f"l_90_txt_{ano_sel}", 
                    on_change=cb_text_90, 
                    placeholder="Ex: https://sistema.defesacivil.gov.br/relatorios/estudo-estrutural.pdf",
                    height=120
                )
                placeholder_links_90 = st.empty()
                links_90_visuais = [u[0] for u in re.findall(regex_pure_url, link_90 or "")]
                if links_90_visuais:
                    placeholder_links_90.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_90_visuais]))

            pts_atuais_90 = d90.get("pontos", 0.0)
            cor_txt_90 = "#28a745" if pts_atuais_90 > 0.0 else ("#dc3545" if v_salvo_90 == "Não (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_90}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 9.0: +{pts_atuais_90:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("9.0", res_data, ano_sel)

    # GATILHO DO MODAL 9.0
    if st.session_state.get(f"gatilho_modal_9_0_{ano_sel}", False):
        modal_aviso_link("9.0", st.session_state.get(f"links_pendentes_9_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = False

   # =============================================================================
    # QUESITO 10.0 • PLANO DE MOBILIDADE URBANA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_10_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 10.0 - Plano de Mobilidade Urbana", expanded=True):
            st.subheader("10.0 • Mobilidade Urbana")
            st.write("**O Município elaborou seu Plano de Mobilidade Urbana?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Mapeamento oficial de opções e pontuações (com penalização)
            opcoes_100 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-100 pts)": -100.0,
                "Não se aplica (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d100 = res_data.get("10.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d100 is None: d100 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_100 = d100.get("valor", "Selecione...")
            chave_radio_100 = f"r_100_{v_salvo_100}_{ano_sel}"

            def cb_radio_100():
                val = st.session_state[chave_radio_100]
                pts = opcoes_100.get(val, 0.0)
                lnk = st.session_state.get(f"l_100_txt_{ano_sel}", d100.get("link", ""))
                
                save_resp("10.0", val, pts, lnk)
                res_data["10.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_100():
                lnk = st.session_state[f"l_100_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_100, v_salvo_100)
                pts = opcoes_100.get(val, 0.0)
                
                save_resp("10.0", val, pts, lnk)
                res_data["10.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d100.get("link", "") or "")]
                
                if lnk != d100.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

            col_r100, col_j100 = st.columns([1, 1])
            with col_r100:
                lista_opcoes_100 = list(opcoes_100.keys())
                idx_100 = lista_opcoes_100.index(v_salvo_100) if v_salvo_100 in lista_opcoes_100 else 0
                
                st.radio(
                    "Status Plano de Mobilidade:",
                    options=lista_opcoes_100,
                    index=idx_100,
                    key=chave_radio_100,
                    on_change=cb_radio_100,
                    label_visibility="collapsed"
                )
                
            with col_j100:
                link_100 = st.text_area(
                    "Evidência (10.0):", 
                    value=d100.get("link", ""), 
                    key=f"l_100_txt_{ano_sel}", 
                    on_change=cb_text_100, 
                    placeholder="Ex: Link do plano publicado, lei municipal ou justificativa legal de não aplicabilidade...",
                    height=120
                )
                placeholder_links_100 = st.empty()
                links_100_visuais = [u[0] for u in re.findall(regex_pure_url, link_100 or "")]
                if links_100_visuais:
                    placeholder_links_100.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_100_visuais]))

            pts_atuais_100 = d100.get("pontos", 0.0)
            if pts_atuais_100 < 0.0:
                cor_txt_100 = "#dc3545"  # Vermelho para penalização (-100)
            elif v_salvo_100 in ["Sim (00 pts)", "Não se aplica (00 pts)"]:
                cor_txt_100 = "#28a745"  # Verde para neutro/regularizado
            else:
                cor_txt_100 = "#6c757d"  # Cinza para não selecionado

            st.markdown(f"<span style='color:{cor_txt_100}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 10.0: {pts_atuais_100:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("10.0", res_data, ano_sel)

    # GATILHO DO MODAL 10.0
    if st.session_state.get(f"gatilho_modal_10_0_{ano_sel}", False):
        modal_aviso_link("10.0", st.session_state.get(f"links_pendentes_10_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 11.0 • TRANSPORTE PÚBLICO COLETIVO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_11_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.0 - Existência de Transporte Público Coletivo", expanded=True):
            st.subheader("11.0 • Transporte Coletivo")
            st.write("**No Município existe transporte público coletivo?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_110 = ["Selecione...", "Sim", "Não"]
            
            # Recupera o estado salvo no dicionário de dados históricos
            d110 = res_data.get("11.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d110 is None: d110 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_110 = d110.get("valor", "Selecione...")
            chave_radio_110 = f"r_110_{v_salvo_110}_{ano_sel}"

            def cb_radio_110():
                val = st.session_state[chave_radio_110]
                pts = 0.0  # Quesito de diagnóstico inicial (0.0 pontos)
                lnk = st.session_state.get(f"l_110_txt_{ano_sel}", d110.get("link", ""))
                
                save_resp("11.0", val, pts, lnk)
                res_data["11.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_110():
                lnk = st.session_state[f"l_110_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_110, v_salvo_110)
                
                save_resp("11.0", val, 0.0, lnk)
                res_data["11.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d110.get("link", "") or "")]
                
                if lnk != d110.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

            col_r110, col_j110 = st.columns([1, 1])
            with col_r110:
                idx_110 = opcoes_110.index(v_salvo_110) if v_salvo_110 in opcoes_110 else 0
                
                st.radio(
                    "Transporte Coletivo:",
                    options=opcoes_110,
                    index=idx_110,
                    key=chave_radio_110,
                    on_change=cb_radio_110,
                    label_visibility="collapsed"
                )
                
                st.markdown("<div style='padding-top: 5px;'></div>", unsafe_allow_html=True)
                if v_salvo_110 == "Sim":
                    st.success("🚌 Município possui sistema de transporte público estruturado.")
                elif v_salvo_110 == "Não":
                    st.info("ℹ️ Não há linhas de transporte público coletivo operando na localidade.")
                
            with col_j110:
                link_110 = st.text_area(
                    "Justificativa / Detalhes (11.0):", 
                    value=d110.get("link", ""), 
                    key=f"l_110_txt_{ano_sel}", 
                    on_change=cb_text_110, 
                    placeholder="Ex: Contrato de concessão, linhas existentes ou link para rotas municipais...",
                    height=110
                )
                placeholder_links_110 = st.empty()
                links_110_visuais = [u[0] for u in re.findall(regex_pure_url, link_110 or "")]
                if links_110_visuais:
                    placeholder_links_110.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_110_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.0: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("11.0", res_data, ano_sel)

    # GATILHO DO MODAL 11.0
    if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
        modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = False

   # =============================================================================
    # QUESITO 11.1 • METAS DE QUALIDADE E DESEMPENHO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_11_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.1 - Metas de Qualidade e Desempenho", expanded=True):
            st.subheader("11.1 • Estabelecimento de Metas")
            st.write("**Foram estabelecidas metas de qualidade e desempenho para o transporte público coletivo municipal?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opts111 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-20 pts)": -20.0
            }
            
            d111 = res_data.get("11.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d111 is None: d111 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_111 = d111.get("valor", "Selecione...")
            chave_radio_111 = f"r_111_{v_salvo_111}_{ano_sel}"

            def cb_radio_111():
                val = st.session_state[chave_radio_111]
                pts = opts111.get(val, 0.0)
                lnk = st.session_state.get(f"l_111_txt_{ano_sel}", d111.get("link", ""))
                
                save_resp("11.1", val, pts, lnk)
                res_data["11.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_111():
                lnk = st.session_state[f"l_111_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_111, v_salvo_111)
                pts = opts111.get(val, 0.0)
                
                save_resp("11.1", val, pts, lnk)
                res_data["11.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d111.get("link", "") or "")]
                
                if lnk != d111.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = True

            col_r111, col_j111 = st.columns([1, 1])
            with col_r111:
                lista_opcoes_111 = list(opts111.keys())
                idx_111 = lista_opcoes_111.index(v_salvo_111) if v_salvo_111 in lista_opcoes_111 else 0
                
                st.radio(
                    "Metas estabelecidas:",
                    options=lista_opcoes_111,
                    index=idx_111,
                    key=chave_radio_111,
                    on_change=cb_radio_111,
                    label_visibility="collapsed"
                )
                
            with col_j111:
                link_111 = st.text_area(
                    "Evidência (11.1):", 
                    value=d111.get("link", ""), 
                    key=f"l_111_txt_{ano_sel}", 
                    on_change=cb_text_111, 
                    placeholder="Ex: Resolução municipal, anexo contratual com metas descritas...",
                    height=110
                )
                placeholder_links_111 = st.empty()
                links_111_visuais = [u[0] for u in re.findall(regex_pure_url, link_111 or "")]
                if links_111_visuais:
                    placeholder_links_111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_111_visuais]))

            pts_atuais_111 = d111.get("pontos", 0.0)
            cor_txt_111 = "#dc3545" if pts_atuais_111 < 0.0 else ("#28a745" if v_salvo_111 == "Sim (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_111}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.1: {pts_atuais_111:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("11.1", res_data, ano_sel)

    if st.session_state.get(f"gatilho_modal_11_1_{ano_sel}", False):
        modal_aviso_link("11.1", st.session_state.get(f"links_pendentes_11_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 11.1.1 • ATENDIMENTO DAS METAS (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_11_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.1.1 - Atingimento de Metas de Desempenho", expanded=True):
            st.subheader("11.1.1 • Cumprimento do Plano de Metas")
            st.write("**As metas de qualidade e desempenho estão sendo atingidas?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opts1111 = {
                "Selecione...": 0.0,
                "Todas as metas foram atingidas (00 pts)": 0.0,
                "A maior parte das metas foram atingidas (-05 pts)": -5.0,
                "A menor parte das metas foram atingidas (-10 pts)": -10.0,
                "As metas não foram atingidas (-20 pts)": -20.0
            }
            
            d1111 = res_data.get("11.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d1111 is None: d1111 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_1111 = d1111.get("valor", "Selecione...")
            chave_radio_1111 = f"r_1111_{v_salvo_1111}_{ano_sel}"

            def cb_radio_1111():
                val = st.session_state[chave_radio_1111]
                pts = opts1111.get(val, 0.0)
                lnk = st.session_state.get(f"l_1111_txt_{ano_sel}", d1111.get("link", ""))
                
                save_resp("11.1.1", val, pts, lnk)
                res_data["11.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_1111():
                lnk = st.session_state[f"l_1111_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_1111, v_salvo_1111)
                pts = opts1111.get(val, 0.0)
                
                save_resp("11.1.1", val, pts, lnk)
                res_data["11.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1111.get("link", "") or "")]
                
                if lnk != d1111.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_1_1_{ano_sel}"] = True

            col_r1111, col_j1111 = st.columns([1, 1])
            with col_r1111:
                lista_opcoes_1111 = list(opts1111.keys())
                idx_1111 = lista_opcoes_1111.index(v_salvo_1111) if v_salvo_1111 in lista_opcoes_1111 else 0
                
                st.radio(
                    "Cumprimento das metas:",
                    options=lista_opcoes_1111,
                    index=idx_1111,
                    key=chave_radio_1111,
                    on_change=cb_radio_1111,
                    label_visibility="collapsed"
                )
                
            with col_j1111:
                link_1111 = st.text_area(
                    "Relatório de Desempenho (11.1.1):", 
                    value=d1111.get("link", ""), 
                    key=f"l_1111_txt_{ano_sel}", 
                    on_change=cb_text_1111, 
                    placeholder="Ex: Link de relatórios quadrimestrais, auditorias de transporte...",
                    height=140
                )
                placeholder_links_1111 = st.empty()
                links_1111_visuais = [u[0] for u in re.findall(regex_pure_url, link_1111 or "")]
                if links_1111_visuais:
                    placeholder_links_1111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1111_visuais]))

            pts_atuais_1111 = d1111.get("pontos", 0.0)
            cor_txt_1111 = "#dc3545" if pts_atuais_1111 < 0.0 else ("#28a745" if v_salvo_1111 == "Todas as metas foram atingidas (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_1111}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.1.1: {pts_atuais_1111:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("11.1.1", res_data, ano_sel)

    if st.session_state.get(f"gatilho_modal_11_1_1_{ano_sel}", False):
        modal_aviso_link("11.1.1", st.session_state.get(f"links_pendentes_11_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_1_1_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 11.1.1.1 • APLICAÇÃO DE PENALIDADES (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_11_1_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.1.1.1 - Aplicação de Sanções Administrativas", expanded=True):
            st.subheader("11.1.1.1 • Penalidades")
            st.write("**Foi aplicada penalidade pela meta não cumprida?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_11111 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-50 pts)": -50.0
            }
            
            d11111 = res_data.get("11.1.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d11111 is None: d11111 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_11111 = d11111.get("valor", "Selecione...")
            chave_radio_11111 = f"r_11111_{v_salvo_11111}_{ano_sel}"

            def cb_radio_11111():
                val = st.session_state[chave_radio_11111]
                pts = opcoes_11111.get(val, 0.0)
                lnk = st.session_state.get(f"l_11111_txt_{ano_sel}", d11111.get("link", ""))
                
                save_resp("11.1.1.1", val, pts, lnk)
                res_data["11.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_11111():
                lnk = st.session_state[f"l_11111_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_11111, v_salvo_11111)
                pts = opcoes_11111.get(val, 0.0)
                
                save_resp("11.1.1.1", val, pts, lnk)
                res_data["11.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d11111.get("link", "") or "")]
                
                if lnk != d11111.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_1_1_1_{ano_sel}"] = True

            col_r11111, col_j11111 = st.columns([1, 1])
            with col_r11111:
                lista_opcoes_11111 = list(opcoes_11111.keys())
                idx_11111 = lista_opcoes_11111.index(v_salvo_11111) if v_salvo_11111 in lista_opcoes_11111 else 0
                
                st.radio(
                    "Aplicação de penalidade:",
                    options=lista_opcoes_11111,
                    index=idx_11111,
                    key=chave_radio_11111,
                    on_change=cb_radio_11111,
                    label_visibility="collapsed"
                )
                
            with col_j11111:
                l11111 = st.text_area(
                    "Auto de Infração (11.1.1.1):", 
                    value=d11111.get("link", ""), 
                    key=f"l_11111_txt_{ano_sel}", 
                    on_change=cb_text_11111, 
                    placeholder="Ex: Link de publicação do diário oficial de multas aplicadas, rescisões...",
                    height=110
                )
                placeholder_links_11111 = st.empty()
                links_11111_atuais = [u[0] for u in re.findall(regex_pure_url, l11111 or "")]
                if links_11111_atuais:
                    placeholder_links_11111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_11111_atuais]))

            pts_atuais_11111 = d11111.get("pontos", 0.0)
            cor_txt_11111 = "#dc3545" if pts_atuais_11111 < 0.0 else ("#28a745" if v_salvo_11111 == "Sim (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_11111}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.1.1.1: {pts_atuais_11111:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("11.1.1.1", res_data, ano_sel)

    if st.session_state.get(f"gatilho_modal_11_1_1_1_{ano_sel}", False):
        modal_aviso_link("11.1.1.1", st.session_state.get(f"links_pendentes_11_1_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_1_1_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 11.2 • PESQUISA DE SATISFAÇÃO DO USUÁRIO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_11_2_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.2 - Pesquisa de Satisfação dos Usuários", expanded=True):
            st.subheader("11.2 • Pesquisa de Satisfação")
            
            # Pega apenas os números do ano (desenraiza textos complexos como "2026 - IEGM")
            ano_puro = "".join([c for c in str(ano_sel) if c.isdigit()])[:4]
            ano_anterior = int(ano_puro) - 1 if ano_puro.isdigit() else "anterior"
            
            st.write(f"**Foi realizada pesquisa de satisfação dos usuários em {ano_anterior}?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_112 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-20 pts)": -20.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d112 = res_data.get("11.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d112 is None: d112 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_112 = d112.get("valor", "Selecione...")
            chave_radio_112 = f"r_112_{v_salvo_112}_{ano_sel}"

            def cb_radio_112():
                val = st.session_state[chave_radio_112]
                pts = opcoes_112.get(val, 0.0)
                lnk = st.session_state.get(f"l_112_txt_{ano_sel}", d112.get("link", ""))
                
                save_resp("11.2", val, pts, lnk)
                res_data["11.2"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_112():
                lnk = st.session_state[f"l_112_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_112, v_salvo_112)
                pts = opcoes_112.get(val, 0.0)
                
                save_resp("11.2", val, pts, lnk)
                res_data["11.2"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d112.get("link", "") or "")]
                
                if lnk != d112.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_2_{ano_sel}"] = True

            col_r112, col_j112 = st.columns([1, 1])
            with col_r112:
                lista_opcoes_112 = list(opcoes_112.keys())
                idx_112 = lista_opcoes_112.index(v_salvo_112) if v_salvo_112 in lista_opcoes_112 else 0
                
                st.radio(
                    "Realizou pesquisa?",
                    options=lista_opcoes_112,
                    index=idx_112,
                    key=chave_radio_112,
                    on_change=cb_radio_112,
                    label_visibility="collapsed"
                )
                
            with col_j112:
                link_112 = st.text_area(
                    f"Resultado da Pesquisa {ano_anterior} (11.2):", 
                    value=d112.get("link", ""), 
                    key=f"l_112_txt_{ano_sel}", 
                    on_change=cb_text_112, 
                    placeholder="Ex: Link dos gráficos de satisfação, relatório consolidado ou formulário aplicado...",
                    height=110
                )
                placeholder_links_112 = st.empty()
                links_112_visuais = [u[0] for u in re.findall(regex_pure_url, link_112 or "")]
                if links_112_visuais:
                    placeholder_links_112.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_112_visuais]))

            pts_atuais_112 = d112.get("pontos", 0.0)
            cor_txt_112 = "#dc3545" if pts_atuais_112 < 0.0 else ("#28a745" if v_salvo_112 == "Sim (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_112}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.2: {pts_atuais_112:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("11.2", res_data, ano_sel)

    # GATILHO DO MODAL 11.2
    if st.session_state.get(f"gatilho_modal_11_2_{ano_sel}", False):
        modal_aviso_link("11.2", st.session_state.get(f"links_pendentes_11_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_2_{ano_sel}"] = False


   # =============================================================================
    # QUESITO 11.2.1 • AÇÕES BASEADAS NA PESQUISA DE SATISFAÇÃO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_11_2_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.2.1 - Ações com Base na Pesquisa de Satisfação", expanded=True):
            st.subheader("11.2.1 • Ações Pós-Pesquisa")
            st.write("**Foram realizadas ações com base nesta pesquisa?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_1121 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-20 pts)": -20.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d1121 = res_data.get("11.2.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d1121 is None: d1121 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_1121 = d1121.get("valor", "Selecione...")
            chave_radio_1121 = f"r_1121_{v_salvo_1121}_{ano_sel}"

            def cb_radio_1121():
                val = st.session_state[chave_radio_1121]
                pts = opcoes_1121.get(val, 0.0)
                lnk = st.session_state.get(f"l_1121_txt_{ano_sel}", d1121.get("link", ""))
                
                save_resp("11.2.1", val, pts, lnk)
                res_data["11.2.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_1121():
                lnk = st.session_state[f"l_1121_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_1121, v_salvo_1121)
                pts = opcoes_1121.get(val, 0.0)
                
                save_resp("11.2.1", val, pts, lnk)
                res_data["11.2.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1121.get("link", "") or "")]
                
                if lnk != d1121.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_2_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_2_1_{ano_sel}"] = True

            col_r1121, col_j1121 = st.columns([1, 1])
            with col_r1121:
                lista_opcoes_1121 = list(opcoes_1121.keys())
                idx_1121 = lista_opcoes_1121.index(v_salvo_1121) if v_salvo_1121 in lista_opcoes_1121 else 0
                
                st.radio(
                    "Ações realizadas?",
                    options=lista_opcoes_1121,
                    index=idx_1121,
                    key=chave_radio_1121,
                    on_change=cb_radio_1121,
                    label_visibility="collapsed"
                )
                
            with col_j1121:
                link_1121 = st.text_area(
                    "Descrição das Ações (11.2.1):", 
                    value=d1121.get("link", ""), 
                    key=f"l_1121_txt_{ano_sel}", 
                    on_change=cb_text_1121, 
                    placeholder="Ex: Link do plano de melhorias, atas de reuniões operacionais, decretos de readequação de rotas...",
                    height=110
                )
                placeholder_links_1121 = st.empty()
                links_1121_visuais = [u[0] for u in re.findall(regex_pure_url, link_1121 or "")]
                if links_1121_visuais:
                    placeholder_links_1121.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1121_visuais]))

            pts_atuais_1121 = d1121.get("pontos", 0.0)
            cor_txt_1121 = "#dc3545" if pts_atuais_1121 < 0.0 else ("#28a745" if v_salvo_1121 == "Sim (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_1121}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.2.1: {pts_atuais_1121:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("11.2.1", res_data, ano_sel)

    # GATILHO DO MODAL 11.2.1
    if st.session_state.get(f"gatilho_modal_11_2_1_{ano_sel}", False):
        modal_aviso_link("11.2.1", st.session_state.get(f"links_pendentes_11_2_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_2_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 11.3 • RESULTADO FINANCEIRO DO TRANSPORTE (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_11_3_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.3 - Resultado Financeiro do Transporte Público", expanded=True):
            st.subheader("11.3 • Resultado Financeiro")
            st.write("**Quanto ao custo do transporte público (tarifa de remuneração da prestação de serviço de transporte público) e o preço de passagem (tarifa pública cobrada do usuário), informe qual o resultado no ano de 2025:**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_113 = {
                "Selecione...": 0.0,
                "Déficit ou subsídio tarifário": 0.0,
                "Superávit tarifário": 0.0,
                "Não sabe informar": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d113 = res_data.get("11.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d113 is None: d113 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_113 = d113.get("valor", "Selecione...")
            chave_radio_113 = f"r_113_{v_salvo_113}_{ano_sel}"

            def cb_radio_113():
                val = st.session_state[chave_radio_113]
                pts = opcoes_113.get(val, 0.0)
                lnk = st.session_state.get(f"l_113_txt_{ano_sel}", d113.get("link", ""))
                
                save_resp("11.3", val, pts, lnk)
                res_data["11.3"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_113():
                lnk = st.session_state[f"l_113_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_113, v_salvo_113)
                pts = opcoes_113.get(val, 0.0)
                
                save_resp("11.3", val, pts, lnk)
                res_data["11.3"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d113.get("link", "") or "")]
                
                if lnk != d113.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_3_{ano_sel}"] = True

            col_r113, col_j113 = st.columns([1, 1])
            with col_r113:
                lista_opcoes_113 = list(opcoes_113.keys())
                idx_113 = lista_opcoes_113.index(v_salvo_113) if v_salvo_113 in lista_opcoes_113 else 0
                
                st.radio(
                    "Resultado:",
                    options=lista_opcoes_113,
                    index=idx_113,
                    key=chave_radio_113,
                    on_change=cb_radio_113,
                    label_visibility="collapsed"
                )
                
            with col_j113:
                link_113 = st.text_area(
                    "Justificativa Financeira (11.3):", 
                    value=d113.get("link", ""), 
                    key=f"l_113_txt_{ano_sel}", 
                    on_change=cb_text_113, 
                    placeholder="Ex: Balanço financeiro do sistema de transporte, dotação orçamentária de subsídios ou ata do conselho municipal...",
                    height=110
                )
                placeholder_links_113 = st.empty()
                links_113_visuais = [u[0] for u in re.findall(regex_pure_url, link_113 or "")]
                if links_113_visuais:
                    placeholder_links_113.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_113_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.3: 0.0 pontos (Diagnóstico Financeiro)</span>", unsafe_allow_html=True)
            bloco_comentarios("11.3", res_data, ano_sel)

    # GATILHO DO MODAL 11.3
    if st.session_state.get(f"gatilho_modal_11_3_{ano_sel}", False):
        modal_aviso_link("11.3", st.session_state.get(f"links_pendentes_11_3_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_3_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 11.3.1 • TRANSPARÊNCIA TARIFÁRIA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_11_3_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 11.3.1 - Transparência dos Benefícios Tarifários", expanded=True):
            st.subheader("11.3.1 • Transparência")
            st.write("**Informe a página eletrônica (link na internet) em que os benefícios tarifários concedidos no valor das tarifas do transporte público foram divulgados: Se não estiver disponível na internet, inserir no campo de resposta o texto XYZ**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            # Recupera o estado salvo no dicionário de dados históricos
            d1131 = res_data.get("11.3.1", {"valor": "Link fornecido", "pontos": 0.0, "link": ""})
            if d1131 is None: d1131 = {"valor": "Link fornecido", "pontos": 0.0, "link": ""}

            def cb_text_1131():
                lnk = st.session_state[f"l_1131_txt_{ano_sel}"]
                val = "Link fornecido"
                
                if lnk and lnk.strip().upper() == "XYZ":
                    val = "Não disponível (XYZ)"
                
                save_resp("11.3.1", val, 0.0, lnk)
                res_data["11.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1131.get("link", "") or "")]
                
                if lnk != d1131.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_3_1_{ano_sel}"] = True

            col_inp1131, col_j1131 = st.columns([1, 1])
            with col_inp1131:
                link_1131 = st.text_input(
                    "Link (Transparência):", 
                    value=d1131.get("link", ""), 
                    key=f"l_1131_txt_{ano_sel}", 
                    on_change=cb_text_1131, 
                    placeholder="Cole a URL oficial do portal de transparência ou digite XYZ..."
                )
                
                placeholder_links_1131 = st.empty()
                links_1131_visuais = [u[0] for u in re.findall(regex_pure_url, link_1131 or "")]
                if links_1131_visuais:
                    placeholder_links_1131.markdown(f"<div style='padding-top: 10px;'>🔗 **Link Ativo:** <a href='{links_1131_visuais[0]}' target='_blank'>{links_1131_visuais[0]}</a></div>", unsafe_allow_html=True)
                elif link_1131 and link_1131.strip().upper() == "XYZ":
                    placeholder_links_1131.markdown("<div style='padding-top: 10px;'>⚠️ *Benefícios não divulgados eletronicamente (Código XYZ registrado).*</div>", unsafe_allow_html=True)
                
            with col_j1131:
                # Campo de justificativa adicionado conforme solicitado
                st.text_area(
                    "Justificativa / Detalhes Adicionais (11.3.1):",
                    value=d1131.get("justificativa", ""),
                    key=f"j_1131_txt_{ano_sel}",
                    placeholder="Espaço para observações internas, motivos da não publicação ou notas sobre os benefícios tarifários...",
                    height=110,
                    on_change=cb_text_1131  # Reutiliza o callback para salvar o estado consolidado
                )

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 11.3.1: 0.0 pontos (Informativo / Transparência)</span>", unsafe_allow_html=True)
            bloco_comentarios("11.3.1", res_data, ano_sel)

    # GATILHO DO MODAL 11.3.1
    if st.session_state.get(f"gatilho_modal_11_3_1_{ano_sel}", False):
        modal_aviso_link("11.3.1", st.session_state.get(f"links_pendentes_11_3_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_11_3_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 12.0 • TRANSPORTE POR APLICATIVO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_12_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 12.0 - Transporte Remunerado Privado Individual (App)", expanded=True):
            st.subheader("12.0 • Transporte por App")
            st.write("**O Município possui transporte remunerado privado individual (App)?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_120 = ["Selecione...", "Sim", "Não"]
            
            # Recupera o estado salvo no dicionário de dados históricos
            d120 = res_data.get("12.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d120 is None: d120 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_120 = d120.get("valor", "Selecione...")
            chave_radio_120 = f"r_120_{v_salvo_120}_{ano_sel}"

            def cb_radio_120():
                val = st.session_state[chave_radio_120]
                pts = 0.0  # Quesito informativo/diagnóstico (0.0 pontos)
                lnk = st.session_state.get(f"l_120_txt_{ano_sel}", d120.get("link", ""))
                
                save_resp("12.0", val, pts, lnk)
                res_data["12.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_120():
                lnk = st.session_state[f"l_120_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_120, v_salvo_120)
                
                save_resp("12.0", val, 0.0, lnk)
                res_data["12.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d120.get("link", "") or "")]
                
                if lnk != d120.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

            col_r120, col_j120 = st.columns([1, 1])
            with col_r120:
                idx_120 = opcoes_120.index(v_salvo_120) if v_salvo_120 in opcoes_120 else 0
                
                st.radio(
                    "Possui transporte por App?",
                    options=opcoes_120,
                    index=idx_120,
                    key=chave_radio_120,
                    on_change=cb_radio_120,
                    label_visibility="collapsed"
                )
                
                st.markdown("<div style='padding-top: 5px;'></div>", unsafe_allow_html=True)
                if v_salvo_120 == "Sim":
                    st.success("📱 Há operação ativa de plataformas de transporte individual privado por aplicativo.")
                elif v_salvo_120 == "Não":
                    st.info("ℹ️ Não há serviços formais de transporte individual por aplicativo operando no território.")
                
            with col_j120:
                link_120 = st.text_area(
                    "Empresas atuantes (12.0):", 
                    value=d120.get("link", ""), 
                    key=f"l_120_txt_{ano_sel}", 
                    on_change=cb_text_120, 
                    placeholder="Ex: Uber, 99, aplicativos locais ou link para a regulamentação do serviço municipal...",
                    height=110
                )
                placeholder_links_120 = st.empty()
                links_120_visuais = [u[0] for u in re.findall(regex_pure_url, link_120 or "")]
                if links_120_visuais:
                    placeholder_links_120.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_120_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 12.0: 0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("12.0", res_data, ano_sel)

    # GATILHO DO MODAL 12.0
    if st.session_state.get(f"gatilho_modal_12_0_{ano_sel}", False):
        modal_aviso_link("12.0", st.session_state.get(f"links_pendentes_12_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 12.1 • REGULAMENTAÇÃO DE APP (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_12_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 12.1 - Regulamentação do Transporte por Aplicativo", expanded=True):
            st.subheader("12.1 • Regulamentação de App")
            st.write("**O Município regulamentou o transporte remunerado privado individual?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opts121 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-50 pts)": -50.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d121 = res_data.get("12.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d121 is None: d121 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_121 = d121.get("valor", "Selecione...")
            chave_radio_121 = f"r_121_{v_salvo_121}_{ano_sel}"

            def cb_radio_121():
                val = st.session_state[chave_radio_121]
                pts = opts121.get(val, 0.0)
                lnk = st.session_state.get(f"l_121_txt_{ano_sel}", d121.get("link", ""))
                
                save_resp("12.1", val, pts, lnk)
                res_data["12.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_121():
                lnk = st.session_state[f"l_121_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_121, v_salvo_121)
                pts = opts121.get(val, 0.0)
                
                save_resp("12.1", val, pts, lnk)
                res_data["12.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d121.get("link", "") or "")]
                
                if lnk != d121.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = True

            col_r121, col_j121 = st.columns([1, 1])
            with col_r121:
                lista_opcoes_121 = list(opts121.keys())
                idx_121 = lista_opcoes_121.index(v_salvo_121) if v_salvo_121 in lista_opcoes_121 else 0
                
                st.radio(
                    "Regulamentado?",
                    options=lista_opcoes_121,
                    index=idx_121,
                    key=chave_radio_121,
                    on_change=cb_radio_121,
                    label_visibility="collapsed"
                )
                
            with col_j121:
                link_121 = st.text_area(
                    "Evidência (Lei/Decreto) (12.1):", 
                    value=d121.get("link", ""), 
                    key=f"l_121_txt_{ano_sel}", 
                    on_change=cb_text_121, 
                    placeholder="Ex: Link da Lei Municipal, Decreto Regulamentador ou publicação no Diário Oficial...",
                    height=110
                )
                placeholder_links_121 = st.empty()
                links_121_visuais = [u[0] for u in re.findall(regex_pure_url, link_121 or "")]
                if links_121_visuais:
                    placeholder_links_121.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_121_visuais]))

            pts_atuais_121 = d121.get("pontos", 0.0)
            cor_txt_121 = "#dc3545" if pts_atuais_121 < 0.0 else ("#28a745" if v_salvo_121 == "Sim (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_121}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 12.1: {pts_atuais_121:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("12.1", res_data, ano_sel)

    # GATILHO DO MODAL 12.1
    if st.session_state.get(f"gatilho_modal_12_1_{ano_sel}", False):
        modal_aviso_link("12.1", st.session_state.get(f"links_pendentes_12_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITOS 12.1.1 e 12.1.2 • DETALHES DA REGULAMENTAÇÃO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_12_1_detalhes_{ano_sel}", border=True):
        with st.expander(f"📌 Quesitos 12.1.1 e 12.1.2 - Dados do Instrumento Normativo", expanded=True):
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado.*")
            
            # Recuperação e sanitização dos estados históricos
            d1211 = res_data.get("12.1.1", {"valor": "", "pontos": 0.0, "link": ""})
            if d1211 is None: d1211 = {"valor": "", "pontos": 0.0, "link": ""}
            
            d1212 = res_data.get("12.1.2", {"valor": "Link fornecido", "pontos": 0.0, "link": ""})
            if d1212 is None: d1212 = {"valor": "Link fornecido", "pontos": 0.0, "link": ""}

            def cb_text_1211():
                val = st.session_state[f"q1211_val_{ano_sel}"]
                save_resp("12.1.1", val, 0.0, "")
                res_data["12.1.1"] = {"valor": val, "pontos": 0.0, "link": ""}

            def cb_text_1212():
                lnk = st.session_state[f"q1212_lnk_{ano_sel}"]
                val = "Link fornecido"
                
                save_resp("12.1.2", val, 0.0, lnk)
                res_data["12.1.2"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1212.get("link", "") or "")]
                
                if lnk != d1212.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = True

            col1, col2 = st.columns([1, 1])
            with col1:
                st.subheader("12.1.1 • Identificação")
                st.write("Informe o Instrumento normativo, Número e Data da publicação:")
                st.text_input(
                    f"Ex: Lei 123 de 01/01/{ano_sel}",
                    value=d1211.get("valor", ""),
                    key=f"q1211_val_{ano_sel}",
                    on_change=cb_text_1211
                )
                bloco_comentarios("12.1.1", res_data, ano_sel)

            with col2:
                st.subheader("12.1.2 • Endereço Eletrônico")
                st.write("Informe a página eletrônica (link na internet) do instrumento:")
                link_1212 = st.text_input(
                    "URL da norma:",
                    value=d1212.get("link", ""),
                    key=f"q1212_lnk_{ano_sel}",
                    on_change=cb_text_1212,
                    placeholder="https://..."
                )
                
                placeholder_links_1212 = st.empty()
                links_1212_visuais = [u[0] for u in re.findall(regex_pure_url, link_1212 or "")]
                if links_1212_visuais:
                    placeholder_links_1212.markdown(f"🔗 **Link Ativo:** [{links_1212_visuais[0]}]({links_1212_visuais[0]})")
                bloco_comentarios("12.1.2", res_data, ano_sel)

    # GATILHO DO MODAL 12.1.2
    if st.session_state.get(f"gatilho_modal_12_1_2_{ano_sel}", False):
        modal_aviso_link("12.1.2", st.session_state.get(f"links_pendentes_12_1_2_{ano_sel}", []))
        st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 12.1.3 • FISCALIZAÇÃO DO SERVIÇO APP (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_12_1_3_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 12.1.3 - Fiscalização Regular do Transporte por Aplicativo", expanded=True):
            st.subheader("12.1.3 • Fiscalização de App")
            st.write("**O Município fiscaliza regularmente o transporte remunerado privado individual de passageiros (táxi por aplicativo)?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_1213 = {
                "Selecione...": 0.0,
                "Sim (00 pts)": 0.0,
                "Não (-50 pts)": -50.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d1213 = res_data.get("12.1.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d1213 is None: d1213 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_1213 = d1213.get("valor", "Selecione...")
            chave_radio_1213 = f"r_1213_{v_salvo_1213}_{ano_sel}"

            def cb_radio_1213():
                val = st.session_state[chave_radio_1213]
                pts = opcoes_1213.get(val, 0.0)
                lnk = st.session_state.get(f"l_1213_txt_{ano_sel}", d1213.get("link", ""))
                
                save_resp("12.1.3", val, pts, lnk)
                res_data["12.1.3"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_1213():
                lnk = st.session_state[f"l_1213_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_1213, v_salvo_1213)
                pts = opcoes_1213.get(val, 0.0)
                
                save_resp("12.1.3", val, pts, lnk)
                res_data["12.1.3"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1213.get("link", "") or "")]
                
                if lnk != d1213.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_3_{ano_sel}"] = True

            col_r1213, col_j1213 = st.columns([1, 1])
            with col_r1213:
                lista_opcoes_1213 = list(opcoes_1213.keys())
                idx_1213 = lista_opcoes_1213.index(v_salvo_1213) if v_salvo_1213 in lista_opcoes_1213 else 0
                
                st.radio(
                    "Fiscaliza?",
                    options=lista_opcoes_1213,
                    index=idx_1213,
                    key=chave_radio_1213,
                    on_change=cb_radio_1213,
                    label_visibility="collapsed"
                )
                
            with col_j1213:
                link_1213 = st.text_area(
                    "Evidência da fiscalização (12.1.3):", 
                    value=d1213.get("link", ""), 
                    key=f"l_1213_txt_{ano_sel}", 
                    on_change=cb_text_1213, 
                    placeholder="Ex: Link de relatórios de blitze operacionais, atas de vistorias ou autos de infração consolidados...",
                    height=110
                )
                placeholder_links_1213 = st.empty()
                links_1213_visuais = [u[0] for u in re.findall(regex_pure_url, link_1213 or "")]
                if links_1213_visuais:
                    placeholder_links_1213.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1213_visuais]))

            pts_atuais_1213 = d1213.get("pontos", 0.0)
            cor_txt_1213 = "#dc3545" if pts_atuais_1213 < 0.0 else ("#28a745" if v_salvo_1213 == "Sim (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_1213}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 12.1.3: {pts_atuais_1213:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("12.1.3", res_data, ano_sel)

    # GATILHO DO MODAL 12.1.3
    if st.session_state.get(f"gatilho_modal_12_1_3_{ano_sel}", False):
        modal_aviso_link("12.1.3", st.session_state.get(f"links_pendentes_12_1_3_{ano_sel}", []))
        st.session_state[f"gatilho_modal_12_1_3_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 12.1.3.1 • PERIODICIDADE DA FISCALIZAÇÃO (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_12_1_3_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 12.1.3.1 - Periodicidade e Evidência das Ações", expanded=True):
            st.subheader("12.1.3.1 • Periodicidade e Evidência")
            st.write("Informe a periodicidade da fiscalização realizada e anexe o comprovante correspondente:")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            perio_opcoes = ["Selecione...", "Diariamente", "Semanalmente", "Mensalmente", "Anualmente"]
            
            # Recupera o estado salvo no dicionário de dados históricos
            d12131 = res_data.get("12.1.3.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d12131 is None: d12131 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_12131 = d12131.get("valor", "Selecione...")
            chave_radio_12131 = f"r_12131_{v_salvo_12131}_{ano_sel}"

            def cb_radio_12131():
                val = st.session_state[chave_radio_12131]
                lnk = st.session_state.get(f"l_12131_txt_{ano_sel}", d12131.get("link", ""))
                
                save_resp("12.1.3.1", val, 0.0, lnk)
                res_data["12.1.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}

            def cb_text_12131():
                lnk = st.session_state[f"l_12131_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_12131, v_salvo_12131)
                
                save_resp("12.1.3.1", val, 0.0, lnk)
                res_data["12.1.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d12131.get("link", "") or "")]
                
                if lnk != d12131.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_3_1_{ano_sel}"] = True

            col_p12131, col_j12131 = st.columns([1, 1])
            with col_p12131:
                idx_p = perio_opcoes.index(v_salvo_12131) if v_salvo_12131 in perio_opcoes else 0
                st.radio(
                    "Periodicidade:", 
                    options=perio_opcoes, 
                    index=idx_p, 
                    key=chave_radio_12131,
                    on_change=cb_radio_12131,
                    label_visibility="collapsed"
                )
                
            with col_j12131:
                link_12131 = st.text_area(
                    "Evidência / Ordem de Serviço (12.1.3.1):", 
                    value=d12131.get("link", ""), 
                    key=f"l_12131_txt_{ano_sel}", 
                    on_change=cb_text_12131, 
                    placeholder="Ex: Link para o cronograma de fiscalização, portaria de designação de fiscais ou escala de plantão...",
                    height=110
                )
                placeholder_links_12131 = st.empty()
                links_12131_visuais = [u[0] for u in re.findall(regex_pure_url, link_12131 or "")]
                if links_12131_visuais:
                    placeholder_links_12131.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_12131_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 12.1.3.1: 0.0 pontos (Informativo de Rotina)</span>", unsafe_allow_html=True)
            bloco_comentarios("12.1.3.1", res_data, ano_sel)

    # GATILHO DO MODAL 12.1.3.1
    if st.session_state.get(f"gatilho_modal_12_1_3_1_{ano_sel}", False):
        modal_aviso_link("12.1.3.1", st.session_state.get(f"links_pendentes_12_1_3_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_12_1_3_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 13.0 • MOBILIDADE ATIVA (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_13_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 13.0 - Estímulo à Mobilidade Ativa e Não Motorizada", expanded=True):
            # Cálculo dinâmico seguro do ano anterior
            ano_anterior = int(str(ano_sel).strip()[:4]) - 1

            st.subheader("13.0 • Mobilidade Ativa")
            st.write(f"**Foram realizadas ações para estimular a adoção/uso dos meios de transporte não motorizados em {ano_anterior}?**")
            st.caption("ℹ *Ex: Ciclovias, campanhas de incentivo ao uso de bicicletas, calçadas acessíveis ou caminhadas. Salvamento automático via callbacks.*")
            
            opcoes_130 = ["Selecione...", "Sim", "Não"]
            
            # Recupera o estado salvo no dicionário de dados históricos
            d130 = res_data.get("13.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d130 is None: d130 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_130 = d130.get("valor", "Selecione...")
            chave_radio_130 = f"r_130_{v_salvo_130}_{ano_sel}"

            def cb_radio_130():
                val = st.session_state[chave_radio_130]
                pts = 0.0  # Quesito diagnóstico/informativo (0.0 pontos)
                lnk = st.session_state.get(f"l_130_txt_{ano_sel}", d130.get("link", ""))
                
                save_resp("13.0", val, pts, lnk)
                res_data["13.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_130():
                lnk = st.session_state[f"l_130_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_130, v_salvo_130)
                
                save_resp("13.0", val, 0.0, lnk)
                res_data["13.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d130.get("link", "") or "")]
                
                if lnk != d130.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = True

            col_r130, col_j130 = st.columns([1, 1])
            with col_r130:
                idx_130 = opcoes_130.index(v_salvo_130) if v_salvo_130 in opcoes_130 else 0
                
                st.radio(
                    "Realizou ações?",
                    options=opcoes_130,
                    index=idx_130,
                    key=chave_radio_130,
                    on_change=cb_radio_130,
                    label_visibility="collapsed"
                )
                
                st.markdown("<div style='padding-top: 5px;'></div>", unsafe_allow_html=True)
                if v_salvo_130 == "Sim":
                    st.success(f"🚲 Ações de incentivo e infraestrutura de mobilidade ativa registradas para o ano de {ano_anterior}.")
                elif v_salvo_130 == "Não":
                    st.info(f"ℹ️ Sem registros de ações específicas ou investimentos em transportes não motorizados em {ano_anterior}.")
                
            with col_j130:
                link_130 = st.text_area(
                    f"Descrição/Evidências {ano_anterior} (13.0):", 
                    value=d130.get("link", ""), 
                    key=f"l_130_txt_{ano_sel}", 
                    on_change=cb_text_130, 
                    placeholder="Ex: Link do plano cicloviário, fotos de inauguração de faixas exclusivas, folders de campanhas públicas de conscientização...",
                    height=110
                )
                placeholder_links_130 = st.empty()
                links_130_visuais = [u[0] for u in re.findall(regex_pure_url, link_130 or "")]
                if links_130_visuais:
                    placeholder_links_130.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_130_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 13.0: 0.0 pontos (Diagnóstico Inicial)</span>", unsafe_allow_html=True)
            bloco_comentarios("13.0", res_data, ano_sel)

    # GATILHO DO MODAL 13.0
    if st.session_state.get(f"gatilho_modal_13_0_{ano_sel}", False):
        modal_aviso_link("13.0", st.session_state.get(f"links_pendentes_13_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 13.1 • AÇÕES DE MOBILIDADE ATIVA REALIZADAS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'
    ano_anterior = int(str(ano_sel).strip()[:4]) - 1

    with st.container(key=f"container_bloco_compdec_13_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 13.1 - Detalhamento das Ações Realizadas em {ano_anterior}", expanded=True):
            st.subheader("13.1 • Ações de Mobilidade Ativa")
            st.write(f"**Assinale as ações realizadas para estimular a adoção/uso dos meios de transporte não motorizados em {ano_anterior}:**")
            st.caption("ℹ *Salvamento automático por eventos nativos de estado.*")
            
            d131 = res_data.get("13.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d131 is None: d131 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            # Sanitização do valor recuperado para conversão segura em lista literal python
            raw_v131 = d131.get("valor", "[]")
            if not raw_v131.startswith("["): raw_v131 = "[]"
            try:
                lista_salva_131 = eval(raw_v131)
            except:
                lista_salva_131 = []

            acoes_131 = [
                "Instalação/manutenção de ciclovias ou ciclofaixas",
                "Instalação/manutenção de pontos de locação de bicicletas",
                "Instalação/manutenção de pontos de locação de patinetes",
                "Outras"
            ]

            def cb_checkbox_131():
                sel_atual = []
                for ac in acoes_131:
                    ac_key = ac.replace(" ", "_").replace("/", "_").replace("-", "_").lower()
                    if st.session_state.get(f"chk_131_{ac_key}_{ano_sel}", False):
                        sel_atual.append(ac)
                
                lnk = st.session_state.get(f"l_131_txt_{ano_sel}", d131.get("link", ""))
                val_str = str(sel_atual)
                
                save_resp("13.1", val_str, 0.0, lnk)
                res_data["13.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}

            def cb_text_131():
                lnk = st.session_state[f"l_131_txt_{ano_sel}"]
                val_str = d131.get("valor", "[]")
                
                save_resp("13.1", val_str, 0.0, lnk)
                res_data["13.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d131.get("link", "") or "")]
                
                if lnk != d131.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = True

            col_c131, col_j131 = st.columns([1, 1])
            with col_c131:
                st.markdown("**Selecione uma ou mais opções aplicáveis:**")
                for ac in acoes_131:
                    ac_key = ac.replace(" ", "_").replace("/", "_").replace("-", "_").lower()
                    st.checkbox(
                        ac, 
                        value=ac in lista_salva_131, 
                        key=f"chk_131_{ac_key}_{ano_sel}",
                        on_change=cb_checkbox_131
                    )
                
            with col_j131:
                link_131 = st.text_area(
                    "Detalhes/Localização (13.1):", 
                    value=d131.get("link", ""), 
                    key=f"l_131_txt_{ano_sel}", 
                    on_change=cb_text_131,
                    placeholder="Especifique os bairros, avenidas, nomes das campanhas ou insira links comprobatórios de execução...",
                    height=130
                )
                placeholder_links_131 = st.empty()
                links_131_visuais = [u[0] for u in re.findall(regex_pure_url, link_131 or "")]
                if links_131_visuais:
                    placeholder_links_131.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_131_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 13.1: 0.0 pontos (Diagnóstico Cumulativo)</span>", unsafe_allow_html=True)
            bloco_comentarios("13.1", res_data, ano_sel)

    # GATILHO DO MODAL 13.1
    if st.session_state.get(f"gatilho_modal_13_1_{ano_sel}", False):
        modal_aviso_link("13.1", st.session_state.get(f"links_pendentes_13_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 13.1.1 • CRONOGRAMA DE MANUTENÇÃO (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_13_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 13.1.1 - Cronograma de Manutenção da Infraestrutura", expanded=True):
            st.subheader("13.1.1 • Cronograma de Ciclovias")
            st.write("**Possui um cronograma de manutenção da infraestrutura das ciclovias ou ciclofaixas?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_1311 = ["Selecione...", "Sim (00 pts)", "Não (-20 pts)"]
            
            # Recupera o estado salvo no dicionário de dados históricos
            d1311 = res_data.get("13.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d1311 is None: d1311 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_1311 = d1311.get("valor", "Selecione...")
            chave_radio_1311 = f"r_1311_{v_salvo_1311}_{ano_sel}"

            def cb_radio_1311():
                val = st.session_state[chave_radio_1311]
                pts = -20.0 if "Não" in val else 0.0
                lnk = st.session_state.get(f"l_1311_txt_{ano_sel}", d1311.get("link", ""))
                
                save_resp("13.1.1", val, pts, lnk)
                res_data["13.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_1311():
                lnk = st.session_state[f"l_1311_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_1311, v_salvo_1311)
                pts = -20.0 if "Não" in val else 0.0
                
                save_resp("13.1.1", val, pts, lnk)
                res_data["13.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1311.get("link", "") or "")]
                
                if lnk != d1311.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_1_1_{ano_sel}"] = True

            col_r1311, col_j1311 = st.columns([1, 1])
            with col_r1311:
                idx_1311 = opcoes_1311.index(v_salvo_1311) if v_salvo_1311 in opcoes_1311 else 0
                st.radio(
                    "Possui cronograma?",
                    options=opcoes_1311,
                    index=idx_1311,
                    key=chave_radio_1311,
                    on_change=cb_radio_1311,
                    label_visibility="collapsed"
                )
                
            with col_j1311:
                link_1311 = st.text_area(
                    f"Link/Arquivo do Cronograma ({ano_sel}) (13.1.1):", 
                    value=d1311.get("link", ""), 
                    key=f"l_1311_txt_{ano_sel}", 
                    on_change=cb_text_1311, 
                    placeholder="Insira o link de publicação do plano de manutenção, portarias de zeladoria ou diário oficial correspondente...",
                    height=110
                )
                placeholder_links_1311 = st.empty()
                links_1311_visuais = [u[0] for u in re.findall(regex_pure_url, link_1311 or "")]
                if links_1311_visuais:
                    placeholder_links_1311.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1311_visuais]))

            pts_atuais_1311 = d1311.get("pontos", 0.0)
            cor_txt_1311 = "#dc3545" if pts_atuais_1311 < 0.0 else ("#28a745" if v_salvo_1311 == "Sim (00 pts)" else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_1311}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 13.1.1: {pts_atuais_1311:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("13.1.1", res_data, ano_sel)

    # GATILHO DO MODAL 13.1.1
    if st.session_state.get(f"gatilho_modal_13_1_1_{ano_sel}", False):
        modal_aviso_link("13.1.1", st.session_state.get(f"links_pendentes_13_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_13_1_1_{ano_sel}"] = False


    # =============================================================================
    # QUESITO 13.1.1.1 • CUMPRIMENTO DAS MANUTENÇÕES PREVENTIVAS (100% INDEPENDENTE)
    # =============================================================================
    with st.container(key=f"container_bloco_compdec_13_1_1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 13.1.1.1 - Cumprimento e Execução das Manutenções Preventivas", expanded=True):
            st.subheader("13.1.1.1 • Execução do Cronograma")
            st.write("**As manutenções preventivas da infraestrutura das ciclovias ou ciclofaixas foram realizadas dentro do prazo?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opts13111 = {
                "Selecione...": 0.0,
                "Sim, para todos os trechos (00 pts)": 0.0,
                "Sim, para a maior parte dos trechos (-05 pts)": -5.0,
                "Sim, para a menor parte dos trechos (-10 pts)": -10.0,
                "Não foram realizadas dentro do prazo (-15 pts)": -15.0,
                "Não foram realizadas manutenções preventivas no exercício (-20 pts)": -20.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d13111 = res_data.get("13.1.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d13111 is None: d13111 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_13111 = d13111.get("valor", "Selecione...")
            chave_radio_13111 = f"r_13111_{v_salvo_13111}_{ano_sel}"

            def cb_radio_13111():
                val = st.session_state[chave_radio_13111]
                pts = float(opts13111.get(val, 0.0))
                lnk = st.session_state.get(f"l_13111_txt_{ano_sel}", d13111.get("link", ""))
                
                save_resp("13.1.1.1", val, pts, lnk)
                res_data["13.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_13111():
                lnk = st.session_state[f"l_13111_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_13111, v_salvo_13111)
                pts = float(opts13111.get(val, 0.0))
                
                save_resp("13.1.1.1", val, pts, lnk)
                res_data["13.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d13111.get("link", "") or "")]
                
                if lnk != d13111.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_1_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_1_1_1_{ano_sel}"] = True

            col_r13111, col_j13111 = st.columns([1, 1])
            with col_r13111:
                lista_opcoes_13111 = list(opts13111.keys())
                idx_13111 = lista_opcoes_13111.index(v_salvo_13111) if v_salvo_13111 in lista_opcoes_13111 else 0
                st.radio(
                    "Status da manutenção:", 
                    options=lista_opcoes_13111, 
                    index=idx_13111, 
                    key=chave_radio_13111,
                    on_change=cb_radio_13111,
                    label_visibility="collapsed"
                )
                
            with col_j13111:
                link_13111 = st.text_area(
                    f"Evidência da execução em {ano_sel} (13.1.1.1):", 
                    value=d13111.get("link", ""), 
                    key=f"l_13111_txt_{ano_sel}", 
                    on_change=cb_text_13111, 
                    placeholder="Ex: Link de relatórios técnicos de engenharia viária, ordens de serviço finalizadas ou medições de contratos de zeladoria...",
                    height=140
                )
                placeholder_links_13111 = st.empty()
                links_13111_visuais = [u[0] for u in re.findall(regex_pure_url, link_13111 or "")]
                if links_13111_visuais:
                    placeholder_links_13111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_13111_visuais]))

            pts_atuais_13111 = d13111.get("pontos", 0.0)
            cor_txt_13111 = "#dc3545" if pts_atuais_13111 < 0.0 else ("#28a745" if v_salvo_13111.startswith("Sim, para todos") else "#6c757d")
            st.markdown(f"<span style='color:{cor_txt_13111}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 13.1.1.1: {pts_atuais_13111:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("13.1.1.1", res_data, ano_sel)

    # GATILHO DO MODAL 13.1.1.1
    if st.session_state.get(f"gatilho_modal_13_1_1_1_{ano_sel}", False):
        modal_aviso_link("13.1.1.1", st.session_state.get(f"links_pendentes_13_1_1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_13_1_1_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 14.0 • ACESSIBILIDADE EM CALÇAMENTOS PÚBLICOS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_14_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 14.0 - Adequação de Calçamentos Públicos para Acessibilidade", expanded=True):
            st.subheader("14.0 • Acessibilidade")
            st.write("**O Município adequou os calçamentos públicos para acessibilidade (PcD e restrição de mobilidade)?**")
            st.caption("ℹ *Nota: Entorno de prédios públicos e locais de grande circulação. Salvamento automático via callbacks.*")
            
            opts140 = {
                "Selecione...": 0.0,
                "Sim, integralmente - Todos os calçamentos públicos (00 pts)": 0.0,
                "Sim, parcialmente - Em parte dos calçamentos públicos (-10 pts)": -10.0,
                "Não possui acessibilidade em calçamentos públicos (-50 pts)": -50.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos com o padrão original do formulário
            d140 = res_data.get("14.0", {"valor": "Não possui acessibilidade em calçamentos públicos (-50 pts)", "pontos": -50.0, "link": ""})
            if d140 is None: d140 = {"valor": "Não possui acessibilidade em calçamentos públicos (-50 pts)", "pontos": -50.0, "link": ""}
            
            v_salvo_140 = d140.get("valor", "Não possui acessibilidade em calçamentos públicos (-50 pts)")
            chave_radio_140 = f"r_140_{v_salvo_140}_{ano_sel}"

            def cb_radio_140():
                val = st.session_state[chave_radio_140]
                pts = float(opts140.get(val, -50.0))
                lnk = st.session_state.get(f"l_140_txt_{ano_sel}", d140.get("link", ""))
                
                save_resp("14.0", val, pts, lnk)
                res_data["14.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_140():
                lnk = st.session_state[f"l_140_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_140, v_salvo_140)
                pts = float(opts140.get(val, -50.0))
                
                save_resp("14.0", val, pts, lnk)
                res_data["14.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d140.get("link", "") or "")]
                
                if lnk != d140.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = True

            col_r140, col_j140 = st.columns([1, 1])
            with col_r140:
                lista_opcoes_140 = list(opts140.keys())
                idx_140 = lista_opcoes_140.index(v_salvo_140) if v_salvo_140 in lista_opcoes_140 else 3
                
                st.radio(
                    "Status da acessibilidade:",
                    options=lista_opcoes_140,
                    index=idx_140,
                    key=chave_radio_140,
                    on_change=cb_radio_140,
                    label_visibility="collapsed"
                )
                
            with col_j140:
                link_140 = st.text_area(
                    "Locais adequados / Fotos / Links (14.0):", 
                    value=d140.get("link", ""), 
                    key=f"l_140_txt_{ano_sel}", 
                    on_change=cb_text_140, 
                    placeholder="Ex: Mapeamento de rotas acessíveis, relatórios fotográficos de rampas e pisos podotáteis, links de portarias de obras...",
                    height=130
                )
                placeholder_links_140 = st.empty()
                links_140_visuais = [u[0] for u in re.findall(regex_pure_url, link_140 or "")]
                if links_140_visuais:
                    placeholder_links_140.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_140_visuais]))

            pts_atuais_140 = d140.get("pontos", -50.0)
            cor_txt_140 = "#dc3545" if pts_atuais_140 == -50.0 else ("#28a745" if v_salvo_140.startswith("Sim, integralmente") else "#ffc107")
            st.markdown(f"<span style='color:{cor_txt_140}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 14.0: {pts_atuais_140:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("14.0", res_data, ano_sel)

    # GATILHO DO MODAL 14.0
    if st.session_state.get(f"gatilho_modal_14_0_{ano_sel}", False):
        modal_aviso_link("14.0", st.session_state.get(f"links_pendentes_14_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 14.1 • RECURSOS DE ACESSIBILIDADE OFERECIDOS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_14_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 14.1 - Detalhamento dos Recursos de Acessibilidade", expanded=True):
            st.subheader("14.1 • Recursos de Acessibilidade")
            st.write("**Informe os recursos de acessibilidade oferecidos pela Prefeitura:**")
            st.caption("ℹ *Salvamento automático por eventos nativos de estado.*")
            
            d141 = res_data.get("14.1", {"valor": "[]", "pontos": 0.0, "link": ""})
            if d141 is None: d141 = {"valor": "[]", "pontos": 0.0, "link": ""}
            
            # Sanitização e conversão segura do estado literal em lista Python
            raw_v141 = d141.get("valor", "[]")
            if not raw_v141.startswith("["): raw_v141 = "[]"
            try:
                lista_salva_141 = eval(raw_v141)
            except:
                lista_salva_141 = []

            recursos_141 = [
                "Calçadas com dimensões mínimas para a circulação",
                "Sinalização tátil em pisos",
                "Rampas de acesso",
                "Escadas com corrimão"
            ]

            def cb_checkbox_141():
                sel_atual = []
                for rec in recursos_141:
                    rec_key = rec.replace(" ", "_").replace("ç", "c").replace("ã", "a").replace("í", "i").lower()[:20]
                    if st.session_state.get(f"chk_141_{rec_key}_{ano_sel}", False):
                        sel_atual.append(rec)
                
                lnk = st.session_state.get(f"l_141_txt_{ano_sel}", d141.get("link", ""))
                val_str = str(sel_atual)
                
                save_resp("14.1", val_str, 0.0, lnk)
                res_data["14.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}

            def cb_text_141():
                lnk = st.session_state[f"l_141_txt_{ano_sel}"]
                val_str = d141.get("valor", "[]")
                
                save_resp("14.1", val_str, 0.0, lnk)
                res_data["14.1"] = {"valor": val_str, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d141.get("link", "") or "")]
                
                if lnk != d141.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = True

            col_c141, col_j141 = st.columns([1, 1])
            with col_c141:
                st.markdown("**Assinale as opções estruturadas no Município:**")
                for rec in recursos_141:
                    rec_key = rec.replace(" ", "_").replace("ç", "c").replace("ã", "a").replace("í", "i").lower()[:20]
                    st.checkbox(
                        rec, 
                        value=rec in lista_salva_141, 
                        key=f"chk_141_{rec_key}_{ano_sel}",
                        on_change=cb_checkbox_141
                    )
                
            with col_j141:
                link_141 = st.text_area(
                    f"Justificativa e Fotos ({ano_sel}) (14.1):", 
                    value=d141.get("link", ""), 
                    key=f"l_141_txt_{ano_sel}", 
                    on_change=cb_text_141,
                    placeholder="Descreva as especificações técnicas adotadas (ex: NBR 9050) ou insira os links de repositórios fotográficos e vistorias...",
                    height=130
                )
                placeholder_links_141 = st.empty()
                links_141_visuais = [u[0] for u in re.findall(regex_pure_url, link_141 or "")]
                if links_141_visuais:
                    placeholder_links_141.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_141_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 14.1: 0.0 pontos (Inventário de Engenharia Viária)</span>", unsafe_allow_html=True)
            bloco_comentarios("14.1", res_data, ano_sel)

    # GATILHO DO MODAL 14.1
    if st.session_state.get(f"gatilho_modal_14_1_{ano_sel}", False):
        modal_aviso_link("14.1", st.session_state.get(f"links_pendentes_14_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO 15.0 • SINALIZAÇÃO VIÁRIA MUNICIPAL (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_15_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 15.0 - Condições de Sinalização Vertical e Horizontal", expanded=True):
            st.subheader("15.0 • Sinalização Viária")
            st.write("**As vias públicas pavimentadas estão devidamente sinalizadas (vertical e horizontalmente) de forma a garantir as condições adequadas de segurança na circulação?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opts150 = {
                "Selecione...": 0.0,
                "Sim, integralmente - Todas as vias públicas municipais (50 pts)": 50.0,
                "Sim, parcialmente - Em parte das vias municipais (10 pts)": 10.0,
                "Não estão sinalizadas (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d150 = res_data.get("15.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d150 is None: d150 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_150 = d150.get("valor", "Selecione...")
            chave_radio_150 = f"r_150_{v_salvo_150}_{ano_sel}"

            def cb_radio_150():
                val = st.session_state[chave_radio_150]
                pts = float(opts150.get(val, 0.0))
                lnk = st.session_state.get(f"l_150_txt_{ano_sel}", d150.get("link", ""))
                
                save_resp("15.0", val, pts, lnk)
                res_data["15.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_150():
                lnk = st.session_state[f"l_150_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_150, v_salvo_150)
                pts = float(opts150.get(val, 0.0))
                
                save_resp("15.0", val, pts, lnk)
                res_data["15.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d150.get("link", "") or "")]
                
                if lnk != d150.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = True

            col_r150, col_j150 = st.columns([1, 1])
            with col_r150:
                lista_opcoes_150 = list(opts150.keys())
                idx_150 = lista_opcoes_150.index(v_salvo_150) if v_salvo_150 in lista_opcoes_150 else 0
                
                st.radio(
                    "Status da sinalização:",
                    options=lista_opcoes_150,
                    index=idx_150,
                    key=chave_radio_150,
                    on_change=cb_radio_150,
                    label_visibility="collapsed"
                )
                
            with col_j150:
                link_150 = st.text_area(
                    f"Evidências da sinalização ({ano_sel}) (15.0):", 
                    value=d150.get("link", ""), 
                    key=f"l_150_txt_{ano_sel}", 
                    on_change=cb_text_150, 
                    placeholder="Ex: Planos de sinalização viária, relatórios contratuais de pintura/placas, inventário do setor de trânsito ou links correlatos...",
                    height=130
                )
                placeholder_links_150 = st.empty()
                links_150_visuais = [u[0] for u in re.findall(regex_pure_url, link_150 or "")]
                if links_150_visuais:
                    placeholder_links_150.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_150_visuais]))

            pts_atuais_150 = d150.get("pontos", 0.0)
            cor_txt_150 = "#dc3545" if pts_atuais_150 == 0.0 else ("#28a745" if pts_atuais_150 == 50.0 else "#ffc107")
            st.markdown(f"<span style='color:{cor_txt_150}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 15.0: {pts_atuais_150:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("15.0", res_data, ano_sel)

    # GATILHO DO MODAL 15.0
    if st.session_state.get(f"gatilho_modal_15_0_{ano_sel}", False):
        modal_aviso_link("15.0", st.session_state.get(f"links_pendentes_15_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = False

  # =============================================================================
    # QUESITO 16.0 • MANUTENÇÃO DE VIAS PÚBLICAS (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_compdec_16_0_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito 16.0 - Condições de Manutenção Viária e Pavimentação", expanded=True):
            st.subheader("16.0 • Manutenção de Vias")
            st.write("**Há manutenção adequada das vias públicas no Município?**")
            st.caption("ℹ *Referência: Manuais de Manutenção Rodoviária do DNIT. Salvamento automático por callbacks nativos.*")
            
            opts160 = {
                "Selecione...": 0.0,
                "Sim, integralmente - Todos os calçamentos públicos (00 pts)": 0.0,
                "Sim, parcialmente - Em parte dos calçamentos públicos (-10 pts)": -10.0,
                "Não possui acessibilidade em calçamentos públicos (-50 pts)": -50.0
            }
            
            # Ajuste de opções baseado no dicionário fornecido na regra de negócios original
            opts160 = {
                "Selecione...": 0.0,
                "Sim, integralmente - Todas as vias públicas municipais (50 pts)": 50.0,
                "Sim, parcialmente - Em parte das vias municipais (10 pts)": 10.0,
                "Não estão adequadas (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            d160 = res_data.get("16.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if d160 is None: d160 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_160 = d160.get("valor", "Selecione...")
            chave_radio_160 = f"r_160_{v_salvo_160}_{ano_sel}"

            def cb_radio_160():
                val = st.session_state[chave_radio_160]
                pts = float(opts160.get(val, 0.0))
                lnk = st.session_state.get(f"l_160_txt_{ano_sel}", d160.get("link", ""))
                
                save_resp("16.0", val, pts, lnk)
                res_data["16.0"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_160():
                lnk = st.session_state[f"l_160_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_160, v_salvo_160)
                pts = float(opts160.get(val, 0.0))
                
                save_resp("16.0", val, pts, lnk)
                res_data["16.0"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, d160.get("link", "") or "")]
                
                if lnk != d160.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = True

            col_r160, col_j160 = st.columns([1, 1])
            with col_r160:
                lista_opcoes_160 = list(opts160.keys())
                idx_160 = lista_opcoes_160.index(v_salvo_160) if v_salvo_160 in lista_opcoes_160 else 0
                
                st.radio(
                    "Qualidade da manutenção:",
                    options=lista_opcoes_160,
                    index=idx_160,
                    key=chave_radio_160,
                    on_change=cb_radio_160,
                    label_visibility="collapsed"
                )
                
            with col_j160:
                link_160 = st.text_area(
                    f"Contratos / Cronograma de Obras ({ano_sel}) (16.0):", 
                    value=d160.get("link", ""), 
                    key=f"l_160_txt_{ano_sel}", 
                    on_change=cb_text_160, 
                    placeholder="Ex: Link do cronograma oficial de recapeamento, contratos de operação tapa-buracos publicados no Portal da Transparência...",
                    height=130
                )
                placeholder_links_160 = st.empty()
                links_160_visuais = [u[0] for u in re.findall(regex_pure_url, link_160 or "")]
                if links_160_visuais:
                    placeholder_links_160.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_160_visuais]))

            pts_atuais_160 = d160.get("pontos", 0.0)
            cor_txt_160 = "#dc3545" if pts_atuais_160 == 0.0 else ("#28a745" if pts_atuais_160 == 50.0 else "#ffc107")
            st.markdown(f"<span style='color:{cor_txt_160}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.0: {pts_atuais_160:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("16.0", res_data, ano_sel)

    # GATILHO DO MODAL 16.0
    if st.session_state.get(f"gatilho_modal_16_0_{ano_sel}", False):
        modal_aviso_link("16.0", st.session_state.get(f"links_pendentes_16_0_{ano_sel}", []))
        st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = False

    # -------------------------------------------------------------------------
    # --- QUESITO 17.1 (ENCERRAMENTO/FEEDBACK) --------------------------------
    # -------------------------------------------------------------------------
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("QUESITO 17.1")
    st.write("**Utilize o espaço abaixo para registrar suas impressões e sugestões sobre o questionário.**")

    d171 = res_data.get("17.1", {"valor": None, "pontos": 0.0, "link": ""})
    opcoes_171 = ["Sim", "Não"]
    idx171 = opcoes_171.index(d171["valor"]) if d171["valor"] in opcoes_171 else None

    col_r171, col_j171 = st.columns([1, 2])
    with col_r171:
        r171 = st.radio(f"Gostaria de registrar impressões em {ano_sel}?", opcoes_171, index=idx171, key=f"q171_radio_{ano_sel}")

    with col_j171:
        l171 = st.text_area(
            "Espaço para Registro (17.1):",
            value=d171["link"],
            key=f"l171_text_{ano_sel}",
            placeholder="Sugestões ou observações sobre este exercício...",
            height=120,
            disabled=(r171 != "Sim")
        )
        
        # MOSTRA O LINK ATIVO AZUL SE EXISTIR NO CAMPO
        links_171_atuais = re.findall(r'(https?://[^\s]+)', l171)
        if links_171_atuais:
            st.markdown(f"🔗 **Link Ativo:** [{links_171_atuais[0]}]({links_171_atuais[0]})")

    # PROCESSAMENTO DE SALVAMENTO E TRAVA DO MODAL DO QUESITO 17.1
    if r171 is not None and (r171 != d171["valor"] or l171 != d171["link"]):
        save_resp("17.1", r171, 0.0, l171)
        
        if links_171_atuais:
            links_171_antigos = re.findall(r'(https?://[^\s]+)', d171["link"])
            if not links_171_antigos or links_171_atuais[0] != links_171_antigos[0]:
                modal_aviso_link("17.1", links_171_atuais)
            else:
                st.rerun()
        else:
            st.rerun()

    bloco_comentarios("17.1", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # =============================================================================
    # SEÇÃO: DADOS EXTERNOS DO i-CIDADE
    # =============================================================================
    st.markdown("## 🌐 DADOS EXTERNOS DO i-CIDADE")

    # =============================================================================
    # QUESITO C1 • ONU MCR2030 (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_externo_c1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito C1 - Programa Construindo Cidades Resilientes (MCR2030) da ONU", expanded=True):
            st.subheader("QUESITO C1")
            st.write(f"**O Município estava inscrito no Programa Construindo Cidades Resilientes 2030 da ONU?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opcoes_c1 = ["Selecione...", "Sim", "Não"]
            
            # Recupera o estado salvo no dicionário de dados históricos
            dc1 = res_data.get("C1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if dc1 is None: dc1 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_c1 = dc1.get("valor", "Selecione...")
            chave_radio_c1 = f"r_c1_{v_salvo_c1}_{ano_sel}"

            def cb_radio_c1():
                val = st.session_state[chave_radio_c1]
                lnk = st.session_state.get(f"l_c1_txt_{ano_sel}", dc1.get("link", ""))
                
                save_resp("C1", val, 0.0, lnk)
                res_data["C1"] = {"valor": val, "pontos": 0.0, "link": lnk}

            def cb_text_c1():
                lnk = st.session_state[f"l_c1_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_c1, v_salvo_c1)
                
                save_resp("C1", val, 0.0, lnk)
                res_data["C1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, dc1.get("link", "") or "")]
                
                if lnk != dc1.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_c1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_c1_{ano_sel}"] = True

            col_rc1, col_jc1 = st.columns([1, 1])
            with col_rc1:
                idx_c1 = opcoes_c1.index(v_salvo_c1) if v_salvo_c1 in opcoes_c1 else 0
                st.radio(
                    "Inscrito no MCR2030?", 
                    options=opcoes_c1, 
                    index=idx_c1, 
                    key=chave_radio_c1,
                    on_change=cb_radio_c1,
                    label_visibility="collapsed"
                )
                
            with col_jc1:
                link_c1 = st.text_area(
                    f"Comprovante ({ano_sel}) (C1):", 
                    value=dc1.get("link", ""), 
                    key=f"l_c1_txt_{ano_sel}", 
                    on_change=cb_text_c1, 
                    placeholder="Insira o link do certificado de adesão, link do perfil público do município no painel MCR2030 ou documento comprobatório ONU...",
                    height=110
                )
                placeholder_links_c1 = st.empty()
                links_c1_visuais = [u[0] for u in re.findall(regex_pure_url, link_c1 or "")]
                if links_c1_visuais:
                    placeholder_links_c1.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_c1_visuais]))

            st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito C1: 0.0 pontos (Indicador de Alinhamento Global)</span>", unsafe_allow_html=True)
            bloco_comentarios("C1", res_data, ano_sel)

    # GATILHO DO MODAL C1
    if st.session_state.get(f"gatilho_modal_c1_{ano_sel}", False):
        modal_aviso_link("C1", st.session_state.get(f"links_pendentes_c1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_c1_{ano_sel}"] = False

    # =============================================================================
    # QUESITO C1.1 • ESTÁGIO MCR2030 DA ONU (100% INDEPENDENTE)
    # =============================================================================
    regex_pure_url = r'((https?://[^\s<>"]+))'

    with st.container(key=f"container_bloco_externo_c1_1_final_{ano_sel}", border=True):
        with st.expander(f"📌 Quesito C1.1 - Estágio de Classificação no Programa MCR2030", expanded=True):
            st.subheader("QUESITO C1.1")
            st.write(f"**O Município foi classificado em qual estágio do Programa?**")
            st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
            
            opts_c11 = {
                "Selecione...": 0.0,
                "Etapa A (10 pts)": 10.0,
                "Etapa B (20 pts)": 20.0,
                "Etapa C (50 pts)": 50.0,
                "Não classificada (00 pts)": 0.0
            }
            
            # Recupera o estado salvo no dicionário de dados históricos
            dc11 = res_data.get("C1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
            if dc11 is None: dc11 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
            
            v_salvo_c11 = dc11.get("valor", "Selecione...")
            chave_radio_c11 = f"r_c11_{v_salvo_c11}_{ano_sel}"

            def cb_radio_c11():
                val = st.session_state[chave_radio_c11]
                pts = float(opts_c11.get(val, 0.0))
                lnk = st.session_state.get(f"l_c11_txt_{ano_sel}", dc11.get("link", ""))
                
                save_resp("C1.1", val, pts, lnk)
                res_data["C1.1"] = {"valor": val, "pontos": pts, "link": lnk}

            def cb_text_c11():
                lnk = st.session_state[f"l_c11_txt_{ano_sel}"]
                val = st.session_state.get(chave_radio_c11, v_salvo_c11)
                pts = float(opts_c11.get(val, 0.0))
                
                save_resp("C1.1", val, pts, lnk)
                res_data["C1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                
                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                links_antigos = [u[0] for u in re.findall(regex_pure_url, dc11.get("link", "") or "")]
                
                if lnk != dc11.get("link", "") and links_atuais:
                    if links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_c1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_c1_1_{ano_sel}"] = True

            col_rc11, col_jc11 = st.columns([1, 1])
            with col_rc11:
                lista_opcoes_c11 = list(opts_c11.keys())
                idx_c11 = lista_opcoes_c11.index(v_salvo_c11) if v_salvo_c11 in lista_opcoes_c11 else 0
                st.radio(
                    "Estágio atual:", 
                    options=lista_opcoes_c11, 
                    index=idx_c11, 
                    key=chave_radio_c11,
                    on_change=cb_radio_c11,
                    label_visibility="collapsed"
                )
                
            with col_jc11:
                link_c11 = st.text_area(
                    f"Evidência Classificação ({ano_sel}) (C1.1):", 
                    value=dc11.get("link", ""), 
                    key=f"l_c11_txt_{ano_sel}", 
                    on_change=cb_text_c11, 
                    placeholder="Insira o link do painel de controle da ONU, relatórios de autoavaliação validados ou documentos técnicos de auditoria MCR2030...",
                    height=130
                )
                placeholder_links_c11 = st.empty()
                links_c11_visuais = [u[0] for u in re.findall(regex_pure_url, link_c11 or "")]
                if links_c11_visuais:
                    placeholder_links_c11.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_c11_visuais]))

            pts_atuais_c11 = dc11.get("pontos", 0.0)
            cor_txt_c11 = "#28a745" if pts_atuais_c11 > 0.0 else "#6c757d"
            st.markdown(f"<span style='color:{cor_txt_c11}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito C1.1: +{pts_atuais_c11:.1f} pontos</span>", unsafe_allow_html=True)
            bloco_comentarios("C1.1", res_data, ano_sel)

    # GATILHO DO MODAL C1.1
    if st.session_state.get(f"gatilho_modal_c1_1_{ano_sel}", False):
        modal_aviso_link("C1.1", st.session_state.get(f"links_pendentes_c1_1_{ano_sel}", []))
        st.session_state[f"gatilho_modal_c1_1_{ano_sel}"] = False

# --- INICIALIZAÇÃO DO SCRIPT ---
if __name__ == "__main__":
    try:
        st.set_page_config(page_title="IEGM i-Cidade", layout="wide", page_icon="🏙️")
    except Exception:
        pass

    init_db()
    mostrar_formulario_cidade()
