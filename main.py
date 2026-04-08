from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import requests
import os
from dotenv import load_dotenv
from google import genai

# Load the API key from the .env file and configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

app = FastAPI()

# Change your CORS middleware to look like this temporarily:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for now (you can lock this down later)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def fetch_mstr_holdings():
    # ... (Keep your existing CoinGecko function exactly as it is) ...
    url = "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin"
    try:
        response = requests.get(url, headers={"accept": "application/json"}, timeout=10)
        response.raise_for_status() 
        data = response.json()
        for company in data.get('companies', []):
            if 'MicroStrategy' in company.get('name', ''):
                return int(company.get('total_holdings', 0))
        return 766970 
    except:
        return 766970 

def fetch_nav_data(period="30d"):
    # ... (Keep your existing data fetching and math exactly as it is) ...
    mstr = yf.Ticker("MSTR").history(period=period)[['Close']].rename(columns={'Close': 'MSTR_Price'})
    btc = yf.Ticker("BTC-USD").history(period=period)[['Close']].rename(columns={'Close': 'BTC_Price'})

    mstr.index = mstr.index.tz_localize(None).normalize()
    btc.index = btc.index.tz_localize(None).normalize()
    df = pd.merge(mstr, btc, left_index=True, right_index=True, how='inner')

    try:
        SHARES_OUTSTANDING = yf.Ticker("MSTR").info.get('sharesOutstanding', 277620000)
    except:
        SHARES_OUTSTANDING = 277620000

    TOTAL_BTC_HELD = fetch_mstr_holdings()

    btc_per_share = TOTAL_BTC_HELD / SHARES_OUTSTANDING
    df['NAV_Per_Share'] = btc_per_share * df['BTC_Price']
    df['Premium_to_NAV_Pct'] = ((df['MSTR_Price'] / df['NAV_Per_Share']) - 1) * 100

    df = df.round(2)
    df.reset_index(inplace=True)
    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    return df.to_dict(orient='records')

# --- NEW: The Gemini 2.0 AI Function ---
def generate_ai_insight(data_records):
    """Passes the most recent 7 days of data to Gemini 2.0 Flash for analysis."""
    # Grab just the last 7 days to keep the prompt focused
    recent_data = data_records[-7:]
    
    prompt = f"""
    You are an expert quantitative crypto analyst. Review this 7-day trend of MicroStrategy's (MSTR) Premium to Net Asset Value (NAV):
    {recent_data}

    Write a sharp, 2-sentence insight explaining the trend direction and what it suggests about current market sentiment or speculative demand. Do not use markdown formatting like bolding.
    """
    
    try:
        # 新版 SDK 的呼叫方法
        response = client.models.generate_content(
            model='gemini-3-flash-preview', 
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return "AI Insight currently unavailable. Please check backend connection."
# Update the endpoint to return both the data array and the AI string
@app.get("/api/nav-data")
def get_nav_data():
    try:
        # 1. Get the math data
        data = fetch_nav_data(period="30d")
        
        # 2. Generate the AI text based on that data
        ai_text = generate_ai_insight(data)
        
        # 3. Send both to React
        return {"status": "success", "data": data, "ai_summary": ai_text}
    except Exception as e:
        return {"status": "error", "message": str(e)}