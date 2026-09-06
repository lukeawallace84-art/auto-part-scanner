import os
import json
import re
import pandas as pd
import streamlit as st
from PIL import Image
import requests

# Set page config for mobile responsiveness
st.set_page_config(
    page_title="Auto Part Sourcing & Velocity Scanner",
    page_icon="🚗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom mobile-friendly styling
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
        border-left: 5px solid #007bff;
    }
    .green-light {
        background-color: #d4edda;
        color: #155724;
        padding: 10px;
        border-radius: 6px;
        font-weight: bold;
        text-align: center;
        margin: 10px 0;
    }
    .yellow-light {
        background-color: #fff3cd;
        color: #856404;
        padding: 10px;
        border-radius: 6px;
        font-weight: bold;
        text-align: center;
        margin: 10px 0;
    }
    .red-light {
        background-color: #f8d7da;
        color: #721c24;
        padding: 10px;
        border-radius: 6px;
        font-weight: bold;
        text-align: center;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# Configuration & API Keys
# -------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ API Configuration")
    gemini_key = st.text_input(
        "Gemini API Key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
        help="Get a free key from Google AI Studio"
    )
    serpapi_key = st.text_input(
        "SerpApi Key",
        value=os.getenv("SERPAPI_KEY", ""),
        type="password",
        help="Used to query eBay live active & sold listings"
    )
    st.markdown("---")
    st.markdown("**Typical Junkyard Costs**")
    default_cost = st.number_input("Default Pull Cost ($)", min_value=0.0, value=35.0, step=5.0)
    est_shipping = st.number_input("Estimated Shipping ($)", min_value=0.0, value=15.0, step=2.0)
    ebay_fee_pct = st.slider("eBay Fee Estimate (%)", min_value=5, max_value=20, value=13)

st.title("🚗 Auto Part Sourcing Scanner")
st.caption("Scan part tags, calculate Sell-Through Rate (STR), and check profit margins on the spot.")

# -------------------------------------------------------------
# Step 1: Image Capture / Input
# -------------------------------------------------------------
st.subheader("1. Take or Upload Part Photo")
photo_mode = st.radio("Input Source", ["Camera", "Upload File"], horizontal=True)

image = None
if photo_mode == "Camera":
    img_file = st.camera_input("Snap a photo of the part tag, barcode, or shell")
    if img_file:
        image = Image.open(img_file)
else:
    img_file = st.file_uploader("Upload an image", type=["jpg", "jpeg", "png", "webp"])
    if img_file:
        image = Image.open(img_file)

manual_override = st.text_input(
    "Optional: Manual Part Number or Description Override",
    placeholder="e.g., 2012 Camaro SS headlight 92244583"
)

yard_cost = st.number_input("Junkyard Asking Cost ($)", min_value=0.0, value=default_cost, step=5.0)

# -------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------
def analyze_part_image(pil_img, api_key: str) -> dict:
    """Uses Gemini 2.5 Flash to extract stamped OEM part numbers and component specs."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        st.error("Missing dependency: pip install google-genai")
        return {}

    client = genai.Client(api_key=api_key)
    prompt = (
        "You are an expert automotive parts appraiser and salvaging specialist. "
        "Analyze this image of an auto part or manufacturer tag. "
        "Focus on finding stamped OEM part numbers, laser-etched codes, manufacturer tags (e.g. GM, Ford, Bosch, Denso), "
        "vehicle platform, and exact part type.\n\n"
        "Return ONLY a JSON object with this exact schema:\n"
        "{\n"
        '  "oem_part_number": "exact part number string or empty string if not visible",\n'
        '  "manufacturer": "e.g. GM, Ford, AC Delco, Bosch",\n'
        '  "part_type": "e.g. OEM Xenon Headlight, Engine Control Module (ECM), Center Stack Screen",\n'
        '  "vehicle_platform": "e.g. 5th Gen Camaro SS, F-150, LS3",\n'
        '  "apparent_condition": "e.g. Clean Used, Broken Tabs, Core Only",\n'
        '  "recommended_ebay_query": "3-5 word concise query for eBay Motors focusing on part number and component name"\n'
        "}"
    )

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[pil_img, prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    return json.loads(response.text)

def query_ebay_velocity(search_query: str, api_key: str):
    """Queries SerpApi for active count, sold count, and the last 10 sold items."""
    endpoint = "https://serpapi.com/search.json"

    # 1. Query Active Listings
    active_params = {
        "engine": "ebay",
        "_nkw": search_query,
        "ebay_domain": "ebay.com",
        "api_key": api_key
    }
    active_resp = requests.get(endpoint, params=active_params, timeout=15).json()
    total_active = active_resp.get("search_information", {}).get("total_results", 0)
    # If total_results isn't parsed, count organic results returned
    if not total_active:
        total_active = len(active_resp.get("organic_results", []))

    # 2. Query Completed & Sold Listings (Last 90 days)
    sold_params = {
        "engine": "ebay",
        "_nkw": search_query,
        "ebay_domain": "ebay.com",
        "sold_items": "true",
        "completed_items": "true",
        "_sop": "13",  # Ended recently
        "api_key": api_key
    }
    sold_resp = requests.get(endpoint, params=sold_params, timeout=15).json()
    total_sold = sold_resp.get("search_information", {}).get("total_results", 0)
    organic_sold = sold_resp.get("organic_results", [])
    if not total_sold:
        total_sold = len(organic_sold)

    parsed_sold = []
    for item in organic_sold[:10]:
        price_raw = item.get("price", {}).get("extracted", 0.0)
        shipping_raw = item.get("shipping", "")
        shipping_val = 0.0
        if "free" in shipping_raw.lower():
            shipping_val = 0.0
        else:
            m = re.search(r"\$([\d,]+\.?\d*)", shipping_raw)
            if m:
                shipping_val = float(m.group(1).replace(",", ""))

        bids = item.get("bids")
        format_type = "Auction" if bids is not None else "Buy It Now"

        parsed_sold.append({
            "Title": item.get("title", "N/A"),
            "Sold Price ($)": round(price_raw, 2),
            "Shipping ($)": round(shipping_val, 2),
            "Total Price ($)": round(price_raw + shipping_val, 2),
            "Sold Date": item.get("sold_date", item.get("date", "N/A")),
            "Format": format_type,
            "Condition": item.get("condition", "Pre-Owned"),
            "URL": item.get("link", "")
        })

    return total_active, total_sold, parsed_sold

# -------------------------------------------------------------
# Step 2: Execution & Results
# -------------------------------------------------------------
if st.button("🚀 Analyze Part & Check Velocity", type="primary", use_container_width=True):
    if not gemini_key and not manual_override:
        st.warning("Please provide a Gemini API Key in the sidebar or enter a manual description.")
        st.stop()
    if not serpapi_key:
        st.warning("Please provide a SerpApi Key in the sidebar to fetch eBay market data.")
        st.stop()

    with st.spinner("Analyzing image and extracting OEM part details..."):
        detected_data = {}
        search_term = ""

        if image and gemini_key:
            detected_data = analyze_part_image(image, gemini_key)
            oem_no = detected_data.get("oem_part_number", "")
            part_type = detected_data.get("part_type", "")
            rec_query = detected_data.get("recommended_ebay_query", "")

            # Prioritize OEM part number if discovered
            if oem_no:
                search_term = f"{oem_no} {part_type}".strip()
            else:
                search_term = rec_query

        if manual_override:
            search_term = manual_override

        if not search_term:
            st.error("Could not formulate a valid search query. Try typing a part number manually.")
            st.stop()

    st.success(f"Target Query: **{search_term}**")
    if detected_data:
        with st.expander("🔍 Detected Specs & Tags", expanded=True):
            st.write(f"**OEM Part #:** `{detected_data.get('oem_part_number', 'Not visible')}`")
            st.write(f"**Part Type:** {detected_data.get('part_type', 'N/A')}")
            st.write(f"**Manufacturer / Platform:** {detected_data.get('manufacturer', '')} ({detected_data.get('vehicle_platform', '')})")
            st.write(f"**Apparent Condition:** {detected_data.get('apparent_condition', 'N/A')}")

    with st.spinner("Fetching active and sold comps from eBay..."):
        total_active, total_sold, sold_items = query_ebay_velocity(search_term, serpapi_key)

    # -------------------------------------------------------------
    # Step 3: Sell-Through Rate & Velocity Protocol
    # -------------------------------------------------------------
    st.subheader("2. Velocity & Demand Validation")
    col1, col2, col3 = st.columns(3)
    col1.metric("Active Listings", total_active)
    col2.metric("Sold (90 Days)", total_sold)

    str_rate = (total_sold / total_active * 100) if total_active > 0 else (100.0 if total_sold > 0 else 0.0)
    col3.metric("Sell-Through Rate (STR)", f"{str_rate:.1f}%")

    # Velocity Protocol Rating
    if str_rate >= 70.0:
        st.markdown("""
        <div class="green-light">
            🟢 GREEN LIGHT: HIGH VELOCITY<br>
            <span style="font-size: 0.9em; font-weight: normal;">
            STR &ge; 70%. Immediate buyer demand. Expected turnover within 5–14 days.
            </span>
        </div>
        """, unsafe_allow_html=True)
    elif 25.0 <= str_rate < 70.0:
        st.markdown("""
        <div class="yellow-light">
            🟡 YELLOW LIGHT: HIGH MARGIN ONLY<br>
            <span style="font-size: 0.9em; font-weight: normal;">
            STR 25%–69%. Moderate turnover. Only buy if margin spread is high.
            </span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="red-light">
            🔴 RED LIGHT: LOW DEMAND / SATURATED<br>
            <span style="font-size: 0.9em; font-weight: normal;">
            STR &lt; 25%. High competition or stagnant market. Risk of tying up capital.
            </span>
        </div>
        """, unsafe_allow_html=True)

    # -------------------------------------------------------------
    # Step 4: Margin & Payout Spread Analysis
    # -------------------------------------------------------------
    st.subheader("3. Financial & Margin Breakdown")

    if sold_items:
        df_sold = pd.DataFrame(sold_items)
        prices = df_sold["Total Price ($)"].tolist()
        avg_gross = sum(prices) / len(prices) if prices else 0.0
        median_gross = df_sold["Total Price ($)"].median()

        # Fee and net profit calculation
        est_fees = avg_gross * (ebay_fee_pct / 100.0)
        est_net_profit = avg_gross - yard_cost - est_shipping - est_fees

        m1, m2, m3 = st.columns(3)
        m1.metric("Avg Sale (Gross)", f"${avg_gross:.2f}")
        m2.metric("Median Sale", f"${median_gross:.2f}")
        m3.metric("Est. Net Profit", f"${est_net_profit:.2f}", delta=f"{est_net_profit:.2f}")

        st.caption(f"Net assumes: ${yard_cost:.2f} pull cost + ${est_shipping:.2f} shipping + {ebay_fee_pct}% eBay fee (${est_fees:.2f}).")

        st.markdown("### 📋 Last Sold Comps")
        st.dataframe(
            df_sold[["Sold Date", "Total Price ($)", "Sold Price ($)", "Shipping ($)", "Format", "Condition", "Title"]],
            hide_index=True,
            use_container_width=True
        )

        # -------------------------------------------------------------
        # Step 5: Export Functionality
        # -------------------------------------------------------------
        csv_data = df_sold.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export Comps to CSV",
            data=csv_data,
            file_name=f"ebay_comps_{search_term.replace(' ', '_')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.info("No completed sales found matching this exact search query. Try broadening the part description.")
