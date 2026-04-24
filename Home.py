import json
import streamlit as st
from engine.scoring import SCORING_PRESETS
from data.loader import load_players
from engine.scoring import apply_scoring_to_df
from engine.vorp import calculate_vor

st.set_page_config(
    page_title="Home",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

def init_session_state():
    defaults = {
        "league_config":      None,
        "draft_state":        None,
        "draft_started":      False,
        "players_df":         None,
        "projections_source": "auto",
        "sim_state":          None,
        "sim_results":        [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

st.title("🏈 Fantasy Football Draft Tool")
st.markdown("""
Welcome! Follow these steps to get started:

1. **League Setup** — Enter your scoring format, roster slots, and draft position
2. **Projections** *(optional)* — Pull ESPN data or upload FantasyPros projections
3. **Draft Board** — Run your live draft with real-time recommendations
4. **Simulator** — Practice strategies before draft day
---
""")

col1, col2, col3 = st.columns(3)

with col1:
    st.info("#### Step 1\nConfigure your league settings before anything else.")

with col2:
    league_ready = st.session_state.league_config is not None
    data_ready   = st.session_state.players_df is not None
    if league_ready and data_ready:
        cfg      = st.session_state.league_config
        has_proj = int((st.session_state.players_df["projected_points"] > 0).sum())
        st.success(
            f"#### ✅ Ready to Draft\n"
            f"{cfg['num_teams']}-team {cfg['scoring_preset']} · "
            f"Pick #{cfg['draft_position']} · "
            f"{has_proj} players with projections"
        )
    elif league_ready:
        st.warning("#### Step 2\nLeague configured — go to League Setup and reload data.")
    else:
        st.warning("#### Step 2\nComplete League Setup first.")

with col3:
    if st.session_state.draft_started and st.session_state.draft_state is not None:
        try:
            ds = st.session_state.draft_state
            st.success(
                f"#### Draft In Progress\n"
                f"Round {ds.current_round}, Pick #{ds.current_pick_number}"
            )
        except Exception:
            st.info("#### Step 3\nDraft Board ready.")
    else:
        st.info("#### Step 3\nDraft Board unlocks after setup is complete.")

st.markdown("---")

# ── Save / Load League Config ─────────────────────────────────────────────────
st.subheader("💾 Save & Restore Your League Settings")
st.markdown(
    "Streamlit resets on page refresh. **Save your league config** as a file "
    "so you can restore it instantly next time without re-entering everything."
)

save_col, load_col = st.columns(2)

with save_col:
    st.markdown("**Save current settings:**")
    if st.session_state.league_config:
        cfg_json = json.dumps(st.session_state.league_config, indent=2)
        st.download_button(
            label="⬇️ Download League Config",
            data=cfg_json,
            file_name="my_league_config.json",
            mime="application/json",
            use_container_width=True,
        )
        st.caption("Save this file — upload it next session to skip League Setup.")
    else:
        st.info("Configure your league first, then save it here.")

with load_col:
    st.markdown("**Restore saved settings:**")
    uploaded_cfg = st.file_uploader(
        "Upload your saved config JSON",
        type=["json"],
        key="cfg_upload",
    )
    if uploaded_cfg:
        try:
            cfg = json.loads(uploaded_cfg.read())
            scoring_type = {"Standard": "standard", "Half-PPR": "half_ppr"}.get(
                cfg.get("scoring_preset", "PPR"), "ppr"
            )
            with st.spinner("Restoring league and loading player data..."):
                players_df = load_players(scoring_type)
                players_df = apply_scoring_to_df(players_df, cfg["scoring"])
                players_df = calculate_vor(players_df, cfg)

            st.session_state.league_config = cfg
            st.session_state.players_df    = players_df
            st.session_state.draft_state   = None
            st.session_state.sim_state     = None
            st.success("✅ League config restored! Head to Draft Board to continue.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not load config: {e}")

st.markdown("---")
st.caption("Data: ESPN Fantasy API (2026) · Sleeper ADP · Upload FantasyPros for full stat projections")
