import logging
import pandas as pd
import streamlit as st

# Tenta importar a conexão global do seu projeto PostgreSQL
# Substitua 'database' pelo módulo correto onde está definida a sua função get_connection() se necessário
try:
    from database import get_connection
except ImportError:
    try:
        from db import get_connection
    except ImportError:

        def get_connection():
            raise NotImplementedError(
                "Função get_connection() não encontrada. Verifique os imports do seu projeto PostgreSQL."
            )


def consultar_soma_pontos_pg(nome_tabela: str, ano: int) -> float:
    """Busca no PostgreSQL a soma dos pontos de uma dimensão específica para determinado ano.

    Suporta tabelas exclusivas (ex: respostas_igov) ou genéricas (ex:
    respostas).
    """
    try:
        ano_int = int(ano)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Tenta buscar na tabela exclusiva informada
                query = f"SELECT SUM(pontos) FROM {nome_tabela} WHERE ano = %s AND id NOT LIKE 'COM_%%'"
                try:
                    cursor.execute(query, (ano_int,))
                    resultado = cursor.fetchone()
                    if resultado and resultado[0] is not None:
                        return float(resultado[0])
                except Exception:
                    # Se a tabela exclusiva não existir, tenta a tabela genérica 'respostas' filtrando por dimensão se aplicável
                    conn.rollback()
                    query_fallback = "SELECT SUM(pontos) FROM respostas WHERE ano = %s AND id NOT LIKE 'COM_%%'"
                    cursor.execute(query_fallback, (ano_int,))
                    resultado = cursor.fetchone()
                    if resultado and resultado[0] is not None:
                        return float(resultado[0])
    except Exception as e:
        logging.error(
            f"Erro ao consultar pontos na tabela {nome_tabela} para o ano {ano}: {e}"
        )

    return 0.0


# =============================================================================
# CARREGAMENTO DAS NOTAS POR DIMENSÃO (POSTGRESQL)
# =============================================================================


def puxar_nota_iplan(ano: int) -> int:
    pts = consultar_soma_pontos_pg("respostas_iplan", ano)
    return int(round(pts))


def puxar_nota_ifiscal(ano: int) -> int:
    """Acessa a tabela respostas_ifiscal aplicando a regra de rebaixamento crítico."""
    try:
        ano_int = int(ano)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                query = "SELECT pontos FROM respostas_ifiscal WHERE ano = %s"
                try:
                    cursor.execute(query, (ano_int,))
                except Exception:
                    conn.rollback()
                    cursor.execute(
                        "SELECT pontos FROM respostas WHERE ano = %s",
                        (ano_int,),
                    )

                linhas = cursor.fetchall()

                if not linhas:
                    return 0

                valores = [float(r[0]) for r in linhas if r[0] is not None]

                # Se houver rebaixamento crítico (-100), a nota da dimensão vai a 0
                if any(v <= -100.0 for v in valores):
                    return 0

                total_pts = sum(v for v in valores if v > -100.0)
                return int(round(total_pts))
    except Exception as e:
        logging.error(f"Erro ao calcular i-Fiscal para o ano {ano}: {e}")
        return 0


def puxar_nota_ieduc(ano: int) -> int:
    pts = consultar_soma_pontos_pg("respostas_ieduc", ano)
    return int(round(pts))


def puxar_nota_isaude(ano: int) -> int:
    pts = consultar_soma_pontos_pg("respostas_isaude", ano)
    return int(round(pts))


def puxar_nota_iamb(ano: int) -> int:
    pts = consultar_soma_pontos_pg("respostas_iamb", ano)
    return int(round(pts))


def puxar_nota_icidade(ano: int) -> int:
    pts = consultar_soma_pontos_pg("respostas_icidade", ano)
    return int(round(pts))


def puxar_nota_igov(ano: int) -> int:
    pts = consultar_soma_pontos_pg("respostas_igov", ano)
    return int(round(pts))


# =============================================================================
# CÁLCULOS E CLASSIFICAÇÃO OFICIAL TCESP
# =============================================================================


def calcular_nota_final(
    plan: float,
    fiscal: float,
    educ: float,
    saude: float,
    amb: float,
    cidade: float,
    gov: float,
) -> int:
    """Calcula a Média Ponderada oficial do IEG-M TCESP (escala 0 a 1000)."""
    try:
        soma_ponderada = (
            (float(plan) * 20)
            + (float(fiscal) * 20)
            + (float(educ) * 20)
            + (float(saude) * 20)
            + (float(amb) * 10)
            + (float(cidade) * 5)
            + (float(gov) * 5)
        )
        nota_final = soma_ponderada / 100.0
        return int(round(nota_final))
    except Exception:
        return 0


def obter_faixa_classificacao(nota: int):
    """Retorna a classificação oficial do TCESP com base na nota acumulada."""
    if nota >= 900:
        return "A (Altamente Efetiva)", "#10B981"
    elif nota >= 750:
        return "B+ (Muito Efetiva)", "#3B82F6"
    elif nota >= 600:
        return "B (Efetiva)", "#F59E0B"
    elif nota >= 500:
        return "C+ (Em Fase de Adequação)", "#F97316"
    else:
        return "C (Baixo Nível de Adequação)", "#EF4444"


# =============================================================================
# COMPONENTE VISUAL DO STREAMLIT
# =============================================================================


