import streamlit as st
import os
import json
import requests
from PIL import Image

# Set up page config
st.set_page_config(page_title="Auto Part Sourcing Scanner", layout="wide")

# Sidebar for API keys
st.sidebar.title("API Configuration")
gemini_key = st.sidebar.text_input("Gemini API Key", value=os.getenv("GEMINI_API_KEY", ""), type="password")
serpapi_key = st.sidebar.text_input("SerpApi Key", value=os.getenv("SERPAPI_KEY", ""), type="password")

st.title("🚗 Auto Part Sourcing Scanner")
st.caption("Scan part tags, calculate Sell-Through Rate (STR), and check profit margins on the spot.")

# Sidebar settings
st.sidebar.markdown("---")
st.sidebar.markdown("**Typical Junkyard Costs**")
default_cost = st.sidebar.number_input("Default Pull Cost ($)", min_value=0.0, value=35.0, step=5.0)
est_shipping = st.sidebar.number_input("Estimated Shipping ($)", min_value=0.0, value=15.0, step=2.0)
ebay_fee_pct = st.sidebar.slider("eBay Fee Estimate (%)", min_value=5, max_value=20, value=13)

# Helper function to analyze image
def analyze_part_image(pil_img, api_key):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        st.error("Missing dependency: pip install google-genai")
        return {}
    
    if not api_key:
        st.error("Please enter a Gemini API Key.")
        return {}
        
    client = genai.Client(api_key=api_key)
    prompt = (
        "You are an expert automotive parts appraiser and salvaging specialist. "
        "Analyze this image of an auto part or manufacturer tag. "
        "Focus on finding stamped OEM part numbers, laser-etched codes, manufacturer tags (e.g. GM, Ford, Bosch, Denso), vehicle platform, and exact part type.\n\n"
        "Return ONLY a JSON object with this exact schema:\n"
        "{\n"
        '  "oem_part_number": "exact part number string or empty string if not visible",\n'
        '  "manufacturer": "e.g., GM, Ford, AC Delco, Bosch",\n'
        '  "part_type": "e.g., OEM Xenon Headlight, Engine Control Module (ECM), Center Stack Screen",\n'
        '  "vehicle_platform": "e.g., 5th Gen Camaro SS, F-150, LS3",\n'
        '  "apparent_condition": "e.g., Clean Used, Broken Tabs, Core Only",\n'
        '  "recommended_ebay_query": "3-5 word concise query for eBay Motors focusing on part number and component name"\n'
        "}"
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[pil_img, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Error calling Gemini API: {e}")
        return {}

def query_ebay_velocity(search_query, api_key):
    if not api_key:
        st.error("Please enter a SerpApi Key.")
        return {}
    endpoint = "https://serpapi.com/search.json"
    
    active_params = {
        "engine": "ebay",
        "_nkw": search_query,
        "ebay_domain": "ebay.com",
        "api_key": api_key
    }
    
    sold_params = {
        "engine": "ebay",
        "_nkw": search_query,
        "ebay_domain": "ebay.com",
        "LH_Sold": "1",
        "api_key": api_key
    }
    
    try:
        active_resp = requests.get(endpoint, params=active_params, timeout=15).json()
        sold_resp = requests.get(endpoint, params=sold_params, timeout=15).json()
        
        active_count = active_resp.get("search_information", {}).get("total_results", 0)
        sold_count = sold_resp.get("search_information", {}).get("total_results", 0)
        
        # Extract prices from sold items
        sold_items = sold_resp.get("organic_results", [])[:10]
        prices = []
        for item in sold_items:
            price_str = item.get("price", {}).get("extracted", 0)
            if price_str:
                prices.append(float(price_str))
        
        avg_price = sum(prices) / len(prices) if prices else 0.0
        
        return {
            "active_count": active_count,
            "sold_count": sold_count,
            "avg_price": avg_price,
            "sold_items": sold_items
        }
    except Exception as e:
        st.error(f"Error querying SerpApi: {e}")
        return {}

# Main UI
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

if st.button("Scan and Analyze Part"):
    search_query = ""
    analysis = {}
    
    if manual_override:
        search_query = manual_override
        st.info(f"Using manual override query: **{search_query}**")
    elif image:
        with st.spinner("Analyzing image with Gemini..."):
            analysis = analyze_part_image(image, gemini_key)
        if analysis:
            st.subheader("Gemini Analysis Results")
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Part Number:** {analysis.get('oem_part_number')}")
                st.write(f"**Manufacturer:** {analysis.get('manufacturer')}")
                st.write(f"**Part Type:** {analysis.get('part_type')}")
            with col2:
                st.write(f"**Vehicle Platform:** {analysis.get('vehicle_platform')}")
                st.write(f"**Condition:** {analysis.get('apparent_condition')}")
                st.write(f"**Recommended Query:** {analysis.get('recommended_ebay_query')}")
            
            search_query = analysis.get("recommended_ebay_query")
    else:
        st.warning("Please provide an image or manual override query.")
        
    if search_query:
        with st.spinner("Fetching eBay market data via SerpApi..."):
            market_data = query_ebay_velocity(search_query, serpapi_key)
            
        if market_data:
            st.subheader("eBay Market Insights")
            active = market_data.get("active_count", 0)
            sold = market_data.get("sold_count", 0)
            avg_sell_price = market_data.get("avg_price", 0.0)
            
            str_rate = (sold / active * 100) if active > 0 else (sold * 100 if sold > 0 else 0.0)
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Active Listings", active)
            c2.metric("Sold Listings (90 days)", sold)
            c3.metric("Sell-Through Rate (STR)", f"{str_rate:.1f}%")
            c4.metric("Avg Sold Price", f"${avg_sell_price:.2f}")
            
            fees = avg_sell_price * (ebay_fee_pct / 100)
            net_profit = avg_sell_price - yard_cost - est_shipping - fees
            
            st.subheader("Profitability Estimation")
            pc1, pc2, pc3 = st.columns(3)
            pc1.write(f"**Gross Revenue:** ${avg_sell_price:.2f}")
            pc2.write(f"**Estimated Costs:** ${yard_cost + est_shipping + fees:.2f} (Cost: ${yard_cost}, Ship: ${est_shipping}, Fees: ${fees:.2f})")
            if net_profit > 0:
                pc3.metric("Estimated Net Profit", f"${net_profit:.2f}", delta="PROFITABLE")
            else:
                pc3.metric("Estimated Net Profit", f"${net_profit:.2f}", delta="LOSS", delta_color="inverse")
