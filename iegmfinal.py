import logging
import pandas as pd
import streamlit as st

# Importa a classe get_connection do seu arquivo icidade_completo.py
try:
    from icidade_completo import get_connection
except ImportError as e:
    logging.error(f"Erro ao importar get_connection do icidade_completo: {e}")

    def get_connection():
        raise ImportError(
            "Não foi possível importar 'get_connection' de 'icidade_completo.py'."
        )


def buscar_pontuacao_dimensao(tabela: str, ano: int) -> float:
    """Consulta a soma REAL de pontos na tabela da dimensão correspondente

    sem multiplicadores arbitrários de escala.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                sql = f"SELECT COALESCE(SUM(pontos), 0) FROM {tabela} WHERE ano = %s;"
                cursor.execute(sql, (int(ano),))
                res = cursor.fetchone()

                if res and res[0] is not None:
                    return float(res[0])
    except Exception as e:
        logging.warning(
            f"[IEG-M Final] Erro ao ler tabela '{tabela}' para ano {ano}: {e}"
        )

    return 0.0


# =============================================================================
# FUNÇÕES DE LEITURA ESPECÍFICAS
# =============================================================================


def puxar_nota_iplan(ano: int) -> float:
    return buscar_pontuacao_dimensao("respostas_iplan", ano)


def puxar_nota_ifiscal(ano: int) -> float:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                sql = "SELECT pontos FROM respostas_ifiscal WHERE ano = %s;"
                cursor.execute(sql, (int(ano),))
                rows = cursor.fetchall()

                if not rows:
                    return 0.0

                pontos_lista = [float(r[0]) for r in rows if r[0] is not None]

                # Regra de rebaixamento crítico TCESP (se houver item crítico reprovado <= -100)
                if any(p <= -100.0 for p in pontos_lista):
                    return 0.0

                total = sum(p for p in pontos_lista if p > -100.0)
                return float(total)
    except Exception as e:
        logging.warning(f"[i-Fiscal] Falha ao ler ano {ano}: {e}")
        return 0.0


def puxar_nota_ieduc(ano: int) -> float:
    return buscar_pontuacao_dimensao("respostas_ieduc", ano)


def puxar_nota_isaude(ano: int) -> float:
    return buscar_pontuacao_dimensao("respostas_isaude", ano)


def puxar_nota_iamb(ano: int) -> float:
    return buscar_pontuacao_dimensao("respostas_iamb", ano)


def puxar_nota_icidade(ano: int) -> float:
    pts = buscar_pontuacao_dimensao("respostas_icidade", ano)
    if pts == 0:
        pts = buscar_pontuacao_dimensao("respostas", ano)
    return pts


def puxar_nota_igov(ano: int) -> float:
    return buscar_pontuacao_dimensao("respostas_igov", ano)


# =============================================================================
# CÁLCULOS OFICIAIS TCESP
# =============================================================================


def calcular_nota_final(
    plan: float,
    fiscal: float,
    educ: float,
    saude: float,
    amb: float,
    cidade: float,
    gov: float,
) -> float:
    """Calcula a Média Ponderada oficial do IEG-M TCESP."""
    try:
        soma = (
            (float(plan) * 0.20)
            + (float(fiscal) * 0.20)
            + (float(educ) * 0.20)
            + (float(saude) * 0.20)
            + (float(amb) * 0.10)
            + (float(cidade) * 0.05)
            + (float(gov) * 0.05)
        )
        return round(soma, 1)
    except Exception:
        return 0.0


def obter_faixa_classificacao(nota: float):
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
# PAINEL PRINCIPAL STREAMLIT
# =============================================================================


def mostrar_painel_iegm_final(ano_selecionado: int):
    st.subheader(
        "🏆 Consolidação do Índice de Efetividade da Gestão Municipal (IEG-M)"
    )

    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    registro_historico = []

    # Leitura dos dados reais no Neon
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
        faixa, _ = obter_faixa_classificacao(nota_f)

        registro_historico.append(
            {
                "Ano": ano,
                "i-Plan": round(plan, 2),
                "i-Fiscal": round(fiscal, 2),
                "i-Educ": round(educ, 2),
                "i-Saúde": round(saude, 2),
                "i-Amb": round(amb, 2),
                "i-Cidade": round(cidade, 2),
                "i-Gov TI": round(gov, 2),
                "Nota Final": round(nota_f, 1),
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
            variacoes.append("▲ +100.0%" if nota_at > 0 else "0.0%")
        else:
            pct = ((nota_at - nota_ant) / nota_ant) * 100
            if pct > 0:
                variacoes.append(f"▲ +{pct:.1f}%")
            elif pct < 0:
                variacoes.append(f"▼ {pct:.1f}%")
            else:
                variacoes.append("0.0%")

    df_historico["Variação %"] = variacoes

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

    # Filtra o ano selecionado
    df_ano_atual = df_historico[df_historico["Ano"] == int(ano_selecionado)]
    dados_ano_atual = (
        df_ano_atual.iloc[0]
        if not df_ano_atual.empty
        else df_historico.iloc[0]
    )

    nota_f_atual = dados_ano_atual["Nota Final"]
    faixa_atual, cor_atual = obter_faixa_classificacao(nota_f_atual)

    st.markdown("---")
    st.markdown(
        f"### Resultado Consolidado Real: Ano de Referência {ano_selecionado}"
    )

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.metric(
            label="Nota Final Calculada",
            value=f"{dados_ano_atual['Nota Final']} pts",
        )
    with c2:
        st.markdown("**Faixa TCESP:**")
        st.markdown(
            f"<div style='padding: 8px; border-radius: 8px; background-color: {cor_atual}; color: white; text-align: center; font-weight: bold;'>{faixa_atual}</div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.info(
            "💡 **Fórmula TCESP:** `(i-Plan×0.20 + i-Fiscal×0.20 + i-Educ×0.20 + i-Saúde×0.20 + i-Amb×0.10 + i-Cidade×0.05 + i-Gov TI×0.05)`"
        )

    st.markdown("#### Desempenho Real das Dimensões")
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
                f"{dados_ano_atual['i-Plan']} pts",
                f"{dados_ano_atual['i-Fiscal']} pts",
                f"{dados_ano_atual['i-Educ']} pts",
                f"{dados_ano_atual['i-Saúde']} pts",
                f"{dados_ano_atual['i-Amb']} pts",
                f"{dados_ano_atual['i-Cidade']} pts",
                f"{dados_ano_atual['i-Gov TI']} pts",
            ],
        }
    )

    st.dataframe(
        dados_tabela_atual.style.set_properties(
            **{"text-align": "center"}
        ).hide(axis="index"),
        use_container_width=True,
    )

    st.markdown("---")
    st.markdown("### 📊 Painel Evolutivo — Série Histórica Real (2023 a 2030)")

    df_grafico = df_historico.set_index("Ano")[["Nota Final"]]
    st.bar_chart(df_grafico)

    st.markdown("#### 📅 Matriz de Dados Históricos Consolidados")
    df_exibicao = df_historico.set_index("Ano")
    st.dataframe(
        df_exibicao.style.set_properties(**{"text-align": "center"}),
        use_container_width=True,
    )

    # =========================================================================
    # DIAGNÓSTICO DO BANCO DE DADOS
    # =========================================================================
    with st.expander(
        f"🛠️ Diagnóstico do PostgreSQL/Neon (Ano {ano_selecionado})"
    ):
        tabelas_para_testar = [
            "respostas_iplan",
            "respostas_ifiscal",
            "respostas_ieduc",
            "respostas_isaude",
            "respostas_iamb",
            "respostas_icidade",
            "respostas_igov",
        ]

        relatorio_db = []
        for tab in tabelas_para_testar:
            try:
                with get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            f"SELECT COUNT(*), COALESCE(SUM(pontos), 0) FROM {tab} WHERE ano = %s;",
                            (int(ano_selecionado),),
                        )
                        qtd, soma = cursor.fetchone()
                        relatorio_db.append(
                            {
                                "Tabela": tab,
                                "Qtd Quesitos": qtd,
                                "Soma Exata do Banco": float(soma),
                                "Status": "OK",
                            }
                        )
            except Exception as err:
                relatorio_db.append(
                    {
                        "Tabela": tab,
                        "Qtd Quesitos": 0,
                        "Soma Exata do Banco": 0.0,
                        "Status": f"Erro/Ausente: {err}",
                    }
                )

        st.dataframe(pd.DataFrame(relatorio_db), use_container_width=True)
