import streamlit as st
import pandas as pd
from rectpack import newPacker, PackingBin
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.backends.backend_pdf import PdfPages
import io
import re

# --- 1. Configuration & Caching ---
st.set_page_config(page_title="bvr Cut Planner", layout="wide")

INV_COLS = ["Board Name", "Width", "Length"]
PART_COLS = ["Part Name", "W", "L", "Qty"]

@st.cache_data
def get_csv_template(columns):
    return pd.DataFrame(columns=columns).to_csv(index=False).encode('utf-8')

# --- 2. Session State Persistence ---
if 'inventory' not in st.session_state:
    st.session_state.inventory = pd.DataFrame([{"Board Name": "Main Slab", "Width": 9.25, "Length": 96.0}]).astype({"Width": float, "Length": float})

if 'parts' not in st.session_state:
    st.session_state.parts = pd.DataFrame([{"Part Name": "Table Leg", "W": 6.0, "L": 24.0, "Qty": 4}]).astype({"W": float, "L": float, "Qty": int})

# --- 3. Sidebar: Tools & Data Management ---
with st.sidebar:
    st.title("🛠️ bvr Toolbox")
    
    # Fraction Converter
    st.subheader("Fraction Converter")
    frac_input = st.text_input("Enter Fraction (e.g. 3 1/4 or 5/8)", placeholder="3 1/4")
    if frac_input:
        try:
            parts_str = re.split(r'[\s\-]+', frac_input.strip())
            if len(parts_str) == 2: 
                decimal = float(parts_str[0]) + (float(parts_str[1].split('/')[0]) / float(parts_str[1].split('/')[1]))
            elif '/' in parts_str[0]: 
                decimal = float(parts_str[0].split('/')[0]) / float(parts_str[0].split('/')[1])
            else: 
                decimal = float(parts_str[0])
            st.success(f"Decimal: **{decimal:.4f}**")
        except Exception:
            st.error("Format error. Try '3 1/4' or '5/8'")

    st.divider()
    
    # Job Settings
    st.header("⚙️ Job Settings")
    kerf = st.number_input("Kerf (inches)", value=0.125, step=0.03125, format="%.4f")
    allow_rotation = st.checkbox("Allow Part Rotation (Ignore Grain)", value=False)

    st.divider()
    
    # Data Management & CSV Uploads (Restored & Fixed)
    st.header("💾 Data Management")
    
    st.download_button("📥 Inventory Template", data=get_csv_template(INV_COLS), file_name="inv_template.csv", mime="text/csv")
    st.download_button("📥 Parts Template", data=get_csv_template(PART_COLS), file_name="parts_template.csv", mime="text/csv")
    
    uploaded_inv = st.file_uploader("Import Inventory CSV", type="csv")
    if uploaded_inv:
        temp_inv = pd.read_csv(uploaded_inv)
        if all(col in temp_inv.columns for col in INV_COLS):
            st.session_state.inventory = temp_inv.astype({"Width": float, "Length": float})
        else:
            st.error(f"Invalid format. Headers must be: {', '.join(INV_COLS)}")

    uploaded_parts = st.file_uploader("Import Project Parts CSV", type="csv")
    if uploaded_parts:
        temp_parts = pd.read_csv(uploaded_parts)
        if all(col in temp_parts.columns for col in PART_COLS):
            st.session_state.parts = temp_parts.astype({"W": float, "L": float, "Qty": int})
        else:
            st.error(f"Invalid format. Headers must be: {', '.join(PART_COLS)}")

# --- 4. Main UI Tables ---
st.title("🪚 bvr Cut Planner")

col_inv, col_parts = st.columns(2)

inv_config = {"Width": st.column_config.NumberColumn(format="%.3f"), "Length": st.column_config.NumberColumn(format="%.3f")}
part_config = {"W": st.column_config.NumberColumn("Width", format="%.3f"), "L": st.column_config.NumberColumn("Length", format="%.3f"), "Qty": st.column_config.NumberColumn("Qty", step=1)}

