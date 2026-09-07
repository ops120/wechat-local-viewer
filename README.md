# WeChat Local Viewer (本地微信数据库查看器)

> ⚠️ **本项目只提供查看界面，不提供任何解密工具**
>
> 本仓库不含密钥提取、数据库解密等任何工具与代码。聊天数据由用户自行准备后导入目录。


> 实测微信版本：**4.1.13.12**（Windows）

让用户在本机直接浏览微信聊天记录：会话列表、消息浏览、全文搜索、多格式导出。数据由用户提供，本工具**只负责查看**，全部本地运行，零外部依赖。

## 功能特性

- 📱 **会话列表**：按时间倒序展示所有会话（单聊/群聊/公众号）
- 💬 **消息浏览**：按时间正序渲染（64 万条消息已实测导入，浏览流畅）
- 🔍 **全文搜索**：基于 FTS5，1 秒内返回搜索结果
- 🤖 **LLM 集成**：支持 OpenAI 兼容协议（DeepSeek / OpenAI / 硅基流动 / Ollama 等），流式输出总结/问答
- ⚡ **本地优先**：所有数据本地处理，零外部依赖（除用户配置的 LLM）

## 环境要求

- Python 3.10+
- Node.js 22+
- Windows 10/11

## 界面预览

![界面预览](demo/ui.png)

## 一键启动

1. 把用户自己的聊天数据放到项目根目录（二选一，自动识别）：
   ```
   wechat-local-viewer/
   ├── decrypted/   （或 .decrypted/）
   │   ├── contact/     # 联系人数据
   │   ├── session/     # 会话数据
   │   ├── message/     # 消息数据（message_*.db）
   │   └── hardlink/    # 图片索引（可选）
   └── start.bat
   ```
2. 双击 `start.bat`
3. 浏览器自动打开 http://127.0.0.1:18787/（后端直接托管前端构建产物）

### 默认端口

| 端口 | 用途 |
|---|---|
| **18787** | 后端 FastAPI（避开 8765 等 Windows 保留端口） |
| **15713** | 前端 Vite dev（避开 5173 易冲突） |

### 自定义端口

```powershell
set WCVIEWER_PORT=28888
set WCVIEWER_FRONT_PORT=25813
start.bat
```

start.bat 启动前会做端口冲突检测，被占用会报错并给出提示。

## 手动启动

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 18787

# 前端（开发模式）
cd frontend
npm install
npm run dev
# 生产用：npm run build → 后端自动托管 dist
```

## 目录结构

### 源数据（用户提供）

```
decrypted/  （或 .decrypted/，二选一自动识别）
├── contact/     # 联系人数据
├── session/     # 会话数据
├── message/     # 消息数据（message_*.db 等）
└── hardlink/    # 图片文件索引（hardlink.db，可选）
```

### 项目结构

```
.
├── backend/           # 后端服务
│   ├── app/
│   │   ├── api/       # API 路由
│   │   ├── parsers/   # 数据解析器
│   │   ├── llm/       # LLM 客户端
│   │   └── etl.py     # ETL 主流程
│   ├── tests/
│   └── requirements.txt
├── frontend/          # 前端应用
│   ├── src/
│   │   ├── api/       # API 客户端
│   │   ├── stores/    # Pinia 状态管理
│   │   ├── views/     # 页面组件
│   │   └── components/# UI 组件
│   └── package.json
├── .github/           # CI 工作流
├── start.bat          # 一键启动脚本
├── refresh.bat        # 增量刷新脚本
├── THIRD_PARTY_NOTICES.md         # 第三方组件说明
├── CONTRIBUTING.md / CHANGELOG.md / LICENSE
└── README.md
```

### 运行时数据目录（不属于仓库）

以下目录由工具/服务在运行时生成或由用户提供，均已通过 `.gitignore` 排除，**不要**提交到版本库：

| 目录 | 作用 |
|---|---|
| `decrypted/` 或 `.decrypted/` | 微信聊天数据（用户提供） |
| `.cache/` | 中间层数据库 `app.db`（ETL 自动创建） |
| `.export/` | 导出产物 |
| `.tmp/` | 日志等临时文件 |

## 系统架构

```
┌──────────────────────────────────────┐
│  数据源（用户提供）                    │
│  decrypted/                           │
└──────────────┬──────────────────────┘
               │ ① ETL (etl.py)
               │    指纹判断：全量 / 增量 / 跳过
               │    parse_sessions→sessions 表
               │    parse_contacts→contacts 表
               │    parse_messages→messages 表 (+FTS5 索引)
               │    _update_session_stats 聚合统计
               ▼
