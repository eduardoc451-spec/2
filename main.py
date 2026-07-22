import streamlit as st
import pandas as pd
from datetime import datetime
import os
import base64
import sys

# Força o interpretador a enxergar a pasta atual para evitar erros de importação dos módulos locais
current_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Importar módulos locais com tratamento de erros dinâmico
def import_local_module(module_name):
    try:
        import importlib
        if module_name in sys.modules:
            return importlib.reload(sys.modules[module_name])
        return importlib.import_module(module_name)
    except Exception:
        return None

icidade = import_local_module("icidade_completo") or import_local_module("icidade")
igov = import_local_module("igov")
iamb = import_local_module("iamb")
ifiscal = import_local_module("ifiscal")
iplan = import_local_module("iplan")
ieduc = import_local_module("ieduc")
isaude = import_local_module("isaude")
iegm_final = import_local_module("iegmfinal") 

# Novos módulos integrados
bib_core = import_local_module("biblioteca")
admin_core = import_local_module("administrador")
atividade = import_local_module("atividade")
plano_acao = import_local_module("plano_acao")
treinamento = import_local_module("treinamento")  # INTEGRADO: Módulo de treinamento

# --- INTEGRADO: Importação do módulo HAL 9000 ---
hal_core = import_local_module("hal")

# Configuração da página
st.set_page_config(
    page_title="IEG-M Francisco Morato",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# FUNÇÃO: Converte a imagem local para Base64
def get_image_base64(filename):
    full_path = os.path.join(current_dir, filename)
    if os.path.exists(full_path):
        with open(full_path, "rb") as img_file:
            return f"data:image/png;base64,{base64.b64encode(img_file.read()).decode()}"
    return None

# CSS Avançado
st.markdown(
    """
    <style>
    .stApp {
        background-color: #FFFFFF !important;
        color: #333333;
    }
    
    /* Quadro de login */
    .cad-frame {
        border: 2px solid #001A4D;
        border-radius: 4px;
        padding: 12px 20px;
        background: #001A4D;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        margin: 0 auto 20px auto;
        max-width: 320px;
    }

    /* CONTAINER DO CARD */
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

    /* Esconde o botão nativo do Streamlit */
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

# Inicialização do banco de dados simulado
if "users_db" not in st.session_state:
    st.session_state.users_db = {
        "jefferson.espanha": {"senha": "fodasse", "email": "jefferson@franciscomorato.sp.gov.br"}
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
    "i-Gov TI": {"img": "i_gov_ti.png", "desc": "Governança de Tecnologia da Informação."},
    "i-Educ": {"img": "i_educ.png", "desc": "Gestão da Educação Municipal"},
    "i-Saúde": {"img": "i_saude.png", "desc": "Gestão da Saúde municipal."},
    "i-Plan": {"img": "i_plan.png", "desc": "Eficiência do planejamento orçamentário."},
    "i-Amb": {"img": "i_amb.png", "desc": "Políticas de meio ambiente e sustentabilidade."},
    "i-Cidade": {"img": "i_cidade.png", "desc": "Defesa Civil e infraestrutura urbana."},
    "i-Fiscal": {"img": "i_fiscal.png", "desc": "Gestão fiscal e execução financeira."},
    "ieg-m": {"img": "i_iegmfinal.png", "desc": "Faixa e Pontuação do IEG-M final"}, 
    "Relatório de Atividades": {"img": "relatorio_atividade.png", "desc": "Monitoramento do PPA"},
    "Plano de Ação": {"img": "plano_acao.png", "desc": "Plano de Ação Corretiva e Metas Estratégicas"},
    "Área de treinamento": {"img": "treinamento.png", "desc": "Área de treinamento e capacitação de pessoal."}
}

def login_page():
    """Página de login."""
    col1, col2, col3 = st.columns([1.1, 1.6, 1.1]) 
    with col2:
        logo_b64 = get_image_base64("iegm.png")
        if logo_b64:
            st.markdown(f'<div style="text-align:center; margin-bottom:20px;"><img src="{logo_b64}" style="max-width:100%; height:auto;"></div>', unsafe_allow_html=True)
        else:
            st.markdown("<div style='padding: 20px;'></div>", unsafe_allow_html=True)

        st.markdown('<div class="cad-frame"><h3 style="text-align: center; color: #FFFFFF; font-size: 16px; margin: 0;">Sistema de Preenchimento do IEG-M</h3></div>', unsafe_allow_html=True)
        username = st.text_input("👤 Usuário", placeholder="jefferson.espanha", key="login_username").strip()
        password = st.text_input("🔐 Senha", type="password", placeholder="••••••••", key="login_password")

        if st.button("🔓 ENTRAR NO SISTEMA", use_container_width=True, key="real_login_btn"):
            if username in st.session_state.users_db and st.session_state.users_db[username]["senha"] == password:
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = "admin" if username == "jefferson.espanha" else "user"
                
                if password == "pmfm1234" and username != "jefferson.espanha":
                    st.session_state.needs_password_change = True
                else:
                    st.session_state.current_page = "dashboard"
                st.rerun()
            elif username == "" or password == "":
                st.warning("⚠️ Preencha todos os campos!")
            else:
                st.error("❌ Usuário ou senha incorretos.")

        with st.expander("❓ Esqueceu sua senha?"):
            st.info("💡 Por favor, entre em contato com o administrador Jefferson Espanha para redefinir suas credenciais.")

        st.markdown("---")
        st.markdown("### 📝 Painel de Cadastro de Novos Usuários")
        with st.expander("Criar Nova Conta"):
            st.write("Apenas o administrador **jefferson.espanha** pode homologar novos acessos.")
            admin_auth_user = st.text_input("Usuário do Admin", key="reg_admin_user").strip()
            admin_auth_pass = st.text_input("Senha do Admin", type="password", key="reg_admin_pass")
            
            st.markdown("---")
            new_username = st.text_input("Nome do Novo Usuário (ex: joao.silva)", key="new_username").strip()
            new_email = st.text_input("✉️ E-mail do Usuário", key="new_email").strip()
            
            if st.button("➕ Cadastrar Usuário", use_container_width=True):
                if admin_auth_user != "jefferson.espanha" or admin_auth_pass != "fodasse":
                    st.error("❌ Credenciais de administrador incorretas.")
                elif not new_username or not new_email:
                    st.warning("⚠️ Preencha o nome de usuário e o e-mail.")
                elif new_username in st.session_state.users_db:
                    st.error("❌ Este usuário já está cadastrado.")
                else:
                    st.session_state.users_db[new_username] = {"senha": "pmfm1234", "email": new_email}
                    st.success(f"✔️ Usuário '{new_username}' cadastrado com sucesso! Senha inicial: 'pmfm1234'")

def change_password_page():
    """Tela intermediária obrigatória para alteração do primeiro acesso."""
    col1, col2, col3 = st.columns([1.1, 1.6, 1.1])
    with col2:
        st.markdown("<div style='text-align:center; padding: 20px;'><h3>🔄 Alteração Obrigatória de Senha</h3><p>Este é o seu primeiro acesso. Altere a sua senha padrão para continuar.</p></div>", unsafe_allow_html=True)
        nova_senha = st.text_input("Nova Senha", type="password", key="force_new_pass")
        confirma_senha = st.text_input("Confirme a Nova Senha", type="password", key="force_confirm_pass")
        
        if st.button("Salvar e Acessar o Sistema", use_container_width=True):
            if not nova_senha:
                st.warning("⚠️ A senha não pode ser vazia.")
            elif nova_senha == "pmfm1234":
                st.error("❌ Você não pode utilizar a senha inicial padrão.")
            elif nova_senha != confirma_senha:
                st.error("❌ As senhas não coincidem.")
            else:
                st.session_state.users_db[st.session_state.username]["senha"] = nova_senha
                st.session_state.needs_password_change = False
                st.session_state.current_page = "dashboard"
                st.success("Senha alterada com sucesso!")
                st.rerun()

def dashboard_page():
    """Página principal."""
    st.markdown(f'<div style="text-align: center; padding: 10px;"><h1 style="color: #001A4D;">IEG-M Francisco Morato</h1><p style="color: #003D99; font-weight: bold;">Bem-vindo, {st.session_state.username}!</p></div>', unsafe_allow_html=True)

    col_space, col_logout = st.columns([5, 1])
    with col_logout:
        if st.button("🚪 Sair", key="logout_btn_dash", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.current_page = "login"
            st.rerun()

    st.markdown("---")
    st.markdown("### 📅 Selecione o Ano de Referência")
    st.session_state.ano_referencia_global = st.select_slider("Ano", options=AVAILABLE_YEARS, value=st.session_state.ano_referencia_global, label_visibility="collapsed")
    st.markdown("---")

    st.markdown("### 📊 Questionários por Dimensão")
    dim_cols = st.columns(4)
    
    for idx, (dim_name, dim_info) in enumerate(DIMENSIONS_DATA.items()):
        with dim_cols[idx % 4]:
            img_b64 = get_image_base64(dim_info["img"])
            img_html = f'<img src="{img_b64}" />' if img_b64 else '<div style="font-size:42px;">📊</div>'
            
            st.markdown(f'<div class="card-container" id="card_{idx}"><div class="card-img-container">{img_html}</div><div class="card-title">{dim_name}</div><div class="card-text">{dim_info["desc"]}</div><div class="hidden-btn-container">', unsafe_allow_html=True)
            if st.button("Acessar", key=f"btn_real_{dim_name}", use_container_width=True):
                st.session_state.selected_dimension = dim_name
                st.session_state.current_page = "dimension"
                st.rerun()
            st.markdown('</div></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🛠️ Ecossistema de Gestão Avançada")
    col_hal, col_bib, col_admin = st.columns(3)

    with col_hal:
        hal_b64 = get_image_base64("hal9000.png")
        hal_html = f'<img src="{hal_b64}" />' if hal_b64 else '<div style="font-size:42px;">🔴</div>'
        st.markdown(f'<div class="card-container" style="border-bottom: 4px solid #DC2626;"><div class="card-img-container">{hal_html}</div><div class="card-title">HAL 9000 — IEG-M AI</div><div class="card-text">Assistente cognitivo inteligente.</div><div class="hidden-btn-container">', unsafe_allow_html=True)
        if st.button("Acessar", key="btn_real_hal", use_container_width=True):
            st.session_state.selected_dimension = "HAL 9000"
            st.session_state.current_page = "dimension"
            st.rerun()
        st.markdown('</div></div>', unsafe_allow_html=True)

    with col_bib:
        bib_b64 = get_image_base64("biblioteca.png")
        bib_html = f'<img src="{bib_b64}" />' if bib_b64 else '<div style="font-size:42px;">📁</div>'
        st.markdown(f'<div class="card-container" style="border-bottom: 4px solid #003D99;"><div class="card-img-container">{bib_html}</div><div class="card-title">Biblioteca Digital</div><div class="card-text">Repositório de gerenciamento de arquivos.</div><div class="hidden-btn-container">', unsafe_allow_html=True)
        if st.button("Acessar", key="btn_real_bib", use_container_width=True):
            st.session_state.selected_dimension = "Biblioteca"
            st.session_state.current_page = "dimension"
            st.rerun()
        st.markdown('</div></div>', unsafe_allow_html=True)

    with col_admin:
        admin_b64 = get_image_base64("administrador.png")
        admin_html = f'<img src="{admin_b64}" />' if admin_b64 else '<div style="font-size:42px;">🔒</div>'
        st.markdown(f'<div class="card-container" style="border-bottom: 4px solid #10B981;"><div class="card-img-container">{admin_html}</div><div class="card-title">Área do Administrador</div><div class="card-text">Gestão de acessos, e-mails e relatórios consolidados.</div><div class="hidden-btn-container">', unsafe_allow_html=True)
        if st.button("Acessar", key="btn_real_admin", use_container_width=True):
            st.session_state.selected_dimension = "Administrador"
            st.session_state.current_page = "dimension"
            st.rerun()
        st.markdown('</div></div>', unsafe_allow_html=True)

def dimension_page():
    """Página de exibição dinâmica."""
    st.markdown("<script>setTimeout(function() { window.scrollTo(0, 0); }, 100);</script>", unsafe_allow_html=True)
    
    dimension = st.session_state.selected_dimension
    year = st.session_state.ano_referencia_global

    col_back, col_title, col_logout = st.columns([1, 4, 1])
    with col_back:
        if st.button("⬅️ Voltar", key="back_to_dash", use_container_width=True):
            st.session_state.current_page = "dashboard"
            st.rerun()
    with col_title:
        st.markdown(f"<div style='text-align: center;'><h2 style='color: #001A4D;'>{dimension} - {year}</h2></div>", unsafe_allow_html=True)
    with col_logout:
        if st.button("🚪 Sair", key="logout_btn_dim", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.current_page = "login"
            st.rerun()

    st.markdown("---")

    # Roteamento central das subpáginas do ecossistema
    if dimension == "Administrador":
        if admin_core:
            admin_core.mostrar_painel_admin(year)
        else:
            st.error("Erro técnico: O arquivo 'administrador.py' não foi detectado no sistema.")
    elif dimension == "Biblioteca":
        st.subheader("📁 Biblioteca de Evidências e Documentos do IEG-M")
        if bib_core:
            bib_core.gerenciar_upload_e_arquivos()
        else:
            st.error("Erro: Módulo 'biblioteca.py' não localizado.")
            
    # --- MODIFICADO: Bloco dinâmico do HAL 9000 buscando de hal.py ---
    elif dimension == "HAL 9000":
        st.subheader("🔴 HAL 9000 — Inteligência Artificial")
        if hal_core:
            if hasattr(hal_core, 'mostrar_chat_hal'):
                hal_core.mostrar_chat_hal()
            elif hasattr(hal_core, 'main'):
                hal_core.main()
            else:
                st.warning("Módulo 'hal.py' carregado, mas nenhuma função de renderização conhecida ('mostrar_chat_hal' ou 'main') foi encontrada.")
                st.chat_input("Como posso ajudar hoje? (Modo de Segurança)")
        else:
            st.error("Erro técnico: O arquivo 'hal.py' não foi detectado no sistema.")
            st.chat_input("Como posso ajudar hoje? (Modo Offline)")
            
    elif dimension == "i-Cidade" and icidade:
        icidade.init_db()
        icidade.mostrar_formulario_cidade()
    elif dimension == "i-Gov TI" and igov:
        igov.mostrar_formulario_gov()
    elif dimension == "i-Amb" and iamb:
        iamb.mostrar_formulario_amb()
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
            
    # --- CORRIGIDO: Nome correspondente ao card "Relatório de Atividades" ---
    elif dimension == "Relatório de Atividades":
        if atividade:
            if hasattr(atividade, 'mostrar_formulario_atividade'):
                atividade.mostrar_formulario_atividade()
            else:
                st.warning("Módulo 'atividade.py' carregado, mas a função 'mostrar_formulario_atividade' não foi encontrada.")
        else:
            st.error("Erro: Módulo 'atividade.py' não localizado.")
            
    # --- CORRIGIDO: Nome correspondente ao card "Plano de Ação" ---
    elif dimension == "Plano de Ação":
        if plano_acao:
            if hasattr(plano_acao, 'mostrar_formulario_plano_acao'):
                plano_acao.mostrar_formulario_plano_acao()
            elif hasattr(plano_acao, 'mostrar_painel_plano_acao'):
                plano_acao.mostrar_painel_plano_acao()
            else:
                st.warning("Módulo carregado, mas a função de renderização padrão não foi encontrada.")
        else:
            st.error("Erro: Módulo 'plano_acao.py' não localizado.")

    # --- INTEGRADO: Bloco dinâmico correspondente ao card "Área de treinamento" ---
    elif dimension == "Área de treinamento":
        st.subheader("🎓 Área de Treinamento e Capacitação")
        if treinamento:
            if hasattr(treinamento, 'mostrar_painel_treinamento'):
                treinamento.mostrar_painel_treinamento()
            elif hasattr(treinamento, 'mostrar_formulario_treinamento'):
                treinamento.mostrar_formulario_treinamento()
            elif hasattr(treinamento, 'main'):
                treinamento.main()
            else:
                st.warning("Módulo 'treinamento.py' carregado, mas nenhuma função de renderização padrão foi detectada.")
        else:
            st.error("Erro técnico: O arquivo 'treinamento.py' não foi detectado no sistema.")
            
    else:
        st.info(f"Módulo {dimension} pronto para integração.")

# Gerenciador de Estado de Telas do Streamlit
if not st.session_state.authenticated:
    login_page()
else:
    if st.session_state.needs_password_change:
        change_password_page()
    elif st.session_state.current_page == "dashboard":
        dashboard_page()
    elif st.session_state.current_page == "dimension":
        dimension_page()