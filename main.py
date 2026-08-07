import base64
from datetime import datetime, date
import json
import os
import sys
import pandas as pd
import streamlit as st

# =============================================================================
# INJEÇÃO DEFINITIVA E BLINDADA NO ST.SECRETS (RENDER / NEON)
# =============================================================================
NEON_URL = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"

SecretsClass = type(st.secrets)

_orig_getitem = getattr(SecretsClass, "__getitem__", None)
_orig_getattr = getattr(SecretsClass, "__getattr__", None)


def _patched_getitem(self, key):
    if key in os.environ and os.environ[key]:
        return os.environ[key]
    if key == "DATABASE_URL":
        return os.environ.get("DATABASE_URL", NEON_URL)
    if _orig_getitem:
        try:
            return _orig_getitem(self, key)
        except Exception:
            pass
    raise KeyError(f"st.secrets has no key '{key}'")


def _patched_getattr(self, key):
    if key in os.environ and os.environ[key]:
        return os.environ[key]
    if key == "DATABASE_URL":
        return os.environ.get("DATABASE_URL", NEON_URL)
    if _orig_getattr:
        try:
            return _orig_getattr(self, key)
        except Exception:
            pass
    raise AttributeError(f"st.secrets has no attribute '{key}'")


SecretsClass.__getitem__ = _patched_getitem
SecretsClass.__getattr__ = _patched_getattr
# =============================================================================

# Força o interpretador a enxergar a pasta atual
current_dir = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in locals()
    else os.getcwd()
)
if current_dir not in sys.path:
    sys.path.append(current_dir)


# --- CARREGAMENTO OTIMIZADO DE MÓDULOS ---
def import_local_module(module_name):
    try:
        import importlib

        return importlib.import_module(module_name)
    except Exception:
        return None


# Importação de Módulos IEG-M
icidade = import_local_module("icidade_completo") or import_local_module(
    "icidade"
)
igov = import_local_module("igov")
iamb = import_local_module("iamb")
ifiscal = import_local_module("ifiscal")
iplan = import_local_module("iplan")
ieduc = import_local_module("ieduc")
isaude = import_local_module("isaude")
iegm_final = import_local_module("iegmfinal")

# Módulos de Gestão
bib_core = import_local_module("biblioteca")
admin_core = import_local_module("administrador")
atividade = import_local_module("atividade")
plano_acao = import_local_module("plano_acao")
treinamento = import_local_module("treinamento")

# Módulos do Sistema de Controle Interno
vistoria = import_local_module("vistoria")
planos = import_local_module("planos")
contratos = import_local_module("contratos")

# Módulo Inteligência Artificial
hal_core = import_local_module("hal")

# Configuração da página
st.set_page_config(
    page_title="IEG-M Francisco Morato",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# HELPER DE SANITIZAÇÃO DE COMENTÁRIOS (CORRIGE O EMPTY_STRING)
# =============================================================================
def _obter_lista_comentarios(dados_banco):
    """Garante que o retorno de 'comentarios' seja sempre uma lista Python válida."""
    raw = dados_banco.get("comentarios", [])
    if isinstance(raw, str):
        if raw in ["EMPTY_STRING", "", "null", "None"]:
            return []
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return raw
    return []


# =============================================================================
# CALLBACKS DE COMENTÁRIO E QUESITO (CORRIGIDOS)
# =============================================================================

def cb_postar_comentario(qid, ano_sel, usuario_atual, id_chave=None):
    """Callback disparado ao clicar em 'Postar Comentário'."""
    chave_busca = id_chave if id_chave else qid
    key_texto = f"v_txt_com_{chave_busca}_{ano_sel}"
    texto = st.session_state.get(key_texto, "").strip()
    
    if texto:
        dados_banco = load_respostas(ano_sel).get(qid, {})
        comentarios = _obter_lista_comentarios(dados_banco)
        
        status_atual = "Pendente"
        for com in reversed(comentarios):
            if isinstance(com, dict) and "status_definido" in com:
                status_atual = com["status_definido"]
                break
                
        nova_mensagem = {
            "autor": usuario_atual,
            "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "texto": texto,
            "status_definido": status_atual
        }
        comentarios.append(nova_mensagem)
        
        save_resp(
            qid=qid,
            valor=dados_banco.get("valor", ""),
            pontos=dados_banco.get("pontos", 0),
            link=dados_banco.get("link", ""),
            comentarios=comentarios
        )
        st.session_state[key_texto] = ""
        if hasattr(load_respostas, "clear"):
            load_respostas.clear()


def cb_alterar_status(qid, ano_sel, usuario_atual, id_chave=None):
    """Callback disparado ao trocar o Radio Button de Pendente/Resolvido."""
    chave_busca = id_chave if id_chave else qid
    key_radio = f"rad_status_{chave_busca}_{ano_sel}"
    novo_status = st.session_state.get(key_radio)
    
    if not novo_status:
        return

    dados_banco = load_respostas(ano_sel).get(qid, {})
    comentarios = _obter_lista_comentarios(dados_banco)
    
    log_mudanca = {
        "autor": "Sistema / " + usuario_atual,
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status.upper()}**.",
        "status_definido": novo_status
    }
    comentarios.append(log_mudanca)
    
    save_resp(
        qid=qid,
        valor=dados_banco.get("valor", ""),
        pontos=dados_banco.get("pontos", 0),
        link=dados_banco.get("link", ""),
        comentarios=comentarios
    )
    if hasattr(load_respostas, "clear"):
        load_respostas.clear()


