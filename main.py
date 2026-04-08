from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import requests
import os
from dotenv import load_dotenv
# 這裡使用的是 Google 最新的 GenAI Python SDK
from google import genai

# 1. 載入環境變數 (本地端讀取 .env，雲端則讀取 Render 的 Environment Variables)
load_dotenv()

# 2. 初始化 Gemini Client (新版 SDK 語法)
# 請確保已在環境變數中設定 GEMINI_API_KEY
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = FastAPI()

# 3. 設定 CORS 權限，允許 Vercel 前端存取
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 部署時可將此替換為你的 Vercel 網址以增加安全性
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def fetch_mstr_holdings():
    """從 CoinGecko 抓取 MicroStrategy 的最新比特幣持倉量"""
    url = "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin"
    try:
        response = requests.get(url, headers={"accept": "application/json"}, timeout=10)
        response.raise_for_status() 
        data = response.json()
        for company in data.get('companies', []):
            if 'MicroStrategy' in company.get('name', ''):
                return int(company.get('total_holdings', 0))
        # 若 API 沒回傳特定欄位，使用目前的預估值
        return 272220 
    except:
        return 272220 

def fetch_nav_data(period="30d"):
    """抓取 MSTR 與 BTC 股價並計算 NAV 溢價率"""
    # 抓取股價資料
    mstr = yf.Ticker("MSTR").history(period=period)[['Close']].rename(columns={'Close': 'MSTR_Price'})
    btc = yf.Ticker("BTC-USD").history(period=period)[['Close']].rename(columns={'Close': 'BTC_Price'})

    # 時間格式統一化
    mstr.index = mstr.index.tz_localize(None).normalize()
    btc.index = btc.index.tz_localize(None).normalize()
    df = pd.merge(mstr, btc, left_index=True, right_index=True, how='inner')

    # 獲取總發行股數與持倉量以計算 NAV
    try:
        SHARES_OUTSTANDING = yf.Ticker("MSTR").info.get('sharesOutstanding', 277620000)
    except:
        SHARES_OUTSTANDING = 277620000

    TOTAL_BTC_HELD = fetch_mstr_holdings()

    # 計算每股內含價值 (NAV) 與溢價
    btc_per_share = TOTAL_BTC_HELD / SHARES_OUTSTANDING
    df['NAV_Per_Share'] = btc_per_share * df['BTC_Price']
    df['Premium_to_NAV_Pct'] = ((df['MSTR_Price'] / df['NAV_Per_Share']) - 1) * 100

    # 格式化資料
    df = df.round(2)
    df.reset_index(inplace=True)
    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    return df.to_dict(orient='records')

def generate_ai_insight(data_records):
    """使用新版 google-genai SDK 呼叫 Gemini 2.0 Flash 進行趨勢分析"""
    # 截取最近 7 天的數據進行分析
    recent_data = data_records[-7:]
    
    prompt = f"""
    You are an expert quantitative crypto analyst. Review this 7-day trend of MicroStrategy's (MSTR) Premium to Net Asset Value (NAV):
    {recent_data}

    Write a sharp, 2-sentence insight explaining the trend direction and what it suggests about current market sentiment or speculative demand. Do not use markdown formatting like bolding.
    """
    
    try:
        # 新版 SDK 的呼叫方法
        response = client.models.generate_content(
            model='gemini-3-flash', 
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return "AI Insight currently unavailable. Please check backend connection."

@app.get("/api/nav-data")
def get_nav_data():
    """主 API 端點：整合數據與 AI 總結"""
    try:
        # 1. 抓取數據
        data = fetch_nav_data(period="30d")
        
        # 2. 生成 AI 見解
        ai_text = generate_ai_insight(data)
        
        # 3. 回傳 JSON 給前端
        return {
            "status": "success", 
            "data": data, 
            "ai_summary": ai_text
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}