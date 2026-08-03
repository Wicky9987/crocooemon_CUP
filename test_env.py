# test_env.py
import os
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI

print("✅ 所有套件（fastapi, httpx, python-dotenv）匯入成功！")

# 測試讀取 .env 檔案
load_dotenv()
api_key = os.getenv("HENRIK_API_KEY")

if api_key:
    print(f"✅ 成功讀取到 .env 設定！Key 前三碼為: {api_key[:3]}***")
else:
    print("⚠️ 提醒：尚未讀取到 HENRIK_API_KEY，請確認同資料夾下是否有 .env 檔案。")