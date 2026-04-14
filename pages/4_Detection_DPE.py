"""
4_Detection_DPE.py - Radar Mandats V2
Détection DPE & Statistiques Agence.
"""

import streamlit as st
import pandas as pd
import urllib.parse
import html as _html
import plotly.express as px
from datetime import date
from ademe_matcher import (
    rnvp_adresse, score_match, normaliser_df_ademe,
    charger_fichiers_ademe, calculer_score_maturite,
)
from ui_utils import CSS, S, fmt_date, dpe_badge, kpi, badge, map_links

st.markdown(CSS, unsafe_allow_html=True)

# ── 1. CHARGEMENT CRM ─────────────────────────────────────────────
df_eval = st.session_state.get("df_scored", st.session_state.get("df_s", pd.DataFrame()))
df_mand = st.session_state.get("df_m", st.session_state.get("df_mandats", pd.DataFrame()))

if df_eval.empty and df_mand.empty:
    st.warning("⚠️ Chargez votre fichier CRM depuis l'accueil pour accéder aux données.")
    st.stop()

# ── 2. SIDEBAR : PARAMÈTRES ET FILTRES ────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Paramètres DPE")
    age_dpe_max  = st.slider("DPE de moins de X mois", 1, 36, 6)
    seuil_match  = st.slider("Score RNVP minimum (matchs)", 85, 100, 90, step=5)
    st.markdown("---")
    st.markdown("### 🔍 Filtres CRM")
    agences_dispos = set(df_eval["agence"].dropna().unique()) | set(df_mand["agence"].dropna().unique())
    ag_sel = st.multiselect("Agences", sorted(list(agences_dispos)), placeholder="Toutes les agences")
    dpe_labels = st.multiselect("Étiquettes DPE (Filtre)", list("ABCDEFG"), default=[])

if ag_sel:
    df_eval_f = df_eval[df_eval["agence"].isin(ag_sel)].copy()
    df_mand_f = df_mand[df_mand["agence"].isin(ag_sel)].copy()
else:
    df_eval_f, df_mand_f = df_eval.copy(), df_mand.copy()

# ── 3. EN-TÊTE ────────────────────────────────────────────────────
st.markdown("## 🎯 Détection DPE & Analyse Agence")
st.markdown("<span style='color:#888;font-size:13px'>Analysez votre portefeuille et identifiez les vendeurs.</span>", unsafe_allow_html=True)
st.markdown("<hr class='sep'>", unsafe_allow_html=True)

st.markdown('<div class="sec">1. Charger la base ADEME (DPE)</div>', unsafe_allow_html=True)
ademe_files = st.file_uploader("Importez vos exports CSV de l'ADEME", type=["csv","xlsx"], accept_multiple_files=True, key="ademe_det", label_visibility="collapsed")

# ── 4. PRÉPARATION DPE ────────────────────────────────────────────
df_ademe = None
if ademe_files:
    ck = "det_" + "_".join(f.name for f in ademe_files)
    if st.session_state.get("det_ademe_key") != ck:
        with st.spinner(f"Chargement de {len(ademe_files)} fichier(s) ADEME..."):
            df_ademe = charger_fichiers_ademe(ademe_files)
        st.session_state["det_ademe_df"] = df_ademe
        st.session_state["det_ademe_key"] = ck
    else: df_ademe = st.session_state["det_ademe_df"]
elif "det_ademe_df" in st.session_state:
    df_ademe = st.session_state["det_ademe_df"]

df_a = pd.DataFrame()
if df_ademe is not None and not df_ademe.empty:
    df_a = df_ademe.copy()
    df_a["_temp_id"] = range(len(df_a)) 
    col_date = next((c for c in ["date_dpe","date_etablissement_dpe"] if c in df_a.columns), None)
    if col_date:
        df_a["_date"] = pd.to_datetime(df_a[col_date], errors="coerce")
        df_a["_age"]  = ((pd.Timestamp(date.today()) - df_a["_date"]).dt.days / 30.44).round(1)
        df_a = df_a[df_a["_age"] <= age_dpe_max].copy()
    col_etiq = next((c for c in ["etiquette_dpe"] if c in df_a.columns), None)
    if dpe_labels and col_etiq: df_a = df_a[df_a[col_etiq].str.upper().str.strip().isin(dpe_labels)]
    df_a = df_a.sort_values("_date", ascending=False, na_position="last").reset_index(drop=True)
    df_a["_addr_full"] = df_a.apply(lambda r: f"{str(r.get('adresse_ban','') or '')} {str(r.get('cp_ban') or r.get('code_postal_ban','') or '')} {str(r.get('ville_ban') or r.get('nom_commune_ban','') or '')}".strip(), axis=1)

