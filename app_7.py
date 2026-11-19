import streamlit as st
import pandas as pd
import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="SPK Table Dashboard",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Database Records")
st.markdown("---")

# ==========================================
# 2. MYSQL DATABASE CONNECTION
# ==========================================
@st.cache_resource
def get_connection():
    try:
        db_config = st.secrets["mysql"]
        connection_url = URL.create(
            drivername="mysql+pymysql",
            username=db_config["DB_USER"],
            password=db_config["DB_PASSWORD"],
            host=db_config["DB_HOST"],
            port=int(db_config["DB_PORT"]),
            database=db_config["DB_NAME"],
        )
    except KeyError as e:
        raise KeyError(f"Missing secret key: {e}. Check your .streamlit/secrets.toml configuration.")

    return create_engine(
        connection_url,
        pool_pre_ping=True,
        pool_recycle=1800,
    )

try:
    engine = get_connection()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    st.sidebar.success("✅ MySQL Connected")
except Exception as e:
    st.error(f"Database Connection Failed: {e}")
    st.stop()

# ==========================================
# 3. LOAD DATA FROM MYSQL
# ==========================================
TABLE_NAME = "view_penerimaan_LSN"

@st.cache_data(ttl=600)
def load_data(_engine):
    current_year = datetime.date.today().year
    
    # 1. Optimize: Only fetch current year from the database
    query = text(f"""
        SELECT * FROM `{TABLE_NAME}` 
        WHERE YEAR(`tglinputspk`) = {current_year}
        ORDER BY `tglinputspk` DESC
    """)
    df = pd.read_sql(query, _engine)
    
    # 2. Convert date columns safely (forces typos like 2925 to NaT)
    date_cols = ['tglspk', 'tglterima', 'tglinputspk']
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            
    # 3. STRICT FILTER: Strip out ANY rows with lingering 2021 dates 
    for col in date_cols:
        if col in df.columns:
            df = df[(df[col].dt.year == current_year) | (df[col].isna())]
            
    # 4. Convert tglspk & tglterima to date, KEEP tglinputspk as full datetime
    for col in ['tglspk', 'tglterima']:
        if col in df.columns:
            df[col] = df[col].dt.date
            
    if 'tglinputspk' in df.columns:
        # Convert Pandas Timestamp to standard Python datetime (flooring seconds for clean UI)
        df['tglinputspk'] = df['tglinputspk'].dt.floor('min').dt.to_pydatetime()
            
    return df

try:
    df = load_data(engine)
except SQLAlchemyError as e:
    st.error(f"Failed to load table data: {e}")
    st.stop()

# ==========================================
# 4. SIDEBAR FILTERS
# ==========================================
st.sidebar.header("🔍 Filter Data")

filtered_df = df.copy()

# A. Dropdown for "namabengkel"
if "namabengkel" in filtered_df.columns:
    bengkel_list = filtered_df["namabengkel"].dropna().unique()
    selected_bengkel = st.sidebar.multiselect("Nama Bengkel", options=bengkel_list)
    if selected_bengkel:
        filtered_df = filtered_df[filtered_df["namabengkel"].isin(selected_bengkel)]

# B. Search for "no_spk"
if "no_spk" in filtered_df.columns:
    search_spk = st.sidebar.text_input("Search No SPK")
    if search_spk:
        filtered_df = filtered_df[filtered_df["no_spk"].astype(str).str.contains(search_spk, case=False, na=False)]

# C. Select for "status_pembebanan"
if "status_pembebanan" in filtered_df.columns:
    status_list = ["All"] + list(filtered_df["status_pembebanan"].dropna().unique())
    selected_status = st.sidebar.selectbox("Status Pembebanan", options=status_list)
    if selected_status != "All":
        filtered_df = filtered_df[filtered_df["status_pembebanan"] == selected_status]

