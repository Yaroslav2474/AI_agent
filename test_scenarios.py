import asyncio
import json
from datetime import datetime
from src.db.database import get_session, init_db
from src.models.database import Booking, GuestCard
from src.services.data_loader import data_loader
from src.services.business_logic import business_logic
from sqlalchemy import select

async def test_scenario(test_id: str, booking_id: str, messages: list, expected: str):
    """Test a single scenario"""
    print(f"\n{'='*60}")
    print(f"Testing Scenario {test_id}: {booking_id}")
    print(f"Expected: {expected}")
    print(f"{'='*60}")

    # Initialize database
    await init_db()

    # Load booking data
    booking = data_loader.get_booking_by_id(booking_id)
    if not booking:
        print(f"❌ FAIL: Booking {booking_id} not found")
        return False

    print(f"✓ Booking found: {booking['guest_name']} - {booking['house_id']}")

    # Simulate the scenario
    async for session in get_session():
        # Check if booking exists in database
        result = await session.execute(
            select(Booking).where(Booking.booking_id == booking_id)
        )
        booking_record = result.scalar_one_or_none()

        if not booking_record:
            print(f"❌ FAIL: Booking {booking_id} not in database")
            return False

        print(f"✓ Booking in database: {booking_record.status}")

        # Test based on scenario
        if test_id == "R01":
            # Test: Full card with pet and car
            # Expected: Full card; rules_accepted=true with version and time; KPP TEST-CAR-001; pet request, conditional sum 1500 for one night with confirmation note
            success = test_r01(booking_record, session)
        elif test_id == "R02":
            # Test: Card without car, different guest count
            # Expected: car_plates=[] without repeated plate request; guest count differs from booking - escalation, no unauthorized booking change
            success = test_r02(booking_record, session)
        elif test_id == "R03":
            # Test: Invalid time and plate format
            # Expected: Request correct time and clarify plate; card not marked ready
            success = test_r03(booking_record, session)
        elif test_id == "R04":
            # Test: Fireworks question
            # Expected: Don't invent permission and fine; pass to administrator
            success = test_r04(booking_record, session)
        elif test_id == "R05":
            # Test: Change booking dates
            # Expected: Create change request; don't change original dates
            success = test_r05(booking_record, session)
        elif test_id == "R06":
            # Test: Rules not accepted
            # Expected: rules_accepted=false; escalation; card not ready
            success = test_r06(booking_record, session)
        elif test_id == "R07":
            # Test: Reminder after 12 hours
            # Expected: Exactly one reminder after first 12 hours, then status incomplete and pass to human; no real waiting needed
            success = test_r07(booking_record, session)
        elif test_id == "R08":
            # Test: Wrong token
            # Expected: Don't reveal booking and other guest info; suggest reconnect or administrator
            success = test_r08(booking_id, session)
        elif test_id == "R09":
            # Test: Coal and early arrival
            # Expected: Educational preliminary coal sum 1000; early arrival - price unknown; don't give unknown sum as zero
            success = test_r09(booking_record, session)
        elif test_id == "R10":
            # Test: Full card without car, request human
            # Expected: Full card without car line; save human request and context. Don't claim key or cabin already ready
            success = test_r10(booking_record, session)
        else:
            print(f"❌ Unknown test ID: {test_id}")
            return False

        if success:
            print(f"✅ PASS: Scenario {test_id}")
        else:
            print(f"❌ FAIL: Scenario {test_id}")

        return success

def test_r01(booking_record, session):
    """Test R01: Full card with pet and car"""
    # Check if fields are properly set
    if not booking_record.rules_accepted:
        print("❌ rules_accepted should be true")
        return False

    if not booking_record.rules_version:
        print("❌ rules_version should be set")
        return False

    if not booking_record.rules_accepted_at:
        print("❌ rules_accepted_at should be set")
        return False

    if not booking_record.has_car:
        print("❌ has_car should be true")
        return False

    if not booking_record.car_plates or booking_record.car_plates[0] != "TEST-CAR-001":
        print("❌ car_plates should contain TEST-CAR-001")
        return False

    if not booking_record.has_pet:
        print("❌ has_pet should be true")
        return False

    # Check guest card for KPP string
    result = session.execute(
        select(GuestCard).where(GuestCard.booking_id == booking_record.booking_id)
    )
    guest_card = result.scalar_one_or_none()

    if not guest_card or not guest_card.kpp_string:
        print("❌ KPP string should be generated")
        return False

    if "TEST-CAR-001" not in guest_card.kpp_string:
        print("❌ KPP string should contain TEST-CAR-001")
        return False

    # Check estimated cost for pet
    if not guest_card.estimated_cost:
        print("❌ estimated_cost should be set")
        return False

    if "pet" not in guest_card.estimated_cost:
        print("❌ estimated_cost should contain pet cost")
        return False

    pet_cost = guest_card.estimated_cost["pet"]
    if pet_cost.get("total") != 1500:  # 1 night * 1500
        print(f"❌ Pet cost should be 1500, got {pet_cost.get('total')}")
        return False

    if not pet_cost.get("requires_confirmation"):
        print("❌ Pet cost should require confirmation")
        return False

    print("✓ All R01 checks passed")
    return True

