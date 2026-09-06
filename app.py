import streamlit as st
import requests
import json
import pandas as pd
from PIL import Image

# -------------------------------------------------------------
# Page Configuration & Mobile CSS
# -------------------------------------------------------------
st.set_page_config(
    page_title="Auto Part Sourcing & Cross-Market Scanner",
    page_icon="🚗",
    layout="centered"
)

st.markdown("""
<style>
    @media (max-width: 640px) {
        .stDataFrame { font-size: 12px; }
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session State
if "df_ebay_sold" not in st.session_state:
    st.session_state.df_ebay_sold = None
if "df_fb" not in st.session_state:
    st.session_state.df_fb = None
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

st.title("🚗 Auto Part Sourcing & Cross-Market Scanner")
st.caption("Scan part tags, evaluate eBay market velocity, and compare local Facebook Marketplace listings.")

# -------------------------------------------------------------
# Sidebar API Configurations & Local Settings
# -------------------------------------------------------------
with st.sidebar:
    st.header("🔑 API Configurations")
    gemini_api_key = st.text_input("Gemini API Key", type="password")
    serpapi_key = st.text_input("SerpApi Key", type="password")
    
    st.header("📍 Local Market Settings")
    user_location = st.text_input("Location (City, State / Zip)", value="Springfield, MO")
    default_cost = st.number_input("Default Junkyard Cost ($)", min_value=0.0, value=25.0, step=5.0)

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

manual_override = st.text_input("Optional: Manual Part Number or Description Override", placeholder="e.g., 2012 Camaro SS headlight 92244583")
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
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[pil_img, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Error during image analysis: {e}")
        return {}

def query_ebay_velocity(search_query: str, api_key: str):
    """Queries SerpApi for active count, sold count, and the last 10 sold items with robust fallbacks."""
    endpoint = "https://serpapi.com/search.json"
    
    # 1. Query Active Listings
    active_params = {
        "engine": "ebay",
        "_nkw": search_query,
        "ebay_domain": "ebay.com",
        "api_key": api_key
    }
    try:
        active_resp = requests.get(endpoint, params=active_params, timeout=15).json()
    except Exception:
        active_resp = {}
        
    total_active = active_resp.get("search_information", {}).get("total_results", 0)
    active_results = active_resp.get("organic_results", [])
    if not total_active and active_results:
        total_active = len(active_results)

    # 2. Query Completed & Sold Listings (Last 90 days)
    sold_params = {
        "engine": "ebay",
        "_nkw": search_query,
        "ebay_domain": "ebay.com",
        "lh_sold": "1",
        "lh_complete": "1",
        "api_key": api_key
    }
    try:
        sold_resp = requests.get(endpoint, params=sold_params, timeout=15).json()
    except Exception:
        sold_resp = {}
        
    total_sold = sold_resp.get("search_information", {}).get("total_results", 0)
    sold_results = sold_resp.get("organic_results", [])
    if not total_sold and sold_results:
        total_sold = len(sold_results)

    return {
        "total_active": total_active,
        "total_sold": total_sold,
        "recent_solds": sold_results[:10]
    }

def query_facebook_marketplace(search_query: str, location: str, api_key: str):
    """Queries Google Search via SerpApi targeting local Facebook Marketplace listings."""
    endpoint = "https://serpapi.com/search.json"
    fb_query = f"{search_query} site:facebook.com/marketplace"
    
    params = {
        "engine": "google",
        "q": fb_query,
        "location": location,
        "api_key": api_key
    }
    
    try:
        resp = requests.get(endpoint, params=params, timeout=15).json()
    except Exception:
        resp = {}
        
    organic = resp.get("organic_results", [])
    items = []
    for result in organic[:8]:
        title = result.get("title", "No Title")
        link = result.get("link", "#")
        snippet = result.get("snippet", "")
        items.append({
            "Title": title,
            "Snippet / Details": snippet,
            "Link": link
        })
    return items

# -------------------------------------------------------------
# Execution Flow
# -------------------------------------------------------------
if image and st.button("Analyze Part & Cross-Compare Markets", type="primary"):
    if not gemini_api_key or not serpapi_key:
        st.warning("Please provide both your Gemini API Key and SerpApi Key in the sidebar.")
    else:
        with st.spinner("Analyzing part image with Gemini 2.5 Flash..."):
            st.session_state.analysis_result = analyze_part_image(image, gemini_api_key)

if st.session_state.analysis_result:
    res = st.session_state.analysis_result
    st.success("Analysis Complete!")
    
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Part Number:** {res.get('oem_part_number', 'N/A')}")
        st.write(f"**Manufacturer:** {res.get('manufacturer', 'N/A')}")
        st.write(f"**Part Type:** {res.get('part_type', 'N/A')}")
    with col2:
        st.write(f"**Platform:** {res.get('vehicle_platform', 'N/A')}")
        st.write(f"**Condition:** {res.get('apparent_condition', 'N/A')}")
        st.write(f"**Suggested Query:** {res.get('recommended_ebay_query', 'N/A')}")

    query_to_run = manual_override if manual_override else res.get('recommended_ebay_query', '')
    if query_to_run:
        # 1. eBay Market Velocity
        with st.spinner(f"Querying eBay marketplace velocity for: '{query_to_run}'..."):
            ebay_data = query_ebay_velocity(query_to_run, serpapi_key)
            
            total_active = ebay_data["total_active"]
            total_sold = ebay_data["total_sold"]
            str_percentage = (total_sold / (total_active + total_sold) * 100) if (total_active + total_sold) > 0 else 0.0

            st.markdown("---")
            st.subheader("📊 eBay Market Velocity & Comps")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Active Listings", total_active)
            m2.metric("Sold Listings (90d)", total_sold)
            m3.metric("Sell-Through Rate (STR)", f"{str_percentage:.1f}%")

            recent_solds = ebay_data["recent_solds"]
            if recent_solds:
                items_data = []
                for item in recent_solds:
                    title = item.get("title", "Unknown Title")
                    price_info = item.get("price", {})
                    extracted_price = price_info.get("extracted", 0.0) if isinstance(price_info, dict) else 0.0
                    link = item.get("link", "#")
                    items_data.append({"Title": title, "Sold Price ($)": extracted_price, "Link": link})
                
                st.session_state.df_ebay_sold = pd.DataFrame(items_data)
                st.dataframe(st.session_state.df_ebay_sold, use_container_width=True)
            else:
                st.info("No recent eBay sold items returned for this specific query.")

        # 2. Local Facebook Marketplace & Classifieds Comps
        with st.spinner(f"Scanning Facebook Marketplace & local comps near {user_location}..."):
            fb_items = query_facebook_marketplace(query_to_run, user_location, serpapi_key)
            
            st.markdown("---")
            st.subheader(f"🌐 Local Marketplace Comps ({user_location})")
            
            if fb_items:
                st.session_state.df_fb = pd.DataFrame(fb_items)
                st.dataframe(st.session_state.df_fb, use_container_width=True)
            else:
                st.info("No direct Facebook Marketplace listings found locally for this exact query.")