┌──────────────────────────────────────┐
│  .cache/app.db  (中间层查询库)        │
│  sessions / contacts / messages + FTS │
└──────────────┬──────────────────────┘
               │ ② API (FastAPI :18787)
               ▼
┌──────────────────────────────────────┐
│  frontend (Vue, 已构建至 dist)        │
│  会话列表 / 消息浏览 / 搜索 / 导出     │
└──────────────────────────────────────┘
```

## 验证步骤

1. **检查文件结构**
   ```powershell
   cd <仓库根目录>
   tree /F frontend
   ```

2. **前端依赖安装**
   ```bash
   cd frontend
   npm config set registry https://registry.npmmirror.com
   npm config set maxsockets 4
   npm config set audit false
   npm install
   ```

3. **一键启动**
   ```powershell
   cd <仓库根目录>
   start.bat
   ```

## API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/sessions` | GET | 会话列表（按 `last_time` 倒序） |
| `/api/sessions/{username}` | GET | 单会话详情 |
| `/api/messages?session=X` | GET | 消息分页 |
| `/api/messages/{id}` | GET | 单消息详情 |
| `/api/messages/{id}/context` | GET | 消息上下文 |
| `/api/search?q=X` | GET | 全文搜索（FTS5） |
| `/api/search/suggest?q=X` | GET | 搜索建议 |
| `/api/admin/etl` | POST | 触发 ETL（`{force:bool}`） |
| `/api/admin/status` | GET | ETL 状态 |
| `/api/admin/logs` | GET | 日志尾部 |
| `/api/admin/rebuild-fts` | POST | 重建 FTS 索引 |
| `/api/admin/stats/daily` | GET | 每日统计 |
| `/api/llm/config` | GET / POST | LLM 配置 |
| `/api/llm/chat` | POST | LLM 流式问答（SSE） |
| `/media/...` | GET | 媒体静态文件（仅已还原的部分图片可用） |

## LLM 配置（可选）

打开页面右上角「设置」，填：

- **Base URL**：OpenAI 兼容服务地址
  - DeepSeek: `https://api.deepseek.com/v1`
  - OpenAI: `https://api.openai.com/v1`
  - Ollama: `http://localhost:11434/v1`
  - 硅基流动: `https://api.siliconflow.cn/v1`
- **API Key**：对应服务的 key
- **Model**：模型名（如 `deepseek-chat`、`gpt-4o-mini`、`qwen2.5:7b`）

API key 仅存浏览器 `localStorage`，随每次问答请求发给后端（也可用环境变量 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 做后备默认值）。未配置时点「总结」会给出明确提示。

## 安全

- **零外发**：除 LLM base_url 外无任何 outbound HTTP。
- 静态 `/media/` 不列目录。
- LLM API key 仅存浏览器 localStorage。

## 性能预算

| 项 | 备注 |
|---|---|
| 启动 → 首屏 | 数秒（64 万消息库，未实测计时） |
| 打开会话（首屏 30 条） | 索引查询，表现良好（未实测计时） |
| 全文搜索 | FTS5 索引，秒级（未实测计时） |
| LLM 流式首字 | 取决于模型服务（未实测计时） |

## 约束

- Python pip 用清华源。
- Node `^22.19.0 || >=24.0.0`。
- 默认端口 **18787（后端）/ 15713（前端）**，避开 8765（Windows 保留）/ 5173（易冲突）。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

## 社区

本项目在 [LINUX DO](https://linux.do) 社区进行开源推广，感谢社区佬友的交流、反馈与建议。

## 致谢 / 第三方组件

- [FastAPI](https://github.com/fastapi/fastapi)、[Vue](https://github.com/vuejs/core)、[Vite](https://github.com/vitejs/vite) 及所有开源依赖的作者。