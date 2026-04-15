"""
7_Analyse_Ventes.py - Radar Mandats V2
Croisement CRM x DPE x DVF (Ventes officielles) — OPTIMISÉ EXTRÊME (Anti-Crash)
"""

import streamlit as st
import pandas as pd
from ademe_matcher import rnvp_adresse, score_match
from ui_utils import CSS

st.markdown(CSS, unsafe_allow_html=True)

# ── 1. VERIFICATION CRM ───────────────────────────────────────────
if st.session_state.get("df_scored") is None:
    st.warning("⚠️ Chargez votre fichier CRM depuis l'accueil pour accéder aux données.")
    st.stop()

df_eval = st.session_state["df_scored"].copy()
df_mand = st.session_state.get("df_mandats", pd.DataFrame()).copy()

# Identification des départements de votre CRM pour filtrer le gros fichier DVF
cps_eval = df_eval["code_postal"].dropna().astype(str).str.zfill(5).str[:5]
cps_mand = df_mand["code_postal"].dropna().astype(str).str.zfill(5).str[:5] if not df_mand.empty else pd.Series()
tous_cps = set(cps_eval) | set(cps_mand)
deps_crm = set([cp[:2] for cp in tous_cps if len(cp) >= 2])

# ── 2. EN-TÊTE ────────────────────────────────────────────────────
st.markdown("## 🤝 Suivi des Ventes & Concurrence (DVF)")
st.markdown(
    "<span style='color:#888;font-size:13px'>"
    "Croisez votre portefeuille avec les actes de vente officiels (DVF) pour repérer les affaires vendues."
    "</span>", unsafe_allow_html=True
)
st.markdown("<hr class='sep'>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Paramètres DVF")
    seuil_match = st.slider("Score de correspondance adresse", 60, 100, 90, step=5)

# ── 3. LECTURE ANTI-CRASH (PAR BLOCS) ─────────────────────────────
def load_dvf_chunked(uploaded_file, deps_filtre):
    first_line_bytes = uploaded_file.readline()
    uploaded_file.seek(0)
    try:
        first_line = first_line_bytes.decode('utf-8')
    except UnicodeDecodeError:
        first_line = first_line_bytes.decode('latin-1')

    sep = '|' if '|' in first_line else ','
    
    headers = pd.read_csv(uploaded_file, sep=sep, nrows=0, encoding='utf-8', on_bad_lines='skip').columns
    uploaded_file.seek(0)
    
    cibles = [
        "Date mutation", "date_mutation", "Valeur fonciere", "valeur_fonciere",
        "No voie", "adresse_numero", "B/T/Q", "Indice de repetition", "adresse_suffixe",
        "Type de voie", "Voie", "adresse_nom_voie", "Code postal", "code_postal", "Commune", "nom_commune"
    ]
    cols_to_use = [c for c in headers if c in cibles]
    
    chunks = []
    reader = pd.read_csv(
        uploaded_file, sep=sep, usecols=cols_to_use, dtype=str, 
        chunksize=50000, low_memory=False, encoding='utf-8', on_bad_lines='skip'
    )
    
    for chunk in reader:
        cp_col = "Code postal" if "Code postal" in chunk.columns else ("code_postal" if "code_postal" in chunk.columns else None)
        if cp_col and deps_filtre:
            dep_series = chunk[cp_col].fillna("").astype(str).str.replace(".0", "", regex=False).str.zfill(5).str[:2]
            chunk = chunk[dep_series.isin(deps_filtre)]
        chunks.append(chunk)

    if not chunks: return pd.DataFrame(columns=cols_to_use)
    return pd.concat(chunks, ignore_index=True)

# ── 4. CHARGEMENT DVF ─────────────────────────────────────────────
st.markdown('<div class="sec">1. Charger la base des ventes (DVF)</div>', unsafe_allow_html=True)
dvf_files = st.file_uploader(
    "Importez vos exports DVF (.txt de data.gouv.fr)", 
    type=["csv", "txt"], accept_multiple_files=True, label_visibility="collapsed"
)