# D. Date & Datetime Sliders
def add_date_slider(col_name, label, include_time=False):
    global filtered_df
    if col_name in filtered_df.columns:
        valid_dates = filtered_df[col_name].dropna()
        if not valid_dates.empty:
            current_year = datetime.date.today().year
            
            if include_time:
                # Use datetime objects with hours and minutes
                start_of_year = datetime.datetime(current_year, 1, 1, 0, 0)
                end_of_year = datetime.datetime(current_year, 12, 31, 23, 59)
                
                min_d = max(pd.to_datetime(valid_dates.min()).to_pydatetime(), start_of_year)
                max_d = min(pd.to_datetime(valid_dates.max()).to_pydatetime(), end_of_year)
                
                if min_d <= max_d:
                    date_range = st.sidebar.slider(
                        label,
                        min_value=start_of_year,
                        max_value=end_of_year,
                        value=(min_d, max_d),
                        step=datetime.timedelta(minutes=15), # Adjust step (e.g., minutes=1 or minutes=30)
                        format="YYYY-MM-DD HH:mm"
                    )
                    filtered_df = filtered_df[
                        (filtered_df[col_name] >= date_range[0]) & 
                        (filtered_df[col_name] <= date_range[1])
                    ]
            else:
                # Standard date-only slider
                start_of_year = datetime.date(current_year, 1, 1)
                end_of_year = datetime.date(current_year, 12, 31)
                
                min_d = max(valid_dates.min(), start_of_year)
                max_d = min(valid_dates.max(), end_of_year)
                
                if min_d <= max_d:
                    date_range = st.sidebar.slider(
                        label, 
                        min_value=start_of_year, 
                        max_value=end_of_year, 
                        value=(min_d, max_d)
                    )
                    filtered_df = filtered_df[
                        (filtered_df[col_name] >= date_range[0]) & 
                        (filtered_df[col_name] <= date_range[1])
                    ]

st.sidebar.markdown("### 📅 Date Filters")
add_date_slider("tglspk", "Tanggal SPK", include_time=False)
add_date_slider("tglterima", "Tanggal Terima", include_time=False)
add_date_slider("tglinputspk", "Tanggal Input SPK", include_time=True)

# ==========================================
# 5. DASHBOARD METRICS (SCORE CARDS)
# ==========================================
sudah_count = len(filtered_df[filtered_df["status_pembebanan"] == "Sudah"]) if "status_pembebanan" in filtered_df.columns else 0
belum_count = len(filtered_df[filtered_df["status_pembebanan"] == "Belum"]) if "status_pembebanan" in filtered_df.columns else 0

col1, col2, col3, col4 = st.columns([1, 1, 1, 1.5])

with col1:
    st.metric(label="✅ Status: Sudah", value=f"{sudah_count:,}")

with col2:
    st.metric(label="⏳ Status: Belum", value=f"{belum_count:,}")

with col3:
    st.metric(label="Total Records", value=f"{len(filtered_df):,}")

with col4:
    st.write("") 
    if st.button("🔄 Refresh / Reset Data", use_container_width=True):
        load_data.clear()
        st.rerun()

st.markdown("---")

# ==========================================
# 6. DISPLAY DATABASE TABLE (REORDER & RENAME)
# ==========================================
st.subheader(f"Penerimaan LSN ({len(filtered_df)} results)")

target_order = [
    "namabengkel", 
    "no_spk", 
    "status_pembebanan", 
    "tglspk", 
    "tglterima", 
    "tglinputspk"
]

available_cols = [col for col in target_order if col in filtered_df.columns]
remaining_cols = [col for col in filtered_df.columns if col not in available_cols]
final_order = available_cols + remaining_cols

display_df = filtered_df[final_order].copy()

column_mapping = {
    "namabengkel": "Nama Bengkel",
    "no_spk": "No SPK",
    "tglspk": "tgl SPK",
    "tglterima": "tgl terima",
    "tglinputspk": "tgl input SPK",
    "status_pembebanan": "Status Pembebanan"
}
display_df = display_df.rename(columns=column_mapping)

# Render the formatted table with explicit hour:minute formatting
st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    height=600,
    column_config={
        "tgl input SPK": st.column_config.DatetimeColumn(
            "tgl input SPK",
            format="YYYY-MM-DD HH:mm"
        )
    }
)

# ==========================================
# 7. FOOTER
# ==========================================
st.markdown("---")
st.caption("SPK Table Dashboard | MySQL Database")
