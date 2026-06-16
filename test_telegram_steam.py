from backend.telegram_bot import send_telegram_message, format_telegram_smart_money_tip

msg = format_telegram_smart_money_tip(
    "Flamengo vs Vasco",
    "17/06 16:00",
    "Pinnacle",
    "HOME",
    2.20,
    1.60,
    27.3
)

print("Sending test message...")
send_telegram_message(msg)
print("Test message sent!")
