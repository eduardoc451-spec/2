import json
import os
import re
import streamlit as st

# Caminho para o arquivo que guardará os vídeos permanentemente
ARQUIVO_BD = "banco_videos_treinamento.json"


def extrair_video_id(url: str):
  """Função auxiliar otimizada para extrair o ID do YouTube via Regex."""
  regex = (
      r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^#\&\?]+)"
  )
  match = re.match(regex, url)
  return match.group(4) if match else None


@st.cache_data(show_spinner=False)
def carregar_videos_salvos():
  """Carrega os vídeos do disco com cache ativo para maximizar a velocidade."""
  if os.path.exists(ARQUIVO_BD):
    try:
      with open(ARQUIVO_BD, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      pass

  # Lista padrão caso o arquivo não exista
  return [{
      "titulo": "Introdução ao IEG-M — Conceitos Básicos",
      "id": "dQw4w9WgXcQ",
      "desc": (
          "Entenda as regras gerais e como funciona a consolidação das notas."
      ),
  }]


def salvar_videos_no_arquivo(lista_videos):
  """Grava a lista de vídeos no arquivo JSON e limpa o cache para atualização rápida."""
  try:
    with open(ARQUIVO_BD, "w", encoding="utf-8") as f:
      json.dump(lista_videos, f, ensure_ascii=False, indent=4)
    # Limpa o cache para forçar a releitura imediata do arquivo atualizado
    carregar_videos_salvos.clear()
  except Exception as e:
    st.error(f"Erro ao salvar dados localmente: {e}")


def inicializar_banco_treinamento():
  """Carrega o estado da sessão caso ainda não exista."""
  if "videos_treinamento" not in st.session_state:
    st.session_state.videos_treinamento = carregar_videos_salvos()


def mostrar_painel_treinamento():
  """Função principal chamada pelo aplicativo para renderizar a área de treinamento rápida."""
  inicializar_banco_treinamento()

  # CSS Minificado e ultra-leve
  st.markdown(
      """
        <style>
        .video-card {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 12px;
            margin-bottom: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
            transition: transform 0.15s ease-in-out;
        }
        .video-card:hover {
            transform: translateY(-2px);
            border-color: #003D99;
        }
        .video-title {
            color: #001A4D;
            font-size: 14px;
            font-weight: bold;
            margin-top: 8px;
            margin-bottom: 4px;
            min-height: 38px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .video-desc {
            color: #64748B;
            font-size: 12px;
            line-height: 1.3;
            min-height: 32px;
        }
        </style>
        """,
      unsafe_allow_html=True,
  )

  st.caption(
      "Gerencie e assista aos tutoriais de capacitação para o preenchimento dos"
      " índices do município."
  )

  # --- PAINEL DO ADMINISTRADOR ---
  if st.session_state.get("role") == "admin":
    with st.expander(
        "➕ Painel do Administrador: Cadastrar Novo Vídeo Tutorial"
    ):
      with st.form("form_novo_video", clear_on_submit=True):
        novo_titulo = st.text_input(
            "Título do Vídeo", placeholder="Ex: Tutorial Avançado i-Gov TI"
        )
        nova_url = st.text_input(
            "Link do Vídeo do YouTube",
            placeholder="https://www.youtube.com/watch?v=...",
        )
        nova_desc = st.text_area(
            "Breve descrição sobre o que o vídeo ensina",
            placeholder=(
                "Ex: Passo a passo para responder a seção de segurança da"
                " informação."
            ),
        )

        btn_salvar = st.form_submit_button(
            "💾 Salvar Vídeo Permanentemente", use_container_width=True
        )

        if btn_salvar:
          video_id = extrair_video_id(nova_url)
          if not novo_titulo or not video_id:
            st.error(
                "❌ Por favor, preencha o título e insira uma URL válida do"
                " YouTube."
            )
          else:
            st.session_state.videos_treinamento.append({
                "titulo": novo_titulo,
                "id": video_id,
                "desc": nova_desc,
            })
            salvar_videos_no_arquivo(st.session_state.videos_treinamento)
            st.success(f"✔️ Vídeo '{novo_titulo}' salvo com sucesso!")
            st.rerun()

  st.markdown("---")

  # --- GRID DE EXIBIÇÃO DE VÍDEOS ---
  videos = st.session_state.videos_treinamento

  if not videos:
    st.info("Nenhum vídeo cadastrado no momento.")
    return

  # Renderização otimizada em blocos de 3 colunas
  cols = st.columns(3)

  for idx, vid in enumerate(videos):
    with cols[idx % 3]:
      thumbnail_url = f"https://img.youtube.com/vi/{vid['id']}/hqdefault.jpg"
      video_url = f"https://www.youtube.com/watch?v={vid['id']}"

      st.markdown(
          f"""
                <div class="video-card">
                    <a href="{video_url}" target="_blank">
                        <img src="{thumbnail_url}" style="width:100%; border-radius: 8px; object-fit: cover; aspect-ratio: 16/9;" alt="Thumbnail">
                    </a>
                    <div class="video-title">{vid['titulo']}</div>
                    <div class="video-desc">{vid['desc']}</div>
                </div>
                """,
          unsafe_allow_html=True,
      )

      # Modal sob demanda (só carrega o player do YouTube quando o usuário clica)
      with st.popover("📺 Assistir", use_container_width=True):
        st.video(video_url)

      # Apenas para Administradores
      if st.session_state.get("role") == "admin":
        if st.button(
            "🗑️ Excluir",
            key=f"del_vid_{idx}",
            use_container_width=True,
            type="secondary",
        ):
          st.session_state.videos_treinamento.pop(idx)
          salvar_videos_no_arquivo(st.session_state.videos_treinamento)
          st.rerun()


if __name__ == "__main__":
  # Execução de teste
  mostrar_painel_treinamento()
