import streamlit as st

st.set_page_config(
    page_title="Home",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

def init_session_state():
    defaults = {
        "league_config":  None,
        "draft_state":    None,
        "draft_started":  False,
        "players_df":     None,
        "projections_source": "auto",
        "sim_state":      None,
        "sim_results":    [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

st.title("🏈 Fantasy Football Draft Tool")
st.markdown("""
Welcome! Follow these steps to get started:

1. **League Setup** — Enter your scoring format, roster slots, and draft position
2. **Projections** *(optional)* — Upload custom projections or refresh free data
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
        cfg = st.session_state.league_config
        has_proj = (st.session_state.players_df["projected_points"] > 0).sum()
        st.success(
            f"#### ✅ Ready to Draft\n"
            f"{cfg['num_teams']}-team {cfg['scoring_preset']} · "
            f"Pick #{cfg['draft_position']} · "
            f"{has_proj} players with projections"
        )
    elif league_ready:
        st.warning("#### Step 2\nLeague configured — data still loading.")
    else:
        st.warning("#### Step 2\nComplete League Setup first.")

with col3:
    if st.session_state.draft_started and st.session_state.draft_state is not None:
        ds = st.session_state.draft_state
        st.success(
            f"#### Draft In Progress\n"
            f"Round {ds.current_round}, Pick #{ds.current_pick_number}"
        )
    else:
        st.info("#### Step 3\nDraft Board unlocks after setup is complete.")

st.markdown("---")
st.caption("Data: nflverse 2024 stats · Sleeper ADP · Upload your own projections for premium accuracy.")
