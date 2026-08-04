import asyncio
import os
import sqlite3
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx

# 1. 載入環境變數
load_dotenv()
API_KEY = os.getenv("HENRIK_API_KEY")

if not API_KEY:
    raise RuntimeError("無法在環境變數中找到 HENRIK_API_KEY，請檢查 .env 檔案")

DB_NAME = "valorant_stats.db"

# 2. 資料庫輔助函式：自動修復舊對戰時間字串 (一次性修復舊 DB)
def fix_existing_match_history_time():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT match_id, player_id, game_start FROM match_history")
        rows = cursor.fetchall()

        tz_tw = timezone(timedelta(hours=8))
        updated_count = 0

        for match_id, player_id, raw_start in rows:
            if not raw_start or "上午" in raw_start or "下午" in raw_start:
                continue

            try:
                # 解析原本 HenrikDev UTC 格式: "Monday, August 03, 2026 09:00 AM"
                dt_utc = datetime.strptime(raw_start, "%A, %B %d, %Y %I:%M %p").replace(tzinfo=timezone.utc)
                dt_tw = dt_utc.astimezone(tz_tw)

                period = "上午" if dt_tw.hour < 12 else "下午"
                hour_12 = dt_tw.hour % 12
                if hour_12 == 0:
                    hour_12 = 12

                new_time_str = f"{dt_tw.year}/{dt_tw.month}/{dt_tw.day} {period}{hour_12}:{dt_tw.minute:02d}"

                cursor.execute("""
                    UPDATE match_history 
                    SET game_start = ? 
                    WHERE match_id = ? AND player_id = ?
                """, (new_time_str, match_id, player_id))
                updated_count += 1
            except Exception:
                pass

        conn.commit()
        conn.close()
        if updated_count > 0:
            print(f"✨ [DB 自動修復] 成功將 {updated_count} 筆雲端舊歷史紀錄的時間轉換為台灣時間！")
    except Exception as e:
        print(f"⚠️ [DB 自動修復跳過]: {e}")

# 取得目前啟用的玩家
def get_active_players_from_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name, tag, team FROM players WHERE is_active = 1")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "tag": r[1], "team": r[2]} for r in rows]

