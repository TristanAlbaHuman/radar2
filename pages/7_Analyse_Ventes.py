"""
7_Analyse_Ventes.py - Radar Mandats V2
Croisement CRM x DPE x DVF (Ventes officielles) — OPTIMISÉ POUR GROS FICHIERS
"""

import streamlit as st
import pandas as pd
import io
from ademe_matcher import rnvp_adresse, score_match
from ui_utils import CSS

st.markdown(CSS, unsafe_allow_html=True)

# ── 1. VERIFICATION CRM ───────────────────────────────────────────
if st.session_state.get("df_scored") is None:
    st.warning("⚠️ Chargez votre fichier CRM depuis l'accueil pour accéder aux données.")
    st.stop()

df_eval = st.session_state["df_scored"].copy()
df_mand = st.session_state.get("df_mandats", pd.DataFrame()).copy()

# ── 2. EN-TÊTE ────────────────────────────────────────────────────
st.markdown("## 🤝 Suivi des Ventes & Concurrence (DVF)")
st.markdown(
    "<span style='color:#888;font-size:13px'>"
    "Croisez votre portefeuille avec les actes de vente officiels (DVF) et les DPE "
    "pour repérer les affaires vendues et les estimations perdues."
    "</span>", unsafe_allow_html=True
)
st.markdown("<hr class='sep'>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Paramètres DVF")
    seuil_match = st.slider("Score de correspondance adresse", 85, 100, 90, step=5)

# ── 3. FONCTION DE CHARGEMENT OPTIMISÉE ───────────────────────────
def load_dvf_optimized(uploaded_file):
    """
    Lit un gros fichier DVF (txt/csv) de 180Mo+ très rapidement :
    - Détecte le bon séparateur (| ou ,)
    - Ne charge QUE les colonnes utiles (Adresse, Prix, Date) pour économiser la RAM
    """
    # 1. Lire la première ligne pour détecter le séparateur
    first_line = uploaded_file.readline().decode('utf-8')
    uploaded_file.seek(0) # Rembobiner le fichier
    sep = '|' if '|' in first_line else ','
    
    # 2. Lire uniquement les en-têtes pour voir ce qui est présent
    headers = pd.read_csv(uploaded_file, sep=sep, nrows=0).columns
    uploaded_file.seek(0)
    
    # 3. Cibler les colonnes utiles (Gère format data.gouv brut ou etalab)
    cibles = [
        "Date mutation", "date_mutation",
        "Valeur fonciere", "valeur_fonciere",
        "No voie", "adresse_numero",
        "B/T/Q", "Indice de repetition", "adresse_suffixe",
        "Type de voie", "Voie", "adresse_nom_voie",
        "Code postal", "code_postal",
        "Commune", "nom_commune"
    ]
    cols_to_use = [c for c in headers if c in cibles]
    
    # 4. Charger avec le moteur C ultra-rapide et uniquement les colonnes nécessaires
    df = pd.read_csv(uploaded_file, sep=sep, usecols=cols_to_use, dtype=str, low_memory=True)
    return df

# ── 4. CHARGEMENT DVF ─────────────────────────────────────────────
st.markdown('<div class="sec">1. Charger la base des ventes (DVF)</div>', unsafe_allow_html=True)
st.info("💡 Vous pouvez uploader directement les gros fichiers `.txt` de data.gouv.fr (150 Mo+). Le système est optimisé pour les traiter rapidement.")

dvf_files = st.file_uploader(
    "Importez vos exports DVF (téléchargés depuis data.gouv.fr)", 
    type=["csv", "txt"], accept_multiple_files=True, label_visibility="collapsed"
)

