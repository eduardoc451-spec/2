import streamlit as st
import re
import json
import os

# Caminho para o arquivo que guardará os vídeos permanentemente
ARQUIVO_BD = "banco_videos_treinamento.json"

def extrair_video_id(url):
    """
    Função auxiliar para extrair o ID de um vídeo do YouTube a partir de diversos formatos de URL.
    """
    regex = r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^#\&\?]+)'
    match = re.match(regex, url)
    if match:
        return match.group(4)
    return None

def carregar_videos_salvos():
    """Carrega os vídeos do arquivo JSON ou retorna a lista padrão caso não exista."""
    if os.path.exists(ARQUIVO_BD):
        try:
            with open(ARQUIVO_BD, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
            
    # Lista padrão inicial caso o arquivo ainda não exista
    return [
        {
            "titulo": "Introdução ao IEG-M — Conceitos Básicos",
            "id": "dQw4w9WgXcQ",
            "desc": "Entenda as regras gerais e como funciona a consolidação das notas."
        }
    ]

def salvar_videos_no_arquivo(lista_videos):
    """Grava a lista de vídeos de forma permanente no arquivo JSON."""
    try:
        with open(ARQUIVO_BD, "w", encoding="utf-8") as f:
            json.dump(lista_videos, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Erro ao salvar dados localmente: {e}")

def inicializar_banco_treinamento():
    """Inicializa a sessão do Streamlit carregando os dados persistidos."""
    if "videos_treinamento" not in st.session_state:
        st.session_state.videos_treinamento = carregar_videos_salvos()

def mostrar_painel_treinamento():
    """Função principal chamada pelo main.py para renderizar a tela de treinamentos."""
    inicializar_banco_treinamento()
    
    # Customização CSS para os cards de vídeo ficarem uniformes e elegantes
    st.markdown(
        """
        <style>
        .video-card {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
            transition: transform 0.2s ease;
        }
        .video-card:hover {
            transform: scale(1.02);
            border-color: #003D99;
        }
        .video-title {
            color: #001A4D;
            font-size: 14px;
            font-weight: bold;
            margin-top: 8px;
            margin-bottom: 4px;
            min-height: 40px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .video-desc {
            color: #64748B;
            font-size: 12px;
            line-height: 1.3;
            min-height: 35px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown("Gerencie e assista aos tutoriais de capacitação para o preenchimento dos índices do município.")

    # --- ABA ADMIN: Apenas o Jefferson ou administradores podem cadastrar novos vídeos ---
    if st.session_state.get("role") == "admin":
        with st.expander("➕ Painel do Administrador: Cadastrar Novo Vídeo Tutorial"):
            novo_titulo = st.text_input("Título do Vídeo", placeholder="Ex: Tutorial Avançado i-Gov TI")
            nova_url = st.text_input("Link do Vídeo do YouTube", placeholder="https://www.youtube.com/watch?v=...")
            nova_desc = st.text_area("Breve descrição sobre o que o vídeo ensina", placeholder="Ex: Passo a passo para responder a seção de segurança da informação.")
            
            if st.button("💾 Salvar Vídeo Permanentemente", use_container_width=True):
                video_id = extrair_video_id(nova_url)
                if not novo_titulo or not video_id:
                    st.error("❌ Por favor, preencha o título e insira uma URL válida do YouTube.")
                else:
                    # Adiciona na memória local
                    st.session_state.videos_treinamento.append({
                        "titulo": novo_titulo,
                        "id": video_id,
                        "desc": nova_desc
                    })
                    # Grava no arquivo JSON para nunca mais sumir
                    salvar_videos_no_arquivo(st.session_state.videos_treinamento)
                    
                    st.success(f"✔️ Vídeo '{novo_titulo}' salvo com sucesso no banco de dados local!")
                    st.rerun()

    st.markdown("---")

    # --- GRID DE EXIBIÇÃO DOS VÍDEOS ---
    videos = st.session_state.videos_treinamento

    if not videos:
        st.info("Nenhum vídeo cadastrado no momento.")
        return

    # Organiza em colunas (3 vídeos por linha)
    cols = st.columns(3)
    
    for idx, vid in enumerate(videos):
        with cols[idx % 3]:
            thumbnail_url = f"https://img.youtube.com/vi/{vid['id']}/hqdefault.jpg"
            video_embed_url = f"https://www.youtube.com/watch?v={vid['id']}"
            
            st.markdown(
                f"""
                <div class="video-card">
                    <a href="{video_embed_url}" target="_blank">
                        <img src="{thumbnail_url}" style="width:100%; border-radius: 8px; object-fit: cover;" alt="Miniatura">
                    </a>
                    <div class="video-title">{vid['titulo']}</div>
                    <div class="video-desc">{vid['desc']}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            with st.popover("📺 Assistir por aqui", use_container_width=True):
                st.video(f"https://www.youtube.com/watch?v={vid['id']}")
            
            # Ao excluir, também atualiza o arquivo físico
            if st.session_state.get("role") == "admin":
                if st.button(f"🗑️ Excluir", key=f"del_{idx}", use_container_width=True):
                    st.session_state.videos_treinamento.pop(idx)
                    salvar_videos_no_arquivo(st.session_state.videos_treinamento)
                    st.success("Vídeo removido do histórico permanente.")
                    st.rerun()