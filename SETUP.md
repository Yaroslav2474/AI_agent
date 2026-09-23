# Setup Guide for Речка и Песок Telegram Bot

## Quick Start

### 1. Environment Setup

```bash
# Copy environment file
cp .env.example .env

# Edit .env with your credentials
# BOT_TOKEN=your_telegram_bot_token
# DATABASE_URL=postgresql+asyncpg://rechkapesok:rechkapesok_password@localhost:5432/rechkapesok
# OPENAI_API_KEY=your_openai_api_key
# ADMIN_IDS=123456789,987654321
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Database Setup

#### Option A: Using Docker (Recommended)
```bash
# Start PostgreSQL
docker-compose up -d postgres

# Initialize database with bookings
python run_init_db.py
```

#### Option B: Local PostgreSQL
```bash
# Create database
createdb rechkapesok

# Initialize database with bookings
python run_init_db.py
```

### 4. Run Services

#### Option A: Using Docker
```bash
# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f bot
docker-compose logs -f admin
```

#### Option B: Local Run
```bash
# Terminal 1: Run bot
python run_bot.py

# Terminal 2: Run admin panel
python run_admin.py
```

### 5. Access Admin Panel

Open browser to: `http://localhost:8000`

## Testing

### Run All Test Scenarios
```bash
python test_scenarios.py
```

### Manual Testing

1. **Start Bot**: Send `/start DEMO-ONLY-R001` to your bot
2. **Provide Info**: Send guest information as natural language
3. **Accept Rules**: Confirm rules acceptance
4. **Check Admin Panel**: Verify card appears in admin panel

### Time Simulation for Testing Reminders

For testing scenario R07 (reminders), use the admin command:
```
/travel_time 12
```

This advances system time by 12 hours to trigger reminder logic.

## Project Structure

```
AI_agent/
├── src/
│   ├── bot/              # Telegram bot
│   ├── db/               # Database configuration
│   ├── api/              # FastAPI admin panel
│   ├── services/         # Business logic
│   ├── models/           # Database models
│   └── utils/            # Configuration
├── data/                 # JSON data files
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── run_*.py             # Startup scripts
```

## Key Features

1. **Token-based Authentication**: Secure access with booking tokens
2. **Natural Language Processing**: LLM-powered message parsing
3. **Smart Validation**: Time, car plate, and data validation
4. **Cost Calculation**: Automatic calculation based on prices.json
5. **KPP Generation**: Automatic pass generation for cars
6. **Reminder System**: 12-hour reminder with escalation
7. **Admin Panel**: Mobile-friendly management interface
8. **Security**: Privacy protection and request escalation

## Troubleshooting

### Database Connection Issues
- Check DATABASE_URL in .env
- Ensure PostgreSQL is running
- Verify database exists

### Bot Not Responding
- Check BOT_TOKEN is correct
- Verify bot has proper permissions
- Check logs for errors

### LLM Integration Issues
- Verify OPENAI_API_KEY is valid
- Check API quota limits
- Review LLM service logs

### Admin Panel Not Loading
- Ensure admin service is running
- Check port 8000 is available
- Verify database connection

## Security Notes

- Never commit .env file to version control
- Use strong tokens and API keys
- Limit admin IDs to trusted personnel
- Regularly update dependencies
- Monitor logs for suspicious activity

## Support

For issues or questions:
- Check logs: `docker-compose logs`
- Review documentation in README.md
- Contact administrator at +7 (844) 255-38-43