if dvf_files:
    if st.button("🚀 Lancer le croisement DVF sur tout le portefeuille", type="primary"):
        with st.spinner("Lecture et optimisation des fichiers DVF..."):
            dfs = []
            for f in dvf_files:
                dfs.append(load_dvf_optimized(f))
            df_dvf = pd.concat(dfs, ignore_index=True)

            # Standardisation des colonnes DVF (robustesse multi-formats)
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

            # Adresse DVF complète
            df_dvf["_addr_full"] = num + " " + suf + " " + tvoie + " " + voie + " " + cp.str[:5] + " " + ville
            df_dvf["_addr_full"] = df_dvf["_addr_full"].str.replace(r"\s+", " ", regex=True).str.strip()

            # Date et Prix
            df_dvf["_date"] = pd.to_datetime(get_c(["date_mutation", "Date mutation"]), format="%d/%m/%Y", errors="coerce").combine_first(
                              pd.to_datetime(get_c(["date_mutation", "Date mutation"]), errors="coerce"))
            df_dvf["_prix"] = pd.to_numeric(get_c(["valeur_fonciere", "Valeur fonciere"]).str.replace(",", "."), errors="coerce")
            
            # Trier pour garder la vente la plus récente en cas de doublon
            df_dvf = df_dvf.sort_values("_date", ascending=False)
            
            # Indexation par Code Postal pour accélérer le matching
            df_dvf["_cp_idx"] = cp.str[:5]
            cp_index = {}
            for r in df_dvf.to_dict("records"):
                cp_index.setdefault(r["_cp_idx"], []).append(r)

        with st.spinner("Matching des adresses CRM avec les ventes DVF..."):
            cols_communes = ["nom_principal", "adresse_bien", "code_postal"]
            df_crm_global = pd.concat([
                df_eval[["id_evaluation"] + cols_communes].rename(columns={"id_evaluation": "id_crm"}).assign(source_crm="Évaluation"),
                df_mand[["id_mandat"] + cols_communes].rename(columns={"id_mandat": "id_crm"}).assign(source_crm="Mandat")
            ], ignore_index=True)

            matchs_dvf = []
            total_crm = len(df_crm_global)
            prog = st.progress(0)
            
            for i, (_, row) in enumerate(df_crm_global.iterrows()):
                if i % 100 == 0: prog.progress(min(i/total_crm, 1.0))
                addr_crm = str(row.get("adresse_bien", ""))
                cp_crm   = rnvp_adresse(addr_crm)["cp"] or str(row.get("code_postal", "")).zfill(5)[:5]
                
                best_sc, best_vente = 0, None
                for vente in cp_index.get(cp_crm, []):
                    sc, _, _ = score_match(addr_crm, vente)
                    if sc > best_sc: 
                        best_sc, best_vente = sc, vente
                        
                if best_sc >= seuil_match and best_vente:
                    matchs_dvf.append({
                        "id_crm": row["id_crm"],
                        "source_crm": row["source_crm"],
                        "dvf_date": best_vente["_date"],
                        "dvf_prix": best_vente["_prix"]
                    })
                    
            prog.empty()
            st.session_state["match_dvf_df"] = pd.DataFrame(matchs_dvf)
            st.success("Croisement DVF terminé !")

# ── 5. AFFICHAGE DES RÉSULTATS (Tableaux personnalisés) ───────────
df_match_dvf = st.session_state.get("match_dvf_df", pd.DataFrame())
df_match_dpe = st.session_state.get("match_crm_df", pd.DataFrame()) # Récupéré de la page 4

if df_match_dpe.empty:
    st.info("💡 **Astuce** : Pour voir les dates de DPE dans le tableau des évaluations, lancez d'abord le croisement ADEME sur la page 'Détection DPE'.")