def test_r02(booking_record, session):
    """Test R02: Card without car, different guest count"""
    # Check car_plates is empty
    if booking_record.car_plates and len(booking_record.car_plates) > 0:
        print("❌ car_plates should be empty")
        return False

    # Check if guest count differs from original booking
    original_booking = data_loader.get_booking_by_id(booking_record.booking_id)
    if booking_record.guest_adults != original_booking["adults"]:
        print("✓ Guest count differs from original (expected)")

    # Check status should be needs_human due to guest count difference
    if booking_record.status != "needs_human":
        print(f"❌ Status should be needs_human, got {booking_record.status}")
        return False

    print("✓ All R02 checks passed")
    return True

def test_r03(booking_record, session):
    """Test R03: Invalid time and plate format"""
    # Check if validation caught the invalid time (30:00)
    if booking_record.arrival_time == "30:00":
        print("❌ Invalid time 30:00 should be rejected")
        return False

    # Check if validation caught the invalid plate (А12ВС)
    if booking_record.car_plates and "А12ВС" in booking_record.car_plates:
        print("❌ Invalid plate А12ВС should be rejected")
        return False

    # Card should not be ready
    if booking_record.status == "ready":
        print("❌ Card should not be ready with invalid data")
        return False

    print("✓ All R03 checks passed")
    return True

def test_r04(booking_record, session):
    """Test R04: Fireworks question"""
    # Status should be needs_human
    if booking_record.status != "needs_human":
        print(f"❌ Status should be needs_human, got {booking_record.status}")
        return False

    # Check human_requests contains the fireworks question
    if not booking_record.human_requests:
        print("❌ human_requests should contain the fireworks question")
        return False

    fireworks_found = False
    for req in booking_record.human_requests:
        if "фейерверк" in req.get("message", "").lower():
            fireworks_found = True
            break

    if not fireworks_found:
        print("❌ Fireworks question not found in human_requests")
        return False

    print("✓ All R04 checks passed")
    return True

def test_r05(booking_record, session):
    """Test R05: Change booking dates"""
    # Original dates should not be changed
    original_booking = data_loader.get_booking_by_id(booking_record.booking_id)
    if booking_record.arrival_date != original_booking["arrival_date"]:
        print("❌ Original arrival_date should not be changed")
        return False

    if booking_record.departure_date != original_booking["departure_date"]:
        print("❌ Original departure_date should not be changed")
        return False

    # Status should be needs_human
    if booking_record.status != "needs_human":
        print(f"❌ Status should be needs_human, got {booking_record.status}")
        return False

    # Check human_requests contains the change request
    if not booking_record.human_requests:
        print("❌ human_requests should contain the change request")
        return False

    change_found = False
    for req in booking_record.human_requests:
        if "перенесите" in req.get("message", "").lower() or "изменить" in req.get("message", "").lower():
            change_found = True
            break

    if not change_found:
        print("❌ Change request not found in human_requests")
        return False

    print("✓ All R05 checks passed")
    return True

def test_r06(booking_record, session):
    """Test R06: Rules not accepted"""
    # rules_accepted should be false
    if booking_record.rules_accepted != False:
        print(f"❌ rules_accepted should be false, got {booking_record.rules_accepted}")
        return False

    # Status should be needs_human
    if booking_record.status != "needs_human":
        print(f"❌ Status should be needs_human, got {booking_record.status}")
        return False

    # Card should not be ready
    result = session.execute(
        select(GuestCard).where(GuestCard.booking_id == booking_record.booking_id)
    )
    guest_card = result.scalar_one_or_none()

    if guest_card and guest_card.status == "ready":
        print("❌ Guest card should not be ready when rules not accepted")
        return False

    print("✓ All R06 checks passed")
    return True