# 3. 帶有指數退避重試機制的 HTTP 請求輔助函式
async def fetch_with_backoff(client: httpx.AsyncClient, url: str, headers: dict, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 429:
                retry_after_hdr = response.headers.get("Retry-After")
                if retry_after_hdr and retry_after_hdr.isdigit():
                    wait_time = int(retry_after_hdr)
                else:
                    wait_time = 2 ** (attempt + 1)
                
                print(f"⚠️ [HTTP 429 限流] 觸發 API 限制，等待 {wait_time} 秒後進行第 {attempt + 1}/{max_retries} 次重試...")
                await asyncio.sleep(wait_time)
                continue
                
            return response
        except httpx.RequestError as e:
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(1.5)
            
    return None

# 4. 定時排程抓取主任務
async def fetch_and_update_all_friends():
    target_players = get_active_players_from_db()
    
    if not target_players:
        print("⚠️ [定時任務] 資料庫內目前沒有設定追蹤的玩家。")
        return

    print(f"\n⏰ [大循環任務啟動] 從 DB 讀取到 {len(target_players)} 位玩家，開始同步戰績...")

    async def process_single_player(client: httpx.AsyncClient, p_info: dict) -> bool:
        name = p_info["name"]
        tag = p_info["tag"]
        team = p_info.get("team", "FREE AGENT")
        player_id = f"{name}#{tag}"
        
        encoded_name = urllib.parse.quote(name)
        encoded_tag = urllib.parse.quote(tag)
        url = f"https://api.henrikdev.xyz/valorant/v3/matches/ap/{encoded_name}/{encoded_tag}?mode=competitive&size=20"
        headers = {"Authorization": API_KEY, "Accept": "application/json"}

        response = await fetch_with_backoff(client, url, headers, max_retries=2)

        if response and response.status_code == 200:
            data = response.json()
            if data.get("status") == 200:
                matches = data.get("data", []) or []
                total_hs, total_hits, wins = 0, 0, 0
                card_icon_url = ""
                clean_name, clean_tag = name.replace(" ", "").lower(), tag.replace(" ", "").lower()

                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()

                for m in matches:
                    if not m:
                        continue
                        
                    metadata = m.get("metadata") or {}
                    match_id = metadata.get("matchid")
                    map_name = metadata.get("map")
                    
                    # 使用 raw timestamp 並轉為台灣時間 (UTC+8)
                    raw_start = metadata.get("game_start")
                    if raw_start:
                        try:
                            tz_tw = timezone(timedelta(hours=8))
                            dt = datetime.fromtimestamp(raw_start, tz=tz_tw)
                            period = "上午" if dt.hour < 12 else "下午"
                            hour_12 = dt.hour % 12
                            if hour_12 == 0:
                                hour_12 = 12
                            game_start = f"{dt.year}/{dt.month}/{dt.day} {period}{hour_12}:{dt.minute:02d}"
                        except Exception:
                            game_start = metadata.get("game_start_patched", "")
                    else:
                        game_start = metadata.get("game_start_patched", "")

                    player_data = None
                    all_players = (m.get("players") or {}).get("all_players") or []
                    for p in all_players:
                        if p and p.get("name", "").replace(" ", "").lower() == clean_name and p.get("tag", "").replace(" ", "").lower() == clean_tag:
                            player_data = p
                            break

                    if player_data:
                        assets = player_data.get("assets") or {}
                        card_assets = assets.get("card") or {}
                        if not card_icon_url:
                            card_icon_url = card_assets.get("small", "")

                        stats = player_data.get("stats") or {}
                        hs = stats.get("headshots", 0) or 0
                        bs = stats.get("bodyshots", 0) or 0
                        ls = stats.get("legshots", 0) or 0
                        kills = stats.get("kills", 0) or 0
                        deaths = stats.get("deaths", 0) or 0
                        assists = stats.get("assists", 0) or 0
                        
                        hits = hs + bs + ls
                        m_hs_rate = round((hs / hits * 100), 1) if hits > 0 else 0.0

                        player_team = (player_data.get("team") or "").lower()
                        teams = m.get("teams") or {}
                        is_win = 1 if (teams.get(player_team) or {}).get("has_won", False) else 0

                        total_hs += hs
                        total_hits += hits
                        wins += is_win

                        cursor.execute('''
                            INSERT INTO match_history 
                            (match_id, player_id, map_name, agent, kills, deaths, assists, headshots, bodyshots, legshots, hs_rate, is_win, game_start)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(match_id, player_id) DO UPDATE SET
                                game_start=excluded.game_start,
                                kills=excluded.kills,
                                deaths=excluded.deaths,
                                assists=excluded.assists,
                                hs_rate=excluded.hs_rate,
                                is_win=excluded.is_win
                        ''', (match_id, player_id, map_name, player_data.get("character"), kills, deaths, assists, hs, bs, ls, m_hs_rate, is_win, game_start))

                match_count = len(matches)
                losses = match_count - wins
                hs_rate_num = round((total_hs / total_hits * 100), 1) if total_hits > 0 else 0.0
                win_rate_num = round((wins / match_count * 100), 1) if match_count > 0 else 0.0

                if not card_icon_url:
                    card_icon_url = "https://vgraphs.com/images/players/cards/valorant-card-display.png"

                cursor.execute('''
                    INSERT INTO player_stats (player_id, name, tag, team, card_icon, wins, losses, win_rate, hs_rate, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(player_id) DO UPDATE SET
                        team=excluded.team,
                        card_icon=excluded.card_icon,
                        wins=excluded.wins,
                        losses=excluded.losses,
                        win_rate=excluded.win_rate,
                        hs_rate=excluded.hs_rate,
                        last_updated=CURRENT_TIMESTAMP
                ''', (player_id, name, tag, team, card_icon_url, wins, losses, f"{win_rate_num}%", f"{hs_rate_num}%"))

                today_date = datetime.now().strftime("%Y-%m-%d")
                cursor.execute('''
                    INSERT INTO daily_stats (player_id, record_date, avg_hs_rate, win_rate)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id, record_date) DO UPDATE SET
                        avg_hs_rate=excluded.avg_hs_rate, win_rate=excluded.win_rate
                ''', (player_id, today_date, hs_rate_num, win_rate_num))

                conn.commit()
                conn.close()
                print(f"✅ [資料同步成功] [{team}] {player_id}")
                return True
        
        status = response.status_code if response else "Error"
        print(f"⚠️ [更新失敗] {player_id} (HTTP {status})")
        return False

    failed_players = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for p_info in target_players:
            try:
                success = await process_single_player(client, p_info)
                if not success:
                    failed_players.append(p_info)
            except Exception as e:
                print(f"❌ [例外錯誤] {p_info['name']}#{p_info['tag']}: {str(e)}")
                failed_players.append(p_info)

            await asyncio.sleep(2.5)

        if failed_players:
            print(f"\n🔄 [開始二次補救重試] 共有 {len(failed_players)} 位玩家第一輪更新失敗，準備重試...")
            await asyncio.sleep(5)

            still_failed_count = 0
            for p_info in failed_players:
                player_id = f"{p_info['name']}#{p_info['tag']}"
                print(f"🛠️ [補救嘗試] 重新請求：{player_id}")
                try:
                    success = await process_single_player(client, p_info)
                    if not success:
                        still_failed_count += 1
                except Exception as e:
                    print(f"❌ [補救失敗] {player_id}: {str(e)}")
                    still_failed_count += 1

                await asyncio.sleep(2.5)

            print(f"\n🏁 [二次重試完成] 成功補救 {len(failed_players) - still_failed_count} 人，最終仍失敗 {still_failed_count} 人。")
        else:
            print("\n✨ [大循環完全成功] 本輪所有玩家皆已順利更新完成！")

# 5. Lifespan 與排程器設定
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 💡 伺服器啟動時，先自動修復舊 DB 資料庫的時間欄位
    fix_existing_match_history_time()

    # 啟動時於背景異步執行第一輪同步
    asyncio.create_task(fetch_and_update_all_friends())
    
    # 每 8 分鐘大循環
    scheduler.add_job(fetch_and_update_all_friends, 'interval', minutes=8)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="Valorant 戰績分析 API", lifespan=lifespan)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 6. API 路由定義
