# Project Rules and Verification Steps

## Build Commands
```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database
python run_init_db.py

# Run bot
python run_bot.py

# Run admin panel
python run_admin.py

# Run tests
python test_scenarios.py
```

## Test Commands
```bash
# Run all scenario tests
python test_scenarios.py

# Test individual scenarios (modify test_scenarios.py to run specific tests)
```

## Verification Steps

### 1. Database Verification
- Check that bookings are loaded from JSON
- Verify database tables are created
- Confirm booking tokens are unique

### 2. Bot Functionality
- Test `/start DEMO-ONLY-R001` command
- Verify token validation (test with wrong token)
- Check natural language parsing
- Validate time format (HH:MM)
- Validate car plate format
- Test rules acceptance
- Verify escalation for security questions

### 3. Admin Panel
- Access http://localhost:8000
- Verify all bookings appear
- Test confirm check-in button
- Test escalate button
- Check mobile responsiveness

### 4. Business Logic
- Verify cost calculations (pet: 1500/night, coal: 500/package)
- Check KPP string generation for cars
- Validate night calculations
- Test reminder system with time simulation

### 5. Security
- Verify wrong token rejection
- Check that booking info is not revealed for invalid tokens
- Confirm escalation for security questions
- Test that original booking data is not modified

## Project-Specific Information

### Data Files Location
All JSON data files are in the `data/` directory:
- bookings.json - Booking data
- rules.json - Business rules
- prices.json - Service prices
- faq.json - FAQ database
- tests.json - Test scenarios
- dialogues.json - Test dialogues

### Key Configuration
- Bot token: Set in .env (BOT_TOKEN)
- Database: PostgreSQL with SQLAlchemy 2.0
- LLM: OpenAI API for message parsing
- Admin IDs: Comma-separated Telegram user IDs

### Important Constraints
1. **Privacy**: Never reveal other guests' booking information
2. **No Hallucination**: Use only prices from prices.json and faq.json
3. **Security**: Escalate questions about rules, fines, changes
4. **Validation**: Reject invalid time formats and car plates
5. **Payment**: Always include "Оплата производится строго на ресепшене при заселении"

### Test Scenarios Summary
1. **R01**: Full card with pet and car - KPP generation, cost calculation
2. **R02**: No car, guest count change - escalation without unauthorized changes
3. **R03**: Invalid time/plate - validation and rejection
4. **R04**: Fireworks question - security escalation
5. **R05**: Date change request - escalation without modifying original dates
6. **R06**: Rules rejection - escalation
7. **R07**: Reminder system - 12-hour reminder with escalation
8. **R08**: Wrong token - security error without revealing info
9. **R09**: Coal and early arrival - cost calculation with unknown prices
10. **R10**: Full card without car, human request - proper escalation

## User Preferences
- Python 3.11+ required
- Docker and Docker Compose for containerization
- Mobile-friendly admin interface
- LLM integration for natural language processing
- Strict adherence to JSON data files for prices and rules