def mostrar_painel_iegm_final(ano_selecionado: int):
    st.subheader(
        "🏆 Consolidação do Índice de Efetividade da Gestão Municipal (IEG-M)"
    )

    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    registro_historico = []

    # Extrai os dados reais gravados no PostgreSQL
    for ano in anos:
        plan = puxar_nota_iplan(ano)
        fiscal = puxar_nota_ifiscal(ano)
        educ = puxar_nota_ieduc(ano)
        saude = puxar_nota_isaude(ano)
        amb = puxar_nota_iamb(ano)
        cidade = puxar_nota_icidade(ano)
        gov = puxar_nota_igov(ano)

        nota_f = calcular_nota_final(
            plan, fiscal, educ, saude, amb, cidade, gov
        )
        faixa, cor = obter_faixa_classificacao(nota_f)

        registro_historico.append(
            {
                "Ano": ano,
                "i-Plan": plan,
                "i-Fiscal": fiscal,
                "i-Educ": educ,
                "i-Saúde": saude,
                "i-Amb": amb,
                "i-Cidade": cidade,
                "i-Gov TI": gov,
                "Nota Final": nota_f,
                "Faixa": faixa.split(" (")[0],
            }
        )

    df_historico = pd.DataFrame(registro_historico)

    # Cálculo da variação percentual
    variacoes = ["-"]
    for i in range(1, len(df_historico)):
        nota_ant = df_historico.loc[i - 1, "Nota Final"]
        nota_at = df_historico.loc[i, "Nota Final"]

        if nota_ant == 0:
            if nota_at > 0:
                variacoes.append("▲ +100.0%")
            else:
                variacoes.append("0.0%")
        else:
            pct = ((nota_at - nota_ant) / nota_ant) * 100
            if pct > 0:
                variacoes.append(f"▲ +{pct:.1f}%")
            elif pct < 0:
                variacoes.append(f"▼ {pct:.1f}%")
            else:
                variacoes.append("0.0%")

    df_historico["Variação %"] = variacoes

    # Reordenar colunas
    colunas_ordenadas = [
        "Ano",
        "i-Plan",
        "i-Fiscal",
        "i-Educ",
        "i-Saúde",
        "i-Amb",
        "i-Cidade",
        "i-Gov TI",
        "Nota Final",
        "Variação %",
        "Faixa",
    ]
    df_historico = df_historico[colunas_ordenadas]

    # Filtra dados do ano selecionado
    df_ano_atual = df_historico[df_historico["Ano"] == int(ano_selecionado)]

    if not df_ano_atual.empty:
        dados_ano_atual = df_ano_atual.iloc[0]
    else:
        dados_ano_atual = df_historico.iloc[0]

    nota_f_atual = dados_ano_atual["Nota Final"]
    faixa_atual, cor_atual = obter_faixa_classificacao(nota_f_atual)

    st.markdown("---")
    st.markdown(
        f"### Resultado Consolidado Real: Ano de Referência {ano_selecionado}"
    )

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.metric(
            label="Nota Final Calculada", value=f"{int(nota_f_atual)} pts"
        )
    with c2:
        st.markdown("**Faixa TCESP:**")
        st.markdown(
            f"<div style='padding: 8px; border-radius: 8px; background-color: {cor_atual}; color: white; text-align: center; font-weight: bold;'>{faixa_atual}</div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.info(
            "💡 **Fórmula TCESP Multiplicada:** `(i-Plan×20 + i-Fiscal×20 + i-Educ×20 + i-Saúde×20 + i-Amb×10 + i-Cidade×5 + i-Gov TI×5) / 100`"
        )

    st.markdown("#### Desempenho das Dimensões (Escala 0-1000)")
    dados_tabela_atual = pd.DataFrame(
        {
            "Dimensão": [
                "i-Plan",
                "i-Fiscal",
                "i-Educ",
                "i-Saúde",
                "i-Amb",
                "i-Cidade",
                "i-Gov TI",
            ],
            "Peso TCESP": ["20%", "20%", "20%", "20%", "10%", "5%", "5%"],
            "Pontuação Obtida": [
                dados_ano_atual["i-Plan"],
                dados_ano_atual["i-Fiscal"],
                dados_ano_atual["i-Educ"],
                dados_ano_atual["i-Saúde"],
                dados_ano_atual["i-Amb"],
                dados_ano_atual["i-Cidade"],
                dados_ano_atual["i-Gov TI"],
            ],
        }
    )

    # Tabela com dados centralizados
    st.dataframe(
        dados_tabela_atual.style.set_properties(
            **{"text-align": "center"}
        ).hide(axis="index"),
        use_container_width=True,
    )

    st.markdown("---")
    st.markdown("### 📊 Painel Evolutivo — Série Histórica Real (2023 a 2030)")

    # Gráfico de Barras Evolutivo
    df_grafico = df_historico.set_index("Ano")[["Nota Final"]]
    st.bar_chart(df_grafico)

    st.markdown("#### 📅 Matriz de Dados Históricos Consolidados")

    # Exibição da Matriz de Dados Históricos Centralizada
    df_exibicao = df_historico.set_index("Ano")
    st.dataframe(
        df_exibicao.style.set_properties(**{"text-align": "center"}),
        use_container_width=True,
    )