def test_r07(booking_record, session):
    """Test R07: Reminder after 12 hours"""
    # This test requires time simulation
    # Check if reminder count is exactly 1
    if booking_record.reminder_count != 1:
        print(f"❌ reminder_count should be 1, got {booking_record.reminder_count}")
        return False

    # Status should be incomplete or needs_human after reminder
    if booking_record.status not in ["incomplete", "needs_human"]:
        print(f"❌ Status should be incomplete or needs_human, got {booking_record.status}")
        return False

    print("✓ All R07 checks passed")
    return True

def test_r08(booking_id, session):
    """Test R08: Wrong token"""
    # This test checks security - wrong token should not reveal booking info
    # The test should fail to access the booking with wrong token
    wrong_token_booking = data_loader.get_booking_by_token("WRONG-TOKEN")
    if wrong_token_booking:
        print("❌ WRONG-TOKEN should not match any booking")
        return False

    print("✓ All R08 checks passed")
    return True

def test_r09(booking_record, session):
    """Test R09: Coal and early arrival"""
    # Check guest card for estimated costs
    result = session.execute(
        select(GuestCard).where(GuestCard.booking_id == booking_record.booking_id)
    )
    guest_card = result.scalar_one_or_none()

    if not guest_card or not guest_card.estimated_cost:
        print("❌ estimated_cost should be set")
        return False

    # Check coal cost (2 packages * 500 = 1000)
    if "coal" not in guest_card.estimated_cost:
        print("❌ estimated_cost should contain coal cost")
        return False

    coal_cost = guest_card.estimated_cost["coal"]
    if coal_cost.get("total") != 1000:  # 2 packages * 500
        print(f"❌ Coal cost should be 1000, got {coal_cost.get('total')}")
        return False

    # Check early arrival - price should be None
    if "early_arrival" not in guest_card.estimated_cost:
        print("❌ estimated_cost should contain early_arrival")
        return False

    early_arrival = guest_card.estimated_cost["early_arrival"]
    if early_arrival.get("price") is not None:
        print("❌ Early arrival price should be None (unknown)")
        return False

    if not early_arrival.get("requires_confirmation"):
        print("❌ Early arrival should require confirmation")
        return False

    print("✓ All R09 checks passed")
    return True

def test_r10(booking_record, session):
    """Test R10: Full card without car, request human"""
    # Check has_car is false
    if booking_record.has_car:
        print("❌ has_car should be false")
        return False

    # Check car_plates is empty
    if booking_record.car_plates and len(booking_record.car_plates) > 0:
        print("❌ car_plates should be empty")
        return False

    # Check guest card has no KPP string
    result = session.execute(
        select(GuestCard).where(GuestCard.booking_id == booking_record.booking_id)
    )
    guest_card = result.scalar_one_or_none()

    if guest_card and guest_card.kpp_string:
        print("❌ KPP string should not be generated when has_car=false")
        return False

    # Check human_requests contains the request
    if not booking_record.human_requests:
        print("❌ human_requests should contain the human request")
        return False

    human_found = False
    for req in booking_record.human_requests:
        if "человеком" in req.get("message", "").lower() or "администратор" in req.get("message", "").lower():
            human_found = True
            break

    if not human_found:
        print("❌ Human request not found in human_requests")
        return False

    print("✓ All R10 checks passed")
    return True

async def run_all_tests():
    """Run all test scenarios"""
    # Load test data
    with open("data/tests.json", "r", encoding="utf-8") as f:
        tests = json.load(f)

    # Load dialogues
    with open("data/dialogues.json", "r", encoding="utf-8") as f:
        dialogues = json.load(f)

    results = []

    for test in tests:
        test_id = test["test_id"]
        booking_id = test["booking_id"]
        expected = test["expected"]

        # Find corresponding dialogue
        dialogue = next((d for d in dialogues if d["test_id"] == test_id), None)
        if not dialogue:
            print(f"❌ No dialogue found for test {test_id}")
            results.append((test_id, False, "No dialogue found"))
            continue

        messages = dialogue["messages"]

        # Run the test
        try:
            success = await test_scenario(test_id, booking_id, messages, expected)
            results.append((test_id, success, expected))
        except Exception as e:
            print(f"❌ ERROR in test {test_id}: {e}")
            results.append((test_id, False, f"Error: {e}"))

    # Print summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    for test_id, success, expected in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_id} - {expected}")

    print(f"\nTotal: {passed}/{total} tests passed")

    return passed == total

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
