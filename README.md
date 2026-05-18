# CodeSage

AI-powered code review platform with GitHub integration.

## Overview

CodeSage analyzes pull requests and provides AI-generated code review feedback using Google Gemini. It integrates with GitHub through OAuth for user authentication and GitHub App for repository access.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.11+ / FastAPI |
| Database | PostgreSQL (SQLAlchemy ORM) |
| Cache/Queue | Redis + BullMQ |
| AI | Google Gemini API |
| Frontend | Angular 17+ (separate HTML/TS/CSS) |

## Project Structure

```
codesage/
├── backend/                     # FastAPI Backend
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/          # API endpoints
│   │   ├── db/
│   │   │   └── models/          # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── security/            # JWT & auth
│   │   ├── services/            # GitHub & Gemini
│   │   └── workers/             # Background jobs
│   ├── alembic/                 # Database migrations
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                    # Angular Frontend (TODO)
│
├── docker-compose.yml          # Local development
└── README.md
```

## Backend Structure

### Core Files

| File | Description |
|------|-------------|
| `app/main.py` | FastAPI application entry point |
| `app/config.py` | Environment configuration with pydantic-settings |
| `app/chunker.py` | Diff chunking for large PRs |
| `app/diff_parser.py` | GitHub diff parsing |

### API Routes (`app/api/routes/`)

| Endpoint | Description |
|----------|-------------|
| `auth.py` | GitHub OAuth login/callback |
| `users.py` | User management |
| `repositories.py` | Repository CRUD |
| `pull_requests.py` | PR listing and details |
| `reviews.py` | AI review operations |
| `webhooks.py` | GitHub webhook handler |
| `health.py` | Health check endpoints |

### Database Models (`app/db/models/`)

| Model | Description |
|-------|-------------|
| `users` | GitHub OAuth users |
| `oauth_tokens` | Encrypted access/refresh tokens |
| `github_installations` | GitHub App installations |
| `repositories` | Connected GitHub repositories |
| `pull_requests` | Tracked PRs |
| `reviews` | AI-generated reviews |
| `review_comments` | Inline review comments |
| `webhook_events` | Webhook audit trail |

### Services (`app/services/`)

| Service | Description |
|---------|-------------|
| `github.py` | GitHub OAuth, App auth, API client, webhook verification |
| `gemini.py` | Google Gemini AI integration for code review |

### Workers (`app/workers/`)

| File | Description |
|------|-------------|
| `review_queue.py` | BullMQ job queue setup |
| `review_processor.py` | Background review processing |
| `main.py` | Worker entry point |

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auth/github/login` | Redirect to GitHub OAuth |
| GET | `/api/auth/github/callback` | OAuth callback handler |
| POST | `/api/auth/refresh` | Refresh JWT token |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/logout` | Logout user |

### Repositories

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/repositories` | List user's repositories |
| POST | `/api/repositories` | Connect a repository |
| GET | `/api/repositories/{id}` | Get repository details |
| PATCH | `/api/repositories/{id}` | Update repository settings |
| DELETE | `/api/repositories/{id}` | Remove repository |

### Pull Requests

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/repositories/{id}/pulls` | List PRs in repository |
| GET | `/api/pulls/{id}` | Get PR details with diff |
| POST | `/api/pulls/{id}/review` | Trigger AI review |

### Reviews

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reviews` | List all reviews |
| GET | `/api/reviews/{id}` | Get review details |
| GET | `/api/reviews/{id}/status` | Check review status |
| POST | `/api/reviews/{id}/retry` | Retry failed review |
| DELETE | `/api/reviews/{id}` | Delete review |
| PATCH | `/api/reviews/{id}/comments/{cid}/resolve` | Resolve comment |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/webhooks/github` | GitHub webhook receiver |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | API health check |
| GET | `/api/health/ready` | Readiness check |
| GET | `/api/health/live` | Liveness check |

## Configuration

Create `.env` from `.env.example`:

```env
# Database
DATABASE_URL=postgresql://codesage:codesage@localhost:5432/codesage

# Redis
REDIS_URL=redis://localhost:6379

# GitHub OAuth App
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_secret

# GitHub App
GITHUB_APP_ID=your_app_id
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."

# Gemini AI
GEMINI_API_KEY=your_gemini_key

# JWT
JWT_SECRET=your_jwt_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# App
APP_NAME=CodeSage
APP_VERSION=1.0.0
DEBUG=true
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:4200

# Webhook
GITHUB_WEBHOOK_SECRET=your_webhook_secret
```

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Node.js 20+ (for frontend)
- GitHub OAuth App credentials
- GitHub App credentials
- Google Gemini API key

### Setup

```bash
# 1. Navigate to backend
cd backend

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 5. Run database migrations
alembic upgrade head

# 6. Start the server
uvicorn app.main:app --reload
```

### Docker (PostgreSQL + Redis)

```bash
# Start database and cache
docker-compose up -d

# Verify services
docker-compose ps
```

### Running Workers

```bash
# In a separate terminal
cd backend
python -m app.workers.main
```

## GitHub Integration Setup

### 1. Create GitHub OAuth App

1. Go to **GitHub Settings** → **Developer settings** → **OAuth Apps**
2. Click **New OAuth App**
3. Fill in:
   - **App name**: CodeSage
   - **Homepage URL**: `http://localhost:4200`
   - **Authorization callback URL**: `http://localhost:8000/api/auth/github/callback`
4. Copy **Client ID** and generate **Client Secret**

### 2. Create GitHub App (for repository access)

1. Go to **GitHub Settings** → **Developer settings** → **GitHub Apps**
2. Click **New GitHub App**
3. Fill in:
   - **App name**: CodeSage
   - **Homepage URL**: `http://localhost:4200`
   - **Callback URL**: `http://localhost:8000/api/auth/github/callback`
4. Set **Permissions**:
   - Repository: Pull requests (Read & Write), Contents (Read)
   - Account: Email addresses (Read)
5. Enable webhook and set URL to `http://localhost:8000/api/webhooks/github`
6. Generate **private key** (.pem file)

## API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

## Database Schema

```sql
-- Users (GitHub OAuth)
users (id, github_id, login, email, name, avatar_url, created_at, updated_at)

-- OAuth Tokens
oauth_tokens (id, user_id, access_token, refresh_token, expires_at)

-- GitHub App Installations
github_installations (id, app_id, installation_id, account_id, account_type, permissions)

-- Repositories
repositories (id, installation_id, github_repo_id, name, full_name, private, default_branch, webhook_id, enabled)

-- Pull Requests
pull_requests (id, repo_id, github_pr_id, number, title, state, author_login, base_sha, head_sha, additions, deletions, changed_files)

-- Reviews
reviews (id, pr_id, status, summary, error_message, gemini_model, tokens_used, started_at, completed_at)

-- Review Comments
review_comments (id, review_id, github_comment_id, file_path, line_number, body, severity, category, resolved)

-- Webhook Events (for idempotency)
webhook_events (id, repo_id, event_type, delivery_id, action, payload, processed)
```

## License

MIT