with col_inv:
    st.subheader("Lumber Inventory")
    inv_df = st.data_editor(st.session_state.inventory, num_rows="dynamic", key="inv_editor", column_config=inv_config, use_container_width=True)

with col_parts:
    st.subheader("Project Parts")
    parts_df = st.data_editor(st.session_state.parts, num_rows="dynamic", key="parts_editor", column_config=part_config, use_container_width=True)

# --- 5. Validating & Packing Engine ---
v_inv = inv_df.dropna(subset=['Width', 'Length'])
v_inv = v_inv[(v_inv['Width'] > 0) & (v_inv['Length'] > 0)].copy()

v_parts = parts_df.dropna(subset=['W', 'L', 'Qty'])
v_parts = v_parts[(v_parts['W'] > 0) & (v_parts['L'] > 0) & (v_parts['Qty'] > 0)].copy()

# Inject user rotation preference
packer = newPacker(bin_algo=PackingBin.BBF, rotation=allow_rotation)
bin_names = {}

for i, (_, row) in enumerate(v_inv.iterrows()):
    # FIX: Add kerf to bin dimensions to prevent "Exact Fit" rejection
    packer.add_bin(row['Length'] + kerf, row['Width'] + kerf)
    bin_names[i] = row['Board Name']

all_parts_requested = []
for _, row in v_parts.iterrows():
    for q in range(int(row['Qty'])):
        p_name = f"{row['Part Name']} ({q+1})"
        all_parts_requested.append(p_name)
        packer.add_rect(row['L'] + kerf, row['W'] + kerf, rid=p_name)

packer.pack()

# --- 6. Visualization & Yield Analysis ---
packed_names = []
pdf_figs = []

st.divider()

if not v_inv.empty:
    for i, bin in enumerate(packer):
        board_name = bin_names.get(i, f"Board {i+1}")
        
        # Calculate Board Yield (Back out the virtual kerf added to the bin)
        true_bin_width = bin.width - kerf
        true_bin_height = bin.height - kerf
        total_area = true_bin_width * true_bin_height
        
        used_area = sum([(r.width - kerf) * (r.height - kerf) for r in bin])
        yield_pct = (used_area / total_area) * 100 if total_area > 0 else 0
        
        st.subheader(f"✅ {board_name} — Yield: {yield_pct:.1f}%")
        
        fig, ax = plt.subplots(figsize=(11, 8.5))
        # Draw the true board size (ignoring the virtual kerf padding)
        ax.add_patch(patches.Rectangle((0, 0), true_bin_width, true_bin_height, color='#D2B48C', alpha=0.3))
        
        for rect in bin:
            packed_names.append(rect.rid)
            ax.add_patch(patches.Rectangle((rect.x, rect.y), rect.width-kerf, rect.height-kerf, 
                                           edgecolor='black', facecolor='#F5DEB3', lw=1.2))
            ax.text(rect.x + ((rect.width-kerf)/2), rect.y + ((rect.height-kerf)/2), rect.rid, 
                    ha='center', va='center', fontsize=8, weight='bold')

        ax.set_title(f"{board_name} | Yield: {yield_pct:.1f}% | Kerf: {kerf}\"", fontsize=14, pad=20)
        ax.set_xlim(-2, true_bin_width + 2)
        ax.set_ylim(-2, true_bin_height + 2)
        ax.set_aspect('equal')
        
        st.pyplot(fig)
        pdf_figs.append(fig)

# --- 7. Missing Parts Reporting ---
missing_parts = [p for p in all_parts_requested if p not in packed_names]

if missing_parts:
    st.error("🚨 CRITICAL: The following parts could not be placed!")
    missing_summary = pd.Series([p.rsplit(" (", 1)[0] for p in missing_parts]).value_counts()
    for name, count in missing_summary.items():
        st.write(f"- **{name}**: {count} units missing")

# --- 8. PDF Export ---
if pdf_figs:
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for f in pdf_figs:
            pdf.savefig(f, bbox_inches='tight')
    
    st.download_button(
        label="🖨️ Download Cut Sheet PDF",
        data=buf.getvalue(),
        file_name="bvr_cut_planner.pdf",
        mime="application/pdf"
    )