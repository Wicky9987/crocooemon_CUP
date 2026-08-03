from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import httpx
import urllib.parse
import traceback

load_dotenv()
API_KEY = os.getenv("HENRIK_API_KEY")

if not API_KEY:
    raise RuntimeError("無法在環境變數中找到 HENRIK_API_KEY，請確認 .env 檔案設定是否正確。")

app = FastAPI(title="Valorant 數據 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/stats")
async def get_player_stats(
    name: str = Query(..., description="Riot ID (不含 #)"),
    tag: str = Query(..., description="Riot Tag (不含 #)")
):
    encoded_name = urllib.parse.quote(name)
    encoded_tag = urllib.parse.quote(tag)
    
    # 採用 HenrikDev v3 API Matches 端點
    url = f"https://api.henrikdev.xyz/valorant/v3/matches/ap/{encoded_name}/{encoded_tag}?mode=competitive&size=20"
    
    headers = {
        "Authorization": API_KEY,
        "Accept": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            data = response.json()

        # 如果 HenrikDev 回傳狀態碼不是 200 (例如 404 找不到玩家、401 Key無效)
        if response.status_code != 200 or data.get("status") != 200:
            error_msg = "HenrikDev API 回應錯誤"
            if "errors" in data and len(data["errors"]) > 0:
                error_msg = data["errors"][0].get("message", error_msg)
            elif "message" in data:
                error_msg = data["message"]
            raise HTTPException(status_code=response.status_code, detail=f"API 錯誤 ({response.status_code}): {error_msg}")

        matches = data.get("data", [])
        if not matches:
            return {"player": f"{name}#{tag}", "message": "查無該玩家的競技模式對戰紀錄"}

        total_headshots = 0
        total_bodyshots = 0
        total_legshots = 0
        wins = 0

        for m in matches:
            # 尋找當前查詢玩家的個人數據
            player_data = None
            for p in m.get("players", {}).get("all_players", []):
                if p.get("name", "").lower() == name.lower() and p.get("tag", "").lower() == tag.lower():
                    player_data = p
                    break
            
            if player_data:
                stats = player_data.get("stats", {})
                total_headshots += stats.get("headshots", 0)
                total_bodyshots += stats.get("bodyshots", 0)
                total_legshots += stats.get("legshots", 0)
                
                # 判斷個人所屬隊伍是否獲勝
                player_team = player_data.get("team", "").lower() # 'red' 或 'blue'
                teams = m.get("teams", {})
                if teams.get(player_team, {}).get("has_won", False):
                    wins += 1

        total_hits = total_headshots + total_bodyshots + total_legshots
        match_count = len(matches)
        losses = match_count - wins

        hs_rate = round((total_headshots / total_hits * 100), 1) if total_hits > 0 else 0.0
        win_rate = round((wins / match_count * 100), 1) if match_count > 0 else 0.0

        return {
            "player": f"{name}#{tag}",
            "total_matches": match_count,
            "wins": wins,
            "losses": losses,
            "win_rate": f"{win_rate}%",
            "hs_rate": f"{hs_rate}%"
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        # 在控制台印出完整報錯，方便排錯
        print("\n=== 後端發生例外狀況 (Exception) ===")
        traceback.print_exc()
        print("===================================\n")
        raise HTTPException(status_code=500, detail=f"後端處理資料時出錯: {str(e)}")