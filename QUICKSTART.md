# OpenNotebookLM 快速入門指南

## 🚀 快速開始

### 前置需求

- Docker Desktop (包含 Docker Compose)
- 至少 4GB RAM
- 10GB 可用硬碟空間

### 安裝步驟

1. **複製專案**
   ```bash
   git clone https://github.com/yourusername/OpenNotebookLM.git
   cd OpenNotebookLM
   ```

2. **配置環境變數**
   ```bash
   cp .env.example .env
   ```
   編輯 `.env` 檔案，設定您的 API 金鑰和偏好設定。

3. **啟動服務**

   **基本啟動（僅後端）：**
   ```bash
   # Linux/Mac
   ./start.sh
   
   # Windows
   start.bat
   ```

   **啟動含本地 LLM（Ollama）：**
   ```bash
   # Linux/Mac
   ./start.sh with-ollama
   
   # Windows
   start.bat with-ollama
   ```

   **啟動含快取（Redis）：**
   ```bash
   # Linux/Mac
   ./start.sh with-cache
   
   # Windows
   start.bat with-cache
   ```

   **完整啟動（所有服務）：**
   ```bash
   # Linux/Mac
   ./start.sh full
   
   # Windows
   start.bat full
   ```

4. **驗證安裝**
   
   服務啟動後，可以訪問：
   - API 文檔：http://localhost:8000/docs
   - 後端 API：http://localhost:8000
   - 前端介面：http://localhost:3000 (如果已部署)

## 📦 服務架構

```
OpenNotebookLM
├── Backend (FastAPI)     :8000
├── Frontend (Next.js)    :3000  [選擇性]
├── Ollama (Local LLM)    :11434 [選擇性]
└── Redis (Cache)         :6379  [選擇性]
```

## 🔧 常用指令

### 查看服務狀態
```bash
docker-compose ps
```

### 查看日誌
```bash
# 所有服務
docker-compose logs -f

# 特定服務
docker-compose logs -f backend
```

### 停止服務
```bash
# Linux/Mac
./stop.sh

# Windows
stop.bat
```

### 重啟服務
```bash
docker-compose restart
```

### 清理所有資料
```bash
docker-compose down -v
```

## 📝 環境變數說明

主要設定項目：

| 變數名稱 | 說明 | 預設值 |
|---------|------|--------|
| `APP_ENV` | 執行環境 | `development` |
| `OPENAI_API_KEY` | OpenAI API 金鑰 | - |
| `ANTHROPIC_API_KEY` | Anthropic API 金鑰 | - |
| `LLM_BACKEND` | LLM 後端選擇 | `openai` |
| `EMBEDDING_BACKEND` | 嵌入後端 | `openai` |
| `USE_LOCAL_MODELS` | 使用本地模型 | `false` |
| `ENABLE_CACHE` | 啟用快取 | `true` |

詳細設定請參考 `.env.example` 檔案。

## 🎯 使用範例

### 上傳文件
```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@document.pdf"
```

### 提問
```bash
curl -X POST "http://localhost:8000/api/v1/chat/query" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "文件中提到了什麼重點？",
    "session_id": "test-session"
  }'
```

## 🐛 故障排除

### Docker 無法啟動
- 確認 Docker Desktop 已啟動
- Windows 用戶：確認 WSL2 已正確設定

### 服務無法連接
- 檢查防火牆設定
- 確認端口未被占用：`netstat -an | grep 8000`

### 記憶體不足
- 增加 Docker Desktop 的記憶體配額
- 減少同時運行的服務

### API 金鑰錯誤
- 檢查 `.env` 檔案中的 API 金鑰設定
- 確認金鑰有效且有足夠額度

## 📚 更多資源

- [完整文檔](./docs/README.md)
- [API 參考](http://localhost:8000/docs)
- [專案規格書](./SPECIFICATION.md)
- [開發指南](./docs/DEVELOPMENT.md)

## 💡 提示

1. **首次啟動**：第一次啟動可能需要 5-10 分鐘下載 Docker 映像
2. **本地開發**：使用 `APP_ENV=development` 以獲得詳細的錯誤訊息
3. **生產部署**：記得更改預設密碼和加強安全設定

## 🆘 獲得幫助

如遇到問題：
1. 查看 [故障排除指南](./docs/TROUBLESHOOTING.md)
2. 檢查 [GitHub Issues](https://github.com/yourusername/OpenNotebookLM/issues)
3. 加入我們的 [Discord 社群](https://discord.gg/yourlink)

---

祝您使用愉快！🎉