def cb_deletar_comentario(qid, ano_sel, idx):
    """Callback para apagar um comentário específico."""
    dados_banco = load_respostas(ano_sel).get(qid, {})
    comentarios = _obter_lista_comentarios(dados_banco)
    
    if 0 <= idx < len(comentarios):
        comentarios.pop(idx)
        save_resp(
            qid=qid,
            valor=dados_banco.get("valor", ""),
            pontos=dados_banco.get("pontos", 0),
            link=dados_banco.get("link", ""),
            comentarios=comentarios
        )
        if hasattr(load_respostas, "clear"):
            load_respostas.clear()


def cb_salvar_questao(qid, ano_sel, usuario_atual):
    """Callback acionado ao clicar em 'Salvar Quesito'."""
    key_val = f"txt_val_{qid}"
    key_link = f"txt_link_{qid}"
    key_pts = f"num_pts_{qid}"
    key_texto = f"v_txt_com_{qid}_{ano_sel}"
    
    novo_valor = st.session_state.get(key_val, "")
    novo_link = st.session_state.get(key_link, "")
    novos_pontos = st.session_state.get(key_pts, 0.0)
    
    dados_banco = load_respostas(ano_sel).get(qid, {})
    comentarios = _obter_lista_comentarios(dados_banco)
    texto_pendente = st.session_state.get(key_texto, "").strip()
    
    if texto_pendente:
        status_atual = "Pendente"
        for com in reversed(comentarios):
            if isinstance(com, dict) and "status_definido" in com:
                status_atual = com["status_definido"]
                break
                
        comentarios.append({
            "autor": usuario_atual,
            "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "texto": texto_pendente,
            "status_definido": status_atual
        })
        st.session_state[key_texto] = ""
        
    save_resp(
        qid=qid,
        valor=novo_valor,
        pontos=novos_pontos,
        link=novo_link,
        comentarios=comentarios
    )
    if hasattr(load_respostas, "clear"):
        load_respostas.clear()


# =============================================================================
# COMPONENTES DE INTERFACE DE RENDERIZAÇÃO
# =============================================================================

def renderizar_questao(qid, res_data):
    """Renderiza a questão."""
    dados_q = res_data.get(qid, {})
    ano_sel = st.session_state.get("ano_referencia_global", date.today().year)
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    val_existente = dados_q.get("valor", "")
    pts_existente = float(dados_q.get("pontos", 0.0))
    link_existente = dados_q.get("link", "")
    
    with st.container(border=True):
        st.markdown(f"#### Quesito: `{qid}`")
        
        col_txt, col_meta = st.columns([3, 1])
        
        with col_txt:
            st.text_area("Resposta / Evidência:", value=val_existente, key=f"txt_val_{qid}", height=100)
            st.text_input("Link da Evidência (opcional):", value=link_existente, key=f"txt_link_{qid}")

        with col_meta:
            st.number_input("Pontuação:", value=pts_existente, key=f"num_pts_{qid}")
            st.markdown("<br>", unsafe_allow_html=True)
            
            st.button(
                f"💾 Salvar Quesito {qid}", 
                key=f"btn_save_{qid}", 
                type="primary", 
                use_container_width=True,
                on_click=cb_salvar_questao,
                args=(qid, ano_sel, usuario_atual)
            )

        bloco_comentarios(qid, res_data)