if dvf_files:
    if st.button("🚀 Lancer le croisement DVF", type="primary"):
        with st.spinner(f"Filtrage intelligent (Conservation des départements : {', '.join(deps_crm)})..."):
            dfs = []
            for f in dvf_files: dfs.append(load_dvf_chunked(f, deps_crm))
            df_dvf = pd.concat(dfs, ignore_index=True)

            if df_dvf.empty:
                st.error("Aucune vente trouvée dans les départements de votre CRM. Vérifiez votre fichier.")
                st.stop()

            def get_c(possible_names):
                for c in possible_names:
                    if c in df_dvf.columns: return df_dvf[c].fillna("")
                return pd.Series([""] * len(df_dvf))

            num   = get_c(["adresse_numero", "No voie"])
            suf   = get_c(["adresse_suffixe", "Indice de repetition", "B/T/Q"])
            voie  = get_c(["adresse_nom_voie", "Voie"])
            tvoie = get_c(["Type de voie"])
            cp    = get_c(["code_postal", "Code postal"])
            ville = get_c(["nom_commune", "Commune"])

            df_dvf["_addr_full"] = num + " " + suf + " " + tvoie + " " + voie + " " + cp.str[:5] + " " + ville
            df_dvf["_addr_full"] = df_dvf["_addr_full"].str.replace(r"\s+", " ", regex=True).str.strip()

            df_dvf["_date"] = pd.to_datetime(get_c(["date_mutation", "Date mutation"]), format="%d/%m/%Y", errors="coerce").combine_first(
                              pd.to_datetime(get_c(["date_mutation", "Date mutation"]), errors="coerce"))
            df_dvf["_prix"] = pd.to_numeric(get_c(["valeur_fonciere", "Valeur fonciere"]).str.replace(",", ".", regex=False), errors="coerce")
            
            df_dvf = df_dvf.sort_values("_date", ascending=False)
            df_dvf["_cp_idx"] = cp.str[:5]
            cp_index = {}
            for r in df_dvf.to_dict("records"): cp_index.setdefault(r["_cp_idx"], []).append(r)

        with st.spinner("Comparaison des adresses..."):
            cols_communes = ["nom_principal", "adresse_bien", "code_postal"]
            df_crm_global = pd.concat([
                df_eval[["id_evaluation"] + cols_communes].rename(columns={"id_evaluation": "id_crm"}).assign(source_crm="Évaluation"),
                df_mand[["id_mandat"] + cols_communes].rename(columns={"id_mandat": "id_crm"}).assign(source_crm="Mandat")
            ], ignore_index=True)

            matchs_dvf = []
            total_crm = len(df_crm_global)
            prog = st.progress(0)
            
            for i, (_, row) in enumerate(df_crm_global.iterrows()):
                if i % 50 == 0: prog.progress(min(i/total_crm, 1.0))
                addr_crm = str(row.get("adresse_bien", ""))
                cp_crm   = rnvp_adresse(addr_crm)["cp"] or str(row.get("code_postal", "")).zfill(5)[:5]
                
                best_sc, best_vente = 0, None
                for vente in cp_index.get(cp_crm, []):
                    sc, _, _ = score_match(addr_crm, vente)
                    if sc > best_sc: best_sc, best_vente = sc, vente
                        
                if best_sc >= seuil_match and best_vente:
                    matchs_dvf.append({
                        "id_crm": row["id_crm"], "source_crm": row["source_crm"],
                        "dvf_date": best_vente["_date"], "dvf_prix": best_vente["_prix"]
                    })
                    
            prog.empty()
            st.session_state["match_dvf_df"] = pd.DataFrame(matchs_dvf)
            st.session_state["dvf_has_run"] = True # Marqueur d'exécution
            st.success("Croisement terminé ! Les résultats sont affichés ci-dessous.")

# ── 5. AFFICHAGE DES RÉSULTATS (Toujours visible si exécuté) ──────
match_dvf_state = st.session_state.get("match_dvf_df")
match_dpe_state = st.session_state.get("match_crm_df")
dvf_run = st.session_state.get("dvf_has_run", False)

df_match_dvf = match_dvf_state if match_dvf_state is not None else pd.DataFrame()
df_match_dpe = match_dpe_state if match_dpe_state is not None else pd.DataFrame()

