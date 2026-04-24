import streamlit as st

st.set_page_config(
    page_title="Fantasy Draft Tool",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
# These are set once here so every page can safely read them without checking
# for existence first.

def init_session_state():
    defaults = {
        # League configuration
        "league_config": None,          # dict set by League Setup page

        # Draft state
        "draft_state": None,            # DraftState object (engine/draft_state.py)
        "draft_started": False,

        # Player data
        "players_df": None,             # Full player DataFrame loaded from data layer
        "projections_source": "auto",   # "auto" | "upload"

        # Simulation
        "sim_results": [],              # List of completed simulation rosters
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ── Home page ─────────────────────────────────────────────────────────────────
st.title("🏈 Fantasy Football Draft Tool")
st.markdown("""
Welcome! Follow these steps to get started:

1. **League Setup** — Enter your league settings (scoring, roster slots, draft position)
2. **Load Projections** — Use our free auto-loaded data or upload your own
3. **Draft Board** — Run your live draft with real-time recommendations
4. **Simulator** — Practice draft strategies before the real thing

---
""")

col1, col2, col3 = st.columns(3)

with col1:
    st.info("#### Step 1\n Configure your league settings before anything else.")

with col2:
    league_ready = st.session_state.league_config is not None
    data_ready = st.session_state.players_df is not None
    if league_ready and data_ready:
        st.success("#### ✅ Ready to Draft\n League configured and data loaded.")
    elif league_ready:
        st.warning("#### Step 2\n League configured — load projections to continue.")
    else:
        st.warning("#### Step 2\n Complete League Setup first.")

with col3:
    if st.session_state.draft_started:
        st.success("#### Draft In Progress\n Head to the Draft Board.")
    else:
        st.info("#### Step 3\n Draft Board unlocks after setup is complete.")

st.markdown("---")
st.caption("Data sources: nflverse · Sleeper ADP · FantasyPros ECR | Upload your own projections for premium accuracy.")