if not df_match_dvf.empty or not df_match_dpe.empty:
    st.markdown("<br/>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["📝 Évaluations (Passées en DPE ou DVF)", "🤝 Mandats (Vendus DVF)"])

    def formater_date(d):
        if pd.isna(d): return "—"
        try: return d.strftime("%d/%m/%Y")
        except: return str(d)

    # ── TAB 1 : ÉVALUATIONS (DPE + DVF)
    with tab1:
        res_eval = df_eval[["id_evaluation", "nom_principal", "adresse_bien", "date_estimation", "date_dernier_suivi"]].copy()
        
        # Ajout des dates DPE
        if not df_match_dpe.empty:
            dpe_e = df_match_dpe[df_match_dpe["source_crm"] == "Évaluation"][["id_crm", "dpe_date"]]
            res_eval = res_eval.merge(dpe_e, left_on="id_evaluation", right_on="id_crm", how="left").drop(columns=["id_crm", "id_evaluation"], errors="ignore")
        else: res_eval["dpe_date"] = None
            
        # Ajout des dates DVF
        if not df_match_dvf.empty:
            dvf_e = df_match_dvf[df_match_dvf["source_crm"] == "Évaluation"][["id_crm", "dvf_date", "dvf_prix"]]
            res_eval = res_eval.merge(dvf_e, left_on="id_evaluation", right_on="id_crm", how="left").drop(columns=["id_crm", "id_evaluation"], errors="ignore")
        else:
            res_eval["dvf_date"] = None
            res_eval["dvf_prix"] = None

        # FILTRE : Uniquement les évals ayant un DPE OU un DVF
        mask = res_eval["dpe_date"].notna() | res_eval["dvf_date"].notna()
        final_eval = res_eval[mask].sort_values("date_estimation", ascending=False).copy()
        
        if final_eval.empty:
            st.info("Aucune de vos évaluations ne se trouve dans les bases DPE ou DVF actuelles.")
        else:
            # Formatage pour l'affichage
            final_eval["date_estimation"] = final_eval["date_estimation"].apply(formater_date)
            final_eval["date_dernier_suivi"] = final_eval["date_dernier_suivi"].apply(formater_date)
            final_eval["dpe_date"] = final_eval["dpe_date"].apply(formater_date)
            final_eval["dvf_date"] = final_eval["dvf_date"].apply(formater_date)
            final_eval["dvf_prix"] = final_eval["dvf_prix"].apply(lambda x: f"{x:,.0f} €".replace(",", " ") if pd.notna(x) else "—")
            
            final_eval = final_eval.rename(columns={
                "nom_principal": "Dossier", "adresse_bien": "Adresse",
                "date_estimation": "Date Saisie Éval", "date_dernier_suivi": "Dernier Suivi",
                "dpe_date": "Date DPE", "dvf_date": "Date Transaction DVF", "dvf_prix": "Prix Transaction"
            })
            
            st.markdown(f"**{len(final_eval)} évaluations** ont été retrouvées avec un DPE récent ou un acte de vente.")
            st.dataframe(final_eval, hide_index=True, use_container_width=True)

    # ── TAB 2 : MANDATS (DVF Uniquement)
    with tab2:
        if df_match_dvf.empty:
            st.info("Lancez le croisement DVF pour voir vos mandats revendus.")
        else:
            res_mand = df_mand[["id_mandat", "nom_principal", "adresse_bien", "date_mandat", "date_dernier_suivi"]].copy()
            dvf_m = df_match_dvf[df_match_dvf["source_crm"] == "Mandat"][["id_crm", "dvf_date", "dvf_prix"]]
            res_mand = res_mand.merge(dvf_m, left_on="id_mandat", right_on="id_crm", how="left").drop(columns=["id_crm", "id_mandat"], errors="ignore")
            
            # FILTRE : Uniquement les mandats ayant un DVF
            final_mand = res_mand[res_mand["dvf_date"].notna()].sort_values("date_mandat", ascending=False).copy()
            
            if final_mand.empty:
                st.info("Aucun de vos mandats ne correspond à une transaction dans ces fichiers DVF.")
            else:
                final_mand["date_mandat"] = final_mand["date_mandat"].apply(formater_date)
                final_mand["date_dernier_suivi"] = final_mand["date_dernier_suivi"].apply(formater_date)
                final_mand["dvf_date"] = final_mand["dvf_date"].apply(formater_date)
                final_mand["dvf_prix"] = final_mand["dvf_prix"].apply(lambda x: f"{x:,.0f} €".replace(",", " ") if pd.notna(x) else "—")
                
                final_mand = final_mand.rename(columns={
                    "nom_principal": "Dossier", "adresse_bien": "Adresse",
                    "date_mandat": "Date Saisie Mandat", "date_dernier_suivi": "Dernier Suivi",
                    "dvf_date": "Date Transaction DVF", "dvf_prix": "Prix Transaction"
                })
                
                st.markdown(f"**{len(final_mand)} mandats** de votre CRM correspondent à une vente officielle DVF.")
                st.dataframe(final_mand, hide_index=True, use_container_width=True)