# ── 5. ONGLETS NATIFS ───────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 Statistiques", "📋 Listes CRM", "🎯 Matchs & Opportunités DPE"])

with tab1:
    st.markdown('<div class="sec">Analyse des Évaluations</div>', unsafe_allow_html=True)
    if not df_eval_f.empty and "date_estimation" in df_eval_f.columns:
        c1, c2 = st.columns(2)
        df_e_plot = df_eval_f.dropna(subset=["date_estimation"]).copy()
        df_e_plot['Mois'] = df_e_plot['date_estimation'].dt.to_period('M').astype(str)
        fig_e_mois = px.bar(df_e_plot.groupby('Mois').size().reset_index(name='Nombre'), x='Mois', y='Nombre', title="Évaluations par mois", text_auto=True, color_discrete_sequence=['#3498db'])
        c1.plotly_chart(fig_e_mois, use_container_width=True)
        if "actif" in df_e_plot.columns:
            df_e_plot['Statut'] = df_e_plot['actif'].apply(lambda x: 'Actif' if x else 'Inactif')
            fig_e_statut = px.pie(df_e_plot.groupby('Statut').size().reset_index(name='Nombre'), names='Statut', values='Nombre', title="Répartition statuts (Évaluations)", color='Statut', color_discrete_map={'Actif':'#2ecc71', 'Inactif':'#e74c3c'})
            c2.plotly_chart(fig_e_statut, use_container_width=True)
            
    st.markdown('<div class="sec">Analyse des Mandats</div>', unsafe_allow_html=True)
    if not df_mand_f.empty and "date_mandat" in df_mand_f.columns:
        c3, c4 = st.columns(2)
        df_m_plot = df_mand_f.dropna(subset=["date_mandat"]).copy()
        df_m_plot['Mois'] = df_m_plot['date_mandat'].dt.to_period('M').astype(str)
        fig_m_mois = px.bar(df_m_plot.groupby('Mois').size().reset_index(name='Nombre'), x='Mois', y='Nombre', title="Mandats par mois", text_auto=True, color_discrete_sequence=['#9b59b6'])
        c3.plotly_chart(fig_m_mois, use_container_width=True)
        if "actif" in df_m_plot.columns:
            df_m_plot['Statut'] = df_m_plot['actif'].apply(lambda x: 'Actif' if x else 'Inactif')
            fig_m_statut = px.pie(df_m_plot.groupby('Statut').size().reset_index(name='Nombre'), names='Statut', values='Nombre', title="Répartition statuts (Mandats)", color='Statut', color_discrete_map={'Actif':'#2ecc71', 'Inactif':'#e74c3c'})
            c4.plotly_chart(fig_m_statut, use_container_width=True)

with tab2:
    st.subheader(f"Liste des Évaluations (limité à 500) — Total : {len(df_eval_f)}")
    st.dataframe(df_eval_f.head(500), use_container_width=True)
    st.subheader(f"Liste des Mandats (limité à 500) — Total : {len(df_mand_f)}")
    st.dataframe(df_mand_f.head(500), use_container_width=True)

