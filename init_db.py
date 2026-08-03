import sqlite3

DB_NAME = "valorant_stats.db"

def setup_database():
    print("🚀 開始初始化 SQLite 資料庫...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. 新增：玩家名單管理表 (追蹤清單)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY, -- 例如 "LBJ wicky9987#3530"
            name TEXT NOT NULL,
            tag TEXT NOT NULL,
            team TEXT DEFAULT 'FREE AGENT',
            is_active INTEGER DEFAULT 1 -- 1 代表追蹤中，0 代表暫停追蹤
        )
    ''')
    print("  [✓] players 名單管理表建立完成")

    # 2. 預先寫入你的初始玩家名單 (若不存在才寫入)
    default_players = [
        ("Yuzumi#Neon", "Yuzumi", "Neon", "TEAM 01"),
        ("稻米米#IITI", "稻米米", "IITI", "TEAM 01"),
        ("3Qsweet#3Qswt", "3Qsweet", "3Qswt", "TEAM 01"),
        ("CG1#7177", "CG1", "7177", "TEAM 01"),

        #==========2==========
        ("抖音小齊#7Z86", "抖音小齊", "7Z86", "TEAM 02"),
        ("勝利v老大#VIVI", "勝利v老大", "VIVI", "TEAM 02"),

        #=========3==========
        ("朔Sakuro#1001", "朔Sakuro", "1001", "TEAM 03"),
        ("冠緯同學2#tw2", "冠緯同學2", "tw2", "TEAM 03"),
        ("拍拍Piper#729", "拍拍Piper", "729", "TEAM 03"),
        ("心 cocor0#心理變態", "心 cocor0", "心理變態", "TEAM 03"),
        ("抹茶是個小土豆#發芽土豆", "抹茶是個小土豆", "發芽土豆", "TEAM 03"),

        #=========4==========
        ("Restia#7115", "Restia", "7115", "TEAM 04"),
        ("烟花學妹#0330", "烟花學妹", "0330", "TEAM 04"),
        ("KSPKSP#8149", "KSPKSP", "8149", "TEAM 04"),
        ("珮蕾同學#0603", "珮蕾同學", "0603", "TEAM 04"),

        #========5==========
        ("雪著點#1227", "雪著點", "1227", "TEAM 05"),
        ("Koo#0416", "Koo", "0416", "TEAM 05"),
        ("niconini#0911", "niconini", "0911", "TEAM 05"),

        #=======6==========
        ("Marika#1494", "Marika", "1494", "TEAM 06"),

        #=======7==========
        ("ev913z#手柄爺", "ev913z", "手柄爺", "TEAM 07"),
        ("m1xture#8787", "m1xture", "8787", "TEAM 07"),
        ("Liang#0714", "Liang", "0714", "TEAM 07"),

        #=======8==========
        ("MayJovo#0501", "MayJovo", "0501", "TEAM 08"),
        ("実在壞#0121", "実在壞", "0121", "TEAM 08"),
        ("罪有悠歸五毒俱全#YuWu", "罪有悠歸五毒俱全", "YuWu", "TEAM 08"),
        ]
    cursor.executemany('''
        INSERT OR IGNORE INTO players (player_id, name, tag, team)
        VALUES (?, ?, ?, ?)
    ''', default_players)
    print("  [✓] 預設玩家名單匯入完成")

    # 3. 玩家戰績快取/主表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_stats (
            player_id TEXT PRIMARY KEY,
            name TEXT,
            tag TEXT,
            team TEXT,
            card_icon TEXT,
            wins INTEGER,
            losses INTEGER,
            win_rate TEXT,
            hs_rate TEXT,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  [✓] player_stats 資料表建立完成")

    # 4. 每場對戰紀錄表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS match_history (
            match_id TEXT PRIMARY KEY,
            player_id TEXT,
            map_name TEXT,
            agent TEXT,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            headshots INTEGER,
            bodyshots INTEGER,
            legshots INTEGER,
            hs_rate REAL,
            is_win INTEGER,
            game_start DATETIME
        )
    ''')
    print("  [✓] match_history 資料表建立完成")

    # 5. 每日爆頭率/勝率趨勢表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT,
            record_date DATE,
            avg_hs_rate REAL,
            win_rate REAL,
            UNIQUE(player_id, record_date)
        )
    ''')
    print("  [✓] daily_stats 資料表建立完成")

    conn.commit()
    conn.close()
    print("🎉 所有資料表與初始名單建立完成！\n")

if __name__ == "__main__":
    setup_database()