if dvf_run or match_dpe_state is not None:
    st.markdown("<br/>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["📝 Évaluations (Passées en DPE ou DVF)", "🤝 Mandats (Vendus DVF)"])

    def formater_date(d):
        if pd.isna(d): return "—"
        try: return d.strftime("%d/%m/%Y")
        except: return str(d)

    with tab1:
        res_eval = df_eval[["id_evaluation", "nom_principal", "adresse_bien", "date_estimation", "date_dernier_suivi"]].copy()
        
        if not df_match_dpe.empty:
            dpe_e = df_match_dpe[df_match_dpe["source_crm"] == "Évaluation"][["id_crm", "dpe_date"]]
            res_eval = res_eval.merge(dpe_e, left_on="id_evaluation", right_on="id_crm", how="left").drop(columns=["id_crm"], errors="ignore")
        else: res_eval["dpe_date"] = None
            
        if not df_match_dvf.empty:
            dvf_e = df_match_dvf[df_match_dvf["source_crm"] == "Évaluation"][["id_crm", "dvf_date", "dvf_prix"]]
            res_eval = res_eval.merge(dvf_e, left_on="id_evaluation", right_on="id_crm", how="left").drop(columns=["id_crm"], errors="ignore")
        else:
            res_eval["dvf_date"] = None
            res_eval["dvf_prix"] = None

        mask = res_eval["dpe_date"].notna() | res_eval["dvf_date"].notna()
        final_eval = res_eval[mask].sort_values("date_estimation", ascending=False).copy()
        
        if final_eval.empty:
            st.warning("⚠️ **Aucune correspondance trouvée !** Les adresses DVF des notaires sont souvent très mal orthographiées. **Baissez le score de correspondance (à gauche) vers 70 ou 80**, et relancez le croisement.")
        else:
            final_eval["date_estimation"] = final_eval["date_estimation"].apply(formater_date)
            final_eval["date_dernier_suivi"] = final_eval["date_dernier_suivi"].apply(formater_date)
            final_eval["dpe_date"] = final_eval["dpe_date"].apply(formater_date)
            final_eval["dvf_date"] = final_eval["dvf_date"].apply(formater_date)
            final_eval["dvf_prix"] = final_eval["dvf_prix"].apply(lambda x: f"{x:,.0f} €".replace(",", " ") if pd.notna(x) else "—")
            
            final_eval = final_eval.rename(columns={
                "nom_principal": "Dossier", "adresse_bien": "Adresse",
                "date_estimation": "Saisie Éval", "date_dernier_suivi": "Dernier Suivi",
                "dpe_date": "Date DPE", "dvf_date": "Date Transaction DVF", "dvf_prix": "Prix Transaction"
            }).drop(columns=["id_evaluation"], errors="ignore")
            
            st.markdown(f"**{len(final_eval)} évaluations** retrouvées.")
            st.dataframe(final_eval, hide_index=True, use_container_width=True)

    with tab2:
        if df_match_dvf.empty and dvf_run:
            st.warning("⚠️ **Aucun mandat trouvé.** Baissez le score de correspondance (vers 70 ou 80) dans le menu de gauche et relancez !")
        elif df_match_dvf.empty and not dvf_run:
            st.info("Lancez le croisement DVF pour voir vos mandats revendus.")
        else:
            res_mand = df_mand[["id_mandat", "nom_principal", "adresse_bien", "date_mandat", "date_dernier_suivi"]].copy()
            dvf_m = df_match_dvf[df_match_dvf["source_crm"] == "Mandat"][["id_crm", "dvf_date", "dvf_prix"]]
            res_mand = res_mand.merge(dvf_m, left_on="id_mandat", right_on="id_crm", how="left").drop(columns=["id_crm"], errors="ignore")
            
            final_mand = res_mand[res_mand["dvf_date"].notna()].sort_values("date_mandat", ascending=False).copy()
            
            if final_mand.empty:
                st.warning("⚠️ **Aucun mandat trouvé.** Baissez le score de correspondance (vers 70 ou 80) dans le menu de gauche et relancez !")
            else:
                final_mand["date_mandat"] = final_mand["date_mandat"].apply(formater_date)
                final_mand["date_dernier_suivi"] = final_mand["date_dernier_suivi"].apply(formater_date)
                final_mand["dvf_date"] = final_mand["dvf_date"].apply(formater_date)
                final_mand["dvf_prix"] = final_mand["dvf_prix"].apply(lambda x: f"{x:,.0f} €".replace(",", " ") if pd.notna(x) else "—")
                
                final_mand = final_mand.rename(columns={
                    "nom_principal": "Dossier", "adresse_bien": "Adresse",
                    "date_mandat": "Saisie Mandat", "date_dernier_suivi": "Dernier Suivi",
                    "dvf_date": "Date Transaction DVF", "dvf_prix": "Prix Transaction"
                }).drop(columns=["id_mandat"], errors="ignore")
                
                st.markdown(f"**{len(final_mand)} mandats** retrouvés.")
                st.dataframe(final_mand, hide_index=True, use_container_width=True)