with tab3:
    if df_a.empty: 
        st.warning("Veuillez charger des fichiers DPE dans l'encart au-dessus pour lancer l'analyse.")
    else:
        st.markdown(f'<div class="sec">Croisement GLOBAL (Évals + Mandats) × ADEME</div>', unsafe_allow_html=True)
        
        # Consolidation CRM (Evals + Mandats) pour le matching
        cols_communes = ["nom_principal", "agence", "adresse_bien", "code_postal", "ville"]
        df_eval_match = df_eval_f[["id_evaluation"] + cols_communes].rename(columns={"id_evaluation": "id_crm"}).assign(source_crm="Évaluation")
        df_mand_match = df_mand_f[["id_mandat"] + cols_communes].rename(columns={"id_mandat": "id_crm"}).assign(source_crm="Mandat")
        df_crm_global = pd.concat([df_eval_match, df_mand_match], ignore_index=True)

        if st.button("🚀 Lancer le matching sur tout le CRM", type="primary"):
            col_cp = next((c for c in ["cp_ban","code_postal_ban"] if c in df_a.columns), None)
            df_a["_cp_idx"] = df_a[col_cp].astype(str).str.strip().str.replace(r"\.0$","",regex=True).str.zfill(5).str[:5]
            
            cp_index = {}
            for r in df_a.to_dict("records"): 
                cp_index.setdefault(r["_cp_idx"], []).append(r)
                
            prog = st.progress(0, text="Matching RNVP sur le portefeuille...")
            matchs_crm = []
            ademe_match_ids = set()
            total_crm = len(df_crm_global)
            
            for i, (_, row) in enumerate(df_crm_global.iterrows()):
                if i % 100 == 0: prog.progress(min(i/total_crm, 1.0), text=f"Analyse {i}/{total_crm}...")
                addr_crm = str(row.get("adresse_bien","") or "")
                cp_crm   = rnvp_adresse(addr_crm)["cp"] or str(row.get("code_postal","")).zfill(5)[:5]
                
                best_sc, best_dpe = 0, None
                for dpe in cp_index.get(cp_crm, []):
                    sc, _, _ = score_match(addr_crm, dpe)
                    if sc > best_sc: 
                        best_sc, best_dpe = sc, dpe
                        
                if best_sc >= seuil_match and best_dpe:
                    ademe_match_ids.add(best_dpe["_temp_id"])
                    rec = row.to_dict()
                    rec.update({
                        "match_score": best_sc, 
                        "dpe_etiquette": best_dpe.get("etiquette_dpe"), 
                        "dpe_surface": best_dpe.get("surface_habitable_logement", best_dpe.get("surface")), 
                        "dpe_adresse": best_dpe.get("_addr_full"), 
                        "dpe_date": best_dpe.get("_date")
                    })
                    matchs_crm.append(rec)
                    
            prog.empty()
            st.session_state["match_crm_df"] = pd.DataFrame(matchs_crm)
            st.session_state["dpe_non_matches_df"] = df_a[~df_a["_temp_id"].isin(ademe_match_ids)]
            st.success("Matching terminé avec succès !")

        # Affichage des résultats
        df_mm = st.session_state.get("match_crm_df", pd.DataFrame())
        df_non_m = st.session_state.get("dpe_non_matches_df", pd.DataFrame())
        
        if not df_mm.empty or not df_non_m.empty:
            st.subheader(f"✅ Biens en portefeuille (CRM) matchés avec un DPE ({len(df_mm)} trouvés)")
            if not df_mm.empty: 
                cols_affich = ["source_crm", "nom_principal", "agence", "adresse_bien", "match_score", "dpe_etiquette", "dpe_surface", "dpe_date"]
                # S'assurer que les colonnes existent avant l'affichage
                cols_affich_exist = [c for c in cols_affich if c in df_mm.columns]
                st.dataframe(df_mm[cols_affich_exist].head(500), use_container_width=True)
            else:
                st.info("Aucun bien de votre CRM n'a matché avec les DPE chargés.")
                
            st.markdown("---")
            
            st.subheader(f"🔥 Opportunités Pures : DPE récents HORS portefeuille ({len(df_non_m)} trouvés)")
            st.caption("Ces particuliers ont fait un DPE récemment, mais ne sont ni dans vos évaluations ni dans vos mandats. Prospectez-les !")
            if not df_non_m.empty: 
                # SÉCURISATION DU KEYERROR ICI 👇
                cols_cibles = ["_addr_full", "etiquette_dpe", "etiquette_ges", "surface_habitable_logement", "surface", "_date", "_age", "type_batiment"]
                # On ne garde que les colonnes qui existent VRAIMENT dans le dataframe
                cols_existants = [c for c in cols_cibles if c in df_non_m.columns]
                
                st.dataframe(df_non_m[cols_existants].head(500), use_container_width=True)