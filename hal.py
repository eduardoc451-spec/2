import psycopg2
import psycopg2.extras
import streamlit as st

# URL DIRETA DO BANCO NEON
NEON_URI = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"


def criar_conexao_direta():
    """Conecta diretamente ao banco de dados Neon."""
    try:
        conn = psycopg2.connect(NEON_URI)
        return conn, None
    except Exception as e:
        return None, str(e)


class SistemaHAL:

    def __init__(self):
        self.questoes_por_dimensao = {}
        self.carregar_dicionarios_globais()

    def carregar_dicionarios_globais(self):
        # Apenas iCidade configurado para este teste
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": (
                    "Foi criada a Coordenadoria Municipal de Proteção e Defesa"
                    " Civil (COMPDEC)..."
                ),
                "1.3": (
                    "A COMPDEC ou órgão similar está associada ou subordinada"
                    " a qual secretaria/diretoria?"
                ),
            }
        }

    def get_db_connection(self):
        return criar_conexao_direta()

    def get_dimensoes(self):
        return list(self.questoes_por_dimensao.keys())

    def get_quesitos_por_dimensao(self, dimensao):
        if dimensao in self.questoes_por_dimensao:
            return [
                f"{codigo} - {texto}"
                for codigo, texto in self.questoes_por_dimensao[
                    dimensao
                ].items()
            ]
        return []

    def get_resposta_municipio(self, dimensao, codigo_quesito, ano):
        """Busca a resposta focando apenas em iCidade (tabela respostas_iplan)."""

        if dimensao != "iCidade":
            return {
                "resposta": "Dimensão em teste",
                "detalhes": "Apenas a dimensão iCidade está ativa no momento.",
                "pontuacao_obtida": 0,
            }

        tabela = "respostas_iplan"

        conn, erro = criar_conexao_direta()
        if not conn:
            return {
                "resposta": "Sem conexão",
                "detalhes": f"Erro de conexão com o Neon: {erro}",
                "pontuacao_obtida": 0,
            }

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                # Usamos SELECT * para ler todas as colunas independente do nome exato
                query = f"SELECT * FROM {tabela} WHERE id = %s AND ano = %s;"
                cur.execute(query, (str(codigo_quesito), int(ano)))
                resultado = cur.fetchone()

                if resultado:
                    # Converte a linha do banco para dicionário
                    dados = dict(resultado)

                    # Busca a resposta (tenta as colunas 'valor', 'resposta' ou 'texto')
                    resp_val = (
                        dados.get("valor")
                        or dados.get("resposta")
                        or dados.get("texto")
                        or "Resposta cadastrada sem texto"
                    )

                    # Busca os pontos (tenta 'pontos' ou 'pontuacao')
                    pontos_val = dados.get("pontos", dados.get("pontuacao", 0))

                    # Trata o link e comentários
                    link = dados.get("link")
                    comentarios = dados.get("comentarios")

                    detalhe_texto = []
                    if link and str(link) not in ["EMPTY_STRING", "None", ""]:
                        detalhe_texto.append(f"Link: {link}")

                    if comentarios and str(comentarios) not in [
                        "EMPTY_STRING",
                        "[]",
                        "None",
                        "",
                    ]:
                        detalhe_texto.append(f"Comentários: {comentarios}")

                    txt_detalhes = (
                        " | ".join(detalhe_texto)
                        if detalhe_texto
                        else "Sem observações adicionais."
                    )

                    return {
                        "resposta": resp_val,
                        "detalhes": txt_detalhes,
                        "pontuacao_obtida": pontos_val,
                    }
                else:
                    return {
                        "resposta": "Sem registro",
                        "detalhes": (
                            f"Nenhum registro encontrado em {tabela} para o"
                            f" item {codigo_quesito} no ano {ano}."
                        ),
                        "pontuacao_obtida": 0,
                    }
        except Exception as e:
            return {
                "resposta": "Erro na consulta",
                "detalhes": f"Erro SQL ao consultar {tabela}: {e}",
                "pontuacao_obtida": 0,
            }
        finally:
            if conn:
                conn.close()


def mostrar_chat_hal():
    st.title("🤖 Assistente HAL - Teste iCidade")

    if "sistema_hal" not in st.session_state:
        st.session_state.sistema_hal = SistemaHAL()

    sistema = st.session_state.sistema_hal

    with st.expander("🔌 Status da Conexão com o Banco", expanded=False):
        conn, erro_conexao = criar_conexao_direta()
        if conn:
            st.success("✅ Conectado ao PostgreSQL (Neon) com sucesso!")
            conn.close()
        else:
            st.error("❌ Falha ao conectar no banco Neon!")
            st.code(f"Erro: {erro_conexao}", language="bash")

    st.subheader("📊 Consulta por Dimensão e Quesito")

    lista_dimensoes = sistema.get_dimensoes()
    lista_anos = [2026, 2025, 2024, 2023]

    col1, col2, col3 = st.columns([1, 2.5, 1])

    with col1:
        dimensao_sel = st.selectbox("Dimensão:", options=lista_dimensoes)

    with col2:
        lista_quesitos_formatados = sistema.get_quesitos_por_dimensao(
            dimensao_sel
        )
        quesito_formatado_sel = st.selectbox(
            "Quesito / Pergunta:", options=lista_quesitos_formatados
        )
        codigo_quesito_sel = (
            quesito_formatado_sel.split(" - ")[0]
            if quesito_formatado_sel
            else ""
        )

    with col3:
        ano_sel = st.selectbox("Ano:", options=lista_anos)

    if quesito_formatado_sel:
        dados_resposta = sistema.get_resposta_municipio(
            dimensao_sel, codigo_quesito_sel, ano_sel
        )

        with st.container(border=True):
            st.markdown(f"### 📍 Resposta do Município ({ano_sel})")
            st.caption(f"**Item:** {quesito_formatado_sel}")
            st.divider()

            col_res1, col_res2 = st.columns([3, 1])
            with col_res1:
                st.write(
                    "**Resposta Cadastrada:**"
                    f" {dados_resposta.get('resposta', 'Sem registro')}"
                )
                st.write(
                    "**Detalhamento:**"
                    f" {dados_resposta.get('detalhes', 'Sem observações')}"
                )
            with col_res2:
                pontos = dados_resposta.get("pontuacao_obtida", 0)
                st.metric("Pontuação", pontos)


if __name__ == "__main__":
    mostrar_chat_hal()