@app.post("/api/players/add")
async def add_player(name: str, tag: str, team: str = "FREE AGENT"):
    player_id = f"{name}#{tag}"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO players (player_id, name, tag, team, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(player_id) DO UPDATE SET is_active=1, team=excluded.team
        ''', (player_id, name, tag, team))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"成功新增玩家: {player_id} 到 {team}"}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"新增失敗: {str(e)}")

@app.get("/api/leaderboard")
async def get_leaderboard():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name, tag, team, card_icon, wins, losses, win_rate, hs_rate, last_updated FROM player_stats")
    rows = cursor.fetchall()
    conn.close()

    return [{
        "name": r[0],
        "tag": r[1],
        "player": f"{r[0]}#{r[1]}",
        "team": r[2] if r[2] else "FREE AGENT",
        "card_icon": r[3] if r[3] else "https://vgraphs.com/images/players/cards/valorant-card-display.png",
        "wins": r[4],
        "losses": r[5],
        "win_rate": r[6],
        "hs_rate": r[7],
        "last_updated": r[8]
    } for r in rows]

@app.get("/api/player/{name}/{tag}/history")
async def get_player_history(name: str, tag: str):
    player_id = f"{name}#{tag}"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT map_name, agent, kills, deaths, assists, hs_rate, is_win, game_start 
        FROM match_history 
        WHERE player_id = ? 
        ORDER BY game_start DESC LIMIT 20
    ''', (player_id,))
    rows = cursor.fetchall()
    conn.close()

    return [{
        "map": r[0], "agent": r[1],
        "kda": f"{r[2]} / {r[3]} / {r[4]}",
        "hs_rate": f"{r[5]}%",
        "result": "勝利" if r[6] == 1 else "敗北",
        "game_time": r[7]
    } for r in rows]

@app.get("/api/player/{name}/{tag}/trend")
async def get_player_trend(name: str, tag: str):
    player_id = f"{name}#{tag}"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT record_date, avg_hs_rate, win_rate 
        FROM daily_stats 
        WHERE player_id = ? 
        ORDER BY record_date ASC
    ''', (player_id,))
    rows = cursor.fetchall()
    conn.close()

    return {
        "dates": [r[0] for r in rows],
        "hs_rates": [r[1] for r in rows],
        "win_rates": [r[2] for r in rows]
    }