def bloco_comentarios(questao_id, res_data, sufixo=None):
    """Renderiza a caixa de comentários e histórico formatado."""
    ano_sel = st.session_state.get("ano_referencia_global", date.today().year)
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
    key_radio = f"rad_status_{id_chave}_{ano_sel}"
    
    dados_questao = res_data.get(questao_id, {})
    historico = _obter_lista_comentarios(dados_questao)
    
    status_global = "Pendente"
    for com in reversed(historico):
        if isinstance(com, dict) and "status_definido" in com:
            status_global = com["status_definido"]
            break
            
    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    
    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global) if status_global in opcoes_status else 1
        
        st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=key_radio,
            on_change=cb_alterar_status,
            args=(questao_id, ano_sel, usuario_atual, id_chave)
        )

        if historico:
            for idx, com in enumerate(historico):
                if isinstance(com, str):
                    com = {"autor": "Usuário", "data": "", "texto": com}

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
                                <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">👤 {autor}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{data_com}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{texto_com}</p>
                            </div>""", unsafe_allow_html=True
                        )
                
                with col_lixeira:
                    st.button(
                        "🗑️", 
                        key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}",
                        on_click=cb_deletar_comentario,
                        args=(questao_id, ano_sel, idx)
                    )
        
        st.text_area("Novo comentário:", key=key_texto, height=70, label_visibility="collapsed")
        
        st.button(
            "Postar Comentário", 
            key=f"btn_com_{id_chave}_{ano_sel}", 
            type="primary",
            on_click=cb_postar_comentario,
            args=(questao_id, ano_sel, usuario_atual, id_chave)
        )


# =============================================================================
# FUNÇÃO AUXILIAR DE IMAGEM
# =============================================================================
def get_image_base64(filename):
    full_path = os.path.join(current_dir, filename)
    if os.path.exists(full_path):
        with open(full_path, "rb") as img_file:
            return f"data:image/png;base64,{base64.b64encode(img_file.read()).decode()}"
    return None


# Estilização CSS
st.markdown(
    """
    <style>
    .stApp {
        background-color: #FFFFFF !important;
        color: #333333;
    }
    
    .cad-frame {
        border: 2px solid #001A4D;
        border-radius: 4px;
        padding: 12px 20px;
        background: #001A4D;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        margin: 0 auto 20px auto;
        max-width: 320px;
    }

    .card-container {
        position: relative;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 16px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.03);
        transition: all 0.3s ease;
        min-height: 250px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        cursor: pointer;
    }
    
    .card-container:hover {
        transform: translateY(-5px);
        box-shadow: 0 12px 22px rgba(0, 26, 77, 0.1);
        border-color: #003D99;
    }

    .card-img-container {
        height: 90px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 12px;
        pointer-events: none;
    }

    .card-img-container img {
        max-height: 85px;
        max-width: 100%;
        object-fit: contain;
    }

    .card-title {
        color: #001A4D;
        font-size: 16px;
        font-weight: 700;
        margin-bottom: 6px;
        pointer-events: none;
    }

    .card-text {
        color: #64748B;
        font-size: 12px;
        line-height: 1.4;
        pointer-events: none;
    }

    .hidden-btn-container {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        opacity: 0;
        z-index: 99;
    }
    
    .hidden-btn-container div.stButton > button {
        width: 100% !important;
        height: 250px !important;
        background: transparent !important;
        border: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Inicialização de Estado Global
if "users_db" not in st.session_state:
    st.session_state.users_db = {
        "jefferson.espanha": {
            "senha": "fodasse",
            "email": "jefferson@franciscomorato.sp.gov.br",
        }
    }

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None
    st.session_state.current_page = "login"
    st.session_state.selected_dimension = None
    st.session_state.ano_referencia_global = 2026
    st.session_state.needs_password_change = False

AVAILABLE_YEARS = [2024, 2025, 2026, 2027, 2028, 2029, 2030]

DIMENSIONS_DATA = {
    "i-Gov TI": {
        "img": "i_gov_ti.png",
        "desc": "Governança de Tecnologia da Informação.",
    },
    "i-Educ": {"img": "i_educ.png", "desc": "Gestão da Educação Municipal"},
    "i-Saúde": {"img": "i_saude.png", "desc": "Gestão da Saúde municipal."},
    "i-Plan": {
        "img": "i_plan.png",
        "desc": "Eficiência do planejamento orçamentário.",
    },
    "i-Amb": {
        "img": "i_amb.png",
        "desc": "Políticas de meio ambiente e sustentabilidade.",
    },
    "i-Cidade": {
        "img": "i_cidade.png",
        "desc": "Defesa Civil e infraestrutura urbana.",
    },
    "i-Fiscal": {
        "img": "i_fiscal.png",
        "desc": "Gestão fiscal e execução financeira.",
    },
    "ieg-m": {
        "img": "i_iegmfinal.png",
        "desc": "Faixa e Pontuação do IEG-M final",
    },
    "Relatório de Atividades": {
        "img": "relatorio_atividade.png",
        "desc": "Monitoramento do PPA",
    },
    "Plano de Ação": {
        "img": "plano_acao.png",
        "desc": "Plano de Ação Corretiva e Metas Estratégicas",
    },
    "Área de treinamento": {
        "img": "treinamento.png",
        "desc": "Área de treinamento e capacitação de pessoal.",
    },
}

CONTROLE_INTERNO_DATA = {
    "Vistorias in loco": {
        "img": "vistoria.png",
        "desc": "Módulo de vistorias técnicas e relatórios in loco.",
    },
    "Planos municipais": {
        "img": "planos.png",
        "desc": "Acompanhamento e gestão de Planos Municipais.",
    },
    "Contratos": {
        "img": "contratos.png",
        "desc": "Gestão e controle interno de contratos administrativos.",
    },
}


def login_page():
    col1, col2, col3 = st.columns([1.1, 1.6, 1.1])
    with col2:
        logo_b64 = get_image_base64("iegm.png")
        if logo_b64:
            st.markdown(
                f'<div style="text-align:center; margin-bottom:20px;"><img src="{logo_b64}" style="max-width:100%; height:auto;"></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='padding: 20px;'></div>", unsafe_allow_html=True
            )

        st.markdown(
            '<div class="cad-frame"><h3 style="text-align: center; color: #FFFFFF; font-size: 16px; margin: 0;">Sistema de Preenchimento do IEG-M</h3></div>',
            unsafe_allow_html=True,
        )
        username = st.text_input(
            "👤 Usuário",
            placeholder="jefferson.espanha",
            key="login_username",
        ).strip()
        password = st.text_input(
            "🔐 Senha", type="password", placeholder="••••••••", key="login_password"
        )

        if st.button(
            "🔓 ENTRAR NO SISTEMA",
            use_container_width=True,
            key="real_login_btn",
        ):
            if (
                username in st.session_state.users_db
                and st.session_state.users_db[username]["senha"] == password
            ):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = (
                    "admin" if username == "jefferson.espanha" else "user"
                )

                if (
                    password == "pmfm1234"
                    and username != "jefferson.espanha"
                ):
                    st.session_state.needs_password_change = True
                else:
                    st.session_state.current_page = "dashboard"
                st.rerun()
            elif username == "" or password == "":
                st.warning("⚠️ Preencha todos os campos!")
            else:
                st.error("❌ Usuário ou senha incorretos.")

        with st.expander("❓ Esqueceu sua senha?"):
            st.info(
                "💡 Por favor, entre em contato com o administrador Jefferson Espanha para redefinir suas credenciais."
            )

        st.markdown("---")
        st.markdown("### 📝 Painel de Cadastro de Novos Usuários")
        with st.expander("Criar Nova Conta"):
            st.write(
                "Apenas o administrador **jefferson.espanha** pode homologar novos acessos."
            )
            admin_auth_user = st.text_input(
                "Usuário do Admin", key="reg_admin_user"
            ).strip()
            admin_auth_pass = st.text_input(
                "Senha do Admin", type="password", key="reg_admin_pass"
            )

            st.markdown("---")
            new_username = st.text_input(
                "Nome do Novo Usuário (ex: joao.silva)", key="new_username"
            ).strip()
            new_email = st.text_input(
                "✉️ E-mail do Usuário", key="new_email"
            ).strip()

            if st.button("➕ Cadastrar Usuário", use_container_width=True):
                if (
                    admin_auth_user != "jefferson.espanha"
                    or admin_auth_pass != "fodasse"
                ):
                    st.error("❌ Credenciais de administrador incorretas.")
                elif not new_username or not new_email:
                    st.warning("⚠️ Preencha o nome de usuário e o e-mail.")
                elif new_username in st.session_state.users_db:
                    st.error("❌ Este usuário já está cadastrado.")
                else:
                    st.session_state.users_db[new_username] = {
                        "senha": "pmfm1234",
                        "email": new_email,
                    }
                    st.success(
                        f"✔️ Usuário '{new_username}' cadastrado com sucesso! Senha inicial: 'pmfm1234'"
                    )


def change_password_page():
    col1, col2, col3 = st.columns([1.1, 1.6, 1.1])
    with col2:
        st.markdown(
            "<div style='text-align:center; padding: 20px;'><h3>🔄 Alteração Obrigatória de Senha</h3><p>Este é o seu primeiro acesso. Altere a sua senha padrão para continuar.</p></div>",
            unsafe_allow_html=True,
        )
        nova_senha = st.text_input(
            "Nova Senha", type="password", key="force_new_pass"
        )
        confirma_senha = st.text_input(
            "Confirme a Nova Senha", type="password", key="force_confirm_pass"
        )

        if st.button("Salvar e Acessar o Sistema", use_container_width=True):
            if not nova_senha:
                st.warning("⚠️ A senha não pode ser vazia.")
            elif nova_senha == "pmfm1234":
                st.error("❌ Você não pode utilizar a senha inicial padrão.")
            elif nova_senha != confirma_senha:
                st.error("❌ As senhas não coincidem.")
            else:
                st.session_state.users_db[st.session_state.username][
                    "senha"
                ] = nova_senha
                st.session_state.needs_password_change = False
                st.session_state.current_page = "dashboard"
                st.success("Senha alterada com sucesso!")
                st.rerun()


def dashboard_page():
    st.markdown(
        f'<div style="text-align: center; padding: 10px;"><h1 style="color: #001A4D;">IEG-M Francisco Morato</h1><p style="color: #003D99; font-weight: bold;">Bem-vindo, {st.session_state.username}!</p></div>',
        unsafe_allow_html=True,
    )

    col_space, col_logout = st.columns([5, 1])
    with col_logout:
        if st.button(
            "🚪 Sair", key="logout_btn_dash", use_container_width=True
        ):
            st.session_state.authenticated = False
            st.session_state.current_page = "login"
            st.rerun()

    st.markdown("---")
    st.markdown("### 📅 Selecione o Ano de Referência")
    st.session_state.ano_referencia_global = st.select_slider(
        "Ano",
        options=AVAILABLE_YEARS,
        value=st.session_state.ano_referencia_global,
        label_visibility="collapsed",
    )
    st.markdown("---")

    # SISTEMA DE GESTÃO AVANÇADA
    st.markdown("### 📊 Sistema de Gestão Avançada")
    dim_cols = st.columns(4)

    for idx, (dim_name, dim_info) in enumerate(DIMENSIONS_DATA.items()):
        with dim_cols[idx % 4]:
            img_b64 = get_image_base64(dim_info["img"])
            img_html = (
                f'<img src="{img_b64}" />'
                if img_b64
                else '<div style="font-size:42px;">📊</div>'
            )

            st.markdown(
                f'<div class="card-container" id="card_{idx}"><div class="card-img-container">{img_html}</div><div class="card-title">{dim_name}</div><div class="card-text">{dim_info["desc"]}</div><div class="hidden-btn-container">',
                unsafe_allow_html=True,
            )
            if st.button(
                "Acessar",
                key=f"btn_real_{dim_name}",
                use_container_width=True,
            ):
                st.session_state.selected_dimension = dim_name
                st.session_state.current_page = "dimension"
                st.rerun()
            st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🛠️ IA, Biblioteca Digital e Área de Administração")
    col_hal, col_bib, col_admin = st.columns(3)

    with col_hal:
        hal_b64 = get_image_base64("hal9000.png")
        hal_html = (
            f'<img src="{hal_b64}" />'
            if hal_b64
            else '<div style="font-size:42px;">🔴</div>'
        )
        st.markdown(
            f'<div class="card-container" style="border-bottom: 4px solid #DC2626;"><div class="card-img-container">{hal_html}</div><div class="card-title">HAL 9000 — IEG-M AI</div><div class="card-text">Assistente cognitivo inteligente.</div><div class="hidden-btn-container">',
            unsafe_allow_html=True,
        )
        if st.button("Acessar", key="btn_real_hal", use_container_width=True):
            st.session_state.selected_dimension = "HAL 9000"
            st.session_state.current_page = "dimension"
            st.rerun()
        st.markdown("</div></div>", unsafe_allow_html=True)

    with col_bib:
        bib_b64 = get_image_base64("biblioteca.png")
        bib_html = (
            f'<img src="{bib_b64}" />'
            if bib_b64
            else '<div style="font-size:42px;">📁</div>'
        )
        st.markdown(
            f'<div class="card-container" style="border-bottom: 4px solid #003D99;"><div class="card-img-container">{bib_html}</div><div class="card-title">Biblioteca Digital</div><div class="card-text">Repositório de gerenciamento de arquivos.</div><div class="hidden-btn-container">',
            unsafe_allow_html=True,
        )
        if st.button("Acessar", key="btn_real_bib", use_container_width=True):
            st.session_state.selected_dimension = "Biblioteca"
            st.session_state.current_page = "dimension"
            st.rerun()
        st.markdown("</div></div>", unsafe_allow_html=True)

    with col_admin:
        admin_b64 = get_image_base64("administrador.png")
        admin_html = (
            f'<img src="{admin_b64}" />'
            if admin_b64
            else '<div style="font-size:42px;">🔒</div>'
        )
        st.markdown(
            f'<div class="card-container" style="border-bottom: 4px solid #10B981;"><div class="card-img-container">{admin_html}</div><div class="card-title">Área do Administrador</div><div class="card-text">Gestão de acessos, e-mails e relatórios consolidados.</div><div class="hidden-btn-container">',
            unsafe_allow_html=True,
        )
        if st.button(
            "Acessar", key="btn_real_admin", use_container_width=True
        ):
            st.session_state.selected_dimension = "Administrador"
            st.session_state.current_page = "dimension"
            st.rerun()
        st.markdown("</div></div>", unsafe_allow_html=True)

    # SISTEMA DE CONTROLE INTERNO
    st.markdown("### 🛡️ Sistema de Controle Interno")
    ci_cols = st.columns(3)

    for idx, (ci_name, ci_info) in enumerate(CONTROLE_INTERNO_DATA.items()):
        with ci_cols[idx % 3]:
            img_b64 = get_image_base64(ci_info["img"])
            img_html = (
                f'<img src="{img_b64}" />'
                if img_b64
                else '<div style="font-size:42px;">🛡️</div>'
            )

            st.markdown(
                f'<div class="card-container" style="border-bottom: 4px solid #001A4D;"><div class="card-img-container">{img_html}</div><div class="card-title">{ci_name}</div><div class="card-text">{ci_info["desc"]}</div><div class="hidden-btn-container">',
                unsafe_allow_html=True,
            )
            if st.button(
                "Acessar", key=f"btn_real_ci_{ci_name}", use_container_width=True
            ):
                st.session_state.selected_dimension = ci_name
                st.session_state.current_page = "dimension"
                st.rerun()
            st.markdown("</div></div>", unsafe_allow_html=True)


def dimension_page():
    """Página de exibição dinâmica."""
    st.markdown(
        "<script>setTimeout(function() { window.scrollTo(0, 0); }, 100);</script>",
        unsafe_allow_html=True,
    )

    dimension = st.session_state.selected_dimension
    year = st.session_state.ano_referencia_global

    col_back, col_title, col_logout = st.columns([1, 4, 1])
    with col_back:
        if st.button(
            "⬅️ Voltar", key="back_to_dash", use_container_width=True
        ):
            st.session_state.current_page = "dashboard"
            st.rerun()
    with col_title:
        st.markdown(
            f"<div style='text-align: center;'><h2 style='color: #001A4D;'>{dimension} - {year}</h2></div>",
            unsafe_allow_html=True,
        )
    with col_logout:
        if st.button(
            "🚪 Sair", key="logout_btn_dim", use_container_width=True
        ):
            st.session_state.authenticated = False
            st.session_state.current_page = "login"
            st.rerun()

    st.markdown("---")

    # Roteamento central das subpáginas do ecossistema
    if dimension == "Administrador":
        if admin_core:
            admin_core.mostrar_painel_admin(year)
        else:
            st.error(
                "Erro técnico: O arquivo 'administrador.py' não foi detectado no sistema."
            )

    # CORRIGIDO: Acesso Direto ao Drive (Sem bib_core.gerenciar_upload_e_arquivos)
    elif dimension == "Biblioteca":
        st.subheader("📚 Biblioteca de Documentos")
        st.markdown(
            "Acesse o acervo documental completo e referências diretamente no Google Drive."
        )
        st.link_button(
            "🔗 Acessar Biblioteca no Google Drive",
            "https://drive.google.com/drive/folders/1iwiuHHbQYZ-p6aEMB9oSjugDEvdB8GVK?usp=drive_link",
            use_container_width=True,
        )

    # Bloco dinâmico do HAL 9000
    elif dimension == "HAL 9000":
        st.subheader("🔴 HAL 9000 — Inteligência Artificial")
        if hal_core:
            if hasattr(hal_core, "mostrar_chat_hal"):
                hal_core.mostrar_chat_hal()
            elif hasattr(hal_core, "main"):
                hal_core.main()
            else:
                st.warning(
                    "Módulo 'hal.py' carregado, mas nenhuma função de renderização conhecida ('mostrar_chat_hal' ou 'main') foi encontrada."
                )
                st.chat_input("Como posso ajudar hoje? (Modo de Segurança)")
        else:
            st.error(
                "Erro técnico: O arquivo 'hal.py' não foi detectado no sistema."
            )
            st.chat_input("Como posso ajudar hoje? (Modo Offline)")

    elif dimension == "i-Cidade":
        if icidade is None:
            st.error(
                "❌ O arquivo 'icidade_completo.py' não foi encontrado ou falhou ao ser importado."
            )
        else:
            try:
                if hasattr(icidade, "init_db"):
                    icidade.init_db()

                funcao_encontrada = None
                for nome_fn in [
                    "mostrar_formulario_cidade",
                    "mostrar_formulario_icidade",
                    "mostrar_icidade",
                    "run",
                    "main",
                    "app",
                ]:
                    if hasattr(icidade, nome_fn):
                        funcao_encontrada = getattr(icidade, nome_fn)
                        break

                if funcao_encontrada:
                    funcao_encontrada()
                else:
                    funcoes_disponiveis = [
                        f
                        for f in dir(icidade)
                        if not f.startswith("_")
                        and callable(getattr(icidade, f))
                    ]
                    st.warning(
                        f"⚠️ Nenhuma função padrão foi encontrada. Funções detectadas no arquivo: {funcoes_disponiveis}"
                    )
            except Exception as e:
                st.error(f"❌ Erro ao executar o i-Cidade: {e}")

    elif dimension == "i-Gov TI" and igov:
        igov.mostrar_formulario_igov()
    elif dimension == "i-Amb" and iamb:
        iamb.mostrar_formulario_iamb()
    elif dimension == "i-Fiscal" and ifiscal:
        ifiscal.mostrar_formulario_ifiscal()
    elif dimension == "i-Plan" and iplan:
        iplan.mostrar_formulario_plan()
    elif dimension == "i-Educ" and ieduc:
        ieduc.mostrar_formulario_educ()
    elif dimension == "i-Saúde" and isaude:
        isaude.mostrar_formulario_saude()
    elif dimension == "ieg-m":
        if iegm_final:
            iegm_final.mostrar_painel_iegm_final(year)
        else:
            st.error("Erro: Módulo 'iegmfinal.py' não localizado.")

    elif dimension == "Relatório de Atividades":
        if atividade:
            if hasattr(atividade, "mostrar_formulario_atividade"):
                atividade.mostrar_formulario_atividade()
            else:
                st.warning(
                    "Módulo 'atividade.py' carregado, mas a função 'mostrar_formulario_atividade' não foi encontrada."
                )
        else:
            st.error("Erro: Módulo 'atividade.py' não localizado.")

    elif dimension == "Plano de Ação":
        if plano_acao:
            if hasattr(plano_acao, "mostrar_formulario_plano_acao"):
                plano_acao.mostrar_formulario_plano_acao()
            elif hasattr(plano_acao, "mostrar_painel_plano_acao"):
                plano_acao.mostrar_painel_plano_acao()
            else:
                st.warning(
                    "Módulo carregado, mas a função de renderização padrão não foi encontrada."
                )
        else:
            st.error("Erro: Módulo 'plano_acao.py' não localizado.")

    elif dimension == "Área de treinamento":
        st.subheader("🎓 Área de Treinamento e Capacitação")
        if treinamento:
            if hasattr(treinamento, "mostrar_painel_treinamento"):
                treinamento.mostrar_painel_treinamento()
            elif hasattr(treinamento, "mostrar_formulario_treinamento"):
                treinamento.mostrar_formulario_treinamento()
            elif hasattr(treinamento, "main"):
                treinamento.main()
            else:
                st.warning(
                    "Módulo 'treinamento.py' carregado, mas nenhuma função de renderização padrão foi detectada."
                )
        else:
            st.error(
                "Erro técnico: O arquivo 'treinamento.py' não foi detectado no sistema."
            )

    # MÓDULOS ADICIONADOS: SISTEMA DE CONTROLE INTERNO
    elif dimension == "Vistorias in loco":
        st.subheader("🔍 Vistorias in loco")
        if vistoria:
            if hasattr(vistoria, "mostrar_painel_vistoria"):
                vistoria.mostrar_painel_vistoria(year)
            elif hasattr(vistoria, "mostrar_formulario_vistoria"):
                vistoria.mostrar_formulario_vistoria()
            elif hasattr(vistoria, "main"):
                vistoria.main()
            else:
                st.warning(
                    "Módulo 'vistoria.py' carregado, mas nenhuma função de renderização foi encontrada."
                )
        else:
            st.error(
                "Erro técnico: O arquivo 'vistoria.py' não foi detectado no sistema."
            )

    elif dimension == "Planos municipais":
        st.subheader("📜 Planos Municipais")
        if planos:
            if hasattr(planos, "mostrar_painel_planos"):
                planos.mostrar_painel_planos(year)
            elif hasattr(planos, "mostrar_formulario_planos"):
                planos.mostrar_formulario_planos()
            elif hasattr(planos, "main"):
                planos.main()
            else:
                st.warning(
                    "Módulo 'planos.py' carregado, mas nenhuma função de renderização foi encontrada."
                )
        else:
            st.error(
                "Erro técnico: O arquivo 'planos.py' não foi detectado no sistema."
            )

    elif dimension == "Contratos":
        st.subheader("📝 Contratos")
        if contratos:
            if hasattr(contratos, "mostrar_painel_contratos"):
                contratos.mostrar_painel_contratos(year)
            elif hasattr(contratos, "mostrar_formulario_contratos"):
                contratos.mostrar_formulario_contratos()
            elif hasattr(contratos, "main"):
                contratos.main()
            else:
                st.warning(
                    "Módulo 'contratos.py' carregado, mas nenhuma função de renderização foi encontrada."
                )
        else:
            st.error(
                "Erro técnico: O arquivo 'contratos.py' não foi detectado no sistema."
            )

    else:
        st.info(f"Módulo {dimension} pronto para integração.")


# =============================================================================
# ROTEAMENTO ÚNICO DE PÁGINAS (Substitua todo aquele bloco final por este)
# =============================================================================
if not st.session_state.authenticated:
    login_page()
else:
    if st.session_state.needs_password_change:
        change_password_page()
    elif st.session_state.current_page == "dashboard":
        dashboard_page()
    elif st.session_state.current_page == "dimension":
        # Garante que a página de dimensão/módulo seja chamada quando selecionada
        if "dimension_page" in globals():
            dimension_page()
        else:
            dashboard_page()

